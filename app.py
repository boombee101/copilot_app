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
# Helpers
# =========================
def read_history(max_items=10):
    """Read last N prompt logs safely."""
    history = []
    try:
        with open('prompt_log/prompts.csv', mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            rows = list(reader)
            for row in reversed(rows[-max_items:]):
                if len(row) >= 3:
                    history.append({"task": row[0], "context": row[1], "prompt": row[2]})
    except Exception as e:
        print(f"⚠️ Failed to load prompt history: {e}")
    return history


def write_history(task, context, final_prompt):
    """Append a new log entry safely."""
    try:
        with open('prompt_log/prompts.csv', 'a', newline='', encoding='utf-8') as file:
            csv.writer(file).writerow([task, context, final_prompt])
    except Exception as e:
        print(f"⚠️ Failed to log prompt: {e}")


def split_helpdesk_sections(full_text):
    """
    Try to split model output into the 4 sections:
      Clarifying Questions, Numbered Steps, Copilot Prompt, Why This Works
    Returns (clarify, steps, prompt_text, why)
    If parsing fails, returns None for missing sections.
    """
    text = full_text.strip()
    pattern = r"(?im)^(?:\s*(?:\d+\)|\d+\.)?\s*(Clarifying Questions|Numbered Steps|Copilot Prompt|Why This Works)\s*:?\s*)$"
    parts = re.split(pattern, text)

    if len(parts) == 1:
        return (None, text, None, None)

    section_map = {}
    current = None
    body = []

    for i in range(1, len(parts)):
        piece = parts[i]
        if piece is None:
            continue
        if piece.strip() in ["Clarifying Questions", "Numbered Steps", "Copilot Prompt", "Why This Works"]:
            if current and body:
                section_map[current] = "\n".join(body).strip()
                body = []
            current = piece.strip()
        else:
            body.append(piece)

    if current and body:
        section_map[current] = "\n".join(body).strip()

    clarify = section_map.get("Clarifying Questions")
    steps   = section_map.get("Numbered Steps")
    promptt = section_map.get("Copilot Prompt")
    why     = section_map.get("Why This Works")
    return (clarify, steps, promptt, why)


# ========= Pretty formatters for AI text -> clean HTML cards =========
STEP_LINE = re.compile(r"^\s*(?:\d+[\.\)]\s+|\-\s+|\•\s+)(.+)$", re.IGNORECASE)

def format_steps_html(text: str) -> str:
    """
    Convert AI text with numbered/bulleted lines into clean HTML 'cards'.
    - Detects lines starting with '1. ', '1) ', '-', or '•'
    - Wraps each detected step in a .step block with a visible number
    - Any line with the word 'warning' becomes an orange warning card
    - Continuation lines are appended to the prior step
    """
    if not text:
        return ""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]

    steps = []
    n = 0
    for line in lines:
        m = STEP_LINE.match(line)
        body = m.group(1).strip() if m else line.strip()
        if m:
            n += 1
            is_warning = bool(re.search(r"\bwarning\b", body, re.IGNORECASE))
            steps.append({
                "num": n,
                "html": html_module.escape(body),
                "warning": is_warning
            })
        else:
            if steps:
                steps[-1]["html"] += "<br>" + html_module.escape(body)
            else:
                n += 1
                steps.append({"num": n, "html": html_module.escape(body), "warning": False})

    out = ['<div class="steps">']
    for s in steps:
        cls = "step warning" if s["warning"] else "step"
        out.append(f'<div class="{cls}"><span class="step-num">{s["num"]}</span> {s["html"]}</div>')
    out.append("</div>")
    return "\n".join(out)

def format_paragraphs_html(text: str) -> str:
    """Basic paragraph wrapper for non-step text."""
    if not text:
        return ""
    parts = [f"<p>{html_module.escape(p.strip())}</p>" for p in text.split("\n") if p.strip()]
    return "\n".join(parts)


# =========================
# Routes
# =========================
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


@app.route('/home', methods=['GET', 'POST'])
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    history = read_history(max_items=10)

    if request.method == 'POST':
        # Phase 1: Generate follow-up questions
        if 'task' in request.form and 'app' in request.form:
            task = request.form['task'].strip()
            app_selected = request.form['app'].strip()
            session['task'] = task
            session['app_selected'] = app_selected

            try:
                response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content":
                            f"You are a Copilot helper guiding a TVA employee using Microsoft {app_selected}. "
                            f"Break this vague task into very clear, non-technical follow-up questions."
                         },
                        {"role": "user", "content": f"The user said: '{task}'"}
                    ],
                    temperature=0.5,
                    max_tokens=600
                )
                raw = response.choices[0].message.content
                questions = [line.strip("-•1234567890. ").strip() for line in raw.splitlines() if line.strip()]
                questions = [q for q in questions if len(q) > 5][:10]
            except Exception as e:
                print(f"⚠️ Error generating questions: {e}")
                questions = ["⚠️ Error generating questions. Try again."]

            session['questions'] = questions
            return render_template(
                "home.html",
                questions=questions,
                original_task=task,
                app_selected=app_selected,
                history=history,
                active_page="home"
            )

        # Phase 2: Generate final Copilot prompt and manual steps
        elif 'original_task' in request.form:
            task = request.form['original_task'].strip()
            app_selected = session.get('app_selected', 'a Microsoft app')
            questions = session.get('questions', []) or []

            answers = []
            for i in range(len(questions)):
                ans = request.form.get(f'answer_{i}', '').strip()
                if ans:
                    answers.append(f"Q: {questions[i]}\nA: {ans}")
            context = "\n".join(answers) if answers else "No extra context provided."

            # Copilot prompt
            try:
                smart_prompt = (
                    f"Write a clear, work-appropriate Copilot prompt for Microsoft {app_selected}.\n\n"
                    f"Task:\n{task}\n\nContext:\n{context}"
                )
                response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content": "You are an expert prompt writer for Microsoft Copilot in Office apps."},
                        {"role": "user", "content": smart_prompt}
                    ],
                    temperature=0.5,
                    max_tokens=400
                )
                final_prompt = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️ Prompt error: {e}")
                final_prompt = "⚠️ Could not generate prompt."

            # Manual instructions
            try:
                manual_instructions_prompt = (
                    f"The user wants to complete this task manually in Microsoft {app_selected}:\n\n"
                    f"Task: {task}\n\nContext:\n{context}\n\n"
                    f"Write beginner-friendly, step-by-step instructions using very simple language."
                )
                manual_response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a helpful trainer writing clear, non-technical instructions."},
                        {"role": "user", "content": manual_instructions_prompt}
                    ],
                    temperature=0.6,
                    max_tokens=700
                )
                manual_instructions = manual_response.choices[0].message.content.strip()
                manual_instructions_html = format_steps_html(manual_instructions)
            except Exception as e:
                print(f"⚠️ Manual error: {e}")
                manual_instructions = "⚠️ Could not generate manual steps."
                manual_instructions_html = ""
            write_history(task, context, final_prompt)

            return render_template(
                "home.html",
                final_prompt=final_prompt,
                app_selected=app_selected,
                task=task,
                context=context,
                manual_instructions=manual_instructions,          # original text (kept)
                manual_instructions_html=manual_instructions_html,# pretty cards
                history=history,
                active_page="home"
            )

    # GET
    return render_template("home.html", history=history, active_page="home")


@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    try:
        data = request.get_json()
        question = (data.get('question') or '').strip()
        if not question:
            return jsonify({"answer": "Please enter a question."})

        response = client.chat_completions.create(  # backward compatibility if needed
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant supporting Microsoft 365 users at TVA."},
                {"role": "user", "content": question}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return jsonify({"answer": response.choices[0].message.content.strip()})
    except Exception:
        # Use the current API style
        try:
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant supporting Microsoft 365 users at TVA."},
                    {"role": "user", "content": question}
                ],
                temperature=0.5,
                max_tokens=300
            )
            return jsonify({"answer": response.choices[0].message.content.strip()})
        except Exception as e2:
            print(f"⚠️ ask_gpt error: {e2}")
            return jsonify({"answer": "⚠️ Failed to respond. Try again later."})


@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
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
        return jsonify({"manual_steps": response.choices[0].message.content.strip()})
    except Exception as e:
        print(f"⚠️ manual API error: {e}")
        return jsonify({"manual_steps": "⚠️ Manual instructions unavailable."})


@app.route('/learn/<app_name>', methods=['GET', 'POST'])
def learn_app(app_name):
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
        lesson_content = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ learn error: {e}")
        lesson_content = "⚠️ Sorry, we couldn’t load your lesson right now. Please try again later."

    return render_template("learn.html",
                           app=app_name_l.title(),
                           lesson=lesson_content,
                           user_topic=user_topic,
                           active_page=f"learn_{app_name_l}")

@app.route('/teach_me', methods=['GET', 'POST'])
def teach_me():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        # form select named "app" from teach_me.html
        chosen = (request.form.get('app') or '').strip().lower()
        valid = {'word', 'excel', 'outlook', 'teams', 'powerpoint'}
        if chosen.lower() in valid:
            return redirect(url_for('learn_app', app_name=chosen))
        # if nothing valid selected, just reload page
    return render_template('teach_me.html', active_page='teach_me')



@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


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
            result = resp.choices[0].message.content.strip()
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


# ======== HELP DESK (RESTORED SIMPLE ONE-BOX FLOW) ========
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
                answer = response.choices[0].message.content.strip()
                answer_html = format_steps_html(answer)
            except Exception as e:
                print(f"⚠️ Help Desk error: {e}")
                answer = "⚠️ Sorry, there was an error fetching help. Please try again."
                answer_html = ""

    return render_template("help.html",
                           answer=answer,           # original text
                           answer_html=answer_html, # pretty cards
                           active_page="help")


# ------- Prompt Builder -------
@app.route("/prompt_builder", methods=["GET", "POST"])
def prompt_builder():
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
# Microsoft 365 Troubleshooter
# =========================

# Network keyword check to nudge users to TVA IT when it looks like connectivity
NETWORK_KEYWORDS = [
    "network", "offline", "no internet", "cannot connect", "connection lost",
    "proxy", "vpn", "firewall", "gateway", "dns", "ssl", "tls", "server unreachable",
    "status.microsoft", "service health", "outage"
]

def _looks_network_related(text: str) -> bool:
    text = (text or "").lower()
    return any(k in text for k in NETWORK_KEYWORDS)

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
            text = resp.choices[0].message.content.strip()

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
# Main
# =========================
if __name__ == '__main__':
    print("✅ SQN Copilot Companion running...")
    app.run(debug=True)
