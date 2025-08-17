# app/__init__.py
from flask import Flask
import os

def create_app():
    app = Flask(
        __name__,
        template_folder="templates",  # app/templates
        static_folder="static"        # app/static
    )
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    # Optional: simple health check
    @app.get("/health")
    def health():
        return "ok", 200

    # Import routes AFTER app is created
    from .routes import init_routes
    init_routes(app)

    return app
