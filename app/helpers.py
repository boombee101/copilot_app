from flask import request
from openai import OpenAI
import os, csv, html as html_module

# =========================
# Configuration
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")

client = OpenAI(api_key=OPENAI_API_KEY)

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
