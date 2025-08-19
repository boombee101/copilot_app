# app/__init__.py
"""
Initialize the app package.

This file marks the folder as a Python package so imports like
`from app import create_app` work correctly.
"""

from .app import create_app  # import the factory from app.py
