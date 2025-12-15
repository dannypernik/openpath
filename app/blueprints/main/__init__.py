"""Main blueprint for public-facing routes."""

from flask import Blueprint

main_bp = Blueprint('', __name__)

from app.blueprints.main import routes  # noqa: F401,E402
