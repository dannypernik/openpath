"""Daily job: email session/test reminders, sync student status with the tutoring sheets, email the admin report.

    python3 reminders.py [--no-reminders] [--report weekly|status]
"""
import datetime
import json
import logging
import math
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from functools import lru_cache
from types import SimpleNamespace

import pytz
from dateutil.parser import isoparse, parse
from dotenv import load_dotenv
from googleapiclient.discovery import build
from sqlalchemy.orm import selectinload

import app.utils as utils
from app import create_app
from app.email import send_reminder_email, send_test_reminder_email, \
    send_registration_reminder_email, send_late_registration_reminder_email, \
    send_weekly_report_email, send_script_status_email
from app.extensions import db
from app.helpers import full_name
from app.logging_config import configure_logging
from app.models import User, TestDate, UserTestDate

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

CENTRAL_TZ = pytz.timezone('US/Central')

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets']

SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
SUMMARY_RANGE = 'Summary!A6:Z'

# The account holder: their sessions feed the Sessions sheet and the "my hours" totals in the report.
OWNER_NAME = 'Danny Pernik'
OWNER_ID = 1


def load_tutors():
    """Tutors with a Google Calendar (and optionally a finance sheet), from tutors.json."""
    with open(os.path.join(basedir, 'tutors.json')) as f:
        return [{'finance_ss_id': None, **t} for t in json.load(f)]


def windows_for(now=None, today=None):
    """Every date window the run needs, derived from one clock reading. Pass both to run on a fixed date."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    bimonth_start = now - datetime.timedelta(hours=now.hour - 8, minutes=now.minute, seconds=now.second)  # 8am UTC today
    prev_month_start = bimonth_start - datetime.timedelta(days=30)
    upcoming_start = bimonth_start + datetime.timedelta(hours=48)
    iso = lambda d: d.isoformat().replace('+00:00', 'Z')
    return SimpleNamespace(
        now=now,
        today=today or datetime.date.today(),
        day_of_week=now.strftime('%A'),
        prev_month_start=prev_month_start, prev_month_start_str=iso(prev_month_start),
        bimonth_start=bimonth_start, bimonth_start_str=iso(bimonth_start),
        bimonth_end_str=iso(now + datetime.timedelta(days=70)),
        yesterday_start=bimonth_start - datetime.timedelta(hours=24),
        upcoming_start=upcoming_start, upcoming_start_formatted=upcoming_start.strftime('%A, %b %-d'),
        upcoming_end=upcoming_start + datetime.timedelta(hours=24),
        tomorrow_end=upcoming_start,
    )


def parse_sheet_date(value):
    """Parse Sheets date values that may be serial numbers or formatted strings."""
    if value in (None, ''):
        return None

    if isinstance(value, (int, float)):
        # Google Sheets serial date origin
        return (datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(value))).date()

    text = str(value).strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except (ValueError, TypeError):
            continue

    try:
        return parse(text).date()
    except Exception:
        return None


def calendar_date_us_central(value):
    """Convert a calendar datetime value to a US Central calendar date."""
    if value in (None, ''):
        return None

    try:
        dt = value if isinstance(value, datetime.datetime) else isoparse(str(value))
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt.astimezone(CENTRAL_TZ).date()


def calendar_date_us_central_str(value):
    date_value = calendar_date_us_central(value)
    return date_value.strftime('%m/%d/%Y') if date_value else None


@lru_cache(maxsize=None)
def _name_pattern(name):
    return re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)')


def mentions(name, title):
    """Does this calendar title name the student? Whole words only: 'Ann Lee' is not in 'Joann Leeds'."""
    return bool(name and title and _name_pattern(name).search(title))


# ---------------------------------------------------------------------------
# Fetching: Google Calendar and Sheets
# ---------------------------------------------------------------------------

def parse_calendar_event(e, tutor_name, w):
    """Sort one Calendar API event into 'bimonth' (from today on), 'yesterday', or 'prev_month'.

    Returns (bucket, event_dict), or None for all-day events.
    """
    if not e['start'].get('dateTime'):
        return None
    e_start = isoparse(e['start']['dateTime'])
    e_end = isoparse(e['end']['dateTime'])
    title = e.get('summary') or ''
    event = {
        'name': title,
        'start': e_start,
        'end': e_end,
        'location': e.get('location', ''),
        'hours': (e_end - e_start).total_seconds() / 3600,
        'tutor': tutor_name,
    }

    if e_start >= w.bimonth_start:
        if 'projected' in title.lower():
            event['time_group'] = 'projected_hours'
        elif e_end.hour + (e_end.minute / 60) <= 16.25:
            event['time_group'] = 'day_hours'
        else:
            event['time_group'] = 'evening_hours'
        start_of_week_0 = w.bimonth_start - datetime.timedelta(days=w.bimonth_start.weekday())
        event['week_num'] = max(1, math.ceil(((e_start - start_of_week_0).days + 1) / 7)) - 1
        return 'bimonth', event
    if e_start >= w.yesterday_start:
        return 'yesterday', event
    # Compared against the Sessions sheet by date string, so keep the raw timestamps.
    return 'prev_month', {**event, 'start': e['start']['dateTime'], 'end': e['end']['dateTime']}


def fetch_calendar_events(service_cal, tutors, w):
    """Returns (bimonth, upcoming, yesterday, prev_month) event lists across every tutor's calendar."""
    buckets = {'bimonth': [], 'yesterday': [], 'prev_month': []}
    upcoming = []
    for tutor in tutors:
        items = service_cal.events().list(
            calendarId=tutor['cal_id'],
            timeMin=w.prev_month_start_str,
            timeMax=w.bimonth_end_str,
            singleEvents=True,
            orderBy='startTime',
            timeZone='UTC'
        ).execute().get('items', [])

        for item in items:
            parsed = parse_calendar_event(item, tutor['name'], w)
            if parsed is None:
                continue
            bucket, event = parsed
            buckets[bucket].append(event)
            if bucket == 'bimonth' and w.tomorrow_end < event['start'] <= w.upcoming_end:
                upcoming.append(event)
        logging.info(f"Events fetched for {tutor['name']}")

    return (sorted(buckets['bimonth'], key=lambda e: e['start']), upcoming,
            buckets['yesterday'], sorted(buckets['prev_month'], key=lambda e: e['start']))


def fetch_payments_due(creds, tutors, today):
    """On biweekly pay days, the amount each tutor's finance sheet says they're owed."""
    if (today - datetime.date(2025, 3, 7)).days % 14 != 0:
        return []
    sheet = build('sheets', 'v4', credentials=creds, cache_discovery=False).spreadsheets()
    payments_due = []
    for tutor in tutors:
        if not tutor['finance_ss_id']:
            continue
        values = sheet.values().get(spreadsheetId=tutor['finance_ss_id'],
            range='Summary!Q3', valueRenderOption='UNFORMATTED_VALUE').execute().get('values', [])
        amount = values[0][0] if values and values[0] else None
        if amount:
            payments_due.append({'tutor': tutor, 'amount': amount})
            logging.info(f"Payment due for {tutor['name']}")
    return payments_due


def fetch_sheet_data(creds, w, retries=3):
    """Returns (summary_rows, last-30-days session rows from the All sheet, sheets resource)."""
    for attempt in range(retries):
        try:
            logging.info('Calling Sheets API #' + str(attempt + 1))
            sheet = build('sheets', 'v4', credentials=creds, cache_discovery=False).spreadsheets()
            summary_data = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=SUMMARY_RANGE,
                valueRenderOption='UNFORMATTED_VALUE'
            ).execute().get('values', [])

            all_sessions = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range='All!A:D',
                valueRenderOption='UNFORMATTED_VALUE'
            ).execute().get('values', [])
            prev_month_sessions = []
            for row in all_sessions:
                if len(row) < 4:
                    continue
                row_date = parse_sheet_date(row[1])
                if row_date and row_date >= w.prev_month_start.date():
                    prev_month_sessions.append({
                        'tutor': str(row[0]).strip(),
                        'start': row_date.strftime('%m/%d/%Y'),
                        'student': str(row[2]).strip(),
                        'duration': row[3]
                    })

            if summary_data:
                logging.info(f'Fetched {len(summary_data)} summary rows and {len(prev_month_sessions)} recent session rows')
                break
            logging.info('summary_data failed')

        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed: {e}", exc_info=True)
            if attempt == retries - 1:
                raise
            delay = [5, 10, 30][attempt]
            logging.info(f"Retrying in {delay} seconds...")
            time.sleep(delay)
    return summary_data, prev_month_sessions, sheet


def get_events_and_data(w, tutors):
    # Load credentials via centralized helper. Prefer a local user token if present.
    creds = utils.load_google_credentials(
        os.path.join(basedir, 'service_account_key.json'), os.path.join(basedir, 'token.json'),
        os.path.join(basedir, 'credentials.json'), prefer_user=True, scopes=SCOPES)

    try:
        logging.info('Calling Calendar API')
        service_cal = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        bimonth_events, upcoming_events, events_yesterday, prev_month_events = fetch_calendar_events(service_cal, tutors, w)
        payments_due = fetch_payments_due(creds, tutors, w.today)
        summary_data, prev_month_sessions, sheet = fetch_sheet_data(creds, w)
        return (bimonth_events, prev_month_events, upcoming_events, events_yesterday,
                summary_data, prev_month_sessions, sheet, payments_due)
    except Exception:
        logging.error('Error in get_events_and_data', exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Per-run state
# ---------------------------------------------------------------------------

def empty_weekly_data():
    return {key: [0] * 11 for key in ('dates', 'sessions', 'day_hours', 'evening_hours', 'projected_hours')}


@dataclass
class Run:
    """Everything the run produces, created up front so the report can go out even if the run fails midway."""
    messages: list = field(default_factory=list)
    status_updates: list = field(default_factory=list)
    add_students_to_data: list = field(default_factory=list)
    cc_sessions: list = field(default_factory=list)
    session_discrepancies: list = field(default_factory=list)
    student_data: list = field(default_factory=list)
    tutoring_events: list = field(default_factory=list)
    my_tutoring_events: list = field(default_factory=list)
    my_tutoring_events_yesterday: list = field(default_factory=list)
    unscheduled_students: list = field(default_factory=list)
    low_scheduled_students: list = field(default_factory=list)
    other_scheduled_students: list = field(default_factory=list)
    tutors_attention: set = field(default_factory=set)
    payments_due: list = field(default_factory=list)
    weekly_data: dict = field(default_factory=empty_weekly_data)
    my_session_count: int = 0
    my_tutoring_hours: float = 0
    other_session_count: int = 0
    other_tutoring_hours: float = 0
    script_status: str = 'failed'
    exception: str = None

    def log(self, msg):
        logging.info(msg)
        self.messages.append(msg)


def student_queries(session):
    """Queries (not results) so the report reflects status changes made during the run."""
    students = session.query(User).order_by(User.first_name).filter(User.role == 'student')
    active = students.filter(User.status == 'active').filter(
        User.subject.in_(['sat', 'act', 'sat/act', '']) | User.subject.is_(None))
    return SimpleNamespace(
        students=students,
        paused=students.filter(User.status == 'paused'),
        unregistered_active=active.filter(User.test_dates.any(UserTestDate.is_registered == False)),
        undecided_active=active.filter(~User.test_dates.any()),
    )


def get_tutor_from_name(tutors, name):
    for tutor in tutors:
        if full_name(tutor) == name:
            return tutor


# ---------------------------------------------------------------------------
# Reminder emails
# ---------------------------------------------------------------------------

def send_session_reminders(run, w, upcoming_events, students, tutors, send):
    """Email students (~2 days ahead) about their sessions."""
    run.log('\nSession reminders for ' + w.upcoming_start_formatted + ':')
    upcoming_students = [s for s in students if s.status in ('active', 'prospective')]
    count = 0
    for e in upcoming_events:
        if 'projected' in e['name'].lower():
            continue
        for student in upcoming_students:
            if mentions(full_name(student), e['name']):
                count += 1
                run.log(send(send_reminder_email, e, student, get_tutor_from_name(tutors, e['tutor'])))
    if count == 0:
        run.log('No reminders sent.')


def mark_past_test_dates(run, session, test_dates, today):
    for d in test_dates:
        if d.status != 'past' and d.date <= today:
            d.status = 'past'
            session.add(d)
            session.commit()
            run.log('Test date ' + str(d.date) + ' marked as past')


def send_test_reminders(run, users, today, send):
    """Registration-deadline and test-day reminders."""
    for u in users:
        for d in u.get_dates():
            if d.date == today and u.is_registered(d):
                run.log(f'{full_name(u)} was registered for today\'s {d.test}')
            elif d.reg_date == today + datetime.timedelta(days=5) and not u.is_registered(d):
                run.log(send(send_registration_reminder_email, u, d))
            elif d.late_date == today + datetime.timedelta(days=5) and not u.is_registered(d):
                run.log(send(send_late_registration_reminder_email, u, d))
            elif d.date == today + datetime.timedelta(days=6) and u.is_registered(d):
                run.log(send(send_test_reminder_email, u, d))


# ---------------------------------------------------------------------------
# Student sync: spreadsheet rows <-> database <-> calendar
# ---------------------------------------------------------------------------

def parse_summary_row(row):
    """The Summary sheet columns we use, tolerating short rows."""
    hours = None
    if len(row) > 3 and row[3] != '':
        try:
            hours = float(row[3])
        except Exception:
            hours = row[3]
    last_session_epoch = None
    if len(row) > 16 and row[16] != '':
        try:
            last_session_epoch = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(row[16]))
        except Exception:
            pass
    return SimpleNamespace(
        status=row[1] if len(row) > 1 else '',
        hours=hours,
        rate=row[4] if len(row) > 4 else None,
        pay_type=row[7] if len(row) > 7 else None,
        tutors=row[8].split(', ') if len(row) > 8 and row[8] else [],
        last_session_epoch=last_session_epoch,
        last_session=last_session_epoch.strftime('%m/%d/%Y') if last_session_epoch else None,
    )


def sync_status(run, session, s, name, sheet_status, bimonth_events):
    """Copy the sheet's status onto the student, and reactivate anyone scheduled in the next ~2 weeks.

    Returns True when the sheet's own status cell needs updating too.
    """
    initial_status = s.status
    reactivated = False
    if sheet_status and sheet_status != s.status.title():
        s.status = sheet_status.lower()

    if s.status not in {'active', 'prospective'} and any(
            mentions(name, e['name']) and e['week_num'] <= 1 for e in bimonth_events):
        s.status = 'active'
        reactivated = True

    if s.status != initial_status:
        try:
            session.merge(s)
            session.commit()
            msg = name + ' DB status = ' + s.status
            logging.info(msg)
            run.status_updates.append(msg)
        except Exception:
            err_msg = name + ' DB status update failed: ' + traceback.format_exc()
            logging.error(err_msg)
            run.messages.append(err_msg)
    return reactivated


def find_session_discrepancies(name, prev_month_events, prev_month_sessions):
    """Last month's sessions that the calendar and the Sessions sheet disagree about."""
    sheet_by_key = {}
    for sess in prev_month_sessions:
        sheet_by_key.setdefault((sess['student'], sess['start'], sess['tutor']), sess)

    found = []
    cal_keys = set()
    for p in prev_month_events:
        if not mentions(name, p['name']):
            continue
        p_date_str = calendar_date_us_central_str(p['start'])
        if not p_date_str:
            continue
        cal_keys.add((p_date_str, p['tutor']))
        sheet_match = sheet_by_key.get((name, p_date_str, p['tutor']))
        if sheet_match is None:
            found.append({
                'type': 'missing_from_sheet',
                'tutor': p['tutor'], 'start': p_date_str,
                'student': name, 'duration': round(p['hours'], 2)
            })
        elif abs(float(sheet_match['duration']) - p['hours']) >= 0.01:
            found.append({
                'type': 'duration_mismatch',
                'tutor': p['tutor'], 'start': p_date_str, 'student': name,
                'calendar_duration': round(p['hours'], 2), 'sheet_duration': sheet_match['duration']
            })

    for sess in prev_month_sessions:
        if sess['student'] == name and (sess['start'], sess['tutor']) not in cal_keys:
            found.append({
                'type': 'missing_from_calendar',
                'tutor': sess['tutor'], 'start': sess['start'],
                'student': name, 'duration': sess['duration']
            })
    return found


def credit_card_amount(rate, hours_this_week, hours_prepaid):
    """What to charge for hours beyond the prepaid balance (card fee included), or None if nothing is due."""
    hours_due = hours_this_week - hours_prepaid
    if hours_due <= 0:
        return None
    payment = round(float(rate) * hours_due + (0.029 * float(rate) * hours_due + 0.3) / 0.971, 2)
    return str(payment) + ' (check hours)' if hours_prepaid != 0 else payment


def build_student_data(run, session, s, summary_rows, bimonth_events, prev_month_events,
                       events_yesterday, prev_month_sessions, w):
    """Reconcile one student with the sheet and calendar. Appends to `run`; returns nothing."""
    name = full_name(s)
    sheet_row = summary_rows.get(name)
    if sheet_row is None:
        logging.info('did not find ' + name)
        run.add_students_to_data.append({'name': name, 'add_to': 'spreadsheet'})
        row_number, info, update_ss_status = None, parse_summary_row([]), None
    else:
        i, row = sheet_row
        row_number, info = i + 6, parse_summary_row(row)  # summary_data starts from A6
        update_ss_status = sync_status(run, session, s, name, info.status, bimonth_events)

    repurchase_deadline = 'ASAP' if (
        info.pay_type == 'Package' and isinstance(info.hours, (int, float)) and info.hours < 0) else ''
    hours_this_week = 0
    credit_card = info.pay_type == 'Credit card'

    for e in events_yesterday:
        if (w.yesterday_start <= e['start'] < w.bimonth_start and mentions(name, e['name'])
                and s.tutor_id == OWNER_ID):
            run.my_tutoring_events_yesterday.append({'event': e, 'student': name})
            logging.info(f"Adding {e['name']} to my tutoring events")
            if credit_card:
                hours_this_week += e['hours']

    if s.status not in {'active', 'prospective'}:
        return

    mine = [e for e in bimonth_events if mentions(name, e['name'])]
    for e in mine:
        if e['week_num'] == 0 and credit_card:
            hours_this_week += e['hours']
        run.tutoring_events.append(e)
        if s.tutor_id == OWNER_ID:
            run.my_tutoring_events.append(e)

    run.session_discrepancies.extend(find_session_discrepancies(name, prev_month_events, prev_month_sessions))

    if credit_card:
        try:
            payment = credit_card_amount(info.rate, hours_this_week, info.hours)
        except (TypeError, ValueError):
            run.log(f"{name}: can't compute the credit card payment (hours={info.hours!r}, rate={info.rate!r})")
            payment = None
        if payment is not None:
            run.cc_sessions.append({'name': name, 'payment': payment})

    next_session, next_tutor, bimonth_hours, rep_date = '', None, 0, w.now
    for e in mine:
        bimonth_hours += e['hours']
        if e['week_num'] == 0:
            hours_this_week += e['hours']
        if next_session == '' and info.last_session and e['start'].date() != info.last_session_epoch.date():
            next_session = e['start'].strftime('%a %b %d')
            next_tutor = e['tutor']
        if (isinstance(info.hours, (int, float)) and info.hours and bimonth_hours > info.hours
                and not repurchase_deadline):
            rep_date = e['start']
            repurchase_deadline = rep_date.strftime('%a %b %d')
            break

    run.student_data.append({
        'name': name,
        'row': row_number,
        'hours': info.hours,
        'rate': info.rate,
        'update_ss_status': update_ss_status,
        'status': s.status.title(),
        'tutors': info.tutors,
        'pay_type': info.pay_type,
        'next_session': next_session,
        'next_tutor': next_tutor,
        'hours_this_week': hours_this_week,
        'rep_date': rep_date,
        'deadline': repurchase_deadline
    })


def sync_students(run, session, students, summary_data, bimonth_events, prev_month_events,
                  events_yesterday, prev_month_sessions, w):
    # First row wins if a name appears twice.
    summary_rows = {}
    for i, row in enumerate(summary_data):
        if row and row[0]:
            summary_rows.setdefault(str(row[0]).strip(), (i, row))

    known = {full_name(s) for s in students}
    for name, (i, row) in summary_rows.items():
        status = row[1].strip() if len(row) > 1 and row[1] else ''
        if name not in known and status != 'Inactive':
            run.add_students_to_data.append({'name': name, 'add_to': 'database'})

    for s in students:
        build_student_data(run, session, s, summary_rows, bimonth_events, prev_month_events,
                           events_yesterday, prev_month_sessions, w)


def classify_students(run, now):
    for s in run.student_data:
        run.tutors_attention.update(s['tutors'])
        hours = s['hours']
        if s['next_session'] == '':
            run.unscheduled_students.append(s)
        elif (isinstance(hours, (int, float)) and hours and (hours < s['hours_this_week'] or hours <= 0)
                and s['rep_date'] <= now + datetime.timedelta(days=7) and s['pay_type'] == 'Package'):
            run.low_scheduled_students.append(s)
        else:
            run.other_scheduled_students.append(s)
    run.low_scheduled_students.sort(key=lambda s: s['rep_date'])


# ---------------------------------------------------------------------------
# Writing back to the sheets
# ---------------------------------------------------------------------------

def update_schedule_sheet(sheet, student_data):
    """Write each student's next session and repurchase deadline (and status, if it changed) to the Summary sheet."""
    batch_updates = []
    for s in student_data:
        if s['row'] is None:  # not on the sheet yet; reported as "add to spreadsheet"
            continue
        if s['update_ss_status']:
            batch_updates.append({'range': f'B{s["row"]}', 'values': [[s['status']]]})
        batch_updates.append({'range': f'J{s["row"]}', 'values': [[s['next_session']]]})
        batch_updates.append({'range': f'K{s["row"]}', 'values': [[s['deadline']]]})
    if batch_updates:
        sheet.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'valueInputOption': 'USER_ENTERED', 'data': batch_updates}
        ).execute(num_retries=3)
        logging.info('Successfully updated student schedule data')


def record_yesterdays_sessions(sheet, sessions):
    """Append yesterday's sessions with the owner's students to the Sessions sheet, skipping ones already there."""
    if not sessions:
        return
    try:
        try:
            existing = sheet.values().get(
                spreadsheetId=SPREADSHEET_ID,
                range='Sessions!B3:C',
                valueRenderOption='UNFORMATTED_VALUE'
            ).execute().get('values', [])
            next_row = 3 + len(existing)
            existing_pairs = {
                (
                    parse_sheet_date(row[0]).strftime('%m/%d/%Y') if parse_sheet_date(row[0]) else str(row[0]).strip(),
                    str(row[1]).strip()
                )
                for row in existing if len(row) >= 2
            }
        except Exception:
            next_row = None
            existing_pairs = set()

        append_rows = []
        for item in sessions:
            ev, student_name = item['event'], item['student']
            date_str = calendar_date_us_central_str(ev.get('start')) or str(ev.get('start')).strip()
            if (date_str, student_name) in existing_pairs:
                logging.info(f'Skipping duplicate row: {student_name} on {date_str}')
                continue
            append_rows.append([date_str, '="' + student_name + '"', round(ev.get('hours', 0), 2)])

        if not append_rows:
            logging.info('No new tutoring event rows to write (all duplicates)')
        elif next_row is None:
            logging.info('Failed to find next row for appending tutoring event rows')
        else:
            range_to_write = f'Sessions!B{next_row}:D{next_row + len(append_rows) - 1}'
            sheet.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=range_to_write,
                valueInputOption='USER_ENTERED',
                body={'values': append_rows}
            ).execute(num_retries=3)
            logging.info(f'Wrote {len(append_rows)} tutoring event rows to {range_to_write}')
    except Exception as e:
        logging.error(f'Failed to write tutoring events to Sessions sheet: {e}', exc_info=True)


# ---------------------------------------------------------------------------
# Admin report
# ---------------------------------------------------------------------------

def compute_weekly_stats(run, today):
    for e in run.tutoring_events:
        if e['week_num'] == 0:
            if e['tutor'] == OWNER_NAME:
                run.my_session_count += 1
                run.my_tutoring_hours += e['hours']
            else:
                run.other_session_count += 1
                run.other_tutoring_hours += e['hours']
    run.my_tutoring_hours = round(run.my_tutoring_hours, 2)
    run.other_tutoring_hours = round(run.other_tutoring_hours, 2)

    next_sunday = today + datetime.timedelta((6 - today.weekday()) % 7)
    for i in range(10):
        run.weekly_data['dates'][i] = (next_sunday + datetime.timedelta(days=i * 7)).strftime('%b %-d')
    for e in run.my_tutoring_events:
        run.weekly_data[e['time_group']][e['week_num']] += e['hours']
        run.weekly_data['sessions'][e['week_num']] += 1


def send_admin_report(run, session, w, report):
    """Weekly report (Mondays) or script status email. Runs whether or not the job succeeded."""
    def all_of(query):
        try:
            return query.all()
        except Exception:
            logging.error('Could not load students for the report', exc_info=True)
            return []

    q = student_queries(session)
    unregistered, undecided = all_of(q.unregistered_active), all_of(q.undecided_active)
    if report == 'weekly':
        try:
            run.weekly_data['score_reports'] = utils.batch_update_weekly_usage()
        except FileNotFoundError as fe:
            logging.warning(f"Weekly usage log not found (dev environment); skipping: {fe}")
        except Exception as e:
            logging.error(f"Failed to batch update weekly usage: {e}", exc_info=True)
        send_weekly_report_email(run.messages, run.status_updates, run.my_session_count, run.my_tutoring_hours,
            run.other_session_count, run.other_tutoring_hours, run.low_scheduled_students, run.unscheduled_students,
            all_of(q.paused), run.tutors_attention, run.weekly_data, run.add_students_to_data, run.cc_sessions,
            run.session_discrepancies, unregistered, undecided, w.now,
            script_status=run.script_status, exception=run.exception or '')
    else:
        send_script_status_email('reminders.py', run.messages, run.status_updates, run.low_scheduled_students,
            run.unscheduled_students, run.other_scheduled_students, run.tutors_attention, run.add_students_to_data,
            run.cc_sessions, run.session_discrepancies, unregistered, undecided,
            run.payments_due, run.script_status, run.exception)


# @profile
def main(send_reminders=True, report=None, session=None, now=None, today=None):
    """send_reminders=False logs the reminders it would send instead of emailing students/parents/tutors.
    report: 'weekly' or 'status' forces which admin email goes out (default: weekly on Mondays).
    session/now/today: for tests; default to the app's db session and the current time."""
    def send(fn, *args):
        return fn(*args) if send_reminders else f'Not sent (send_reminders=False): {fn.__name__}'

    w = windows_for(now, today)
    report = report or ('weekly' if w.day_of_week == 'Monday' else 'status')
    session = session or db.session
    run = Run()

    try:
        logging.info('reminders.py started')
        tutors = load_tutors()
        students = student_queries(session).students.all()
        db_tutors = session.query(User).order_by(User.id.desc()).filter(User.role == 'tutor').all()
        test_reminder_users = session.query(User).options(
            selectinload(User.planned_tests).selectinload(UserTestDate.test_date)
        ).filter(
            User.test_dates.any(),
            User.test_reminders == True
        ).order_by(User.first_name).all()

        (bimonth_events, prev_month_events, upcoming_events, events_yesterday,
         summary_data, prev_month_sessions, sheet, run.payments_due) = get_events_and_data(w, tutors)
        logging.info('Fetched upcoming events successfully')

        send_session_reminders(run, w, upcoming_events, students, db_tutors, send)
        sync_students(run, session, students, summary_data, bimonth_events, prev_month_events,
                      events_yesterday, prev_month_sessions, w)
        classify_students(run, w.now)
        update_schedule_sheet(sheet, run.student_data)
        record_yesterdays_sessions(sheet, run.my_tutoring_events_yesterday)

        mark_past_test_dates(run, session, session.query(TestDate).all(), w.today)
        send_test_reminders(run, test_reminder_users, w.today, send)
        compute_weekly_stats(run, w.today)

        run.script_status = 'succeeded'
        logging.info('reminders.py succeeded')

    except Exception:
        logging.error('reminders.py failed: %s', traceback.format_exc())
        run.exception = traceback.format_exc()

    finally:
        try:
            send_admin_report(run, session, w, report)
        finally:
            session.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-reminders', action='store_true', help='skip all student/parent/tutor reminder emails')
    parser.add_argument('--report', choices=['weekly', 'status'], help='force which admin email is sent')
    args = parser.parse_args()
    app = create_app()
    # create_app() points the root logger at logs/openpath.log; take it back for this script.
    configure_logging(log_file=os.path.join(basedir, 'logs', 'reminders.log'))
    with app.app_context():
        main(send_reminders=not args.no_reminders, report=args.report)
