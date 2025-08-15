import os
import csv
import re
import html as html_module
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI

def create_app():
    # =========================
    # App & configuration
    # =========================
    load_dotenv()

    # If your templates/static are at repo root: /templates and /static
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    APP_PASSWORD   = os.getenv("APP_PASSWORD")
    DEFAULT_MODEL  = os.getenv("OPENAI_MODEL") or os.getenv("DEFAULT_MODEL") or "gpt-4o"

    client = OpenAI(api_key=OPENAI_API_KEY)

    os.makedirs('prompt_log', exist_ok=True)

    # =========================
    # Helpers
    # =========================
    def log_prompt_to_csv(task, copilot_prompt, manual_steps):
        csv_path = os.path.join('prompt_log', 'prompts.csv')
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([task, copilot_prompt, manual_steps])

    def generate_followup_question(conversation_history):
        messages = [{"role": "system", "content": (
            "You are a Microsoft 365 Copilot Prompt Expert for TVA employees. "
            "You may ask as many follow-up questions as needed (no limit)."
        )}]
        messages.extend(conversation_history)
        messages.append({
            "role": "user",
            "content": "Do I need to ask another question? If yes, ask it. If no, reply with EXACTLY 'ENOUGH_INFO'."
        })
        response = client.chat.completions.create(model=DEFAULT_MODEL, messages=messages)
        question = response.choices[0].message.content.strip()
        return None if question == "ENOUGH_INFO" else question

    def build_final_prompt(conversation_history):
        messages = [{"role": "system", "content": (
            "You are a Microsoft 365 Copilot Prompt Expert for TVA employees. "
            "Now build a perfect Copilot prompt for the user."
        )}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": "Now create the final Copilot prompt."})
        response = client.chat.completions.create(model=DEFAULT_MODEL, messages=messages)
        return response.choices[0].message.content.strip()

    # =========================
    # Routes
    # =========================
    @app.route('/', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            password = request.form.get('password', '').strip()
            if password == APP_PASSWORD:
                session['logged_in'] = True
                return redirect(url_for('home'))
            else:
                error = "Invalid password"
        return render_template('login.html', error=error)

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/home')
    def home():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return render_template('home.html')

    # =========================
    # Ask for Help
    # =========================
    @app.route('/ask_help', methods=['GET', 'POST'])
    def ask_help():
        if not session.get('logged_in'):
            if request.method == 'GET':
                return redirect(url_for('login'))
            return jsonify({"error": "Not logged in"}), 403

        if request.method == 'GET':
            return render_template('ask_help.html', app_selected='', problem='', result_html='')

        data = request.get_json(silent=True) or request.form or {}
        app_selected = data.get('app', '').strip()
        problem = data.get('problem', '').strip()

        if not app_selected or not problem:
            return render_template(
                'ask_help.html',
                app_selected=app_selected,
                problem=problem,
                result_html="<p style='color:red;'>Please select an app and describe the problem.</p>"
            )

        answer = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are a Microsoft 365 help assistant for TVA employees. "
                    "First provide a short diagnosis, then clear numbered steps in beginner-friendly language."
                )},
                {"role": "user", "content": f"App: {app_selected}\nProblem: {problem}"}
            ]
        ).choices[0].message.content.strip()

        if request.is_json:
            return jsonify({"answer": answer})
        return render_template(
            'ask_help.html',
            app_selected=app_selected,
            problem=problem,
            result_html=answer
        )

    # =========================
    # Smart Copilot Prompt Builder
    # =========================
    @app.route('/prompt_builder')
    def prompt_builder():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        session['conversation_history'] = []
        return render_template('prompt_builder.html')

    @app.route('/prompt_builder/start', methods=['POST'])
    def prompt_builder_start():
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403
        data = request.get_json(force=True) or {}
        initial_task = (data.get("task") or "").strip()
        if not initial_task:
            return jsonify({"error": "Please enter a task."}), 400
        session['conversation_history'] = [
            {"role": "user", "content": f"My task is: {initial_task}"}
        ]
        first_question = generate_followup_question(session['conversation_history'])
        if first_question:
            return jsonify({"question": first_question})
        else:
            final_prompt = build_final_prompt(session['conversation_history'])
            return jsonify({"final_prompt": final_prompt})

    @app.route('/prompt_builder/answer', methods=['POST'])
    def prompt_builder_answer():
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403
        data = request.get_json(force=True) or {}
        answer = (data.get("answer") or "").strip()
        if not answer:
            return jsonify({"error": "Please enter an answer."}), 400
        conversation = session.get('conversation_history', [])
        conversation.append({"role": "user", "content": answer})
        session['conversation_history'] = conversation
        next_question = generate_followup_question(conversation)
        if next_question:
            return jsonify({"question": next_question})
        else:
            final_prompt = build_final_prompt(conversation)
            return jsonify({"final_prompt": final_prompt})

    return app
