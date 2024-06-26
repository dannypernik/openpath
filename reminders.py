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
    send_admin_report_email, send_script_status_email, send_tutor_email
from sqlalchemy.orm import joinedload
import requests
import traceback


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets']

# ID and ranges of a sample spreadsheet.
SPREADSHEET_ID = app.config['SPREADSHEET_ID']
SUMMARY_RANGE = 'Student summary!A1:S'
calendars = [
    'danny@openpathtutoring.com', # d@OPT
    'n6dbnktn1mha2t4st36h6ljocg@group.calendar.google.com', # Sean
    '47e09e4974b3dbeaace26e3e593062110f42148a9b400dd077ecbe7b2ae4dc8b@group.calendar.google.com', #John
    'beb1bf9632e190e774619add16675537c871f5367f00b0260cec261dde8717b7@group.calendar.google.com', # Michele
]

now = datetime.datetime.utcnow()
now_tz_aware = pytz.utc.localize(now)
today = datetime.date.today()
day_of_week = datetime.datetime.strftime(now, format="%A")
upcoming_start = now + datetime.timedelta(hours=33)
upcoming_start_str = upcoming_start.isoformat() + 'Z'
upcoming_start_formatted = datetime.datetime.strftime(upcoming_start, format="%A, %b %-d")
upcoming_end = now_tz_aware + datetime.timedelta(hours=57)
bimonth_end = now + datetime.timedelta(days=70, hours=33)
bimonth_end_str = bimonth_end.isoformat() + 'Z'
upcoming_events = []
events_by_week = []
events_next_week = []
bimonth_events = []
bimonth_events_list = []
tutoring_events = []
my_tutoring_events = []
unscheduled_list = []
outsourced_unscheduled_list = []
paused_list = []
scheduled_students = set()
future_schedule = set()
outsourced_scheduled_students = set()
low_active_students = []

reminder_list = []
students = User.query.order_by(User.first_name).filter(User.role == 'student')
test_reminder_users = User.query.order_by(User.first_name).filter(
    User.test_dates).filter(User.test_reminders).options(joinedload('parent'), joinedload('tutor'))
active_students = students.filter(User.status == 'active')
upcoming_students = students.filter((User.status == 'active') | (User.status == 'prospective'))
paused_students = students.filter(User.status == 'paused')
primary_tutor = User.query.filter(User.email == app.config['ADMIN_EMAIL']).first()
student_names_db = []
status_updates = []
low_hours_students = []
add_students_to_db = []
messages = []

### Test date reminders
test_dates = TestDate.query.all()

def get_events_and_data():
    """
    """
    flow = Flow.from_client_secrets_file(
                os.path.join(basedir, 'credentials.json'), SCOPES)

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
    for id in calendars:
        bimonth_cal_events = service_cal.events().list(calendarId=id, timeMin=upcoming_start_str,
            timeMax=bimonth_end_str, singleEvents=True, orderBy='startTime', timeZone='UTC').execute()
        bimonth_events_result = bimonth_cal_events.get('items', [])

        for e in range(len(bimonth_events_result)):
            if bimonth_events_result[e]['start'].get('dateTime'):
                bimonth_events.append(bimonth_events_result[e])

    # Call the Sheets API
    service_sheets = build('sheets', 'v4', credentials=creds)
    sheet = service_sheets.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                range=SUMMARY_RANGE).execute()
    summary_data = result.get('values', [])

    return bimonth_events, summary_data


def get_upcoming_events():
    bimonth_events, summary_data = get_events_and_data()

    for e in range(len(bimonth_events)):
        e_start = isoparse(bimonth_events[e]['start'].get('dateTime'))
        e_end = isoparse(bimonth_events[e]['end'].get('dateTime'))
        duration = str(e_end - e_start)
        (h, m, s) = duration.split(':')
        hours = int(h) + int(m) / 60 + int(s) / 3600

        if 'projected' in bimonth_events[e].get('summary').lower():
            time_group = 'projected_hours'
        elif e_end.hour + (e_end.minute / 60) <= 16.25:
            time_group = 'day_hours'
        else:
            time_group = 'evening_hours'


        week_num = max(1, math.ceil(((e_start - pytz.utc.localize(upcoming_start)).days + 1) / 7)) - 1

        events_by_week.append({
            'name': bimonth_events[e].get('summary'),
            'hours': hours,
            'time_group': time_group,
            'week_num': week_num
        })

        if week_num == 0:
            events_next_week.append({
                'name': bimonth_events[e].get('summary'),
                'date': bimonth_events[e]['start'].get('dateTime'),
                'hours': hours
            })
            if e_start < upcoming_end:
                upcoming_events.append(bimonth_events[e])
    
    return events_by_week, events_next_week, upcoming_events, bimonth_events, summary_data


def main():
    try:
        events_by_week, events_next_week, upcoming_events, bimonth_events, \
            summary_data = get_upcoming_events()
        
        tutors = User.query.order_by(User.id.desc() ).filter_by(role='tutor')
        
        msg = "\nSession reminders for " + upcoming_start_formatted + ":"
        print(msg)
        messages.append(msg)

        ### Send reminder email to students ~2 days in advance
        for event in upcoming_events:
            for student in upcoming_students:
                name = full_name(student)
                if name in event.get('summary') and 'projected' not in event.get('summary').lower():
                    reminder_list.append(name)
                    msg = send_reminder_email(event, student)
                    print(msg)
                    messages.append(msg)
        
        if len(reminder_list) == 0:
            msg = "No reminders sent."
            print(msg)
            messages.append(msg)
        
        messages.append('')

        # get list of event names for the bimonth
        for e in bimonth_events:
            bimonth_events_list.append(e.get('summary'))
        
        # Get list of students with conflicting statuses, low hours, or missing from DB
        for i, row in enumerate(summary_data):
            if row[0] == '':
                break
            for s in students:
                name = full_name(s)
                student_names_db.append(name)

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
                    if s.status not in ['active', 'prospective'] and any(name in event['name'] for event in events_next_week):
                        msg = name + ' is scheduled next week. Change status to active.'
                        print(msg)
                        status_updates.append(msg)
            
            if row[1] == 'Active' and row[5] == 'Package' and float(row[3]) <= 1.5:
                msg = {
                    'name': row[0],
                    'hours': row[3],
                    'tutor': row[15]
                }
                low_hours_students.append(msg)
            
            if row[1] in ['Active', 'Prospective'] and row[0] not in student_names_db:
                add_students_to_db.append(row[0])
        

        ### mark test dates as past
        for d in test_dates:
            if d.status != 'past' and d.date <= today:
                d.status = 'past'
                db.session.merge(d)
                db.session.commit()
                msg = 'Test date ' + str(d.date) + ' marked as past'
                print(msg)
                messages.append(msg)


        ### send registration and test reminder emails
        # for u in test_reminder_users:
        #     for d in u.get_dates():
        #         if d.reg_date == today + datetime.timedelta(days=5) and u.not_registered(d):
        #             msg = send_registration_reminder_email(u, d)
        #             print(msg)
        #             messages.append(msg)
        #         elif d.late_date == today + datetime.timedelta(days=5) and u.not_registered(d):
        #             msg = send_late_registration_reminder_email(u, d)
        #             print(msg)
        #             messages.append(msg)
        #         elif d.date == today + datetime.timedelta(days=6) and u.is_registered(d):
        #             msg = send_test_reminder_email(u, d)
        #             print(msg)
        #             messages.append(msg)


        ### send weekly reports
        if day_of_week == 'Wednesday':
            session_count = 0
            tutoring_hours = 0
            outsourced_hours = 0
            outsourced_session_count = 0

            # Get number of active students, number of sessions, and list of unscheduled students
            for student in upcoming_students:
                name = full_name(student)
                for x in events_by_week:
                    if name in x['name']:
                        tutoring_events.append(x)
                        if student.tutor_id == 1:
                            my_tutoring_events.append(x)

                if any(name in e['name'] for e in events_next_week):
                    for x in events_next_week:
                        count = 0
                        hours = 0
                        if name in x['name']:
                            count += 1
                            hours += x['hours']
                            if student.tutor_id == 1:
                                scheduled_students.add(name)
                                session_count += count
                                tutoring_hours += hours
                            else:
                                outsourced_scheduled_students.add(name)
                                outsourced_session_count += count
                                outsourced_hours += hours
                elif any(name in e['name'] for e in tutoring_events):
                    future_schedule.add(name)
                elif student.tutor_id == 1:
                    unscheduled_list.append(name)
                else:
                    outsourced_unscheduled_list.append({
                        'name': name,
                        'tutor_id': student.tutor_id
                    })

            for student in paused_students:
                name = full_name(student)
                paused_list.append(name)
            
            for tutor in tutors:
                if any(s['tutor_id'] == tutor.id for s in outsourced_unscheduled_list):
                    send_tutor_email(tutor, outsourced_unscheduled_list, low_hours_students)

        ### Generate admin report
            weekly_data = {
                'dates': [0,0,0,0,0,0,0,0,0,0],
                'sessions': [0,0,0,0,0,0,0,0,0,0],
                'day_hours': [0,0,0,0,0,0,0,0,0,0],
                'evening_hours': [0,0,0,0,0,0,0,0,0,0],
                'projected_hours': [0,0,0,0,0,0,0,0,0,0]
            }

            next_sunday = today + datetime.timedelta((6 - today.weekday()) % 7)

            for i in range(10):
                s = next_sunday + datetime.timedelta(days=(i * 7))
                s_str = s.strftime('%b %-d')
                weekly_data['dates'][i] = s_str

            for e in my_tutoring_events:
                weekly_data[e['time_group']][e['week_num']] += e['hours']
                weekly_data['sessions'][e['week_num']] += 1        

            # Spreadsheet data
            if not summary_data:
                msg = 'No summary data found.'
                print(msg)
                messages.append(msg)
                return

            send_admin_report_email(str(session_count), '{:0.2f}'.format(tutoring_hours), str(len(scheduled_students)), \
                future_schedule, unscheduled_list, str(outsourced_session_count), \
                str(outsourced_hours), str(len(outsourced_scheduled_students)), \
                outsourced_unscheduled_list, paused_list, weekly_data, now)
        
        message, author, header = get_quote()
        msg = '\n' + message + " - " + author
        print(msg)
        messages.append(msg)
        print('Script succeeded')
        send_script_status_email('reminders.py', messages, status_updates, tutors, low_hours_students, add_students_to_db, 'succeeded')

    except Exception:
        print('Script failed:', traceback.format_exc() )
        send_script_status_email('reminders.py', messages, status_updates, tutors, low_hours_students, add_students_to_db, 'failed', traceback.format_exc())
    

def get_student_events(full_name):
    student_events = []
    bimonth_events, summary_data = get_events_and_data()

    for event in bimonth_events:
        if full_name in event.get('summary'):
            student_events.append(event)
    
    return student_events


if __name__ == '__main__':
    main()