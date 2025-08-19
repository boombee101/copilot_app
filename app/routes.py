# app/routes.py
from flask import render_template, request, redirect, session, url_for, jsonify
import os
from app.helpers import ai_chat, get_data, log_prompt_to_csv

# Load APP_PASSWORD from environment
APP_PASSWORD = os.getenv("APP_PASSWORD")

def init_routes(app):
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
                # reset conversation state for prompt builder
                session['pb_convo'] = []
                session['pb_clarifications'] = 0
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
    # Prompt Builder
    # =========================
    @app.route('/prompt_builder')
    def prompt_builder():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return render_template('prompt_builder.html')

    @app.route('/pb_start', methods=['POST'])
    def pb_start():
        """Start a new prompt builder session."""
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = get_data()
        app_choice = (data.get("app") or "").strip()
        goal = (data.get("goal") or "").strip()

        if not app_choice or not goal:
            return jsonify({"error": "Missing app or goal"}), 400

        # reset conversation
        session['pb_convo'] = [
            {"role": "system", "content": (
                "You are an assistant that helps build perfect Microsoft Copilot prompts. "
                "Ask smart, beginner-friendly follow-up questions in plain language (like a 'for dummies' guide). "
                "Keep them clear and simple. Do NOT finalize until explicitly asked. "
                "When finalizing, output exactly two sections:\n\n"
                "===COPILOT PROMPT===\nFinal Copilot prompt.\n\n"
                "===MANUAL STEPS===\nStep-by-step beginner instructions."
            )},
            {"role": "user", "content": f"App: {app_choice}\nGoal: {goal}"}
        ]
        session['pb_clarifications'] = 0

        reply = ai_chat(session['pb_convo'])
        session['pb_convo'].append({"role": "assistant", "content": reply})
        session['pb_clarifications'] += 1

        return jsonify({"reply": reply})

    @app.route('/pb_reply', methods=['POST'])
    def pb_reply():
        """Handle user reply or detect final output inline."""
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = get_data()
        user_reply = (data.get("message") or "").strip()

        if not user_reply:
            return jsonify({"error": "Missing message"}), 400

        convo = session.get('pb_convo', [])
        convo.append({"role": "user", "content": user_reply})

        reply = ai_chat(convo)
        convo.append({"role": "assistant", "content": reply})
        session['pb_convo'] = convo
        session['pb_clarifications'] = session.get('pb_clarifications', 0) + 1

        # Detect if model finalized inside the chat
        if "===COPILOT PROMPT===" in reply:
            parts = reply.split("===MANUAL STEPS===")
            copilot_text = parts[0].replace("===COPILOT PROMPT===", "").strip()
            manual_text = parts[1].strip() if len(parts) > 1 else ""

            try:
                log_prompt_to_csv(copilot_text, copilot_text, manual_text)
            except Exception as e:
                print("⚠️ Failed to log prompt:", e)

            return jsonify({
                "finalized": True,
                "copilot": copilot_text,
                "manual": manual_text
            })

        return jsonify({"reply": reply})

    @app.route('/pb_finalize', methods=['POST'])
    def pb_finalize():
        """Generate the final Copilot prompt and manual instructions."""
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        convo = session.get('pb_convo', [])
        convo.append({
            "role": "user",
            "content": (
                "Finalize now. IMPORTANT: Provide output in exactly two sections:\n\n"
                "===COPILOT PROMPT===\nOnly the Copilot prompt.\n\n"
                "===MANUAL STEPS===\nOnly manual beginner steps."
            )
        })

        final = ai_chat(convo)
        convo.append({"role": "assistant", "content": final})
        session['pb_convo'] = convo

        copilot_text, manual_text = "", ""
        if "===MANUAL STEPS===" in final:
            parts = final.split("===MANUAL STEPS===")
            copilot_text = parts[0].replace("===COPILOT PROMPT===", "").strip()
            manual_text = parts[1].strip()
        else:
            copilot_text = final.strip()

        try:
            log_prompt_to_csv(copilot_text, copilot_text, manual_text)
        except Exception as e:
            print("⚠️ Failed to log prompt:", e)

        return jsonify({"copilot": copilot_text, "manual": manual_text})

    # =========================
    # Explain Prompt / Explain Question
    # =========================
    @app.route('/explain_prompt', methods=['POST'])
    def explain_prompt():
        """Explain the FINAL Copilot prompt in beginner-friendly terms."""
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = get_data()
        prompt_text = (data.get("prompt") or "").strip()
        if not prompt_text:
            return jsonify({"explanation": "No prompt provided to explain."})

        convo = [
            {"role": "system", "content": (
                "You explain Microsoft Copilot prompts to beginners. "
                "Write a short, friendly explanation that covers:\n"
                "1) What this prompt will make Copilot do\n"
                "2) What info it assumes / needs\n"
                "3) Any data-safety or privacy cautions for a workplace\n"
                "4) 2–3 optional tweaks to improve the prompt\n"
                "Use plain language and short bullet points."
            )},
            {"role": "user", "content": f"Explain this Copilot prompt:\n{prompt_text}"}
        ]
        explanation = ai_chat(convo)
        return jsonify({"explanation": explanation})

    @app.route('/explain_question', methods=['POST'])
    def explain_question():
        """Explain why AI asked a clarifying question (kept for the clarifications UI)."""
        if not session.get('logged_in'):
            return jsonify({"error": "Not logged in"}), 403

        data = get_data()
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"explanation": "This follow-up is asking for more detail so the prompt is precise."})

        convo = [
            {"role": "system", "content": (
                "You are an assistant explaining to beginners why a specific clarifying question is useful "
                "for building a better Microsoft Copilot prompt. Keep your explanation simple and supportive."
            )},
            {"role": "user", "content": f"Why is this question important? -> {question}"}
        ]
        explanation = ai_chat(convo)
        return jsonify({"explanation": explanation})

    # =========================
    # Help / Tools Pages
    # =========================
    @app.route('/help')
    def help():
        """General Help page (overview + quick AI Q&A)."""
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return render_template('help.html')

    @app.route('/ask_help', methods=['GET', 'POST'])
    def ask_help():
        """AI Troubleshooter page."""
        if not session.get('logged_in'):
            return redirect(url_for('login'))

        app_selected = ""
        problem = ""
        result = None

        if request.method == 'POST':
            app_selected = (request.form.get("app") or "").strip()
            problem = (request.form.get("problem") or "").strip()

            if not app_selected or not problem:
                result = "⚠️ Please select an app and describe the problem."
            else:
                convo = [
                    {"role": "system", "content": (
                        "You are a helpful Microsoft 365 troubleshooter. "
                        "Given an app name and a problem, respond in plain language with clear, numbered steps. "
                        "Keep it beginner-friendly, like a 'for dummies' guide. "
                        "If the problem looks network-related, advise the user to contact TVA IT support."
                    )},
                    {"role": "user", "content": f"App: {app_selected}\nProblem: {problem}"}
                ]
                result = ai_chat(convo)

        return render_template(
            'ask_help.html',
            app_selected=app_selected,
            problem=problem,
            result=result
        )

    @app.route('/troubleshooter')
    def troubleshooter():
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return render_template('troubleshooter.html')

    @app.route('/teach_me', methods=['GET', 'POST'])
    def teach_me():
        if not session.get('logged_in'):
            return redirect(url_for('login'))

        lesson = None
        if request.method == 'POST':
            app_choice = (request.form.get("app") or "").strip()
            if app_choice:
                convo = [
                    {"role": "system", "content": (
                        "You are a Microsoft 365 tutor. "
                        "When asked about an app, explain it step-by-step in a simple 'for dummies' style. "
                        "Keep it friendly, beginner-focused, and clear."
                    )},
                    {"role": "user", "content": f"Teach me the basics of {app_choice}. Explain step by step."}
                ]
                lesson = ai_chat(convo)

        return render_template('teach_me.html', lesson=lesson)
