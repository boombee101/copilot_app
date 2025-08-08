from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv

# Load environment variables
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
client = OpenAI(api_key=OPENAI_API_KEY)

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

    history = []
    try:
        with open('prompt_log/prompts.csv', mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            rows = list(reader)
            for row in reversed(rows[-10:]):
                if len(row) >= 3:
                    history.append({"task": row[0], "context": row[1], "prompt": row[2]})
    except Exception as e:
        print(f"⚠️ Failed to load prompt history: {e}")

    if request.method == 'POST':
        if 'task' in request.form and 'app' in request.form:
            task = request.form['task']
            app_selected = request.form['app']
            session['task'] = task
            session['app_selected'] = app_selected

            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": (
                            f"You are a Copilot helper guiding a TVA employee using Microsoft {app_selected}. "
                            f"Break this vague task into very clear, non-technical follow-up questions."
                        )},
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
            return render_template("home.html", questions=questions, original_task=task, app_selected=app_selected, history=history)

        elif 'original_task' in request.form:
            task = request.form['original_task']
            app_selected = session.get('app_selected', 'a Microsoft app')
            questions = session.get('questions', [])
            answers = [f"Q: {questions[i]}\nA: {request.form.get(f'answer_{i}', '')}" for i in range(len(questions)) if request.form.get(f'answer_{i}', '')]
            context = "\n".join(answers) if answers else "No extra context provided."

            try:
                smart_prompt = (
                    f"Write a clear, work-appropriate Copilot prompt for Microsoft {app_selected}.\n\n"
                    f"Task:\n{task}\n\nContext:\n{context}"
                )
                response = client.chat.completions.create(
                    model="gpt-4",
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

            try:
                manual_instructions_prompt = (
                    f"The user wants to complete this task manually in Microsoft {app_selected}:\n\n"
                    f"Task: {task}\n\nContext:\n{context}\n\n"
                    f"Write beginner-friendly, step-by-step instructions using very simple language."
                )
                manual_response = client.chat.completions.create(
                    model="gpt-4",
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

            try:
                with open('prompt_log/prompts.csv', 'a', newline='', encoding='utf-8') as file:
                    csv.writer(file).writerow([task, context, final_prompt])
            except Exception as e:
                print(f"⚠️ Failed to log prompt: {e}")

            return render_template("home.html", final_prompt=final_prompt, app_selected=app_selected, task=task, context=context, manual_instructions=manual_instructions, history=history)

    return render_template("home.html", history=history)

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        if not question:
            return jsonify({"answer": "Please enter a question."})

        response = client.chat.completions.create(
            model="gpt-4",
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
        task = data.get('task', '')
        context = data.get('context', '')
        app_selected = data.get('app_selected', 'a Microsoft app')

        prompt = (
            f"The user wants to manually complete this task in Microsoft {app_selected}:\n\n"
            f"Task: {task}\n\nContext:\n{context}\n\n"
            "Write detailed, beginner-friendly instructions with plain language."
        )

        response = client.chat.completions.create(
            model="gpt-4",
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

    app_name = app_name.lower()
    valid_apps = ['word', 'excel', 'outlook', 'teams', 'powerpoint']
    if app_name not in valid_apps:
        return "Invalid app", 404

    user_topic = request.form.get('topic', '').strip() if request.method == 'POST' else ""

    if user_topic:
        prompt = (
            f"You are teaching a total beginner how to use Microsoft {app_name.title()} to do this:\n"
            f"'{user_topic}'\n\n"
            "Use a step-by-step format with super simple explanations, plain language, and zero technical jargon. "
            "Make it feel like a helpful live training session for a TVA employee who has never used the app before."
        )
    else:
        prompt = (
            f"You're teaching a brand new TVA employee how to use Microsoft {app_name.title()} from scratch. "
            "Assume they have zero experience. Walk them through it slowly, like a beginner class. "
            "Use very plain language, examples, and short, clear steps. No technical terms. "
            "The tone should be friendly and for-dummies style."
        )

    try:
        response = client.chat.completions.create(
            model="gpt-4",
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

    return render_template("learn.html", app=app_name.title(), lesson=lesson_content, user_topic=user_topic)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/ask_help', methods=['GET', 'POST'])
def ask_help():
    # For now, just redirect to home or show a placeholder
    return render_template('home.html')


if __name__ == '__main__':
    print("✅ SQN Copilot Companion running...")
    app.run(debug=True)
