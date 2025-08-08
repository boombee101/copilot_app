from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv
import re

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
    # Normalize line endings
    text = full_text.strip()

    # Create a robust split by recognized headings (tolerates numbering and colons)
    pattern = r"(?im)^(?:\s*(?:\d+\)|\d+\.)?\s*(Clarifying Questions|Numbered Steps|Copilot Prompt|Why This Works)\s*:?\s*)$"
    parts = re.split(pattern, text)

    # parts structure after split: [pre, H1, body1, H2, body2, ...]
    if len(parts) == 1:
        # No headings detected; treat entire text as "Numbered Steps"
        return (None, text, None, None)

    section_map = {}
    current = None
    body = []

    # Start at index 1 to skip any preface
    for i in range(1, len(parts)):
        piece = parts[i]
        if piece is None:
            continue
        if piece.strip() in ["Clarifying Questions", "Numbered Steps", "Copilot Prompt", "Why This Works"]:
            # Save previous section
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
                history=history
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
            except Exception as e:
                print(f"⚠️ Manual error: {e}")
                manual_instructions = "⚠️ Could not generate manual steps."

            write_history(task, context, final_prompt)

            return render_template(
                "home.html",
                final_prompt=final_prompt,
                app_selected=app_selected,
                task=task,
                context=context,
                manual_instructions=manual_instructions,
                history=history
            )

    # GET
    return render_template("home.html", history=history)


@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
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
        return jsonify({"answer": response.choices[0].message.content.strip()})
    except Exception as e:
        print(f"⚠️ ask_gpt error: {e}")
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
            "The tone should be friendly and for-dummies style."
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

    return render_template("learn.html", app=app_name_l.title(), lesson=lesson_content, user_topic=user_topic)


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
        except Exception as e:
            print(f"⚠️ ask_help AI error: {e}")
            result = "⚠️ Sorry, we could not generate help right now. Try again."

    return render_template(
        'ask_help.html',
        app_selected=app_selected or 'Word',
        problem=problem or '',
        result=result
    )


@app.route('/help', methods=['GET', 'POST'])
def help_desk():
    """
    Rebuilt Help Desk with Guided + Quick modes and structured output:
      1) Clarifying Questions (if needed)
      2) Numbered Steps
      3) Copilot Prompt
      4) Why This Works
    """
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    answer = None
    prompt_text = None
    why_text = None
    user_question = ""

    try:
        mode = (request.form.get('mode') or '').strip()

        if request.method == 'POST' and mode == 'guided':
            app_sel   = (request.form.get('app_select') or '').strip()
            issue_type = (request.form.get('issue_type') or '').strip()
            symptoms  = (request.form.get('symptoms') or '').strip()
            tried     = (request.form.get('tried') or '').strip()
            user_question = f"App: {app_sel}\nIssue Type: {issue_type}\nSymptoms: {symptoms}\nTried: {tried}"

        elif request.method == 'POST' and mode == 'quick':
            user_question = (request.form.get('user_question') or '').strip()

        if request.method == 'POST':
            if not user_question:
                answer = "Please describe your Microsoft 365 issue on the left."
            else:
                prompt = (
                    "You are a Microsoft 365 support agent for TVA employees. "
                    "Return the following sections in this exact order and with those headings:\n\n"
                    "Clarifying Questions\n"
                    "Numbered Steps\n"
                    "Copilot Prompt\n"
                    "Why This Works\n\n"
                    "Rules: Avoid jargon, no sensitive data. Use short sentences. "
                    "Tailor the steps to the user's details. If they tried things already, incorporate that.\n\n"
                    f"User details:\n{user_question}\n"
                )

                resp = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content": "Be direct, clear, beginner-friendly. Always produce the 4 sections listed, even if some are brief."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=900
                )
                full = resp.choices[0].message.content.strip()

                clarify, steps, copilot_p, whyw = split_helpdesk_sections(full)

                # In the UI we primarily show steps, then prompt, then why.
                answer = steps or full
                prompt_text = copilot_p
                why_text = whyw

    except Exception as e:
        print(f"⚠️ Help Desk error: {e}")
        answer = "⚠️ Sorry, we couldn't get an answer from the AI. Please try again later."

    return render_template("help.html",
                           answer=answer,
                           prompt_text=prompt_text,
                           why_text=why_text,
                           user_question=user_question)


# =========================
# Main
# =========================
if __name__ == '__main__':
    print("✅ SQN Copilot Companion running...")
    app.run(debug=True)
