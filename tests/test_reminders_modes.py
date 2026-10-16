"""reminders.main(): send_reminders=False emails no one but the admin report; report= picks which one."""
import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import reminders


def _mock(name):
    m = MagicMock(return_value='sent')
    m.__name__ = name  # main() reads fn.__name__ when it skips a send
    return m


@pytest.fixture
def run_main():
    student = SimpleNamespace(first_name='Ann', last_name='Lee', status='active', tutor_id=2)
    event = {'name': 'Ann Lee tutoring', 'tutor': 'T', 'start': datetime.datetime.now(), 'end': datetime.datetime.now()}
    sess = MagicMock()
    chain = sess.query.return_value.order_by.return_value.filter.return_value
    chain.filter.return_value = chain  # students.filter(...) etc. all yield the same one student
    chain.__iter__.side_effect = lambda: iter([student])
    names = ['send_reminder_email', 'send_weekly_report_email', 'send_script_status_email']

    def go(**kwargs):
        with patch.object(reminders, 'session', sess), \
             patch.object(reminders, 'get_events_and_data', return_value=([], [], [event], [], [['Ann Lee', 'Active']], [], MagicMock(), [])), \
             patch.multiple(reminders, **{n: _mock(n) for n in names}), \
             patch.object(reminders.utils, 'batch_update_weekly_usage', return_value={}):
            reminders.main(**kwargs)
            return {n: getattr(reminders, n) for n in names}

    return go


def test_default_sends_student_reminder(run_main):
    assert run_main(report='status')['send_reminder_email'].called


def test_no_reminders_skips_student_email_but_sends_status_report(run_main):
    m = run_main(send_reminders=False, report='status')
    assert not m['send_reminder_email'].called
    assert m['send_script_status_email'].called and not m['send_weekly_report_email'].called
    assert m['send_script_status_email'].call_args.args[-1] is None  # main() finished without an exception


def test_report_weekly_forces_weekly_email(run_main):
    m = run_main(send_reminders=False, report='weekly')
    assert m['send_weekly_report_email'].called and not m['send_script_status_email'].called
