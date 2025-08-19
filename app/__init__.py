# app/__init__.py
from flask import Flask
import os

def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    @app.get("/health")
    def health():
        return "ok", 200

    # Import routes after app is created
    from .routes import init_routes
    init_routes(app)

    return app
