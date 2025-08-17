from flask import render_template, request, redirect, session, url_for, jsonify
import os, csv
from app.helpers import ai_chat, get_data, log_prompt_to_csv

# Load APP_PASSWORD from environment
APP_PASSWORD = os.getenv("APP_PASSWORD")

def init_routes(app):
    # =========================
    # Auth & Home
    # =========================
    @app.route('/', methods=['GET', 'POST'])
    def login():
        if session.get('logged_in'):
            return redirect(url_for('home'))
        error = None
        if request.method == 'POST':
            if (request.form.get('password') or '').strip() == (APP_PASSWORD or ''):
                session['logged_in'] = True
                session['pb_convo'] = []
                return redirect(url_for('home'))
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
    # Prompt Builder
    # =========================
    @app.route('/prompt_builder', methods=['GET'])
    def prompt_builder():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        session['pb_convo'] = []
        return render_template('prompt_builder.html')

    @app.route('/prompt_builder/start', methods=['POST'])
    def pb_start():
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = request.get_json(force=True)
        app_name = (data.get("app") or "").strip()
        goal = (data.get("goal") or "").strip()

        if not app_name or not goal:
            return jsonify({"error": "Missing app or goal"}), 400

        convo = [
            {"role": "system", "content": (
                "You are a helpful Copilot prompt engineer for TVA employees. "
                "Ask clear follow-up questions until enough detail is gathered, then stop and create the final prompt. "
                "The final prompt should NEVER end with a question, only a clean Copilot instruction.")},
            {"role": "user", "content": f"App: {app_name}\nGoal: {goal}"}
        ]
        session['pb_convo'] = convo

        enough = ai_chat([
            {"role": "system", "content": "Do we now have enough detail to create a strong Copilot prompt? Answer EXACTLY 'YES' or 'NO'."}
        ] + convo)

        if enough.strip().upper() == "YES":
            return generate_final(convo, goal)

        next_q = ai_chat([
            {"role": "system", "content": "Ask one simple, clear follow-up question to clarify the user's goal."}
        ] + convo)

        convo.append({"role": "assistant", "content": next_q})
        session['pb_convo'] = convo

        return jsonify({"question": next_q, "history": convo})

    @app.route('/prompt_builder/answer', methods=['POST'])
    def pb_answer():
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = request.get_json(force=True)
        answer = (data.get("answer") or "").strip()
        convo = session.get('pb_convo', [])

        convo.append({"role": "user", "content": answer})
        session['pb_convo'] = convo

        enough = ai_chat([
            {"role": "system", "content": "Do we now have enough detail to create a strong Copilot prompt? Answer EXACTLY 'YES' or 'NO'."}
        ] + convo)

        if enough.strip().upper() == "YES":
            return generate_final(convo, "Prompt Builder")

        next_q = ai_chat([
            {"role": "system", "content": "Ask one simple, clear follow-up question to clarify the user's goal."}
        ] + convo)

        convo.append({"role": "assistant", "content": next_q})
        session['pb_convo'] = convo

        return jsonify({"question": next_q, "history": convo})

    def generate_final(convo, goal):
        final_response = ai_chat([
            {"role": "system", "content": (
                "You are an expert Microsoft Copilot prompt writer. "
                "From the conversation, generate ONE final Copilot prompt in natural language. "
                "It must be short, actionable, and ready to paste directly into Microsoft Copilot. "
                "Do NOT give instructions or steps. Only write the Copilot prompt. "
                "Also include a short explanation (2–3 sentences max) of why this is a strong prompt. "
                "Format STRICTLY as:\n"
                "PROMPT: <the Copilot-ready prompt>\n"
                "EXPLANATION: <your explanation>"
            )}
        ] + convo)

        if "EXPLANATION:" in final_response:
            prompt_text, explanation = final_response.split("EXPLANATION:", 1)
            prompt_text = prompt_text.replace("PROMPT:", "").strip()
            explanation = explanation.strip()
        else:
            prompt_text, explanation = final_response.strip(), ""

        try:
            log_prompt_to_csv(goal, prompt_text, explanation)
        except Exception:
            pass

        return jsonify({
            "final_prompt": prompt_text,
            "explanation": explanation,
            "history": convo
        })

    # =========================
    # Troubleshooter
    # =========================
    @app.route('/troubleshooter', methods=['GET', 'POST'])
    def troubleshooter():
        if not session.get('logged_in'):
            if request.method == 'GET':
                return redirect(url_for('login'))
            return jsonify({"error": "Not logged in"}), 403

        if request.method == 'GET':
            return render_template('troubleshooter.html')

        data = get_data()
        problem = data.get('issue') or data.get('problem') or ''
        problem = problem.strip()
        if not problem:
            return render_template('troubleshooter.html', solution="<p style='color:red;'>Please describe the issue.</p>")

        solution = ai_chat([
            {"role": "system", "content":
             "You are a friendly Microsoft 365 troubleshooting assistant for TVA employees. "
             "Give a brief diagnosis, then clear numbered steps. "
             "If it's likely a network or account issue, advise contacting TVA IT."},
            {"role": "user", "content": problem}
        ])

        if request.is_json:
            return jsonify({"solution": solution})
        return render_template('troubleshooter.html', solution=solution)

    # =========================
    # Teach Me
    # =========================
    @app.route('/teach_me', methods=['GET', 'POST'])
    def teach_me():
        if not session.get('logged_in'):
            if request.method == 'GET':
                return redirect(url_for('login'))
            return jsonify({"error": "Not logged in"}), 403

        if request.method == 'GET':
            return render_template('teach_me.html')

        data = get_data()
        app_name = data.get('app', '').strip()
        topic = data.get('topic', '').strip()

        if not app_name:
            msg = "<p style='color:red;'>Please choose an app.</p>"
            return render_template('teach_me.html', lesson=msg)

        if not topic:
            prompt = (f"Create a short beginner-friendly starter lesson for Microsoft {app_name}. "
                      "Explain what it’s used for at work, then give 5–8 numbered steps for a basic, useful task.")
        else:
            prompt = (f"Teach this topic in Microsoft {app_name} with clear numbered steps, "
                      f"beginner-friendly language, and short explanations: {topic}")

        lesson = ai_chat([
            {"role": "system", "content":
             "You are a Microsoft 365 trainer for TVA employees. "
             "Write in very clear, simple, friendly language."},
            {"role": "user", "content": prompt}
        ])

        if request.is_json:
            return jsonify({"lesson": lesson})
        return render_template('teach_me.html', lesson=lesson)

    # =========================
    # Help Page
    # =========================
    @app.route('/help', methods=['GET'])
    def help_page():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return render_template('help.html')

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

        data = get_data()
        app_selected = data.get('app', '').strip()
        problem = data.get('problem', '').strip()

        if not app_selected or not problem:
            return render_template(
                'ask_help.html',
                app_selected=app_selected,
                problem=problem,
                result_html="<p style='color:red;'>Please select an app and describe the problem.</p>"
            )

        answer = ai_chat([
            {"role": "system", "content":
             "You are a Microsoft 365 help assistant for TVA employees. "
             "First provide a short diagnosis, then clear numbered steps in beginner-friendly language."},
            {"role": "user", "content": f"App: {app_selected}\nProblem: {problem}"}
        ])

        if request.is_json:
            return jsonify({"answer": answer})
        return render_template('ask_help.html',
                               app_selected=app_selected,
                               problem=problem,
                               result_html=answer)

    @app.route('/ask_gpt', methods=['GET', 'POST'])
    def ask_gpt_redirect():
        return redirect(url_for('ask_help'))

    # =========================
    # Prompt History
    # =========================
    @app.route('/prompt_history')
    def prompt_history():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        csv_path = os.path.join('prompt_log', 'prompts.csv')
        history = []
        if os.path.exists(csv_path):
            with open(csv_path, newline='', encoding='utf-8') as f:
                history = list(csv.reader(f))
        return render_template('prompt_history.html', history=history)
