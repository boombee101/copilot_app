from openai import OpenAI
from flask import current_app

def _client():
    api_key = current_app.config["OPENAI_API_KEY"]
    return OpenAI(api_key=api_key)

def ask_gpt(messages, model=None):
    client = _client()
    mdl = model or current_app.config["DEFAULT_MODEL"]
    resp = client.chat.completions.create(model=mdl, messages=messages, temperature=0.3)
    return resp.choices[0].message.content.strip()

def explain_question_plain(question_text, app_context_label):
    """Return a for-dummies style explanation of the follow-up question."""
    system = {
        "role": "system",
        "content": (
            "You are a patient Microsoft 365 coach for TVA employees. "
            "Explain the question in simple, friendly terms. "
            "Give 1–2 short examples. End with a note that the user can skip."
        )
    }
    user = {
        "role": "user",
        "content": (
            f"App context: {app_context_label}\n"
            f"Follow-up question to explain: {question_text}\n"
            "Write in plain language, short sentences."
        )
    }
    return ask_gpt([system, user])
