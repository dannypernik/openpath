from datetime import date
from unittest.mock import MagicMock

import pytest

HEADERS = ['Test date', 'SAT Registration deadline', 'Late registration deadline', '', '', 'Student score release date']


def _sheet(ranges):
    svc = MagicMock()

    def get(spreadsheetId, range):
        req = MagicMock()
        req.execute.return_value = {'values': ranges.get(range, [])}
        return req
    svc.spreadsheets().values().get.side_effect = get
    return svc


def _setup(monkeypatch, utils, headers=HEADERS):
    ranges = {
        'Test dates!A1:F1': [headers],
        'Test dates!A2:A16': [['Aug 22, 2026'], ['Sept. 12, 2026'], ['Oct 3, 2026'], ['Nov 7, 2026']],
        'Test dates!B2:B16': [['Aug 8, 2026'], ['Aug 28, 2026'], ['Sep 18, 2026'], ['Oct 23, 2026']],
        # release table lists dates in different rows and formats, and omits Oct 3
        'Test dates!E2:F13': [['Nov 7, 2026', 'Nov 20, 2026'], ['Sept. 12, 2026', 'Sept. 25, 2026'], ['Aug 22, 2026', 'Sep 4, 2026']],
    }
    monkeypatch.setenv('SPREADSHEET_ID', 'ss')
    monkeypatch.setattr(utils.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(utils.ServiceAccountCredentials, 'from_service_account_file', lambda *a, **k: None)
    monkeypatch.setattr(utils, 'build', lambda *a, **k: _sheet(ranges))


def test_sat_score_release_matched_by_test_date_and_existing_rows_updated(app, monkeypatch):
    import app.utils as utils
    from app.extensions import db
    from app.models import TestDate
    _setup(monkeypatch, utils)

    with app.app_context():
        # Aug 22 exists with a stale score date; Oct 3 exists with a score date the table doesn't list
        db.session.add_all([
            TestDate(test='sat', date=date(2026, 8, 22), score_date=date(2026, 1, 1), status='confirmed'),
            TestDate(test='sat', date=date(2026, 10, 3), score_date=date(2026, 10, 16), status='confirmed'),
        ])
        db.session.commit()
        utils.add_test_dates_from_ss()
        got = {t.date: t.score_date for t in TestDate.query.filter_by(test='sat')}

    assert got == {
        date(2026, 8, 22): date(2026, 9, 4),
        date(2026, 9, 12): date(2026, 9, 25),
        date(2026, 10, 3): date(2026, 10, 16),
        date(2026, 11, 7): date(2026, 11, 20),
    }


def test_date_without_score_match_is_still_added(app, monkeypatch):
    import app.utils as utils
    from app.models import TestDate
    _setup(monkeypatch, utils)

    with app.app_context():
        utils.add_test_dates_from_ss()
        oct3 = TestDate.query.filter_by(test='sat', date=date(2026, 10, 3)).one()
        assert oct3.score_date is None


@pytest.mark.parametrize('bad_index, bad_cell', [(1, 'B1'), (2, 'C1'), (5, 'F1')])
def test_header_mismatch_raises_and_updates_nothing(app, monkeypatch, bad_index, bad_cell):
    import app.utils as utils
    from app.models import TestDate
    headers = list(HEADERS)
    headers[bad_index] = 'something else'
    _setup(monkeypatch, utils, headers)

    with app.app_context(), pytest.raises(ValueError, match=bad_cell):
        utils.add_test_dates_from_ss()
    with app.app_context():
        assert TestDate.query.count() == 0


def test_route_flashes_header_error(app, client, monkeypatch):
    import app.blueprints.admin.admin_routes as routes

    def boom():
        raise ValueError('Test dates not updated, spreadsheet headers do not match: B1 ...')
    monkeypatch.setattr(routes, 'add_test_dates_from_ss', boom)
    # bypass login/admin decorators by unwrapping to the view itself
    fn = routes.add_test_dates
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    with app.test_request_context():
        resp = fn()
        from flask import get_flashed_messages
        assert resp.status_code == 302
        assert get_flashed_messages(with_categories=True)[0][0] == 'error'
