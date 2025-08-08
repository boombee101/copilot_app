from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv
import json
from datetime import datetime

# ----------------------------
# Setup
# ----------------------------
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
client = OpenAI(api_key=OPENAI_API_KEY)

LOG_DIR = "prompt_log"
LOG_FILE = os.path.join(LOG_DIR, "prompts.csv")
os.makedirs(LOG_DIR, exist_ok=True)

VALID_APPS = ["Word", "Excel", "Outlook", "Teams", "PowerPoint"]

# Optional: default TVA/SQN-safe presets per app
APP_PRESETS = {
    "Word": {
        "common_tasks": [
            "Summarize a long document",
            "Rewrite for plain language",
            "Turn notes into a clean memo",
            "Create a checklist from text"
        ]
    },
    "Excel": {
        "common_tasks": [
            "Turn messy rows into a clean table",
            "Explain a formula step by step",
            "Summarize a data range with bullets",
            "Create a pivot-ready summary plan"
        ]
    },
    "Outlook": {
        "common_tasks": [
            "Draft a clear email",
            "Turn bullet notes into a message",
            "Summarize a long thread",
            "Create a follow-up list from emails"
        ]
    },
    "Teams": {
        "common_tasks": [
            "Summarize a channel discussion",
            "Draft a short update post",
            "Extract action items from chat",
            "Turn thread notes into a meeting recap"
        ]
    },
    "PowerPoint": {
        "common_tasks": [
            "Turn notes into a slide outline",
            "Summarize a report into slides",
            "Create a title and agenda slide",
            "List key risks and actions as slides"
        ]
    }
}

# ----------------------------
# Helpers
# ----------------------------
def _safe(val: str) -> str:
    if not val:
        return ""
    return val.strip()

def _csv_log_row(*cols):
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
    except Exception as e:
        print(f"⚠️ Failed to log prompt: {e}")

def _load_history(limit=10):
    history = []
    try:
        with open(LOG_FILE, mode="r", encoding="utf-8") as file:
            reader = csv.reader(file)
            rows = list(reader)
            for row in reversed(rows[-limit:]):
                # timestamp, app, task, context, final_prompt
                if len(row) >= 5:
                    history.append({
                        "timestamp": row[0],
                        "app": row[1],
                        "task": row[2],
                        "context": row[3],
                        "prompt": row[4]
                    })
    except Exception as e:
        print(f"⚠️ Failed to load prompt history: {e}")
    return history

def _build_safety_block(app_selected: str) -> str:
    return (
        "Safety and privacy notes:\n"
        "- Do not paste any sensitive, restricted, or private TVA content.\n"
        "- Summarize sensitive items in general terms only.\n"
        f"- Assume you are working in Microsoft {app_selected}.\n"
    )

def _build_constraints_text(length_limit: str, tone: str, style_guide: str) -> str:
    parts = []
    if length_limit:
        parts.append(f"Keep it under {length_limit}.")
    if tone:
        parts.append(f"Use a {tone} tone.")
    if style_guide:
        parts.append(f"Follow these style preferences: {style_guide}.")
    parts.append("Use plain language. Short sentences. No jargon.")
    return "\n- ".join(parts)

def _parse_model_text_to_questions(raw: str, max_q=10):
    # Robustly split any list the model returns
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    cleaned = []
    for ln in lines:
        # remove leading bullets or numbers
        while ln and (ln[0] in "-•*0123456789. "):
            ln = ln[1:].lstrip()
        if len(ln) > 5:
            cleaned.append(ln)
    # de-dup while preserving order
    seen = set()
    uniq = []
    for q in cleaned:
        if q not in seen:
            uniq.append(q)
            seen.add(q)
    return uniq[:max_q]

def _question_system_prompt(app_selected: str):
    return (
        "You are a Copilot guide for TVA employees. "
        f"Ask specific, beginner-friendly questions needed to complete a task in Microsoft {app_selected}. "
        "Avoid technical jargon. Ask only what you truly need. "
        "Do not ask for sensitive data. If the user mentions sensitive data, tell them to generalize it."
    )

def _final_prompt_system_prompt():
    return (
        "You are an expert prompt writer for Microsoft Copilot in Office apps. "
        "Write clear, structured prompts that are easy for non-technical employees."
    )

# ----------------------------
# Auth
# ----------------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Incorrect password.')
    return render_template('login.html')

# ----------------------------
# Home + Prompt Builder
# ----------------------------
@app.route('/home', methods=['GET', 'POST'])
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    history = _load_history(limit=10)

    if request.method == 'POST':
        # Branch 1: Generate follow-up questions
        if 'task' in request.form and 'app' in request.form:
            task = _safe(request.form['task'])
            app_selected = _safe(request.form['app'])
            if app_selected not in VALID_APPS:
                app_selected = "Word"  # default fallback

            # Optional advanced fields (will be empty unless the HTML sends them)
            audience = _safe(request.form.get('audience', ''))
            tone = _safe(request.form.get('tone', ''))
            length_limit = _safe(request.form.get('length_limit', ''))
            format_pref = _safe(request.form.get('format_pref', ''))  # outline, bullets, table, etc.
            must_include = _safe(request.form.get('must_include', ''))  # comma separated
            must_exclude = _safe(request.form.get('must_exclude', ''))
            deadline = _safe(request.form.get('deadline', ''))
            style_guide = _safe(request.form.get('style_guide', ''))

            session['task'] = task
            session['app_selected'] = app_selected
            session['advanced'] = {
                "audience": audience,
                "tone": tone,
                "length_limit": length_limit,
                "format_pref": format_pref,
                "must_include": must_include,
                "must_exclude": must_exclude,
                "deadline": deadline,
                "style_guide": style_guide
            }

            try:
                # Build a richer question prompt with context
                user_msg = (
                    f"User stated task: '{task}'.\n"
                    f"Known preferences:\n"
                    f"- Audience: {audience or 'not specified'}\n"
                    f"- Tone: {tone or 'not specified'}\n"
                    f"- Length limit: {length_limit or 'not specified'}\n"
                    f"- Format: {format_pref or 'not specified'}\n"
                    f"- Must include: {must_include or 'not specified'}\n"
                    f"- Must exclude: {must_exclude or 'not specified'}\n"
                    f"- Deadline/Timing: {deadline or 'not specified'}\n"
                    f"- Style guide: {style_guide or 'not specified'}\n\n"
                    "Ask 6 to 10 precise questions that would let Copilot do this well. "
                    "Keep questions short, plain, and task-focused. "
                    "If any detail above is missing, ask for it. "
                    "Do not request or store sensitive TVA data."
                )

                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": _question_system_prompt(app_selected)},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=0.4,
                    max_tokens=700
                )
                raw = response.choices[0].message.content
                questions = _parse_model_text_to_questions(raw, max_q=10)
                if not questions:
                    questions = ["Describe the input in general terms without sensitive details.",
                                 "Who is the audience?",
                                 "What format do you want the output to be in?",
                                 "What is the purpose or outcome you need?",
                                 "Any hard limits like word count or bullets?"]
            except Exception as e:
                print(f"⚠️ Error generating questions: {e}")
                questions = ["⚠️ Error generating questions. Try again."]

            session['questions'] = questions
            return render_template("home.html",
                                   questions=questions,
                                   original_task=task,
                                   app_selected=app_selected,
                                   presets=APP_PRESETS.get(app_selected, {}),
                                   history=history)

        # Branch 2: Build final prompt and manual steps
        elif 'original_task' in request.form:
            task = _safe(request.form['original_task'])
            app_selected = session.get('app_selected', 'Word')
            if app_selected not in VALID_APPS:
                app_selected = "Word"

            questions = session.get('questions', [])
            answers = []
            for i in range(len(questions)):
                ans = _safe(request.form.get(f'answer_{i}', ''))
                if ans:
                    answers.append(f"Q: {questions[i]}\nA: {ans}")
            context = "\n".join(answers) if answers else "No extra context provided."

            # Advanced fields remembered from step 1
            adv = session.get('advanced', {}) or {}
            audience = adv.get("audience", "")
            tone = adv.get("tone", "")
            length_limit = adv.get("length_limit", "")
            format_pref = adv.get("format_pref", "")
            must_include = adv.get("must_include", "")
            must_exclude = adv.get("must_exclude", "")
            deadline = adv.get("deadline", "")
            style_guide = adv.get("style_guide", "")

            constraints_list = _build_constraints_text(length_limit, tone, style_guide)

            # Build a structured, app-aware final prompt
            try:
                smart_prompt = (
                    f"You are Microsoft Copilot in {app_selected}.\n\n"
                    f"Task:\n{task}\n\n"
                    f"Context (user answers):\n{context}\n\n"
                    f"{_build_safety_block(app_selected)}\n"
                    f"Audience: {audience or 'General TVA staff'}\n"
                    f"Deadline/Timing: {deadline or 'Not specified'}\n"
                    f"Required elements: {must_include or 'None specified'}\n"
                    f"Do not include: {must_exclude or 'None'}\n"
                    f"Preferred output format: {format_pref or 'Clear bullets or short sections'}\n\n"
                    f"Constraints:\n- {constraints_list}\n\n"
                    "Output structure:\n"
                    "1) Short title\n"
                    "2) One line purpose\n"
                    "3) 3 to 7 bullet points with specifics\n"
                    "4) If actions exist, list who should do what and by when\n"
                    "If anything needed is still unclear, ask up to two short clarifying questions first."
                )

                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": _final_prompt_system_prompt()},
                        {"role": "user", "content": smart_prompt}
                    ],
                    temperature=0.4,
                    max_tokens=700
                )
                final_prompt = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️ Prompt error: {e}")
                final_prompt = "⚠️ Could not generate prompt."

            # Manual instructions for the same task
            try:
                manual_instructions_prompt = (
                    f"The user wants to complete this task manually in Microsoft {app_selected}:\n\n"
                    f"Task:\n{task}\n\n"
                    f"Context (user answers):\n{context}\n\n"
                    "Write beginner-friendly, numbered steps in short sentences. "
                    "Explain where to click and what to type. Keep it plain and simple."
                )
                manual_response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a helpful trainer writing clear, non-technical Microsoft 365 instructions."},
                        {"role": "user", "content": manual_instructions_prompt}
                    ],
                    temperature=0.5,
                    max_tokens=900
                )
                manual_instructions = manual_response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️ Manual error: {e}")
                manual_instructions = "⚠️ Could not generate manual steps."

            # Log with timestamp and app
            try:
                timestamp = datetime.utcnow().isoformat()
                _csv_log_row(timestamp, app_selected, task, context, final_prompt)
            except Exception as e:
                print(f"⚠️ Failed to log prompt: {e}")

            history = _load_history(limit=10)
            return render_template("home.html",
                                   final_prompt=final_prompt,
                                   app_selected=app_selected,
                                   task=task,
                                   context=context,
                                   manual_instructions=manual_instructions,
                                   presets=APP_PRESETS.get(app_selected, {}),
                                   history=history)

    # GET
    return render_template("home.html",
                           presets=APP_PRESETS.get("Word", {}),
                           history=history)

# ----------------------------
# Ask GPT (Sidebar helper)
# ----------------------------
@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    try:
        data = request.get_json()
        question = _safe(data.get('question', ''))
        if not question:
            return jsonify({"answer": "Please enter a question."})

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant supporting Microsoft 365 users at TVA."},
                {"role": "user", "content": question}
            ],
            temperature=0.4,
            max_tokens=500
        )
        return jsonify({"answer": response.choices[0].message.content.strip()})
    except Exception as e:
        print(f"⚠️ ask_gpt error: {e}")
        return jsonify({"answer": "⚠️ Failed to respond. Try again later."})

# ----------------------------
# Do It Manually API
# ----------------------------
@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
    try:
        data = request.get_json()
        task = _safe(data.get('task', ''))
        context = _safe(data.get('context', ''))
        app_selected = _safe(data.get('app_selected', 'Word'))
        if app_selected not in VALID_APPS:
            app_selected = "Word"

        prompt = (
            f"The user wants to manually complete this task in Microsoft {app_selected}:\n\n"
            f"Task:\n{task}\n\nContext:\n{context}\n\n"
            "Write detailed, numbered steps in plain language. "
            "Assume a beginner. Show where to click and what to type. "
            "Keep steps short and clear."
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an AI writing step-by-step guides for Microsoft 365 beginners."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=900
        )
        return jsonify({"manual_steps": response.choices[0].message.content.strip()})
    except Exception as e:
        print(f"⚠️ manual API error: {e}")
        return jsonify({"manual_steps": "⚠️ Manual instructions unavailable."})

# ----------------------------
# Learn Module
# ----------------------------
@app.route('/learn/<app_name>', methods=['GET', 'POST'])
def learn_app(app_name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    app_name = app_name.lower()
    valid_apps = ['word', 'excel', 'outlook', 'teams', 'powerpoint']
    if app_name not in valid_apps:
        return "Invalid app", 404

    user_topic = _safe(request.form.get('topic', '')) if request.method == 'POST' else ""

    if user_topic:
        prompt = (
            f"You are teaching a total beginner how to use Microsoft {app_name.title()} to do this:\n"
            f"'{user_topic}'\n\n"
            "Use a step-by-step format with super simple explanations and plain language. "
            "Make it feel like a helpful live training session for a TVA employee who has never used the app."
        )
    else:
        prompt = (
            f"Teach a brand new TVA employee how to use Microsoft {app_name.title()} from scratch. "
            "Walk through the basics in short, numbered steps. Use very plain language and examples. "
            "Avoid technical terms."
        )

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a Microsoft 365 trainer for beginners at TVA. Keep tone simple and non-technical."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=900
        )
        lesson_content = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ learn error: {e}")
        lesson_content = "⚠️ Sorry, we could not load your lesson right now. Please try again later."

    return render_template("learn.html", app=app_name.title(), lesson=lesson_content, user_topic=user_topic)

# ----------------------------
# Help Desk
# ----------------------------
@app.route('/help', methods=['GET', 'POST'])
def help_desk():
    answer = None
    user_question = ""
    if request.method == 'POST':
        user_question = _safe(request.form.get('user_question', ''))
        if user_question:
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": (
                            "You are an expert Microsoft 365 support agent for TVA employees. "
                            "Provide clear, plain-language, numbered steps to help solve their problem. "
                            "Avoid jargon."
                        )},
                        {"role": "user", "content": f"Issue: {user_question}"}
                    ],
                    temperature=0.3,
                    max_tokens=700
                )
                answer = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️ OpenAI error: {e}")
                answer = "⚠️ Sorry, we could not get an answer from the AI. Please try again later."
        else:
            answer = "Please enter your Microsoft 365 issue or question above."
    return render_template("help.html", answer=answer, user_question=user_question)

# ----------------------------
# Misc
# ----------------------------
@app.route('/ask_help', methods=['GET', 'POST'])
def ask_help():
    # Placeholder route kept for compatibility
    return render_template('home.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ----------------------------
# Run
# ----------------------------
if __name__ == '__main__':
    print("✅ SQN Copilot Companion running...")
    app.run(debug=True)
