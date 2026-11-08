from datetime import date
from unittest.mock import MagicMock



def _sheet(ranges):
    svc = MagicMock()

    def get(spreadsheetId, range):
        req = MagicMock()
        req.execute.return_value = {'values': ranges.get(range, [])}
        return req
    svc.spreadsheets().values().get.side_effect = get
    return svc


def test_sat_score_release_matched_by_test_date_from_separate_table(app, monkeypatch):
    import app.utils as utils
    from app.models import TestDate

    ranges = {
        'Test dates!A2:A16': [['Aug 22, 2026'], ['Sept. 12, 2026'], ['Oct 3, 2026'], ['Nov 7, 2026']],
        'Test dates!B2:B16': [['Aug 8, 2026'], ['Aug 28, 2026'], ['Sep 18, 2026'], ['Oct 23, 2026']],
        # release table lists dates in different rows and formats, and omits Oct 3
        'Test dates!E2:F13': [['Nov 7, 2026', 'Nov 20, 2026'], ['Sept. 12, 2026', 'Sept. 25, 2026'], ['Aug 22, 2026', 'Sep 4, 2026']],
    }
    monkeypatch.setenv('SPREADSHEET_ID', 'ss')
    monkeypatch.setattr(utils.os.path, 'exists', lambda p: True)
    monkeypatch.setattr(utils.ServiceAccountCredentials, 'from_service_account_file', lambda *a, **k: None)
    monkeypatch.setattr(utils, 'build', lambda *a, **k: _sheet(ranges))

    with app.app_context():
        utils.add_test_dates_from_ss()
        got = {t.date: t.score_date for t in TestDate.query.filter_by(test='sat')}

    assert got == {
        date(2026, 8, 22): date(2026, 9, 4),
        date(2026, 9, 12): date(2026, 9, 25),
        date(2026, 10, 3): None,
        date(2026, 11, 7): date(2026, 11, 20),
    }
