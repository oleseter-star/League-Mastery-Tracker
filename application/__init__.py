from flask import Flask
from application.config import Config


def create_app():
    app = Flask(__name__)

    app.config["DATABASE_FILE"] = Config.DATABASE_FILE

    from application.routes.home import home_bp
    app.register_blueprint(home_bp)

    return app