from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import os
import csv
import json

# Load environment variables
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False

# Setup OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Incorrect password")
    return render_template('login.html')

@app.route('/home', methods=['GET', 'POST'])
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    history = []
    try:
        with open('prompt_log/prompts.csv', mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reversed(list(reader))[-10:]:
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
                            f"You are a prompt assistant helping non-technical TVA employees use Microsoft {app_selected}. "
                            "Break their vague task into extremely clear, detailed follow-up questions. "
                            "Write the questions in plain language, like you're guiding someone with no technical background. "
                            "Avoid jargon. If the task is about searching emails, use wording like: 'What are you trying to find in the emails?' "
                            "Be supportive and step-by-step. Output only the questions."
                        )},
                        {"role": "user", "content": f"The user said: '{task}'"}
                    ],
                    temperature=0.6,
                    max_tokens=700
                )
                raw = response.choices[0].message.content
                questions = [line.strip("-•1234567890. ").strip() for line in raw.splitlines() if line.strip()]
                questions = [q for q in questions if len(q) > 5][:10]
            except Exception as e:
                print(f"⚠️ Error generating follow-up questions: {e}")
                questions = ["Something went wrong. Please try again."]

            session['questions'] = questions
            return render_template("home.html", questions=questions, original_task=task, app_selected=app_selected, history=history)

        elif 'original_task' in request.form:
            task = request.form['original_task']
            app_selected = session.get('app_selected', 'a Microsoft app')
            questions = session.get('questions', [])
            answers = [f"Q: {questions[i]}\nA: {request.form.get(f'answer_{i}', '').strip()}" for i in range(len(questions)) if request.form.get(f'answer_{i}', '').strip()]
            context = "\n".join(answers) if answers else "No extra info provided."

            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": (
                            f"You are a Microsoft Copilot assistant helping TVA staff using {app_selected}. "
                            "Write the clearest, most helpful prompt possible based on their original task and clarified answers."
                        )},
                        {"role": "user", "content": f"Original Task: {task}\n\nClarified Context:\n{context}"}
                    ],
                    temperature=0.5,
                    max_tokens=400
                )
                final_prompt = response.choices[0].message.content.strip()
            except Exception as e:
                final_prompt = "⚠️ Something went wrong."
                print(f"⚠️ Error generating final prompt: {e}")

            try:
                with open('prompt_log/prompts.csv', mode='a', newline='', encoding='utf-8') as file:
                    csv.writer(file).writerow([task, context, final_prompt])
            except Exception as e:
                print(f"⚠️ Error saving prompt: {e}")

            return render_template("home.html", final_prompt=final_prompt, app_selected=app_selected, task=task, context=context, history=history)

    return render_template("home.html", history=history)

@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
    try:
        data = request.get_json()
        task = data.get('task', '')
        context = data.get('context', '')
        app_selected = data.get('app_selected', 'a Microsoft app')

        prompt = (
            f"You are a friendly technical assistant for employees at TVA who are not familiar with Microsoft {app_selected}. "
            f"The user wants to complete this task manually, without using Copilot:\n\n"
            f"Task: {task}\n\nAdditional Details:\n{context}\n\n"
            "Write step-by-step instructions in very simple, beginner-friendly language. "
            "Break it down clearly. Assume they don’t know anything technical. Avoid jargon."
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You help people understand how to do Microsoft 365 tasks manually using clear, simple steps."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=600
        )
        manual_steps = response.choices[0].message.content.strip()
        return jsonify({"manual_steps": manual_steps})
    except Exception as e:
        print(f"⚠️ /how_to_manual error: {e}")
        return jsonify({"manual_steps": "⚠️ Failed to generate instructions. Please try again."})

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        if not question:
            return jsonify({"answer": "Please enter a valid question."})

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": (
                    "You're a friendly assistant guiding non-technical users at TVA to ask good Microsoft Copilot questions. "
                    "Keep your response short, clear, and beginner-friendly."
                )},
                {"role": "user", "content": question}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return jsonify({"answer": response.choices[0].message.content.strip()})
    except Exception as e:
        print(f"⚠️ /ask_gpt error: {e}")
        return jsonify({"answer": "⚠️ GPT error. Try again later."})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    print("✅ TVA Copilot Assistant running...")
    app.run(debug=True)
