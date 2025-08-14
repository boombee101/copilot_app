from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os, csv, html as html_module, uuid

# =========================
# App & configuration
# =========================
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD   = os.getenv("APP_PASSWORD")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")
client = OpenAI(api_key=OPENAI_API_KEY)

os.makedirs('prompt_log', exist_ok=True)

# =========================
# Helpers
# =========================
def ai_chat(messages):
    """Small wrapper to call OpenAI chat."""
    resp = client.chat.completions.create(model=DEFAULT_MODEL, messages=messages)
    return resp.choices[0].message.content.strip()

def get_data():
    """Merge JSON body and form data safely."""
    data = request.get_json(silent=True) or {}
    # add form fields if present
    for k, v in request.form.items():
        data.setdefault(k, v)
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}

def log_prompt_to_csv(task, copilot_prompt, manual_steps):
    csv_path = os.path.join('prompt_log', 'prompts.csv')
    with open(csv_path, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([task, copilot_prompt, manual_steps])

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
# Prompt Builder (matches your prompt_builder.html)
# =========================
@app.route('/prompt_builder', methods=['GET'])
def prompt_builder():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # store per-session conversation
    session['pb_conversation'] = []
    session['pb_meta'] = {}
    return render_template('prompt_builder.html')

@app.route('/prompt_builder/start', methods=['POST'])
def prompt_builder_start():
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403
    data = get_data()
    app_name = data.get('app', '').strip()
    goal     = data.get('goal', '').strip()
    if not app_name or not goal:
        return jsonify({"error": "Please select an app and enter your goal."}), 400

    # seed conversation with app + goal so follow-ups are contextual
    convo = [{"role":"user","content": f"App: {app_name}\nGoal: {goal}"}]
    session['pb_conversation'] = convo
    session['pb_meta'] = {"app": app_name, "goal": goal}
    session_id = str(uuid.uuid4())

    # ask first follow-up
    question = ai_chat([
        {"role":"system","content":(
            "You are a Microsoft 365 Copilot Prompt Expert for TVA employees. "
            "Ask one specific follow-up question at a time to clarify the user's goal. "
            "Keep the wording simple and beginner-friendly.")}
    ] + convo + [{"role":"user","content":"Ask one best follow-up question now."}])

    return jsonify({"session_id": session_id, "question": question})

@app.route('/prompt_builder/answer', methods=['POST'])
def prompt_builder_answer():
    if not session.get('logged_in'):
        return jsonify({"error":"Not logged in"}), 403
    data = get_data()
    answer = data.get('answer', '').strip()
    if not answer:
        return jsonify({"error":"Please enter an answer."}), 400

    convo = session.get('pb_conversation', [])
    meta  = session.get('pb_meta', {})
    convo.append({"role":"user","content": answer})
    session['pb_conversation'] = convo

    # decide whether we have enough info
    enough = ai_chat([
        {"role":"system","content":
         "You decide if enough info has been gathered to draft a great Copilot prompt. "
         "Answer EXACTLY 'YES' if enough, otherwise 'NO'."}
    ] + convo)

    if enough.strip().upper() == "YES":
        prompt_text = ai_chat([
            {"role":"system","content":(
                "Create the final Microsoft Copilot prompt for the user's goal at TVA. "
                "Be specific, include context from the conversation, keep it succinct.")},
        ] + convo + [{"role":"user","content":"Generate the final Copilot prompt now."}])
        # optionally log
        try:
            log_prompt_to_csv(meta.get('goal',''), prompt_text, "")
        except Exception:
            pass
        return jsonify({"done": True, "prompt": prompt_text})

    # otherwise ask next question
    next_q = ai_chat([
        {"role":"system","content":
         "Ask exactly one helpful follow-up question to clarify the user's goal. Keep it simple."}
    ] + convo)
    return jsonify({"done": False, "question": next_q})

# =========================
# Troubleshooter (matches troubleshooter.html)
# =========================
@app.route('/troubleshooter', methods=['GET', 'POST'])
def troubleshooter():
    if not session.get('logged_in'):
        if request.method == 'GET':
            return redirect(url_for('login'))
        return jsonify({"error":"Not logged in"}), 403

    if request.method == 'GET':
        return render_template('troubleshooter.html')

    data = get_data()
    # Accept either 'issue' (from your form) or 'problem' (from JSON callers)
    problem = data.get('issue') or data.get('problem') or ''
    problem = problem.strip()
    if not problem:
        # render back to page with a friendly message
        return render_template('troubleshooter.html', solution="<p style='color:red;'>Please describe the issue.</p>")

    solution = ai_chat([
        {"role":"system","content":
         "You are a friendly Microsoft 365 troubleshooting assistant for TVA employees. "
         "Give a brief diagnosis, then clear numbered steps. "
         "If it's likely a network or account issue, advise contacting TVA IT."},
        {"role":"user","content": problem}
    ])

    # If the request was JSON, return JSON; else render into the page
    if request.is_json:
        return jsonify({"solution": solution})
    return render_template('troubleshooter.html', solution=solution)

# =========================
# Teach Me (matches teach_me.html form: only 'app' required)
# If 'topic' missing, generate a starter lesson for that app.
# =========================
@app.route('/teach_me', methods=['GET', 'POST'])
def teach_me():
    if not session.get('logged_in'):
        if request.method == 'GET':
            return redirect(url_for('login'))
        return jsonify({"error":"Not logged in"}), 403

    if request.method == 'GET':
        return render_template('teach_me.html')

    data = get_data()
    app_name = data.get('app','').strip()
    topic    = data.get('topic','').strip()

    if not app_name:
        msg = "<p style='color:red;'>Please choose an app.</p>"
        return render_template('teach_me.html', lesson=msg)

    if not topic:
        # Starter lesson when only app is chosen (matches your current UI)
        prompt = (f"Create a short beginner-friendly starter lesson for Microsoft {app_name}. "
                  "Explain what it’s used for at work, then give 5–8 numbered steps for a basic, useful task.")
    else:
        prompt = (f"Teach this topic in Microsoft {app_name} with clear numbered steps, "
                  "beginner-friendly language, and short explanations: {topic}")

    lesson = ai_chat([
        {"role":"system","content":
         "You are a Microsoft 365 trainer for TVA employees. "
         "Write in very clear, simple, friendly language."},
        {"role":"user","content": prompt}
    ])

    if request.is_json:
        return jsonify({"lesson": lesson})
    return render_template('teach_me.html', lesson=lesson)

# =========================
# Simple Help page that posts to ask_help
# =========================
@app.route('/help', methods=['GET'])
def help_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # You have a help.html that posts to ask_help
    return render_template('help.html')

# =========================
# Ask for Help (matches ask_help.html form)
# =========================
@app.route('/ask_help', methods=['GET', 'POST'])
def ask_help():
    if not session.get('logged_in'):
        if request.method == 'GET':
            return redirect(url_for('login'))
        return jsonify({"error":"Not logged in"}), 403

    if request.method == 'GET':
        # Show empty form
        return render_template('ask_help.html', app_selected='', problem='', result_html='')

    data = get_data()
    app_selected = data.get('app','').strip()
    problem      = data.get('problem','').strip()

    if not app_selected or not problem:
        return render_template(
            'ask_help.html',
            app_selected=app_selected,
            problem=problem,
            result_html="<p style='color:red;'>Please select an app and describe the problem.</p>"
        )

    answer = ai_chat([
        {"role":"system","content":
         "You are a Microsoft 365 help assistant for TVA employees. "
         "First provide a short diagnosis, then clear numbered steps in beginner-friendly language."},
        {"role":"user","content": f"App: {app_selected}\nProblem: {problem}"}
    ])

    if request.is_json:
        return jsonify({"answer": answer})
    return render_template('ask_help.html',
                           app_selected=app_selected,
                           problem=problem,
                           result_html=answer)

# Back-compat: send old /ask_gpt to /ask_help
@app.route('/ask_gpt', methods=['GET', 'POST'])
def ask_gpt_redirect():
    return redirect(url_for('ask_help'))

# =========================
# Prompt History (unchanged)
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

# =========================
# Run app
# =========================
if __name__ == '__main__':
    app.run(debug=True)
