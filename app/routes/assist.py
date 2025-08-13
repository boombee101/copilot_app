from flask import Blueprint, request, jsonify
from ..services.ai import ask_gpt, explain_question_plain
from ..services.history import log_prompt_row
from datetime import datetime

bp = Blueprint("assist", __name__)

@bp.route("/ask_gpt", methods=["POST"])
def ask_gpt_route():
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    out = ask_gpt(messages)
    return jsonify({"content": out})

@bp.route("/followups/next", methods=["POST"])
def next_followup():
    data = request.get_json(force=True)
    # you likely already have this logic in app.py; move it here.
    # Return the next question or final result in the same JSON shape as before.
    return jsonify({"question": "What Microsoft 365 app are you working in?"})

@bp.route("/followups/explain", methods=["POST"])
def explain_followup():
    data = request.get_json(force=True)
    question_text = data.get("question_text", "")
    app_label = data.get("app_context", "General")
    explanation = explain_question_plain(question_text, app_label)
    return jsonify({
        "explanation": explanation,
        "note": "You can skip this question if you are unsure."
    })

@bp.route("/history/log", methods=["POST"])
def log_history():
    data = request.get_json(force=True)
    row = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "app": data.get("app",""),
        "task": data.get("task",""),
        "prompt": data.get("prompt",""),
        "manual_summary": data.get("manual_summary","")
    }
    log_prompt_row(row)
    return jsonify({"ok": True})
