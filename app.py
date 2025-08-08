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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/learn/<app_name>', methods=['GET', 'POST'])
def learn_app(app_name):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    app_name = app_name.lower()
    valid_apps = ['word', 'excel', 'outlook', 'teams', 'powerpoint']
    if app_name not in valid_apps:
        return "Invalid app", 404

    lesson_content = ""
    user_topic = ""

    if request.method == 'POST':
        user_topic = request.form.get('topic', '').strip()
        if user_topic:
            prompt = (
                f"You are a friendly Microsoft 365 trainer helping a total beginner at TVA learn {app_name.title()}. "
                f"Explain the topic: '{user_topic}' using step-by-step, plain-language instructions. "
                "Avoid technical jargon. Write like you're teaching someone with no experience. Be very detailed and supportive."
            )
        else:
            prompt = (
                f"Teach a complete beginner how to use Microsoft {app_name.title()}. "
                "Write a full, clear, detailed lesson. Use simple words and short steps. "
                "Assume no prior knowledge. Make it feel like a live class for someone who has never used the app before."
            )

        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a patient trainer who teaches Microsoft 365 apps in a beginner-friendly, for-dummies style."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=900
            )
            lesson_content = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"⚠️ AI Lesson Error: {e}")
            lesson_content = "⚠️ Sorry, something went wrong while generating your lesson."

    return render_template("learn.html", app=app_name.title(), lesson=lesson_content, user_topic=user_topic)


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
                            "Break their vague task into extremely clear, detailed follow-up questions. Use plain, supportive language."
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
                smart_prompt = (
                    f"The user wants help using Microsoft Copilot in {app_selected}. Based on the goal and context below, write a clear, workplace-friendly prompt for Microsoft Copilot. "
                    f"Do not write code. Assume the user is non-technical.\n\nTask:\n{task}\n\nContext:\n{context}"
                )
                prompt_response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": (
                            "You are an expert at writing Microsoft Copilot prompts for Office apps (Word, Excel, Outlook, Teams). "
                            "Keep it simple, natural, and work-focused."
                        )},
                        {"role": "user", "content": smart_prompt}
                    ],
                    temperature=0.5,
                    max_tokens=400
                )
                final_prompt = prompt_response.choices[0].message.content.strip()
            except Exception as e:
                final_prompt = "⚠️ Something went wrong."
                print(f"⚠️ Error generating final prompt: {e}")

            try:
                manual_prompt = (
                    f"The user needs to do the following task in Microsoft {app_selected} without Copilot:\n\n"
                    f"Task: {task}\n\nContext:\n{context}\n\n"
                    "Write step-by-step instructions in plain language that a beginner could follow."
                )
                manual_response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are an expert at writing easy-to-follow Microsoft 365 instructions for beginners."},
                        {"role": "user", "content": manual_prompt}
                    ],
                    temperature=0.6,
                    max_tokens=600
                )
                manual_instructions = manual_response.choices[0].message.content.strip()
            except Exception as e:
                manual_instructions = "⚠️ Failed to generate manual instructions."
                print(f"⚠️ Manual instructions error: {e}")

            try:
                with open('prompt_log/prompts.csv', mode='a', newline='', encoding='utf-8') as file:
                    csv.writer(file).writerow([task, context, final_prompt])
            except Exception as e:
                print(f"⚠️ Error saving prompt: {e}")

            return render_template("home.html", final_prompt=final_prompt, app_selected=app_selected, task=task, context=context, manual_instructions=manual_instructions, history=history)

    return render_template("home.html", history=history)

@app.route('/how_to_manual', methods=['POST'])
def how_to_manual():
    try:
        data = request.get_json()
        task = data.get('task', '')
        context = data.get('context', '')
        app_selected = data.get('app_selected', 'a Microsoft app')

        prompt = (
            f"You are a friendly assistant for employees at TVA who are not familiar with Microsoft {app_selected}. "
            f"The user wants to complete this task manually:\n\nTask: {task}\n\nContext:\n{context}\n\n"
            "Write step-by-step instructions in very simple, beginner-friendly language. Avoid jargon."
        )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You help people understand Microsoft 365 using clear, simple steps."},
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
                    "You're a helpful assistant guiding non-technical users at TVA to write good Microsoft Copilot tasks."
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

@app.route('/learn/<app_name>')
def learn_app(app_name):
    lessons = {
        'word': {
            "summary": "Microsoft Word is used for creating and formatting documents such as reports, letters, and forms.",
            "copilot_uses": [
                "Summarize long documents",
                "Fix grammar or improve tone",
                "Generate drafts based on meeting notes",
                "Insert tables or headings automatically"
            ],
            "manual_tip": "To insert a table in Word: Click 'Insert' > 'Table' > Select size.",
            "prompt_example": "Summarize this document into bullet points for a quick briefing."
        },
        'excel': {
            "summary": "Microsoft Excel is used for data organization, calculations, charts, and financial tracking.",
            "copilot_uses": [
                "Generate charts from tables",
                "Summarize data trends",
                "Write formulas for tasks",
                "Clean up inconsistent data"
            ],
            "manual_tip": "To create a chart: Select data > Click 'Insert' > Choose a chart type.",
            "prompt_example": "Create a bar chart showing monthly sales totals from this sheet."
        },
        'outlook': {
            "summary": "Microsoft Outlook is used for email communication, calendars, and scheduling.",
            "copilot_uses": [
                "Summarize email threads",
                "Draft responses",
                "Find important deadlines",
                "Schedule meetings"
            ],
            "manual_tip": "To schedule a meeting: Go to Calendar > New Event > Add attendees and time.",
            "prompt_example": "Draft a polite reply confirming attendance at the meeting on Friday."
        },
        'teams': {
            "summary": "Microsoft Teams is used for chat, meetings, and collaboration within TVA teams.",
            "copilot_uses": [
                "Summarize chat threads",
                "Extract action items from meetings",
                "Create agendas or notes",
                "Draft announcements"
            ],
            "manual_tip": "To start a new post: Go to the channel > Click 'New conversation'.",
            "prompt_example": "Summarize this Teams conversation into 3 key decisions and next steps."
        },
        'powerpoint': {
            "summary": "Microsoft PowerPoint is used for creating slide-based presentations.",
            "copilot_uses": [
                "Generate slide outlines",
                "Summarize reports into slides",
                "Fix formatting or layout",
                "Add speaker notes"
            ],
            "manual_tip": "To add a slide: Click 'New Slide' > Choose a layout.",
            "prompt_example": "Create a 5-slide summary of our safety report with bullet points and visuals."
        }
    }

    content = lessons.get(app_name.lower())
    if not content:
        return "App not found", 404

    return render_template("learn.html", app=app_name.title(), content=content)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    print("✅ TVA Copilot Assistant running...")
    app.run(debug=True)
