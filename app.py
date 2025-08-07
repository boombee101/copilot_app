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
                            f"You are helping a non-technical TVA employee write a better Copilot prompt for Microsoft {app_selected}. "
                            "Ask follow-up questions in very plain English to clarify what they want to do. "
                            "Imagine they’ve never used Copilot before. Keep the questions friendly, clear, and simple — like you're walking them through the task. "
                            "List the questions as plain numbered sentences. Only return the list of questions."
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
    f"You are an expert Microsoft Copilot prompt engineer helping a non-technical TVA employee. "
    f"The user is working in **{app_selected}**. Their goal is to accomplish a specific task, and you have their clarified input below. "
    "Your job is to create one excellent Copilot prompt tailored for that Microsoft app — short, clear, and formatted like a real Copilot command.\n\n"
    "DO:\n"
    "- Write only the Copilot prompt (no extra explanation)\n"
    "- Start with an action word like 'Summarize', 'Extract', 'Draft', 'Find', etc.\n"
    "- Include any important keywords, names, filters, or context mentioned\n"
    "- Use terms specific to the selected app (e.g., files/folders for SharePoint, messages for Teams, emails for Outlook)\n"
    "DO NOT:\n"
    "- Do not repeat the question or context\n"
    "- Do not say 'Here's your prompt:' or 'Based on your input...'\n\n"
    "The result should look like a polished, ready-to-use command that could be pasted directly into Copilot."
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

            return render_template("home.html", final_prompt=final_prompt, app_selected=app_selected, history=history)

    return render_template("home.html", history=history)

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
                    "You are a Copilot assistant at TVA. Answer user questions clearly and simply, as if you're helping someone who just started using Copilot today."
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
