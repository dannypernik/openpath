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

    # # Default request logging for all routes
    # @app.before_request
    # def _log_request_start():
    #     g._req_start = time.time()
    #     app.logger.info(
    #         "REQUEST START: %s %s from %s",
    #         request.method,
    #         request.path,
    #         request.remote_addr or 'unknown'
    #     )

    # @app.after_request
    # def _log_request_end(response):
    #     start = getattr(g, "_req_start", None)
    #     duration_ms = (time.time() - start) * 1000 if start else -1
    #     app.logger.info(
    #         "REQUEST END: %s %s %s %d %.2fms",
    #         request.method,
    #         request.path,
    #         request.environ.get('SERVER_PROTOCOL', ''),
    #         response.status_code,
    #         duration_ms
    #     )
    #     return response

    @app.teardown_request
    def _log_request_teardown(exc):
        if exc:
            app.logger.exception("REQUEST ERROR during %s %s: %s", request.method, request.path, exc)

    # Setup Jinja environment
    app.jinja_env.auto_reload = True

    # Register dynamic template routes
    register_template_routes(app)

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
    """Setup application logging."""
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/openpath.log', maxBytes=51200, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s'))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    # Filter to ignore static asset access logs so terminal stays focused
    class IgnoreStaticFilter(logging.Filter):
        def filter(self, record):
            try:
                msg = record.getMessage()
                # Filter requests for static assets and common static endpoints
                if '/static/' in msg or '/favicon.ico' in msg or '/manifest.webmanifest' in msg:
                    return False
            except Exception:
                pass
            return True

    # Configure werkzeug logger to use the same handlers but ignore static assets
    werk = logging.getLogger('werkzeug')
    werk.setLevel(logging.INFO)
    werk.propagate = False
    static_filter = IgnoreStaticFilter()
    for h in app.logger.handlers:
        # attach filter to handlers so static messages are filtered out
        h.addFilter(static_filter)
        werk.addHandler(h)
    werk.addFilter(static_filter)


    try:
        def _base_log_request(self, code='-', size='-'):
            # Use the werkzeug logger so the configured handlers/formatters are used
            logger = logging.getLogger('werkzeug')
            # address_string may be slow; use self.address_string()
            try:
                addr = self.address_string()
            except Exception:
                addr = '-'
            logger.info('%s - "%s" %s', addr, self.requestline, str(code))

        WSGIRequestHandler.log_request = _base_log_request
    except Exception:
        # If Werkzeug internals change or import fails, skip the override silently
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
