from flask import Flask
import os

def create_app():
    """Initialize Flask app and register routes."""
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    # Import routes AFTER app is created
    from .routes import init_routes
    init_routes(app)

    return app
