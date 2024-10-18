from __future__ import print_function
import datetime
from dateutil.parser import parse, isoparse
from dateutil import tz
import pytz
import os.path
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from app import app, db, full_name
from dotenv import load_dotenv
from app.models import User, TestDate, UserTestDate
from app.email import get_quote, send_reminder_email, send_test_reminder_email, \
    send_registration_reminder_email, send_late_registration_reminder_email, \
    send_weekly_report_email, send_script_status_email, send_tutor_email
from sqlalchemy.orm import joinedload, sessionmaker
import requests
import traceback
from pprint import pprint
import logging
import time

# Configure logging
# error_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/errors.log')
# logging.basicConfig(filename=error_file_path, level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

info_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/info.log')
logging.basicConfig(filename=info_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a new session
session = db.session

now = datetime.datetime.utcnow()
bimonth_start = now - datetime.timedelta(hours=now.hour-8, minutes=now.minute, seconds=now.second)
bimonth_start_str = bimonth_start.isoformat() + 'Z'
bimonth_start_tz_aware = pytz.utc.localize(bimonth_start)
upcoming_start = bimonth_start_tz_aware + datetime.timedelta(hours=48)
upcoming_start_formatted = datetime.datetime.strftime(upcoming_start, format='%A, %b %-d')
upcoming_end = bimonth_start_tz_aware + datetime.timedelta(hours=72)
today = datetime.date.today()
day_of_week = datetime.datetime.strftime(now, format='%A')

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets']

# ID and ranges of a sample spreadsheet.
SPREADSHEET_ID = app.config['SPREADSHEET_ID']
SUMMARY_RANGE = 'Student summary!A1:Z'
calendars = [
    { 'tutor': 'Danny Pernik', 'id': 'danny@openpathtutoring.com' },
    { 'tutor': 'Sean Palermo', 'id': 'n6dbnktn1mha2t4st36h6ljocg@group.calendar.google.com' },
    { 'tutor': 'John Vasiloff', 'id': '47e09e4974b3dbeaace26e3e593062110f42148a9b400dd077ecbe7b2ae4dc8b@group.calendar.google.com' },
    { 'tutor': 'Michele Mundy', 'id': 'beb1bf9632e190e774619add16675537c871f5367f00b0260cec261dde8717b7@group.calendar.google.com' },
    { 'tutor': 'Elizabeth Walker', 'id': '2f96dd1a476fb24970a6307a96fb718867066c1b8ff0c9de865a440e874cb329@group.calendar.google.com' }
]

# gspread to write to spreadsheet
service_creds = ServiceAccountCredentials.from_json_keyfile_name(os.path.join(basedir, 'service_account_key.json'), scopes=SCOPES)
file = gspread.authorize(service_creds)
workbook = file.open_by_key(SPREADSHEET_ID)
sheet = workbook.sheet1

def get_events_and_data():
    '''
    '''
    flow = Flow.from_client_secrets_file(os.path.join(basedir, 'credentials.json'), SCOPES)

    authorization_url, state = flow.authorization_url(
    # Enable offline access so that you can refresh an access token without
    # re-prompting the user for permission. Recommended for web server apps.
    access_type='offline',
    # Enable incremental authorization. Recommended as a best practice.
    include_granted_scopes='true')

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                os.path.join(basedir, 'credentials.json'), SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        logging.info('Calling Calendar API')
        # Call the Calendar API
        service_cal = build('calendar', 'v3', credentials=creds)
        bimonth_end = now + datetime.timedelta(days=70)
        bimonth_end_str = bimonth_end.isoformat() + 'Z'
        bimonth_events = []

        # Collect next 2 months of events for all calendars
        for cal in calendars:
            try:
                bimonth_cal_events = service_cal.events().list(calendarId=cal['id'], timeMin=bimonth_start_str,
                    timeMax=bimonth_end_str, singleEvents=True, orderBy='startTime', timeZone='UTC').execute()
                bimonth_events_result = bimonth_cal_events.get('items', [])

                for e in bimonth_events_result:
                    if e['start'].get('dateTime'):
                        bimonth_events.append({
                            'event': e,
                            'tutor': cal['tutor']
                        })
                logging.info(f"Events fetched for {cal['tutor']}")
            except Exception as e:
                logging.error(f"Error fetching events for {cal['tutor']}: {e}", exc_info=True)
                raise

        bimonth_events = sorted(bimonth_events, key=lambda e: e['event']['start'].get('dateTime'))

        try:
            # Call the Sheets API
            service_sheets = build('sheets', 'v4', credentials=creds)
            sheet = service_sheets.spreadsheets()
            result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                        range=SUMMARY_RANGE).execute()
            summary_data = result.get('values', [])

            logging.info('summary data fetched')
        except Exception as e:
            logging.error(f"Error fetching summary data: {e}", traceback.format_exc(), exc_info=True)
            raise

        logging.info(f'Fetched {len(summary_data)} rows of summary data from Google Sheets')
        return bimonth_events, summary_data, bimonth_start_tz_aware

    except Exception as e:
        logging.error(f"Error in get_events_and_data: {e}", traceback.format_exc())
        raise

def get_upcoming_events():
    logging.info('Getting upcoming events')
    bimonth_events, summary_data, bimonth_start_tz_aware = get_events_and_data()

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

            week_num = max(1, math.ceil(((e_start - bimonth_start_tz_aware).days + 1) / 7)) - 1

            events_by_week.append({
                'name': e['event'].get('summary'),
                'date': e['event']['start'].get('dateTime'),
                'hours': hours,
                'tutor': e['tutor'],
                'time_group': time_group,
                'week_num': week_num
            })

            if upcoming_start < e_start <= upcoming_end:
                upcoming_events.append(e)

        return events_by_week, upcoming_events, bimonth_events, summary_data
    except Exception as e:
        logging.error(f"Error getting upcoming events: {e}", traceback.format_exc())
        raise


def main():
    try:
        logging.info('reminders.py started')
        students = session.query(User).order_by(User.first_name).filter(User.role == 'student')
        tutors = session.query(User).order_by(User.id.desc()).filter(User.role == 'tutor')
        test_dates = session.query(TestDate).all()
        test_reminder_users = session.query(User).order_by(User.first_name).filter(
            User.test_dates).filter(User.test_reminders)
        upcoming_students = students.filter((User.status == 'active') | (User.status == 'prospective'))
        paused_students = students.filter(User.status == 'paused')
        unregistered_active_students = students.filter(User.status == 'active').filter(User.test_dates.any(UserTestDate.is_registered == False))
        undecided_active_students = students.filter(User.status == 'active').filter(~User.test_dates.any())
        unscheduled_students = []
        low_scheduled_students = []
        other_scheduled_students = []
        status_updates = []
        student_data = []
        tutors_attention = set()
        tutoring_events = []
        my_tutoring_events = []
        add_students_to_data = []
        messages = []

        events_by_week, upcoming_events, bimonth_events, \
            summary_data = get_upcoming_events()
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
            ss_status = None
            ss_hours = None
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
                    # update DB status based on spreadsheet status
                    if row[1] != s.status.title():
                        s.status = row[1].lower()

                    # check for students who should be listed as active
                    if s.status not in {'active', 'prospective'} and any(name in event['name'] and event['week_num'] <= 1 for event in events_by_week):
                        sheet.update_cell(i+1, 2, 'Active')
                        s.status = 'active'
                        msg = name + ' is scheduled soon. Status changed to Active.'
                        logging.info(msg)
                        status_updates.append(msg)
                    if initial_status != s.status:
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

                    ss_status = row[1]
                    ss_hours = float(row[3].replace('(','-').replace(')',''))
                    ss_tutors = row[8].split(', ')
                    ss_pay_type = row[7]
                    if ss_pay_type == 'Monthly':
                        repurchase_deadline = ''
                    elif ss_hours < 0:
                        repurchase_deadline = 'ASAP'
                    if row[16] != '':
                        ss_last_session = datetime.datetime.strptime(row[16], '%m/%d/%Y')
                    else:
                        ss_last_session = None
                    break
                elif row == summary_data[-1]:
                    logging.info('did not find ' + name)
                    add_students_to_data.append({'name': name, 'add_to': 'spreadsheet'})
                    break

            if ss_status in {'Active', 'Prospective'}:
                for e in events_by_week:
                    if name in e['name']:
                        tutoring_events.append(e)
                        if s.tutor_id == 1:
                            my_tutoring_events.append(e)

                if any(name in e['name'] for e in tutoring_events):
                    for e in tutoring_events:
                        e_date = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%SZ')
                        if name in e['name']:
                            bimonth_hours += e['hours']
                            if e['week_num'] == 0:
                                hours_this_week += e['hours']
                            if next_session == '':
                                next_date = e_date
                                if ss_last_session and next_date.date() != ss_last_session.date():
                                    next_session = datetime.datetime.strftime(next_date, '%a %b %d')
                                    next_tutor = e['tutor']
                            if bimonth_hours > ss_hours and repurchase_deadline == '':
                                rep_date = e_date
                                repurchase_deadline = datetime.datetime.strftime(rep_date, '%a %b %d')
                                break

                s_data = {
                    'name': name,
                    'row': i+1,
                    'hours': ss_hours,
                    'status': ss_status,
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
        for s in student_data:
            for attempt in range(retries):
                try:
                    sheet.update_cell(s['row'], 10, s['next_session'])
                    sheet.update_cell(s['row'], 11, s['deadline'])
                    logging.info(f"Successfully updated {s['name']} in the spreadsheet")
                    break
                except gspread.exceptions.APIError as e:
                    logging.error(f"APIError: {e.response.text}")
                    if attempt < retries - 1:
                        logging.info(f"Attempt {attempt + 1} in {delay} seconds...")
                        time.sleep(2)
                    else:
                        raise
                except Exception as e:
                    logging.error(f"Unexpected error: {str(e)}")
                    raise

            tutors_attention.update(s['tutors'])

            if s['next_session'] == '':
                unscheduled_students.append(s)
            elif (s['hours'] < s['hours_this_week'] or s['hours'] <= 0) and s['rep_date'] <= (now + datetime.timedelta(days=7)) and s['pay_type'] == 'Package' :
                low_scheduled_students.append(s)
            else:
                other_scheduled_students.append(s)

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
                if d.reg_date == today + datetime.timedelta(days=5) and u.not_registered(d):
                    msg = send_registration_reminder_email(u, d)
                    logging.info(msg)
                    messages.append(msg)
                elif d.late_date == today + datetime.timedelta(days=5) and u.not_registered(d):
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
            'dates': [0,0,0,0,0,0,0,0,0,0],
            'sessions': [0,0,0,0,0,0,0,0,0,0],
            'day_hours': [0,0,0,0,0,0,0,0,0,0],
            'evening_hours': [0,0,0,0,0,0,0,0,0,0],
            'projected_hours': [0,0,0,0,0,0,0,0,0,0]
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

        if day_of_week == 'Monday':
            # TODO: implement unregistered_active_students and undecided_active_students
            for tutor in tutors:
                if full_name(tutor) in tutors_attention and tutor.id != 1:
                    msg = send_tutor_email(tutor, low_scheduled_students, unscheduled_students,
                        other_scheduled_students, paused_students, unregistered_active_students, undecided_active_students)
                    logging.info(msg)
                    messages.append(msg)

        if day_of_week == 'Sunday':
            # TODO: implement unregistered_active_students and undecided_active_students
            send_weekly_report_email(messages, status_updates, my_session_count, my_tutoring_hours, other_session_count,
                other_tutoring_hours, low_scheduled_students, unscheduled_students, paused_students, tutors_attention,
                weekly_data, add_students_to_data, unregistered_active_students, undecided_active_students, now)
        else:
            send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students, unscheduled_students,
                other_scheduled_students, tutors_attention, add_students_to_data, unregistered_active_students, undecided_active_students, 'succeeded')
        logging.info('reminders.py succeeded')

    except Exception:
        logging.error('reminders.py failed:', traceback.format_exc() )
        send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students, unscheduled_students,
            other_scheduled_students, tutors_attention, add_students_to_data, 'failed', traceback.format_exc())

    finally:
        session.close()


def get_student_events(full_name):
    student_events = []
    bimonth_events, summary_data = get_events_and_data()

    for event in bimonth_events:
        if full_name in event.get('summary'):
            student_events.append(event)

    return student_events


def get_tutor_from_name(tutors, name):
    for tutor in tutors:
        if full_name(tutor) == name:
            return tutor


if __name__ == '__main__':
    main()