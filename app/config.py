import os
from dotenv import load_dotenv

def configure_settings(app):
    load_dotenv()
    app.config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
    app.config["APP_PASSWORD"]   = os.getenv("APP_PASSWORD")
    app.config["DEFAULT_MODEL"]  = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    app.config["PROMPTS_CSV"]    = os.getenv("PROMPTS_CSV", "prompts.csv")
