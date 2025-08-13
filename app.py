from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv
import re
import html as html_module

# =========================
# App & configuration
# =========================
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD   = os.getenv("APP_PASSWORD")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")  # fallback if gpt-4 is unavailable
client = OpenAI(api_key=OPENAI_API_KEY)

# Ensure prompt_log directory exists so CSV reads/writes do not fail
os.makedirs('prompt_log', exist_ok=True)

# =========================
# Helper Functions
# =========================

def log_prompt_to_csv(task, copilot_prompt, manual_steps):
    """Log generated prompts to a CSV file."""
    csv_path = os.path.join('prompt_log', 'prompts.csv')
    with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([task, copilot_prompt, manual_steps])

def generate_followup_question(conversation_history):
    """Ask the next follow-up question or stop if enough info is collected."""
    messages = [{"role": "system", "content": (
        "You are a Microsoft 365 Copilot Prompt Expert for TVA employees. "
        "Ask as many follow-up questions as needed (no 3-question limit). "
        "Stop asking only when you have enough detail."
    )}]
    messages.extend(conversation_history)
    messages.append({
        "role": "user",
        "content": "Do I need to ask another question? If yes, ask it. If no, reply EXACTLY 'ENOUGH_INFO'."
    })

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages
    )
    question = response.choices[0].message.content.strip()
    return None if question == "ENOUGH_INFO" else question

def build_final_prompt(conversation_history):
    """Create the final Copilot prompt from collected answers."""
    messages = [{"role": "system", "content": (
        "You are a Microsoft 365 Copilot Prompt Expert for TVA employees. "
        "Build the perfect Copilot prompt based on all gathered answers."
    )}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": "Now create the final Copilot prompt."})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages
    )
    return response.choices[0].message.content.strip()

# =========================
# Routes
# =========================

@app.route('/', methods=['GET', 'POST'])
def login():
    """Login page using shared password from .env"""
    if session.get('logged_in'):
        return redirect(url_for('home'))  # Already logged in → skip login page

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
    """Logout and clear session."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/home')
def home():
    """Home page after login."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('home.html')

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
    final_prompt = build_final_prompt(conversation)
    return jsonify({"final_prompt": final_prompt})

# =========================
# Troubleshooter
# =========================
@app.route('/troubleshooter', methods=['POST'])
def troubleshooter():
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403
    data = request.get_json(force=True) or {}
    problem = (data.get("problem") or "").strip()
    if not problem:
        return jsonify({"error": "Please describe your problem."}), 400
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "You are a friendly Microsoft 365 troubleshooting assistant for TVA employees. Give clear, plain-language steps. If it’s a network issue, advise contacting TVA IT."},
            {"role": "user", "content": problem}
        ]
    )
    return jsonify({"solution": response.choices[0].message.content.strip()})

# =========================
# Teach Me
# =========================
@app.route('/teach_me', methods=['POST'])
def teach_me():
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403
    data = request.get_json(force=True) or {}
    app_name = (data.get("app") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not app_name or not topic:
        return jsonify({"error": "Please select an app and topic."}), 400
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": f"You are a Microsoft 365 trainer for TVA employees. Teach the topic in {app_name} in plain, beginner-friendly steps."},
            {"role": "user", "content": topic}
        ]
    )
    return jsonify({"lesson": response.choices[0].message.content.strip()})

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
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            history = list(reader)
    return render_template('prompt_history.html', history=history)

# =========================
# Manual Instructions Generator
# =========================
@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403
    data = request.get_json(force=True) or {}
    app_name = (data.get("app") or "").strip()
    task = (data.get("task") or "").strip()
    if not app_name or not task:
        return jsonify({"error": "Please select an app and describe the task."}), 400
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": f"You are a Microsoft 365 expert for TVA employees. Provide plain-language, step-by-step instructions for {app_name}."},
            {"role": "user", "content": task}
        ]
    )
    return jsonify({"steps": response.choices[0].message.content.strip()})

# =========================
# Help Desk
# =========================
@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant for TVA employees using Microsoft 365. Be clear and concise."},
            {"role": "user", "content": question}
        ]
    )
    return jsonify({"answer": response.choices[0].message.content.strip()})

# =========================
# Run the app
# =========================
if __name__ == '__main__':
    app.run(debug=True)
