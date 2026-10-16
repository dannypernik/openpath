"""Fixed-data scenario for reminders.main(), used to pin its behaviour across refactors."""
import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.helpers import full_name

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 12, 16, 0, 0, tzinfo=UTC)  # a Monday
TODAY = datetime.date(2026, 10, 12)
EMAILS = ['send_reminder_email', 'send_registration_reminder_email', 'send_late_registration_reminder_email',
          'send_test_reminder_email', 'send_weekly_report_email', 'send_script_status_email']


def dt(day, hour, minutes=0):
    return datetime.datetime(2026, 10, day, hour, minutes, tzinfo=UTC)


def serial(d):
    return (d - datetime.date(1899, 12, 30)).days


def ev(name, start, hours, tutor, week_num, time_group='evening_hours'):
    return {'name': name, 'start': start, 'end': start + datetime.timedelta(hours=hours), 'location': '',
            'hours': hours, 'tutor': tutor, 'time_group': time_group, 'week_num': week_num}


def student(first, last, status, tutor_id):
    return SimpleNamespace(first_name=first, last_name=last, status=status, tutor_id=tutor_id)


class FakeQuery:
    """Just enough of a SQLAlchemy Query: role/status filters narrow, everything else is a no-op."""
    def __init__(self, items, test_users=()):
        self.items, self.test_users = list(items), list(test_users)

    def order_by(self, *a):
        return self

    def options(self, *a):
        return FakeQuery(self.test_users)

    def filter(self, *criteria):
        items = self.items
        for c in criteria:
            key, value = getattr(getattr(c, 'left', None), 'key', None), getattr(getattr(c, 'right', None), 'value', None)
            if key == 'role':
                items = [u for u in items if u.role == value]
            elif key == 'status' and value == 'paused':
                items = [u for u in items if u.status == 'paused']
        return FakeQuery(items, self.test_users)

    def all(self):
        return list(self.items)

    def __iter__(self):
        return iter(self.items)


def build():
    """Returns (data, mocks): the inputs main() reads and the recorders for what it does."""
    ann, bob, cy, ed = (student('Ann', 'Lee', 'active', 1), student('Bob', 'Ray', 'active', 2),
                        student('Cy', 'Dee', 'paused', 2), student('Ed', 'Gil', 'prospective', 2))
    for s in (ann, bob, cy, ed):
        s.role = 'student'
    tutor = student('Sean', 'Palermo', 'active', None)
    tutor.role = 'tutor'
    tutor.email = 'sean@example.com'

    test_date = SimpleNamespace(date=TODAY - datetime.timedelta(days=2), status='upcoming', test='sat',
                                reg_date=TODAY + datetime.timedelta(days=5), late_date=None)
    remind_user = student('Ann', 'Lee', 'active', 1)
    remind_user.get_dates = lambda: [test_date]
    remind_user.is_registered = lambda d: False
    old_date = SimpleNamespace(date=TODAY - datetime.timedelta(days=1), status='upcoming')

    def row(name, status, hours, rate, pay, tutors, last=None):
        r = [name, status, '', hours, rate, '', '', pay, tutors] + [''] * 8
        r[16] = serial(last) if last else ''
        return r

    summary = [
        row('Ann Lee', 'Active', 1.5, 100, 'Package', 'Sean Palermo, Danny Pernik', datetime.date(2026, 10, 7)),
        row('Bob Ray', 'Active', 0, 80, 'Credit card', 'Sean Palermo'),
        row('Cy Dee', 'Paused', 0, 90, 'Package', ''),
        row('Ed Gil', 'Inactive', 3, 90, 'Package', 'Sean Palermo', datetime.date(2026, 10, 1)),
        row('Gus Ito', 'Active', 2, 90, 'Package', ''),
    ]
    D, S = 'Danny Pernik', 'Sean Palermo'
    bimonth = [
        ev('Ann Lee', dt(14, 17), 1, D, 0), ev('Bob Ray', dt(14, 18), 1, S, 0),
        ev('Ann Lee', dt(16, 17), 1, D, 0, 'day_hours'), ev('Ann Lee', dt(21, 17), 1, D, 1),
        ev('Ed Gil', dt(22, 19), 1.5, S, 1), ev('Ann Lee projected', dt(28, 17), 1, D, 2, 'projected_hours'),
    ]
    yesterday = [{'name': 'Ann Lee', 'start': dt(11, 18), 'end': dt(11, 19), 'location': '', 'hours': 1, 'tutor': D}]
    prev_events = [
        {'name': 'Ann Lee', 'start': '2026-10-01T22:00:00Z', 'end': '', 'location': '', 'hours': 1, 'tutor': D},
        {'name': 'Ann Lee', 'start': '2026-10-03T22:00:00Z', 'end': '', 'location': '', 'hours': 1, 'tutor': D},
    ]
    prev_sessions = [
        {'tutor': D, 'start': '10/01/2026', 'student': 'Ann Lee', 'duration': 1.5},
        {'tutor': D, 'start': '10/02/2026', 'student': 'Ann Lee', 'duration': 1},
    ]
    upcoming = [bimonth[0]]
    sheet = MagicMock()
    sheet.values.return_value.get.return_value.execute.return_value = {'values': []}
    payments = [{'tutor': {'name': S, 'cal_id': 'x', 'finance_ss_id': 'abc'}, 'amount': 120}]

    session = MagicMock()
    session.query.side_effect = lambda model: (
        FakeQuery([], []) if False else FakeQuery(model.items) if hasattr(model, 'items') else None)
    return SimpleNamespace(
        students=[ann, bob, cy, ed], tutors=[tutor], test_dates=[old_date], remind_users=[remind_user],
        events=(bimonth, prev_events, upcoming, yesterday, summary, prev_sessions, sheet, payments),
        sheet=sheet, session=session, test_date=test_date, old_date=old_date)


def make_session(data):
    """session.query(User|TestDate) stand-in backed by `data`."""
    session = MagicMock()
    users = FakeQuery(data.students + data.tutors, data.remind_users)
    # By name: other test modules may reload app.models, so `is User` can't be trusted.
    session.query.side_effect = lambda model: FakeQuery(data.test_dates) if model.__name__ == 'TestDate' else users
    return session


def norm(x):
    """JSON-able view of anything main() hands to an email function."""
    if isinstance(x, SimpleNamespace):
        return full_name(x) if hasattr(x, 'first_name') else norm(vars(x))
    if isinstance(x, (datetime.datetime, datetime.date)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): norm(v) for k, v in x.items()}
    if isinstance(x, (set, frozenset)):
        return sorted(norm(v) for v in x)
    if isinstance(x, (list, tuple, FakeQuery)):
        return [norm(v) for v in x]
    if isinstance(x, MagicMock):
        return '<mock>'
    return x


def record(email_mocks, data):
    calls = {n: [norm(c.args) for c in m.call_args_list] for n, m in email_mocks.items()}
    sheet_calls = [[c[0], norm(c.kwargs)] for c in data.sheet.values.return_value.mock_calls
                   if c[0] in ('batchUpdate', 'update')]
    return json.loads(json.dumps({
        'emails': calls, 'sheet': sheet_calls,
        'statuses': {full_name(s): s.status for s in data.students},
        'test_date_status': data.old_date.status,
    }, default=str))
