from flask import Flask
from dotenv import load_dotenv
import os

# =========================
# App & configuration
# =========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APP_PASSWORD   = os.getenv("APP_PASSWORD")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")

def create_app():
    """Factory function for Flask app."""
    app = Flask(__name__)
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    # Register routes from routes.py
    from app.routes import init_routes
    init_routes(app)

    return app
