# =========================
# TVA SQN Copilot Companion
# Updated: Aug 2025
# All features preserved, routes reordered for safe url_for usage
# =========================

from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv
import re
import html as html_module

# =========================
# App & Configuration
# =========================
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o")
client = OpenAI(api_key=OPENAI_API_KEY)

# Ensure prompt_log directory exists so CSV reads/writes do not fail
os.makedirs('prompt_log', exist_ok=True)

# =========================
# Helper Functions
# =========================

def format_steps_html(text):
    """
    Convert a string with numbered steps into HTML cards.
    Example:
      "1. Step one\n2. Step two"
    becomes styled HTML for the frontend.
    """
    if not text:
        return ""
    lines = text.split("\n")
    html_parts = []
    for line in lines:
        match = re.match(r"^\s*(\d+)[\.\)]\s*(.*)", line)
        if match:
            num, content = match.groups()
            html_parts.append(
                f'<div class="step-card"><div class="step-num">{num}</div><div class="step-text">{html_module.escape(content)}</div></div>'
            )
        else:
            if line.strip():
                html_parts.append(f'<p>{html_module.escape(line.strip())}</p>')
    return "\n".join(html_parts)


def _looks_network_related(text: str) -> bool:
    """Check if a problem description looks network related."""
    NETWORK_KEYWORDS = [
        "network", "offline", "no internet", "cannot connect", "connection lost",
        "proxy", "vpn", "firewall", "gateway", "dns", "ssl", "tls", "server unreachable",
        "status.microsoft", "service health", "outage"
    ]
    text = (text or "").lower()
    return any(k in text for k in NETWORK_KEYWORDS)


# =========================
# Authentication
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    """
    Shared password login for the TVA SQN Copilot Companion.
    Password is stored in .env as APP_PASSWORD.
    """
    error = None
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            error = "Incorrect password. Please try again."
    return render_template("login.html", error=error)
# =========================
# Logout
# =========================
@app.route("/logout")
def logout():
    """Clear session and return to login page."""
    session.clear()
    return redirect(url_for('login'))


# =========================
# Home
# =========================
@app.route("/home")
def home():
    """
    Main dashboard after login.
    Loads prompt history if available.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    history = []
    log_file = os.path.join('prompt_log', 'prompts.csv')
    if os.path.exists(log_file):
        try:
            with open(log_file, newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) >= 2:
                        history.append({"timestamp": row[0], "prompt": row[1]})
        except Exception as e:
            print(f"⚠️ Error reading history: {e}")

    return render_template("home.html", history=history, active_page="home")


# =========================
# Teach Me
# =========================
@app.route("/teach_me", methods=["GET", "POST"])
def teach_me():
    """
    Beginner-friendly Microsoft 365 lessons in a 'for dummies' style.
    Uses global OpenAI client for consistency.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    lesson = None
    if request.method == "POST":
        selected_app = request.form.get("app")
        if selected_app:
            try:
                system_msg = {
                    "role": "system",
                    "content": (
                        "You are a friendly Microsoft 365 instructor for TVA employees. "
                        "Always explain in a 'for dummies' style with plain, simple language, short sentences, "
                        "and step-by-step instructions. Include TVA-friendly examples when possible. "
                        "Avoid technical jargon unless you explain it first. "
                        "Imagine teaching someone who has never used this app before."
                    )
                }
                user_msg = {
                    "role": "user",
                    "content": f"Give me a beginner-friendly lesson on how to use {selected_app}."
                }
                response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[system_msg, user_msg],
                    temperature=0.4
                )
                lesson = (response.choices[0].message.content or "").strip()
            except Exception as e:
                lesson = f"Error loading lesson: {e}"

    return render_template("teach_me.html", lesson=lesson, active_page="teach_me")
# =========================
# Learning & Assistance
# =========================

@app.route('/learn/<app_name>', methods=['GET', 'POST'])
def learn_app(app_name):
    """
    Full lesson mode for a specific Microsoft 365 app.
    If POST with 'topic', tailors the lesson to that topic.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    app_name_l = app_name.lower()
    valid_apps = ['word', 'excel', 'outlook', 'teams', 'powerpoint']
    if app_name_l not in valid_apps:
        return "Invalid app", 404

    user_topic = request.form.get('topic', '').strip() if request.method == 'POST' else ""

    if user_topic:
        prompt = (
            f"You are teaching a total beginner how to use Microsoft {app_name_l.title()} to do this:\n"
            f"'{user_topic}'\n\n"
            "Use a step-by-step format with super simple explanations, plain language, and zero technical jargon. "
            "Make it feel like a helpful live training session for a TVA employee who has never used the app before."
        )
    else:
        prompt = (
            f"You're teaching a brand new TVA employee how to use Microsoft {app_name_l.title()} from scratch. "
            "Assume they have zero experience. Walk them through it slowly, like a beginner class. "
            "Use very plain language, examples, and short, clear steps. No technical terms. "
            "The tone should be friendly and for dummies style."
        )

    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a Microsoft 365 trainer for beginners at TVA. Keep your tone extremely simple, helpful, and non-technical."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=900
        )
        lesson_content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"⚠️ learn error: {e}")
        lesson_content = "⚠️ Sorry, we couldn’t load your lesson right now. Please try again later."

    return render_template("learn.html",
                           app=app_name_l.title(),
                           lesson=lesson_content,
                           user_topic=user_topic,
                           active_page=f"learn_{app_name_l}")


@app.route('/explain_question', methods=['POST'])
def explain_question():
    """
    JSON endpoint used by the 'I'm Not Sure' buttons.
    Body: { "app": "...", "task": "...", "question": "..." }
    Returns: { "explanation": "..." }
    """
    if not session.get('logged_in'):
        return jsonify({"error": "Not logged in"}), 403

    try:
        data = request.get_json(force=True) or {}
        app_selected = (data.get("app") or session.get("app_selected") or "Microsoft 365").strip()
        task = (data.get("task") or session.get("task") or "").strip()
        question = (data.get("question") or "").strip()

        if not question:
            return jsonify({"explanation": "This follow-up is asking for more detail. If you're not sure, you can skip it."})

        explanation = _ai_explain_question(app_selected, task, question)
        return jsonify({"explanation": explanation})
    except Exception as e:
        print(f"⚠️ explain_question error: {e}")
        return jsonify({"explanation": "Sorry, we couldn't clarify that question right now."}), 500


@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    """
    General GPT question endpoint.
    Returns AI answer to any Microsoft 365-related question.
    """
    try:
        data = request.get_json()
        question = (data.get('question') or '').strip()
        if not question:
            return jsonify({"answer": "Please enter a question."})

        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant supporting Microsoft 365 users at TVA."},
                {"role": "user", "content": question}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return jsonify({"answer": (response.choices[0].message.content or "").strip()})
    except Exception as e2:
        print(f"⚠️ ask_gpt error: {e2}")
        return jsonify({"answer": "⚠️ Failed to respond. Try again later."})


@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
    """
    Returns beginner-friendly manual instructions for a given task.
    """
    try:
        data = request.get_json()
        task = (data.get('task') or '').strip()
        context = (data.get('context') or '').strip()
        app_selected = (data.get('app_selected') or 'a Microsoft app').strip()

        prompt = (
            f"The user wants to manually complete this task in Microsoft {app_selected}:\n\n"
            f"Task: {task}\n\nContext:\n{context}\n\n"
            "Write detailed, beginner-friendly instructions with plain language."
        )

        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are an AI writing step-by-step guides for Microsoft 365 beginners."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=700
        )
        return jsonify({"manual_steps": (response.choices[0].message.content or "").strip()})
    except Exception as e:
        print(f"⚠️ manual API error: {e}")
        return jsonify({"manual_steps": "⚠️ Manual instructions unavailable."})
# =========================
# Support Tools
# =========================

@app.route('/ask_help', methods=['GET', 'POST'])
def ask_help():
    """
    Simple Ask for Help page (separate from the full Help Desk).
    Renders ask_help.html and returns a short numbered answer.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    result = None
    result_html = ""
    app_selected = (request.form.get('app') or '').strip()
    problem = (request.form.get('problem') or '').strip()

    if request.method == 'POST' and app_selected and problem:
        try:
            resp = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content":
                        "You are a TVA Microsoft 365 support expert. Provide short, numbered, beginner steps. Avoid jargon."},
                    {"role": "user", "content":
                        f"App: {app_selected}\nProblem: {problem}\n"
                        "Give a short diagnosis first, then numbered steps to fix it. Keep it simple."}
                ],
                temperature=0.3,
                max_tokens=550
            )
            result = (resp.choices[0].message.content or "").strip()
            result_html = format_steps_html(result)
        except Exception as e:
            print(f"⚠️ ask_help AI error: {e}")
            result = "⚠️ Sorry, we could not generate help right now. Try again."
            result_html = ""

    return render_template(
        'ask_help.html',
        app_selected=app_selected or 'Word',
        problem=problem or '',
        result=result,             # original text
        result_html=result_html,   # pretty cards
        active_page="ask_help"
    )


@app.route('/help', methods=['GET', 'POST'])
def help_desk():
    """
    Simple, one-box Help Desk:
      - User types any question about Word/Excel/Outlook/Teams/PowerPoint
      - We return beginner-friendly, numbered steps in plain language
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    answer = None
    answer_html = ""

    if request.method == 'POST':
        user_question = (request.form.get('question') or '').strip()
        if user_question:
            try:
                response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a friendly Microsoft 365 help assistant for TVA employees. "
                                "When given a question about Microsoft Word, Excel, Outlook, Teams, or PowerPoint, "
                                "explain the answer in very clear, numbered, step-by-step instructions in a 'for dummies' style. "
                                "Avoid technical jargon unless absolutely necessary, and if you must use a term, explain it briefly in plain language. "
                                "Do not include or request any sensitive information."
                            ),
                        },
                        {"role": "user", "content": user_question},
                    ],
                    temperature=0.4,
                    max_tokens=700
                )
                answer = (response.choices[0].message.content or "").strip()
                answer_html = format_steps_html(answer)
            except Exception as e:
                print(f"⚠️ Help Desk error: {e}")
                answer = "⚠️ Sorry, there was an error fetching help. Please try again."
                answer_html = ""

    return render_template("help.html",
                           answer=answer,           # original text
                           answer_html=answer_html, # pretty cards
                           active_page="help")


@app.route("/troubleshooter", methods=["GET", "POST"])
def troubleshooter():
    """
    Microsoft 365 Troubleshooter:
      - Form posts m365_app, error_code, description
      - Returns Step-by-Step Fix and a Copilot Prompt
      - If it looks like network trouble, shows a TVA IT note
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    manual_steps_html = None
    copilot_prompt_text = None
    network_note = None
    chosen_app = None

    if request.method == "POST":
        m365_app = request.form.get("m365_app", "Auto-detect")
        error_code = request.form.get("error_code", "").strip()
        description = request.form.get("description", "").strip()
        chosen_app = m365_app

        if _looks_network_related(" ".join([m365_app or "", error_code or "", description or ""])):
            network_note = "This may be a network or connectivity issue. Please contact TVA IT."

        system_prompt = (
            "You are a Microsoft 365 Troubleshooter for beginner users at a utility. "
            "Output two sections:\n"
            "Step-by-Step Fix: Numbered, plain-language instructions with short steps. Avoid jargon. "
            "Warn before any step that could risk data loss.\n"
            "Copilot Prompt: A single prompt the user can paste into Microsoft 365 Copilot."
        )
        user_prompt = (
            f"App: {m365_app}\n"
            f"Error Code: {error_code or 'None'}\n"
            f"Description: {description or 'None provided'}"
        )

        try:
            resp = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
            )
            text = (resp.choices[0].message.content or "").strip()

            lower = text.lower()
            marker = "copilot prompt"
            split_idx = lower.find(marker)

            if split_idx != -1:
                fix_text = text[:split_idx].strip()
                prompt_text = text[split_idx + len(marker):].lstrip(":").strip()
            else:
                fix_text = text
                prompt_text = ""

            manual_steps_html = format_steps_html(fix_text)
            copilot_prompt_text = prompt_text

        except Exception as e:
            print(f"⚠️ Troubleshooter error: {e}")
            manual_steps_html = "<p>Sorry, something went wrong generating steps. Please try again.</p>"
            copilot_prompt_text = None

    return render_template(
        "troubleshooter.html",
        manual_steps=manual_steps_html,  # pretty cards already
        copilot_prompt=copilot_prompt_text,
        network_note=network_note,
        chosen_app=chosen_app,
        active_page="troubleshooter"
    )
# =========================
# Prompt Builder
# =========================
@app.route("/prompt_builder", methods=["GET", "POST"])
def prompt_builder():
    """
    Creates a Microsoft Copilot prompt based on user input.
    Returns a generated prompt string that can be copied into Copilot.
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    prompt_text = None
    app_selected = (request.form.get("app") or "Word").strip()
    task = (request.form.get("task") or "").strip()
    outcome = (request.form.get("outcome") or "").strip()
    audience = (request.form.get("audience") or "").strip()
    tone = (request.form.get("tone") or "professional").strip()
    format_pref = (request.form.get("format_pref") or "").strip()
    constraints = (request.form.get("constraints") or "").strip()

    if request.method == "POST":
        safety = (
            "Do not include any TVA-sensitive, personal, or confidential information. "
            "Use generic placeholders instead of real names, emails, or files."
        )
        lines = []
        lines.append(f"You are Copilot inside Microsoft {app_selected}.")
        lines.append(f"Goal: {task or 'Help me accomplish a task in this app.'}")
        if outcome:
            lines.append(f"Desired outcome: {outcome}.")
        if audience:
            lines.append(f"Audience: {audience}.")
        lines.append(f"Tone: {tone}.")
        if format_pref:
            lines.append(f"Output format: {format_pref}.")
        if constraints:
            lines.append(f"Constraints or notes: {constraints}.")
        lines.append(
            "Instructions: Provide clear, numbered steps in beginner friendly language. "
            "Offer a short example if helpful. End with a quick checklist of what the user should verify."
        )
        lines.append(f"Safety: {safety}")
        prompt_text = "\n".join(lines)

    return render_template(
        "prompt_builder.html",
        prompt_text=prompt_text,
        app_selected=app_selected,
        active_page="prompt"
    )


# =========================
# Follow-up Question Helper
# =========================
@app.route("/followups/explain", methods=["POST"])
def explain_followup():
    """
    Returns a beginner-friendly, 'for dummies' style explanation of a follow-up question.
    """
    data = request.get_json(force=True)
    app_name = data.get("app", "")
    task = data.get("task", "")
    question_text = data.get("question_text", "")

    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are a friendly Microsoft 365 coach for TVA employees. "
                "When asked to explain a follow-up question, break it down in plain, beginner-friendly language. "
                "Keep it short, clear, and supportive — as if speaking to someone with no technical background. "
                "Give 1–2 simple examples. "
                "End with a note that the user can skip this question if they want."
            )
        }
        user_msg = {
            "role": "user",
            "content": (
                f"Microsoft 365 app: {app_name}\n"
                f"User task: {task}\n"
                f"Follow-up question: {question_text}"
            )
        }
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[system_msg, user_msg],
            temperature=0.3
        )
        explanation = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"⚠️ Follow-up explain error: {e}")
        explanation = (
            f"This question is asking: '{question_text}'. "
            "Think about it in very simple terms. "
            "Example: if it asks about 'version of Word', it means something like Word 2016 or Word 365. "
            "You can skip this question if you want."
        )

    return jsonify({"explanation": explanation})


@app.route("/followups/submit", methods=["POST"])
def submit_followups():
    """
    Receives and processes follow-up answers.
    """
    data = request.get_json(force=True)
    answers = data.get("answers", {})

    # You can process answers here, for example:
    print("Follow-up answers received:", answers)

    # Return something back to the frontend
    return jsonify({"status": "ok", "message": "Follow-ups received", "answers": answers})
# =========================
# Internal AI Helpers
# =========================

def _ai_explain_question(app_selected, task, question):
    """
    Generates a simple explanation for a follow-up question.
    Called by /explain_question.
    """
    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are a friendly Microsoft 365 coach for TVA employees. "
                "Explain questions in plain language and a 'for dummies' style. "
                "Keep it short, clear, and non-technical."
            )
        }
        user_msg = {
            "role": "user",
            "content": (
                f"Microsoft 365 app: {app_selected}\n"
                f"Task: {task}\n"
                f"Question: {question}"
            )
        }
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[system_msg, user_msg],
            temperature=0.3
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"⚠️ _ai_explain_question error: {e}")
        return (
            f"This question is asking about: '{question}'. "
            "Think of it in simple terms. "
            "Example: if it asks for 'version of Word', it means something like Word 2016 or Word 365."
        )


# =========================
# App Runner
# =========================
if __name__ == "__main__":
    # When running locally
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
