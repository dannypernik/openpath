"""reminders.py: the failure report, sheet writes, name matching, and tutor config."""
import datetime
from unittest.mock import MagicMock, patch

import pytest

import reminders
from tests import reminders_scenario as sc


def run_main(events=None, error=None, **kwargs):
    data = sc.build()
    mocks = {}
    for n in sc.EMAILS:
        mocks[n] = MagicMock(return_value='sent')
        mocks[n].__name__ = n
    fetch = {'return_value': events or data.events} if error is None else {'side_effect': error}
    with patch.multiple(reminders, **mocks), \
         patch.object(reminders, 'get_events_and_data', **fetch), \
         patch.object(reminders.utils, 'batch_update_weekly_usage', return_value={}):
        reminders.main(session=sc.make_session(data), now=sc.NOW, today=sc.TODAY, **kwargs)
    return data, mocks


@pytest.mark.parametrize('report, email', [('status', 'send_script_status_email'), ('weekly', 'send_weekly_report_email')])
def test_report_still_goes_out_when_the_run_fails(report, email):
    _, mocks = run_main(error=RuntimeError('calendar down'), report=report)
    assert mocks[email].call_count == 1
    sent = mocks[email].call_args
    exception = sent.args[-1] if report == 'status' else sent.kwargs['exception']
    status = sent.args[-2] if report == 'status' else sent.kwargs['script_status']
    assert 'calendar down' in exception and status == 'failed'


def test_no_reminders_emails_no_one_but_still_reports():
    _, mocks = run_main(report='status', send_reminders=False)
    for n in ('send_reminder_email', 'send_registration_reminder_email'):
        assert not mocks[n].called
    assert mocks['send_script_status_email'].call_args.args[-1] is None  # finished cleanly


def test_unmatched_student_is_reported_and_writes_nothing():
    data = sc.build()
    fay = sc.student('Fay', 'Hu', 'active', 2)
    fay.role = 'student'
    data.students.append(fay)
    data.events[0].append(sc.ev('Fay Hu', sc.dt(15, 17), 1, 'Sean Palermo', 0))
    mocks = {n: MagicMock(return_value='sent') for n in sc.EMAILS}
    for n, m in mocks.items():
        m.__name__ = n
    with patch.multiple(reminders, **mocks), patch.object(reminders, 'get_events_and_data', return_value=data.events):
        reminders.main(session=sc.make_session(data), now=sc.NOW, today=sc.TODAY, report='status')
    body = data.sheet.values.return_value.batchUpdate.call_args.kwargs['body']
    rows = {u['range'][1:] for u in body['data']}
    assert rows == {'6', '7', '9'}  # Ann, Bob, Ed -- not Fay, and not the sheet's last row (10)
    args = mocks['send_script_status_email'].call_args.args
    assert {'name': 'Fay Hu', 'add_to': 'spreadsheet'} in args[7]


def test_sheet_writes_retry_transient_errors():
    data, _ = run_main(report='status')
    assert data.sheet.values.return_value.batchUpdate.return_value.execute.call_args.kwargs == {'num_retries': 3}


@pytest.mark.parametrize('name, title, expected', [
    ('Ann Lee', 'Ann Lee', True),
    ('Ann Lee', "Ann Lee's SAT", True),
    ('Ann Lee', 'Ann Lee / Bob Ray', True),
    ('Ann Lee', 'Joann Leeds', False),
    ('Ann Lee', 'Ann Leeson', False),
    ('Ann Lee', None, False),
    ('', 'Ann Lee', False),
])
def test_mentions_matches_whole_names_only(name, title, expected):
    assert reminders.mentions(name, title) is expected


def test_a_shared_session_is_not_double_counted_in_hours():
    run = reminders.Run()
    ann, bob = sc.student('Ann', 'Lee', 'active', 2), sc.student('Bob', 'Ray', 'active', 2)
    events = [sc.ev('Ann Lee / Bob Ray', sc.dt(14, 17), 1, 'Sean Palermo', 0), sc.ev('Ann Lee', sc.dt(16, 17), 1, 'Sean Palermo', 0)]
    rows = {'Ann Lee': (0, ['Ann Lee', 'Active', '', 1.5, 100, '', '', 'Package', '']),
            'Bob Ray': (1, ['Bob Ray', 'Active', '', 5, 100, '', '', 'Package', ''])}
    w = reminders.windows_for(sc.NOW, sc.TODAY)
    for s in (bob, ann):  # Bob first: his copy of the shared session used to leak into Ann's totals
        reminders.build_student_data(run, MagicMock(), s, rows, events, [], [], [], w)
    ann_data = next(d for d in run.student_data if d['name'] == 'Ann Lee')
    assert ann_data['hours_this_week'] == 2
    assert ann_data['deadline'] == 'Fri Oct 16'  # 1h + 1h > 1.5h on her second session


def test_every_tutor_has_a_finance_sheet_key():
    tutors = reminders.load_tutors()
    assert len(tutors) >= 2 and all('finance_ss_id' in t and t['cal_id'] and t['name'] for t in tutors)
    assert tutors[0]['finance_ss_id'] is None  # Danny has none; that used to be a KeyError


def test_windows_are_derived_from_the_given_clock():
    w = reminders.windows_for(sc.NOW, sc.TODAY)
    assert w.day_of_week == 'Monday'
    assert w.bimonth_start == datetime.datetime(2026, 10, 12, 8, tzinfo=datetime.timezone.utc)
    assert w.prev_month_start == w.bimonth_start - datetime.timedelta(days=30)
    assert w.upcoming_start_formatted == 'Wednesday, Oct 14'


def test_weekly_email_says_when_the_run_failed():
    import os
    from flask import Flask
    from app import email as email_mod
    app = Flask('t', template_folder=os.path.join(reminders.basedir, 'app', 'templates'))
    app.config['SERVER_NAME'] = 'localhost'
    sent = {}
    mailjet = MagicMock()
    mailjet.send.create.side_effect = lambda data: sent.update(data['Messages'][0]) or MagicMock(status_code=200)
    args = ([], [], 0, 0, 0, 0, [], [], [], set(), reminders.empty_weekly_data(), [], [], [], [], [], sc.NOW)
    with app.app_context(), patch.object(email_mod, 'mailjet', mailjet), patch.object(email_mod, 'get_quote', return_value=('q', 'a', 'h')):
        email_mod.send_weekly_report_email(*args, script_status='failed', exception='Traceback: calendar down')
    assert sent['Subject'] == 'reminders.py failed - Admin tutoring report'
    assert 'calendar down' in sent['HTMLPart']
    with app.app_context(), patch.object(email_mod, 'mailjet', mailjet), patch.object(email_mod, 'get_quote', return_value=('q', 'a', 'h')):
        email_mod.send_weekly_report_email(*args)
    assert sent['Subject'] == 'reminders.py succeeded - Admin tutoring report' and 'reminders.py failed' not in sent['HTMLPart']


@pytest.mark.parametrize('last_session, expected', [
    (None, 'Wed Oct 14'),                       # no previous session: the first one is still "next"
    (datetime.date(2026, 10, 7), 'Wed Oct 14'),
    (datetime.date(2026, 10, 14), 'Fri Oct 16'),  # a session on the same day as the last logged one is skipped
])
def test_next_session_does_not_require_a_previous_session(last_session, expected):
    run = reminders.Run()
    events = [sc.ev('Ann Lee', sc.dt(14, 17), 1, 'Sean Palermo', 0), sc.ev('Ann Lee', sc.dt(16, 17), 1, 'Sean Palermo', 0)]
    row = ['Ann Lee', 'Active', '', 5, 100, '', '', 'Package', ''] + [''] * 8
    row[16] = sc.serial(last_session) if last_session else ''
    reminders.build_student_data(run, MagicMock(), sc.student('Ann', 'Lee', 'active', 2), {'Ann Lee': (0, row)},
                                 events, [], [], [], reminders.windows_for(sc.NOW, sc.TODAY))
    assert run.student_data[0]['next_session'] == expected
