"""API blueprint routes for API-like endpoints."""

from flask import request

from app.blueprints.api import api_bp
from app.email import send_schedule_conflict_email


@api_bp.route('/cal-check', methods=['POST'])
def cal_check():
    if 1 == 0:
        send_schedule_conflict_email(request.json)
    return ('', 200, None)
