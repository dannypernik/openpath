from __future__ import print_function
import datetime
from dateutil.parser import parse, isoparse
from dateutil import tz
import pytz
import os.path
import math
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

# Create a new session
session = db.session

now = datetime.datetime.utcnow()
now_str = now.isoformat() + 'Z'
now_tz_aware = pytz.utc.localize(now)
today = datetime.date.today()
day_of_week = datetime.datetime.strftime(now, format="%A")
upcoming_start = now_tz_aware + datetime.timedelta(hours=42)
upcoming_start_formatted = datetime.datetime.strftime(upcoming_start, format="%A, %b %-d")
upcoming_end = now_tz_aware + datetime.timedelta(hours=66)
bimonth_end = now + datetime.timedelta(days=70)
bimonth_end_str = bimonth_end.isoformat() + 'Z'
bimonth_events = []
events_by_week = []
upcoming_events = []
tutoring_events = []
my_tutoring_events = []

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets']

# ID and ranges of a sample spreadsheet.
SPREADSHEET_ID = app.config['SPREADSHEET_ID']
SUMMARY_RANGE = 'Student summary!A1:S'
calendars = [
    { 'tutor': 'Danny Pernik', 'id': 'danny@openpathtutoring.com' },
    { 'tutor': 'Sean Palermo', 'id': 'n6dbnktn1mha2t4st36h6ljocg@group.calendar.google.com' },
    { 'tutor': 'John Vasiloff', 'id': '47e09e4974b3dbeaace26e3e593062110f42148a9b400dd077ecbe7b2ae4dc8b@group.calendar.google.com' },
    { 'tutor': 'Michele Mundy', 'id': 'beb1bf9632e190e774619add16675537c871f5367f00b0260cec261dde8717b7@group.calendar.google.com' }
]


def get_events_and_data():
    """
    """
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

    # Call the Calendar API
    service_cal = build('calendar', 'v3', credentials=creds)

    # Collect next 2 months of events for all calendars
    for cal in calendars:
        bimonth_cal_events = service_cal.events().list(calendarId=cal['id'], timeMin=now_str,
            timeMax=bimonth_end_str, singleEvents=True, orderBy='startTime', timeZone='UTC').execute()
        bimonth_events_result = bimonth_cal_events.get('items', [])

        for e in bimonth_events_result:
            if e['start'].get('dateTime'):
                bimonth_events.append({
                    'event': e,
                    'tutor': cal['tutor']
                })

    # Call the Sheets API
    service_sheets = build('sheets', 'v4', credentials=creds)
    sheet = service_sheets.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                range=SUMMARY_RANGE).execute()
    summary_data = result.get('values', [])

    if not summary_data:
        msg = 'No summary data found.'
        print(msg)
        messages.append(msg)
        return

    return bimonth_events, summary_data


def get_upcoming_events():
    bimonth_events, summary_data = get_events_and_data()

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

        week_num = max(1, math.ceil(((e_start - now_tz_aware).days + 1) / 7)) - 1

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


def main():
    try:
        students = session.query(User).order_by(User.first_name).filter(User.role == 'student')
        tutors = session.query(User).order_by(User.id.desc()).filter(User.role == 'tutor')
        test_dates = session.query(TestDate).all()
        test_reminder_users = session.query(User).order_by(User.first_name).filter(
            User.test_dates).filter(User.test_reminders) #.options(joinedload('parent'), joinedload('tutor'))
        upcoming_students = students.filter((User.status == 'active') | (User.status == 'prospective'))
        paused_students = students.filter(User.status == 'paused')
        unscheduled_students = []
        low_scheduled_students = []
        other_scheduled_students = []
        status_updates = []
        student_data = []
        add_students_to_db = []
        messages = []
        tutors_attention = set()


        events_by_week, upcoming_events, bimonth_events, \
            summary_data = get_upcoming_events()

        msg = "\nSession reminders for " + upcoming_start_formatted + ":"
        print(msg)
        messages.append(msg)

        # Send reminder email to students ~2 days in advance
        reminder_count = 0
        for e in upcoming_events:
            for student in upcoming_students:
                name = full_name(student)
                if name in e['event'].get('summary') and 'projected' not in e['event'].get('summary').lower():
                    reminder_count += 1
                    msg = send_reminder_email(e, student, get_tutor_from_name(e['tutor']))
                    print(msg)
                    messages.append(msg)

        if reminder_count == 0:
            msg = "No reminders sent."
            print(msg)
            messages.append(msg)

        messages.append('')

        bimonth_hours = 0
        for s in students:
            ss_status = None
            ss_hours = None
            ss_tutors = []
            ss_pay_type = None
            next_session = None
            hours_this_week = 0
            next_tutor = None
            repurchase_deadline = None

            name = full_name(s)

            for i, row in enumerate(summary_data):
                if row[0] == '':
                    add_students_to_db.append(name)
                    break

                if row[0] == name:
                    # Update DB status based on spreadsheet status
                    if row[1] != s.status.title():
                        s.status = row[1].lower()
                        try:
                            db.session.merge(s)
                            db.session.commit()
                            msg = name + ' DB status = ' + s.status
                            print(msg)
                            status_updates.append(msg)
                        except Exception:
                            err_msg = name + ' DB status update failed: ' + traceback.format_exc()
                            print(err_msg)
                            messages.append(err_msg)

                    # check for students who should be listed as active
                    if s.status not in {'active', 'prospective'} and any(name in event['name'] and event['week_num'] == 0 for event in events_by_week):
                        msg = name + ' is scheduled next week. Change status to active.'
                        print(msg)
                        status_updates.append(msg)

                    ss_status = row[1]
                    ss_hours = float(row[3])
                    ss_tutors = row[6].split(', ')
                    ss_pay_type = row[5]
                    break

            if ss_status in {'Active', 'Prospective'}:
                for e in events_by_week:
                    if name in e['name']:
                        tutoring_events.append(e)
                        if s.tutor_id == 1:
                            my_tutoring_events.append(e)

                if any(name in e['name'] for e in tutoring_events):
                    for e in tutoring_events:
                        if name in e['name']:
                            bimonth_hours += e['hours']
                            if e['week_num'] == 0:
                                hours_this_week += e['hours']
                            if next_session is None:
                                next_date = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%SZ')
                                next_session = datetime.datetime.strftime(next_date, '%a %b %-d')
                                next_tutor = e['tutor']
                            if ss_hours < 0:
                                repurchase_deadline = 'ASAP'
                            elif bimonth_hours > ss_hours and repurchase_deadline is None:
                                rep_date = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%SZ')
                                repurchase_deadline = datetime.datetime.strftime(rep_date, '%a %b %d')

                s_data = {
                    'name': name,
                    'hours': ss_hours,
                    'status': ss_status,
                    'tutors': ss_tutors,
                    'pay_type': ss_pay_type,
                    'next_session': next_session,
                    'next_tutor': next_tutor,
                    'hours_this_week' : hours_this_week,
                    'deadline': repurchase_deadline
                }

                student_data.append(s_data)

        for s in student_data:
            if s['next_session'] is None:
                unscheduled_students.append(s)
                tutors_attention.update(s['tutors'])
            elif (s['hours'] < s['hours_this_week'] or s['hours'] < 0) and s['pay_type'] == 'Package' :
                low_scheduled_students.append(s)
                tutors_attention.update(s['tutors'])
            else:
                other_scheduled_students.append(s)

        ### mark test dates as past
        for d in test_dates:
            if d.status != 'past' and d.date <= today:
                d.status = 'past'
                db.session.add(d)
                db.session.commit()
                msg = 'Test date ' + str(d.date) + ' marked as past'
                print(msg)
                messages.append(msg)

        ### send registration and test reminder emails
        for u in test_reminder_users:
            for d in u.get_dates():
                if d.reg_date == today + datetime.timedelta(days=5) and u.not_registered(d):
                    msg = send_registration_reminder_email(u, d)
                    print(msg)
                    messages.append(msg)
                elif d.late_date == today + datetime.timedelta(days=5) and u.not_registered(d):
                    msg = send_late_registration_reminder_email(u, d)
                    print(msg)
                    messages.append(msg)
                elif d.date == today + datetime.timedelta(days=6) and u.is_registered(d):
                    msg = send_test_reminder_email(u, d)
                    print(msg)
                    messages.append(msg)


        ### send weekly reports
        if day_of_week == 'Sunday':
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

            ### Generate admin report
            for i in range(10):
                s = next_sunday + datetime.timedelta(days=(i * 7))
                s_str = s.strftime('%b %-d')
                weekly_data['dates'][i] = s_str

            for e in my_tutoring_events:
                weekly_data[e['time_group']][e['week_num']] += e['hours']
                weekly_data['sessions'][e['week_num']] += 1

            for tutor in tutors:
                if any(full_name(tutor) in s['tutors'] for s in student_data):
                    send_tutor_email(tutor, low_scheduled_students, unscheduled_students, other_scheduled_students)

            send_weekly_report_email(my_session_count, my_tutoring_hours, other_session_count,
                other_tutoring_hours, low_scheduled_students, unscheduled_students,
                paused_students, tutors_attention, weekly_data, now)

        message, author, header = get_quote()
        msg = '\n' + message + " - " + author
        print(msg)
        messages.append(msg)
        print('Script succeeded')
        send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students, unscheduled_students, other_scheduled_students, tutors_attention, add_students_to_db, 'succeeded')

    except Exception:
        print('Script failed:', traceback.format_exc() )
        send_script_status_email('reminders.py', messages, status_updates, low_scheduled_students, unscheduled_students, other_scheduled_students, tutors_attention, add_students_to_db, 'failed', traceback.format_exc())

    finally:
        session.close()


def get_student_events(full_name):
    student_events = []
    bimonth_events, summary_data = get_events_and_data()

    for event in bimonth_events:
        if full_name in event.get('summary'):
            student_events.append(event)

    return student_events


def get_tutor_from_name(name):
    for tutor in tutors:
        if full_name(tutor) == name:
            return tutor


if __name__ == '__main__':
    main()