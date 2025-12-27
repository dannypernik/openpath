"""Admin blueprint for administrative routes."""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from app.blueprints.admin import admin_routes  # noqa: F401,E402
