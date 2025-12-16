"""
Application factory for the Flask application.
"""

import os
import time
import logging
from logging.handlers import RotatingFileHandler
from werkzeug.serving import WSGIRequestHandler

from flask import Flask, redirect, url_for, request, flash, g
from celery import Celery

from config import config, Config
from app.extensions import db, migrate, bootstrap, hcaptcha, login, init_extensions
from app.helpers import full_name


# Celery instance - created outside of factory for use by tasks module
celery = Celery(__name__)
celery.conf.update(
        broker_url='redis://localhost:6379/0',
        result_backend='redis://localhost:6379/0',
        worker_max_tasks_per_child=1,
        task_acks_late=True,
        broker_connection_retry_on_startup=False
    )

# Create a Flask app for Celery workers to use
def make_celery_app():
    """Create a minimal Flask app for Celery workers."""
    from flask import Flask
    flask_app = Flask(__name__)
    # Load minimal config needed for tasks
    config_name = os.environ.get('FLASK_CONFIG') or os.environ.get('FLASK_ENV') or 'development'
    flask_app.config.from_object(config[config_name])

    # Initialize only what's needed for tasks (db, etc.)
    from app.extensions import db
    db.init_app(flask_app)

    return flask_app

_celery_app = make_celery_app()

class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with _celery_app.app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask


def create_app(config_name=None):
    """
    Application factory for creating Flask app instances.

    Args:
        config_name: Configuration name ('development', 'testing', 'production')
                    Defaults to FLASK_CONFIG or FLASK_ENV environment variable, or 'development'

    Returns:
        Flask application instance
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG') or os.environ.get('FLASK_ENV') or 'development'

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    init_extensions(app)

    # Setup login manager unauthorized handler
    @login.unauthorized_handler
    def unauthorized():
        """Redirect unauthorized users to the login page."""
        flash('Please sign in to access this page.')
        return redirect(url_for('auth.login', next=request.endpoint, org=request.view_args.get('org')))

    # Register blueprints
    register_blueprints(app)

    # Register error handlers
    register_error_handlers(app)

    # Setup logging
    setup_logging(app)

    @app.teardown_request
    def _log_request_teardown(exc):
        if exc:
            app.logger.exception("REQUEST ERROR during %s %s: %s", request.method, request.path, exc)

    # Setup Jinja environment
    app.jinja_env.auto_reload = True

    # Register dynamic template routes
    register_template_routes(app)

    @app.after_request
    def log_response(response):
        # Skip logging for static files
        if request.path.startswith('/static/'):
            return response

        # timestamp = time.strftime('[%Y-%b-%d %H:%M]')
        # IP - - "METHOD PATH PROTOCOL" STATUS -
        ip = request.remote_addr
        method = request.method
        path = request.full_path if request.query_string else request.path
        protocol = request.environ.get('SERVER_PROTOCOL')
        status = response.status_code

        # User requested format: INFO: 127.0.0.1 - -  "GET /new-student?id=156 HTTP/1.1" 200 -
        # The logger adds TIMESTAMP and LEVEL. We provide the rest.
        message = f'{ip} -- "{method} {path} {protocol}" {status} -'

        app.logger.info(message)
        return response

    return app


def register_blueprints(app):
    """Register Flask blueprints."""
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)


def register_error_handlers(app):
    """Register error handlers."""
    from flask import render_template

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500

    @app.errorhandler(502)
    def server_error(e):
        app.logger.error(f"502 Error: {e}")
        return render_template('502.html'), 502


def setup_logging(app):
    """Setup application logging via the canonical logging configuration.

    This delegates to `app.logging_config.configure_logging` to ensure a single
    canonical setup for both the app and stand-alone scripts.
    """
    try:
        from app.logging_config import configure_logging
        # Use the default log file under logs/openpath.log and enable console
        configure_logging()
    except Exception:
        # If logging config fails for any reason, fall back silently.
        pass


def register_template_routes(app):
    """Register dynamic template routes for HTML templates without explicit routes."""
    def TemplateRenderer(application):
        def register_template_endpoint(name, endpoint):
            from flask import render_template

            @application.route('/' + name, endpoint=endpoint)
            def route_handler():
                title = name.replace('-', ' ').capitalize()
                return render_template(name + '.html', title=title)
        return register_template_endpoint

    # Get existing endpoints
    endpoints = []
    for r in app.url_map._rules:
        endpoints.append(r.endpoint)

    # Get template list
    template_list = []
    templates_dir = os.path.join(app.root_path, 'templates')
    if os.path.exists(templates_dir):
        for f in os.listdir(templates_dir):
            if f.endswith('html') and not f.startswith('_'):
                template_list.append(f[0:-5])

    register_template_endpoint = TemplateRenderer(app)
    for path in template_list:
        endpoint = path.replace('-', '_')
        if endpoint not in endpoints:
            register_template_endpoint(path, endpoint)


# For backwards compatibility, create a default app instance
# This allows existing code that imports 'app' directly to still work
def get_app():
    """Get or create the default app instance."""
    return create_app()
