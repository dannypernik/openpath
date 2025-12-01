"""
Flask extension instances for the application.
Extensions are initialized here without being bound to a specific app,
following the application factory pattern.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bootstrap import Bootstrap
from flask_hcaptcha import hCaptcha

# Initialize extensions without binding to app
db = SQLAlchemy()
migrate = Migrate()
bootstrap = Bootstrap()
hcaptcha = hCaptcha()
login = LoginManager()


def init_extensions(app):
    """
    Initialize all Flask extensions with the application.

    Args:
        app: Flask application instance
    """
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True, compare_type=True)
    bootstrap.init_app(app)
    hcaptcha.init_app(app)

    login.init_app(app)
    login.login_view = 'auth.login'
