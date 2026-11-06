"""Unsubscribe / resubscribe flow: db request row, celery task, sheet helpers, notification subject."""

from unittest.mock import MagicMock
import pytest

import app.tasks as tasks
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
def notify(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(tasks, 'send_email_list_change_email', mock)
    return mock


def run_task(email, action):
    tasks.email_list_task.run(email, action)


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


def test_task_success_deletes_row_and_reports(client, queued, notify, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', lambda e: 'added')
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.count() == 0
    notify.assert_called_once_with('a@x.com', 'unsubscribe', 'added')


def test_task_already_present_deletes_row(client, queued, notify, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', lambda e: 'already')
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.count() == 0
    notify.assert_called_once_with('a@x.com', 'unsubscribe', 'already')


def test_task_failure_keeps_row_and_reports_failed(client, queued, notify, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})

    def boom(e):
        raise RuntimeError('sheets down')
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', boom)
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.count() == 1
    notify.assert_called_once_with('a@x.com', 'unsubscribe', 'failed')


def test_next_unsubscribe_retries_failed_write(client, queued, notify, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', MagicMock(side_effect=RuntimeError))
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.count() == 1

    client.post('/unsubscribe', data={'email': 'a@x.com'})
    assert EmailListRequest.query.count() == 1
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', lambda e: 'added')
    run_task('a@x.com', 'unsubscribe')
    assert EmailListRequest.query.count() == 0


def test_resubscribe_supersedes_pending_unsubscribe(client, queued, notify, monkeypatch):
    client.post('/unsubscribe', data={'email': 'a@x.com'})
    client.post('/resubscribe', data={'email': 'a@x.com'})
    assert EmailListRequest.query.one().action == 'resubscribe'

    add = MagicMock()
    monkeypatch.setattr(tasks, 'add_email_to_unsubscribe_list', add)
    run_task('a@x.com', 'unsubscribe')  # stale task from the first request
    add.assert_not_called()
    notify.assert_not_called()

    monkeypatch.setattr(tasks, 'remove_email_from_unsubscribe_list', lambda e: 'already')
    run_task('a@x.com', 'resubscribe')
    assert EmailListRequest.query.count() == 0
    notify.assert_called_once_with('a@x.com', 'resubscribe', 'already')


@pytest.mark.parametrize('action,status,phrase', [
    ('unsubscribe', 'added', 'successfully unsubscribed'),
    ('unsubscribe', 'already', 'already unsubscribed'),
    ('unsubscribe', 'failed', 'failed to be automatically unsubscribed'),
    ('resubscribe', 'removed', 'successfully resubscribed'),
    ('resubscribe', 'already', 'already subscribed'),
    ('resubscribe', 'failed', 'failed to be automatically resubscribed'),
])
def test_email_subject(app, monkeypatch, action, status, phrase):
    mj = MagicMock()
    mj.send.create.return_value = MagicMock(status_code=200)
    monkeypatch.setattr(email_mod, 'mailjet', mj)
    with app.test_request_context():
        email_mod.send_email_list_change_email('a@x.com', action, status)
    subject = mj.send.create.call_args.kwargs['data']['Messages'][0]['Subject']
    assert subject == f'{action.capitalize()} request from a@x.com: {phrase}'


@pytest.fixture
def sheet(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(nsf, 'sheets_service', svc)
    return svc


def test_add_appends_only_when_absent(sheet):
    sheet.spreadsheets().values().get().execute.return_value = {'values': [['a@x.com'], ['b@x.com']]}
    assert nsf.add_email_to_unsubscribe_list('c@x.com') == 'added'
    assert sheet.spreadsheets().values().append.call_args.kwargs['body'] == {'values': [['c@x.com']]}
    sheet.spreadsheets().values().append.reset_mock()
    assert nsf.add_email_to_unsubscribe_list('B@x.com') == 'already'
    sheet.spreadsheets().values().append.assert_not_called()


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
