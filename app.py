from flask import Flask, request
from dotenv import load_dotenv
from openai import OpenAI
import os, csv, html as html_module

# =========================
# App & configuration
# =========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD   = os.getenv("APP_PASSWORD")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")

client = OpenAI(api_key=OPENAI_API_KEY)

def create_app():
    """Factory function for Flask app."""
    app = Flask(__name__)
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    # Register routes from routes.py
    from app.routes import init_routes
    init_routes(app)

    return app

os.makedirs('prompt_log', exist_ok=True)

# =========================
# Helpers
# =========================
def ai_chat(messages):
    """Small wrapper to call OpenAI chat."""
    resp = client.chat.completions.create(model=DEFAULT_MODEL, messages=messages)
    return resp.choices[0].message.content.strip()

def get_data():
    """Merge JSON body and form data safely."""
    data = request.get_json(silent=True) or {}
    for k, v in request.form.items():
        data.setdefault(k, v)
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}

def log_prompt_to_csv(task, copilot_prompt, manual_steps):
    """Log generated prompts to CSV in prompt_log/prompts.csv"""
    csv_path = os.path.join('prompt_log', 'prompts.csv')
    with open(csv_path, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([task, copilot_prompt, manual_steps])
