"""Unsubscribe-list requests: sync one request to the 'Email list' sheet, and the daily digest of results."""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models import EmailListRequest
from app.new_student_folders import add_email_to_unsubscribe_list, remove_email_from_unsubscribe_list
from app.email import send_unsubscribe_digest_email


def sync_request(req):
    """Make the sheet match the request. True (and confirmed_at set) once the sheet has the change,
    including when it was already there; False if the sheet couldn't be updated."""
    try:
        if req.action == 'unsubscribe':
            add_email_to_unsubscribe_list(req.email)
        else:
            remove_email_from_unsubscribe_list(req.email)
    except Exception:
        logging.error(f'Email list {req.action} failed for {req.email}', exc_info=True)
        return False
    req.confirmed_at = datetime.now(timezone.utc)
    db.session.commit()
    return True


def send_unsubscribe_digest():
    """Retry unconfirmed requests, then email one summary. Confirmed rows are deleted once the digest
    has gone out; unconfirmed rows stay and are reported as needing attention."""
    requests = EmailListRequest.query.order_by(EmailListRequest.timestamp).all()
    if not requests:
        return

    for req in requests:
        if not req.confirmed_at:
            sync_request(req)

    confirmed = [r for r in requests if r.confirmed_at]
    pending = [r for r in requests if not r.confirmed_at]
    status = send_unsubscribe_digest_email(
        unsubscribed=[r.email for r in confirmed if r.action == 'unsubscribe'],
        resubscribed=[r.email for r in confirmed if r.action == 'resubscribe'],
        pending=[{'email': r.email, 'action': r.action, 'date': r.timestamp} for r in pending])

    if status == 200:
        for req in confirmed:
            db.session.delete(req)
        db.session.commit()
