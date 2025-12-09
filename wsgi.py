"""
WSGI entrypoint for the Flask application.
Used by Gunicorn and other WSGI servers.

Usage:
    gunicorn wsgi:app
    gunicorn wsgi:application
"""

from app import create_app

# Create the application instance using the factory
app = create_app()
application = app  # For compatibility with different WSGI servers
