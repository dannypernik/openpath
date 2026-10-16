"""reminders.main() output on a fixed scenario must not change across refactors.

Regenerate the expected file deliberately: RECORD_GOLDEN=1 pytest tests/test_reminders_golden.py
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

import reminders
from tests import reminders_scenario as sc

GOLDEN = os.path.join(os.path.dirname(__file__), 'fixtures', 'reminders_golden.json')


def run(report, send_reminders=True):
    data = sc.build()
    email_mocks = {}
    for n in sc.EMAILS:
        m = MagicMock(return_value='sent')
        m.__name__ = n
        email_mocks[n] = m
    w = reminders.windows_for(sc.NOW, sc.TODAY) if hasattr(reminders, 'windows_for') else None
    with patch.multiple(reminders, **email_mocks), \
         patch.object(reminders, 'get_events_and_data', return_value=data.events), \
         patch.object(reminders.utils, 'batch_update_weekly_usage', return_value={'sat': 3}), \
         patch.object(reminders, 'db', MagicMock()):
        if w is None:
            fixed = reminders_globals()
            with patch.multiple(reminders, session=sc.make_session(data), **fixed):
                reminders.main(send_reminders=send_reminders, report=report)
        else:
            reminders.main(send_reminders=send_reminders, report=report, session=sc.make_session(data), now=sc.NOW, today=sc.TODAY)
    return sc.record(email_mocks, data)


def reminders_globals():
    """Pre-refactor: main() reads these from module globals."""
    import datetime
    now = sc.NOW
    shift = datetime.timedelta(hours=now.hour - 8, minutes=now.minute, seconds=now.second)
    bimonth_start = now - shift
    upcoming_start = bimonth_start + datetime.timedelta(hours=48)
    return dict(now=now, today=sc.TODAY, day_of_week='Monday', bimonth_start=bimonth_start,
                yesterday_start=bimonth_start - datetime.timedelta(hours=24), upcoming_start=upcoming_start,
                upcoming_start_formatted=upcoming_start.strftime('%A, %b %-d'))


SCENARIOS = {'weekly': dict(report='weekly'), 'status': dict(report='status'),
             'status_no_reminders': dict(report='status', send_reminders=False)}


def test_golden():
    got = {name: run(**kw) for name, kw in SCENARIOS.items()}
    if os.environ.get('RECORD_GOLDEN'):
        with open(GOLDEN, 'w') as f:
            json.dump(got, f, indent=1, sort_keys=True)
        pytest.skip('recorded')
    with open(GOLDEN) as f:
        assert json.loads(json.dumps(got, sort_keys=True)) == json.load(f)
