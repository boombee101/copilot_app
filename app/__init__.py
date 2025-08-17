# app/__init__.py

import importlib

def create_app():
    """
    Factory function that imports the root app.py Flask instance
    so Gunicorn and wsgi.py can find it.
    """
    app_module = importlib.import_module("app")  # this finds app.py at root
    return app_module.app
