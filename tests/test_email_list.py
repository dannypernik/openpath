"""Unsubscribe / resubscribe flow: db request row, celery task, sheet helpers, notification subject."""

from unittest.mock import MagicMock
import pytest

import app.tasks as tasks
import app.email_list as email_list
import app.new_student_folders as nsf
import app.email as email_mod
from app.extensions import db
from app.models import EmailListRequest


@pytest.fixture
def queued(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(tasks.email_list_task, 'delay', mock)
    return mock


@pytest.fixture
def fail_mail(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(tasks, 'send_email_list_failure_email', mock)
    return mock


def run_task(email, action):
    tasks.email_list_task.run(email, action)


def set_sheet(monkeypatch, add=None, remove=None):
    monkeypatch.setattr(email_list, 'add_email_to_unsubscribe_list', add or MagicMock(return_value='added'))
    monkeypatch.setattr(email_list, 'remove_email_from_unsubscribe_list', remove or MagicMock(return_value='removed'))


def test_unsubscribe_post_confirms_immediately_and_queues(client, queued):
    resp = client.post('/unsubscribe', data={'email': 'Kid@Example.com'})
    body = resp.get_data(as_text=True)
    assert 'You have been unsubscribed' in body
    assert 'Resubscribe' in body
    assert 'Unsubscribe from SAT Resources' not in body
    req = EmailListRequest.query.filter_by(email='kid@example.com').one()
    assert req.action == 'unsubscribe'
    queued.assert_called_once_with('kid@example.com', 'unsubscribe')


def test_resubscribe_post(client, queued):
    resp = client.post('/resubscribe', data={'email': 'kid@example.com'})
    assert 'You have been resubscribed' in resp.get_data(as_text=True)
    assert EmailListRequest.query.one().action == 'resubscribe'
    queued.assert_called_once_with('kid@example.com', 'resubscribe')


def test_task_success_confirms_without_sending_email(client, queued, fail_mail, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch)
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.one().confirmed_at is not None
    fail_mail.assert_not_called()


def test_task_already_present_counts_as_success(client, queued, fail_mail, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch, add=MagicMock(return_value='already'))
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.one().confirmed_at is not None
    fail_mail.assert_not_called()


def test_task_failure_stays_pending_and_sends_failure_email(client, queued, fail_mail, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch, add=MagicMock(side_effect=RuntimeError('sheets down')))
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.one().confirmed_at is None
    fail_mail.assert_called_once_with('a@x.com', 'unsubscribe')


def test_next_unsubscribe_retries_failed_write(client, queued, fail_mail, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch, add=MagicMock(side_effect=RuntimeError))
    run_task('a@x.com', 'unsubscribe')

    client.post('/unsubscribe', data={'email': 'a@x.com'})
    assert EmailListRequest.query.count() == 1
    set_sheet(monkeypatch)
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.one().confirmed_at is not None


def test_new_request_resets_confirmed_row(client, queued, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch)
    run_task('a@x.com', 'unsubscribe')
    client.post('/resubscribe', data={'email': 'a@x.com'})
    req = EmailListRequest.query.one()
    assert (req.action, req.confirmed_at) == ('resubscribe', None)


def test_resubscribe_supersedes_pending_unsubscribe(client, queued, fail_mail, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    client.post('/resubscribe', data={'email': 'a@x.com'})
    assert EmailListRequest.query.one().action == 'resubscribe'

    add = MagicMock()
    set_sheet(monkeypatch, add=add, remove=MagicMock(return_value='already'))
    run_task('a@x.com', 'unsubscribe')  # stale task from the first request
    add.assert_not_called()

    run_task('a@x.com', 'resubscribe')
    assert EmailListRequest.query.one().confirmed_at is not None


@pytest.fixture
def digest(monkeypatch):
    mock = MagicMock(return_value=200)
    monkeypatch.setattr(email_list, 'send_unsubscribe_digest_email', mock)
    return mock


def test_digest_no_requests_sends_nothing(app, digest):
    email_list.send_unsubscribe_digest()
    digest.assert_not_called()


def test_digest_all_succeeded_lists_emails_and_clears_rows(client, queued, digest, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    client.post('/unsubscribe', data={'email': 'b@x.com'})
    client.post('/resubscribe', data={'email': 'c@x.com'})
    set_sheet(monkeypatch)
    email_list.send_unsubscribe_digest()
    digest.assert_called_once_with(unsubscribed=['a@x.com', 'b@x.com'], resubscribed=['c@x.com'], pending=[])
    assert EmailListRequest.query.count() == 0


def test_digest_picks_up_manually_added_email(client, queued, digest, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch, add=MagicMock(side_effect=RuntimeError))
    run_task('a@x.com', 'unsubscribe')
    set_sheet(monkeypatch, add=MagicMock(return_value='already'))  # manually added; the recheck finds it
    email_list.send_unsubscribe_digest()
    assert digest.call_args.kwargs['pending'] == []
    assert digest.call_args.kwargs['unsubscribed'] == ['a@x.com']
    assert EmailListRequest.query.count() == 0


def test_digest_reports_pending_and_keeps_those_rows(client, queued, digest, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    client.post('/unsubscribe', data={'email': 'b@x.com'})
    add = MagicMock(side_effect=lambda e: 'added' if e == 'a@x.com' else (_ for _ in ()).throw(RuntimeError()))
    set_sheet(monkeypatch, add=add)
    email_list.send_unsubscribe_digest()
    kwargs = digest.call_args.kwargs
    assert kwargs['unsubscribed'] == ['a@x.com']
    assert [(p['email'], p['action']) for p in kwargs['pending']] == [('b@x.com', 'unsubscribe')]
    assert [r.email for r in EmailListRequest.query.all()] == ['b@x.com']


def test_digest_keeps_rows_when_email_fails_to_send(client, queued, digest, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    set_sheet(monkeypatch)
    digest.return_value = 500
    email_list.send_unsubscribe_digest()
    assert EmailListRequest.query.count() == 1


def send_digest_mail(app, monkeypatch, **kwargs):
    mj = MagicMock()
    mj.send.create.return_value = MagicMock(status_code=200)
    monkeypatch.setattr(email_mod, 'mailjet', mj)
    with app.test_request_context():
        email_mod.send_unsubscribe_digest_email(**kwargs)
    message = mj.send.create.call_args.kwargs['data']['Messages'][0]
    return message['Subject'], message['HTMLPart']


def test_digest_email_all_succeeded(app, monkeypatch):
    subject, html = send_digest_mail(app, monkeypatch, unsubscribed=['a@x.com'], resubscribed=['c@x.com'], pending=[])
    assert subject.startswith('Unsubscribe digest for ')
    assert 'All unsubscribe updates succeeded' in html
    assert 'a@x.com' in html and 'c@x.com' in html
    assert 'Drive' not in html and 'folder' not in html


def test_digest_email_requires_attention(app, monkeypatch):
    from datetime import datetime
    pending = [{'email': 'b@x.com', 'action': 'unsubscribe', 'date': datetime(2026, 11, 6)}]
    subject, html = send_digest_mail(app, monkeypatch, unsubscribed=['a@x.com'], resubscribed=[], pending=pending)
    assert subject == 'Unsubscribe list requires attention'
    assert 'All unsubscribe updates succeeded' not in html
    assert 'b@x.com' in html and 'Nov 6' in html


@pytest.mark.parametrize('action,phrase', [
    ('unsubscribe', 'failed to be automatically unsubscribed'),
    ('resubscribe', 'failed to be automatically resubscribed'),
])
def test_failure_email_subject(app, monkeypatch, action, phrase):
    mj = MagicMock()
    mj.send.create.return_value = MagicMock(status_code=200)
    monkeypatch.setattr(email_mod, 'mailjet', mj)
    with app.test_request_context():
        email_mod.send_email_list_failure_email('a@x.com', action)
    message = mj.send.create.call_args.kwargs['data']['Messages'][0]
    assert message['Subject'] == f'{action.capitalize()} request from a@x.com: {phrase}'
    assert 'folder' not in message['HTMLPart']


@pytest.fixture
def sheet(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(nsf, 'sheets_service', svc)
    monkeypatch.setattr(nsf, 'EMAIL_LIST_SPREADSHEET_ID', 'test-ss-id')
    return svc


def test_missing_ss_id_raises(sheet, monkeypatch):
    monkeypatch.setattr(nsf, 'EMAIL_LIST_SPREADSHEET_ID', None)
    with pytest.raises(RuntimeError, match='EMAIL_LIST_SS_ID'):
        nsf.add_email_to_unsubscribe_list('a@x.com')


def test_add_writes_to_first_free_row_only_when_absent(sheet):
    sheet.spreadsheets().values().get().execute.return_value = {'values': [['a@x.com'], ['b@x.com']]}
    assert nsf.add_email_to_unsubscribe_list('c@x.com') == 'added'
    kwargs = sheet.spreadsheets().values().update.call_args.kwargs
    assert kwargs['range'] == "'Email list'!A3"
    assert kwargs['body'] == {'values': [['c@x.com']]}
    sheet.spreadsheets().values().update.reset_mock()
    assert nsf.add_email_to_unsubscribe_list('B@x.com') == 'already'
    sheet.spreadsheets().values().update.assert_not_called()


def test_remove_deletes_matching_rows_bottom_up(sheet):
    sheet.spreadsheets().values().get().execute.return_value = {'values': [['a@x.com'], [], ['b@x.com'], ['A@x.com']]}
    sheet.spreadsheets().get().execute.return_value = {'sheets': [
        {'properties': {'sheetId': 1, 'title': 'Other'}},
        {'properties': {'sheetId': 42, 'title': 'Email list'}}]}
    assert nsf.remove_email_from_unsubscribe_list('a@x.com') == 'removed'
    reqs = sheet.spreadsheets().batchUpdate.call_args.kwargs['body']['requests']
    assert [r['deleteRange']['range']['startRowIndex'] for r in reqs] == [3, 0]
    assert all(r['deleteRange']['range']['sheetId'] == 42 for r in reqs)


def test_remove_absent_email_is_noop(sheet):
    sheet.spreadsheets().values().get().execute.return_value = {'values': [['b@x.com']]}
    assert nsf.remove_email_from_unsubscribe_list('a@x.com') == 'already'
    sheet.spreadsheets().batchUpdate.assert_not_called()


def test_sheet_helpers_raise_without_service(monkeypatch):
    monkeypatch.setattr(nsf, 'sheets_service', None)
    with pytest.raises(RuntimeError):
        nsf.add_email_to_unsubscribe_list('a@x.com')
