from __future__ import print_function
import datetime
from dateutil.parser import parse, isoparse
from dateutil import tz
import pytz
import os
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from app import create_app
from app.extensions import db
from app.helpers import full_name
from dotenv import load_dotenv
from app.models import User, TestDate, UserTestDate
from app.email import get_quote, send_reminder_email, send_test_reminder_email, \
    send_registration_reminder_email, send_late_registration_reminder_email, \
    send_weekly_report_email, send_script_status_email, send_tutor_email
from sqlalchemy.orm import sessionmaker, selectinload
import requests
import traceback
import logging
from app.logging_config import configure_logging
import time
import app.utils as utils

# session will be initialized inside `main()` after an app context is created
session = None

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
configure_logging(log_file=os.path.join(basedir, 'logs', 'reminders.log'))

now = datetime.datetime.utcnow()
bimonth_start = now - datetime.timedelta(hours=now.hour-8, minutes=now.minute, seconds=now.second)
bimonth_start_str = bimonth_start.isoformat() + 'Z'
bimonth_start_tz_aware = pytz.utc.localize(bimonth_start)
upcoming_start = bimonth_start_tz_aware + datetime.timedelta(hours=48)
upcoming_start_formatted = datetime.datetime.strftime(upcoming_start, format='%A, %b %-d')
upcoming_end = upcoming_start + datetime.timedelta(hours=24)
today = datetime.date.today()
day_of_week = datetime.datetime.strftime(now, format='%A')
tomorrow_start = bimonth_start_tz_aware + datetime.timedelta(hours=24)
tomorrow_end = upcoming_start

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets']

# ID and ranges of a sample spreadsheet.
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
SUMMARY_RANGE = 'Summary!A6:Z'


tutor_data = [
    {
        'name': 'Danny Pernik',
        'cal_id': 'danny@openpathtutoring.com'
    },
    {
        'name': 'Sean Palermo',
        'cal_id': 'n6dbnktn1mha2t4st36h6ljocg@group.calendar.google.com',
        'finance_ss_id': '1xAE_SiN7m6B8jYumBIOFC0zpl4PTkFXhGp1ynFYyF_4'
    },
    {
        'name': 'John Vasiloff',
        'cal_id': '47e09e4974b3dbeaace26e3e593062110f42148a9b400dd077ecbe7b2ae4dc8b@group.calendar.google.com',
        'finance_ss_id': '1vgLg_MlqlqN68JOR8kEFinDEVb8auITINhHfj9Spb_I'
    },
    {
        'name': 'Michele Mundy',
        'cal_id': 'beb1bf9632e190e774619add16675537c871f5367f00b0260cec261dde8717b7@group.calendar.google.com',
        'finance_ss_id': '1Y6LoD_awVY2um8gM3OqPu1wbnykrAqBZTThMp-sxP-E'
    },
    {
        'name': 'Elizabeth Walker',
        'cal_id': '2f96dd1a476fb24970a6307a96fb718867066c1b8ff0c9de865a440e874cb329@group.calendar.google.com',
        'finance_ss_id': '1Wt6D6peAjjyTk9YT-NF3xxHcWlhDrgKXtoj-_D06ndI'
    },
    {
        'name': 'Hannah Gustafson',
        'cal_id': 'cc063cbfcb84d6c89d1befd047caf6377a3bdffca7f564b75fcc4c8b8141d3d1@group.calendar.google.com',
        'finance_ss_id': '14qh4wsq5DB3aqFkqpt6nulUG7TLlIcB6LvVAxNHaHq8'
    },
    {
        'name': 'Jessica Ball',
        'cal_id': '9d581473f34ba690876c7373e64bc33e31da958d9678cdcb5b848f5f907803cb@group.calendar.google.com',
        'finance_ss_id': '1SyN3x3c5E8hCUlyE5-68i2oy1hHfON_IZ5GSyTIn4js'
    }
]

# gspread to write to spreadsheet - initialized lazily
service_creds = None
file = None
workbook = None
sheet = None


def init_gspread():
    """Initialize gspread credentials and workbook lazily."""
    global service_creds, file, workbook, sheet
    if service_creds is None:
        service_account_path = os.path.join(basedir, 'service_account_key.json')
        if os.path.exists(service_account_path):
            service_creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, scopes=SCOPES)
            file = gspread.authorize(service_creds)
            workbook = file.open_by_key(SPREADSHEET_ID)
            sheet = workbook.sheet1
        else:
            logging.warning("service_account_key.json not found, gspread functionality disabled")


# @profile
def get_events_and_data():
    '''
    '''
    # Load credentials via centralized helper. Prefer a local user token if present.
    token_path = os.path.join(basedir, 'token.json')
    client_secrets = os.path.join(basedir, 'credentials.json')
    service_account_json = os.path.join(basedir, 'service_account_key.json')
    creds = utils.load_google_credentials(service_account_json, token_path, client_secrets, prefer_user=True, scopes=SCOPES)

    try:
        logging.info('Calling Calendar API')
        # Call the Calendar API
        service_cal = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        bimonth_end = now + datetime.timedelta(days=70)
        bimonth_end_str = bimonth_end.isoformat() + 'Z'
        bimonth_events = []
        payments_due = []

        # Collect next 2 months of events for all calendars
        try:
            for tutor in tutor_data:
                bimonth_cal_events = service_cal.events().list(
                    calendarId=tutor['cal_id'],
                    timeMin=bimonth_start_str,
                    timeMax=bimonth_end_str,
                    singleEvents=True,
                    orderBy='startTime',
                    timeZone='UTC'
                ).execute()
                bimonth_events_result = bimonth_cal_events.get('items', [])

                for e in bimonth_events_result:
                    if e['start'].get('dateTime'):
                        bimonth_events.append({
                            'event': e,
                            'tutor': tutor['name']
                        })
                logging.info(f"Events fetched for {tutor['name']}")

                if (today - datetime.date(2025, 3, 7)).days % 14 == 0:
                    # Fetch finance spreadsheet data for tutors other than Danny
                    if tutor['name'] != 'Danny Pernik':
                        service_sheets = build('sheets', 'v4', credentials=creds, cache_discovery=False)
                        sheet = service_sheets.spreadsheets()
                        result = sheet.values().get(spreadsheetId=tutor['finance_ss_id'],
                            range='Summary!R3', valueRenderOption='UNFORMATTED_VALUE').execute()
                        biweekly_due_cell = result.get('values', [])

                        biweekly_due = biweekly_due_cell[0][0]
                        if biweekly_due:
                            payments_due.append({
                                'tutor': tutor['name'],
                                'amount': biweekly_due
                            })
                            logging.info(f"Payment due for {tutor['name']}")

            bimonth_events = sorted(bimonth_events, key=lambda e: e['event']['start'].get('dateTime'))
        except Exception as e:
            logging.error(f"Error fetching events for {tutor['name']}: {e}", exc_info=True)
            raise

        retries = 3
        for attempt in range(retries):
            try:
                logging.info('Calling Sheets API #' + str(attempt + 1))
                # Call the Sheets API
                service_sheets = build('sheets', 'v4', credentials=creds, cache_discovery=False)
                logging.info('Sheets API called')
                sheet = service_sheets.spreadsheets()
                logging.info('Sheet service created')
                result = sheet.values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=SUMMARY_RANGE,
                    valueRenderOption='UNFORMATTED_VALUE'
                ).execute()
                summary_data = result.get('values', [])

                if not summary_data:
                    logging.info('summary_data failed')
                else:
                    logging.info('summary_data fetched')
                    break
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed: {e}", exc_info=True)
                if attempt < retries - 1:
                    delay = [5, 10, 30][attempt]
                    logging.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise

        logging.info(f'Fetched {len(summary_data)} rows of summary data from Google Sheets')
        return bimonth_events, summary_data, bimonth_start_tz_aware, sheet, payments_due

    except Exception as e:
        logging.error(f"Error in get_events_and_data: {e}", traceback.format_exc())
        raise

# @profile
def get_upcoming_events():
    logging.info('Getting upcoming events')
    bimonth_events, summary_data, bimonth_start_tz_aware, sheet, payments_due = get_events_and_data()

    events_by_week = []
    upcoming_events = []

    try:
        # Collect necessary event information
        for e in bimonth_events:
            e_start = isoparse(e['event']['start'].get('dateTime'))
            e_end = isoparse(e['event']['end'].get('dateTime'))
            duration = str(e_end - e_start)
            (h, m, s) = duration.split(':')
            hours = int(h) + int(m) / 60 + int(s) / 3600

            if 'projected' in e['event'].get('summary').lower():
                time_group = 'projected_hours'
            elif e_end.hour + (e_end.minute / 60) <= 16.25:
                time_group = 'day_hours'
            else:
                time_group = 'evening_hours'

            start_of_week_0 = bimonth_start_tz_aware - datetime.timedelta(days=bimonth_start_tz_aware.weekday())
            week_num = max(1, math.ceil(((e_start - start_of_week_0).days + 1) / 7)) - 1

            events_by_week.append({
                'name': e['event'].get('summary'),
                'date': e['event']['start'].get('dateTime'),
                'hours': hours,
                'tutor': e['tutor'],
                'time_group': time_group,
                'week_num': week_num
            })

            if tomorrow_end < e_start <= upcoming_end:
                upcoming_events.append(e)

        return bimonth_events, events_by_week, upcoming_events, summary_data, sheet, payments_due
    except Exception as e:
        logging.error(f"Error getting upcoming events: {e}", traceback.format_exc())
        raise

# @profile
def main():
    try:
        logging.info('reminders.py started')
        messages = []

        global session
        if session is None:
            session = db.session

        students = session.query(User).order_by(User.first_name).filter(User.role == 'student')
        tutors = session.query(User).order_by(User.id.desc()).filter(User.role == 'tutor')
        test_dates = session.query(TestDate).all()
        test_reminder_users = session.query(User).options(
            selectinload(User.test_dates).selectinload(UserTestDate.test_dates)
        ).filter(
            User.test_dates.any(),
            User.test_reminders == True
        ).order_by(User.first_name)
        upcoming_students = students.filter((User.status == 'active') | (User.status == 'prospective'))
        paused_students = students.filter(User.status == 'paused')
        unregistered_active_students = students.filter(User.status == 'active').filter(
            User.subject.in_(['sat', 'act', 'sat/act', '']) | User.subject.is_(None)
        ).filter(User.test_dates.any(UserTestDate.is_registered == False))
        undecided_active_students = students.filter(User.status == 'active').filter(
            User.subject.in_(['sat', 'act', 'sat/act', '']) | User.subject.is_(None)
        ).filter(~User.test_dates.any())
        unscheduled_students = []
        low_scheduled_students = []
        other_scheduled_students = []
        status_updates = []
        student_data = []
        tutors_attention = set()
        tutoring_events = []
        my_tutoring_events = []
        cc_sessions = []
        add_students_to_data = []

        bimonth_events, events_by_week, upcoming_events, \
            summary_data, sheet, payments_due = get_upcoming_events()
        logging.info('Fetched upcoming events successfully')

        msg = '\nSession reminders for ' + upcoming_start_formatted + ':'
        logging.info(msg)
        messages.append(msg)

        # Send reminder email to students ~2 days in advance
        reminder_count = 0
        for e in upcoming_events:
            for student in upcoming_students:
                name = full_name(student)
                if name in e['event'].get('summary') and 'projected' not in e['event'].get('summary').lower():
                    reminder_count += 1
                    msg = send_reminder_email(e, student, get_tutor_from_name(tutors, e['tutor']))
                    logging.info(msg)
                    messages.append(msg)

        if reminder_count == 0:
            msg = 'No reminders sent.'
            logging.info(msg)
            messages.append(msg)

        for row in summary_data:
            if row[0] not in [full_name(s) for s in students] and row[1] != 'Inactive':
                add_students_to_data.append({'name': row[0], 'add_to': 'database'})

        for s in students:
            ss_hours = None
            ss_rate = None
            ss_tutors = []
            ss_pay_type = None
            next_session = ''
            hours_this_week = 0
            bimonth_hours = 0
            next_tutor = None
            rep_date = now
            repurchase_deadline = ''

            name = full_name(s)

            for i, row in enumerate(summary_data):
                if row[0] == name:
                    initial_status = s.status
                    update_ss_status = False
                    # update DB status based on spreadsheet status
                    if row[1] != s.status.title():
                        s.status = row[1].lower()

                    # check for students who should be listed as active
                    if s.status not in {'active', 'prospective'} and any(name in event['name'] and event['week_num'] <= 1 for event in events_by_week):
                        s.status = 'active'
                        update_ss_status = True
                        msg = name + ' is scheduled soon. Status changed to Active.'
                    if s.status != initial_status:
                        try:
                            db.session.merge(s)
                            db.session.commit()
                            msg = name + ' DB status = ' + s.status
                            logging.info(msg)
                            status_updates.append(msg)
                        except Exception:
                            err_msg = name + ' DB status update failed: ' + traceback.format_exc()
                            logging.error(err_msg)
                            messages.append(err_msg)

                    ss_hours = row[3]
                    ss_rate = row[4]
                    ss_tutors = row[8].split(', ')
                    ss_pay_type = row[7]
                    if ss_pay_type != 'Package':
                        repurchase_deadline = ''
                    elif ss_hours < 0:
                        repurchase_deadline = 'ASAP'
                    if row[16] != '':
                        ss_last_session_epoch = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=row[16])
                        ss_last_session = ss_last_session_epoch.strftime('%m/%d/%Y')
                    else:
                        ss_last_session = None
                    break
                elif row == summary_data[-1]:
                    logging.info('did not find ' + name)
                    add_students_to_data.append({'name': name, 'add_to': 'spreadsheet'})
                    break

            if s.status in {'active', 'prospective'}:
                hours_this_week = 0
                for e in events_by_week:
                    if name in e['name']:
                        if e['week_num'] == 0 and ss_pay_type == 'Credit card':
                            hours_this_week += e['hours']

                        tutoring_events.append(e)
                        if s.tutor_id == 1:
                            my_tutoring_events.append(e)

                if ss_pay_type == 'Credit card':
                    hours_due = hours_this_week - ss_hours
                    if hours_due > 0:
                        payment = round(float(ss_rate) * hours_due + (0.029 * float(ss_rate) * hours_due + 0.3 ) / 0.971, 2)
                        if ss_hours != 0:
                            payment = str(payment) + ' (check hours)'
                        cc_sessions.append({
                            'name': name,
                            'payment': payment
                        })

                if any(name in e['name'] for e in tutoring_events):
                    for e in tutoring_events:
                        e_date = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%SZ')
                        if name in e['name']:
                            bimonth_hours += e['hours']
                            if e['week_num'] == 0:
                                hours_this_week += e['hours']
                            if next_session == '':
                                next_date = e_date
                                if ss_last_session and next_date.date() != ss_last_session_epoch.date():
                                    next_session = datetime.datetime.strftime(next_date, '%a %b %d')
                                    next_tutor = e['tutor']
                            if ss_hours and bimonth_hours > ss_hours and not repurchase_deadline:
                                rep_date = e_date
                                repurchase_deadline = datetime.datetime.strftime(rep_date, '%a %b %d')
                                break

                s_data = {
                    'name': name,
                    'row': i + 6,         # summary_data starts from A6
                    'hours': ss_hours,
                    'rate': ss_rate,
                    'update_ss_status': update_ss_status,
                    'status': s.status.title(),
                    'tutors': ss_tutors,
                    'pay_type': ss_pay_type,
                    'next_session': next_session,
                    'next_tutor': next_tutor,
                    'hours_this_week' : hours_this_week,
                    'rep_date': rep_date,
                    'deadline': repurchase_deadline
                }

                student_data.append(s_data)

        retries = 3
        batch_updates = []
        for s in student_data:
            for attempt in range(retries):
                try:
                    cell_updates = [
                        *([{'range': f'B{s["row"]}', 'values': [[s['status']]]}] if s['update_ss_status'] else []),
                        {'range': f'J{s["row"]}', 'values': [[s['next_session']]]},
                        {'range': f'K{s["row"]}', 'values': [[s['deadline']]]}
                    ]

                    batch_updates.extend(cell_updates)
                    break
                except gspread.exceptions.APIError as e:
                    logging.error(f"APIError: {e.response.text}")
                    if attempt < retries - 1:
                        logging.info(f"Attempt {attempt + 1}...")
                        time.sleep(2)
                    else:
                        raise
                except Exception as e:
                    logging.error(f"Unexpected error: {str(e)}")
                    raise

            tutors_attention.update(s['tutors'])

            if s['next_session'] == '':
                unscheduled_students.append(s)
            elif s['hours'] and (s['hours'] < s['hours_this_week'] or s['hours'] <= 0) and s['rep_date'] <= (now + datetime.timedelta(days=7)) and s['pay_type'] == 'Package' :
                low_scheduled_students.append(s)
            else:
                other_scheduled_students.append(s)
        if batch_updates:
            body = {
                'valueInputOption': 'USER_ENTERED',
                'data': batch_updates
            }
            sheet.values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=body
            ).execute()
            logging.info('Successfully updated student schedule data')

        low_scheduled_students = sorted(low_scheduled_students, key=lambda s: s['rep_date'])

        ### mark test dates as past
        for d in test_dates:
            if d.status != 'past' and d.date <= today:
                d.status = 'past'
                db.session.add(d)
                db.session.commit()
                msg = 'Test date ' + str(d.date) + ' marked as past'
                logging.info(msg)
                messages.append(msg)

        ### send registration and test reminder emails
        for u in test_reminder_users:
            for d in u.get_dates():
                if d.date == today and u.is_registered(d):
                    msg = f'{full_name(u)} was registered for today\'s {d.test}'
                    logging.info(msg)
                    messages.append(msg)
                elif d.reg_date == today + datetime.timedelta(days=5) and not u.is_registered(d):
                    msg = send_registration_reminder_email(u, d)
                    logging.info(msg)
                    messages.append(msg)
                elif d.late_date == today + datetime.timedelta(days=5) and not u.is_registered(d):
                    msg = send_late_registration_reminder_email(u, d)
                    logging.info(msg)
                    messages.append(msg)
                elif d.date == today + datetime.timedelta(days=6) and u.is_registered(d):
                    msg = send_test_reminder_email(u, d)
                    logging.info(msg)
                    messages.append(msg)

        my_session_count = 0
        my_student_count = 0
        my_tutoring_hours = 0
        other_session_count = 0
        other_student_count = 0
        other_tutoring_hours = 0
        next_sunday = today + datetime.timedelta((6 - today.weekday()) % 7)
        weekly_data = {
            'dates': [0,0,0,0,0,0,0,0,0,0,0],
            'sessions': [0,0,0,0,0,0,0,0,0,0,0],
            'day_hours': [0,0,0,0,0,0,0,0,0,0,0],
            'evening_hours': [0,0,0,0,0,0,0,0,0,0,0],
            'projected_hours': [0,0,0,0,0,0,0,0,0,0,0]
        }

        for e in tutoring_events:
            if e['week_num'] == 0:
                if e['tutor'] == 'Danny Pernik':
                    my_session_count += 1
                    my_tutoring_hours += e['hours']
                else:
                    other_session_count += 1
                    other_tutoring_hours += e['hours']
        my_tutoring_hours = round(my_tutoring_hours, 2)
        other_tutoring_hours = round(other_tutoring_hours, 2)

        ### Generate admin report
        for i in range(10):
            s = next_sunday + datetime.timedelta(days=(i * 7))
            s_str = s.strftime('%b %-d')
            weekly_data['dates'][i] = s_str

        for e in my_tutoring_events:
            weekly_data[e['time_group']][e['week_num']] += e['hours']
            weekly_data['sessions'][e['week_num']] += 1

        # if day_of_week == 'Monday':
        #     # TODO: implement unregistered_active_students and undecided_active_students
        #     for tutor in tutors:
        #         if full_name(tutor) in tutors_attention and tutor.id != 1:
        #             msg = send_tutor_email(tutor, low_scheduled_students, unscheduled_students,
        #                 other_scheduled_students, paused_students, unregistered_active_students, undecided_active_students)
        #             logging.info(msg)
        #             messages.append(msg)


        if day_of_week == 'Monday':
            weekly_data['score_reports'] = utils.batch_update_weekly_usage()
            send_weekly_report_email(messages, status_updates, my_session_count, my_tutoring_hours, other_session_count,
                other_tutoring_hours, low_scheduled_students, unscheduled_students, paused_students, tutors_attention,
                weekly_data, add_students_to_data, cc_sessions, unregistered_active_students, undecided_active_students, now)
        else:
            send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students,
                unscheduled_students, other_scheduled_students, tutors_attention, add_students_to_data,
                cc_sessions, unregistered_active_students, undecided_active_students, payments_due, 'succeeded')
        logging.info('reminders.py succeeded')

    except Exception as e:
        logging.error('reminders.py failed: %s', traceback.format_exc())
        send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students,
            unscheduled_students, other_scheduled_students, tutors_attention, add_students_to_data,
            cc_sessions, unregistered_active_students, undecided_active_students, payments_due, 'failed',
            traceback.format_exc())

    finally:
        session.close()


def get_student_events(full_name):
    student_events = []
    bimonth_events, summary_data, bimonth_start_tz_aware, sheet, payments_due = get_events_and_data()

    for event in bimonth_events:
        if full_name in event.get('summary'):
            student_events.append(event)

    return student_events


def get_tutor_from_name(tutors, name):
    for tutor in tutors:
        if full_name(tutor) == name:
            return tutor


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        main()