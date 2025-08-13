import os
from flask import Flask
from .config import configure_settings

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.secret_key = os.urandom(24)
    app.config['SESSION_PERMANENT'] = False

    # env, model, passwords, file paths
    configure_settings(app)

    # register blueprints
    from .routes.main import bp as main_bp
    from .routes.assist import bp as assist_bp
    # add others as you split them out
    app.register_blueprint(main_bp)        # no url_prefix so routes stay identical
    app.register_blueprint(assist_bp)

    return app
