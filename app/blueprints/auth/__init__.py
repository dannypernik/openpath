"""Auth blueprint for authentication routes."""

from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

from app.blueprints.auth import auth_routes  # noqa: F401,E402
