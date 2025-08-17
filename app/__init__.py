from flask import Flask
import os

def create_app():
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    # Import routes AFTER app is created
    from . import routes
    return app
