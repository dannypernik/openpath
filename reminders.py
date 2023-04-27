from __future__ import print_function
import datetime
from dateutil.parser import parse, isoparse
from dateutil import tz
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from app import app, db
from dotenv import load_dotenv
from app.models import User, TestDate, UserTestDate
from app.email import send_reminder_email, send_weekly_report_email, \
    send_registration_reminder_email, send_late_registration_reminder_email, \
    send_spreadsheet_report_email, send_test_reminders_email
import requests
from sqlalchemy.orm import joinedload


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly']

# ID and ranges of a sample spreadsheet.
SPREADSHEET_ID = app.config['SPREADSHEET_ID']
SUMMARY_RANGE = 'Student summary!A1:Q'

def main():
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

    # Call the Sheets API
    service_sheets = build('sheets', 'v4', credentials=creds)
    sheet = service_sheets.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                range=SUMMARY_RANGE).execute()
    summary_data = result.get('values', [])

    now  = datetime.datetime.strptime(datetime.datetime.utcnow().isoformat(), "%Y-%m-%dT%H:%M:%S.%f")
    today = datetime.date.today()
    day_of_week = datetime.datetime.strftime(now, format="%A")
    upcoming_start = (now + datetime.timedelta(hours=39)).isoformat() + 'Z'
    upcoming_end = (now + datetime.timedelta(hours=63)).isoformat() + 'Z'
    week_end = (now + datetime.timedelta(days=7, hours=31)).isoformat() + 'Z'
    bimonth_end = (now + datetime.timedelta(days=60, hours=31)).isoformat() + 'Z'
    calendars = ['primary', "n6dbnktn1mha2t4st36h6ljocg@group.calendar.google.com"]

    upcoming_events = []
    week_events = []
    week_events_list = []
    bimonth_events = []
    bimonth_events_list = []
    unscheduled_list = []
    outsourced_unscheduled_list = []
    paused_list = []
    scheduled_students = set()
    future_schedule = set()
    outsourced_scheduled_students = set()
    low_active_students = []

    tutoring_hours = 0
    session_count = 0
    outsourced_hours = 0
    outsourced_session_count = 0

    reminder_list = []
    students = User.query.order_by(User.first_name).filter(User.role == 'student')
    test_reminder_users = User.query.order_by(User.first_name).filter(
        User.test_dates).filter(User.test_reminders).options(joinedload('parent'), joinedload('tutor'))
    active_students = students.filter(User.status == 'active')
    upcoming_students = students.filter((User.status == 'active') | (User.status == 'prospective'))
    paused_students = students.filter(User.status == 'paused')
    status_fixes = []

    # Use fallback quote if request fails
    quote = None
    quote = requests.get("https://zenquotes.io/api/today")

    def full_name(user):
        if user.last_name == "" or user.last_name is None:
            name = user.first_name
        else:
            name = user.first_name + " " + user.last_name
        return name

### Test date reminders
    test_dates = TestDate.query.all()

    # mark test dates as past
    for d in test_dates:
        if d.date == today:
            d.status = 'past'
            db.session.add(d)
            db.session.commit()
            print('Test date', d.date, 'marked as past')

    for u in test_reminder_users:
        for d in u.get_dates():
            if d.reg_date == today + datetime.timedelta(days=5):
                email = send_registration_reminder_email(u, d)
            elif d.late_date == today + datetime.timedelta(days=5):
                send_late_registration_reminder_email(u, d)
            elif d.date == today + datetime.timedelta(days=6):
                send_test_reminders_email(u, d)

    for id in calendars:
        bimonth_cal_events = service_cal.events().list(calendarId=id, timeMin=upcoming_start,
            timeMax=bimonth_end, singleEvents=True, orderBy='startTime').execute()
        bimonth_events_result = bimonth_cal_events.get('items', [])

        for e in range(len(bimonth_events_result)):
            if bimonth_events_result[e]['start'].get('dateTime'):
                bimonth_events.append(bimonth_events_result[e])

    for e in range(len(bimonth_events)):
        event_start = bimonth_events[e]['start'].get('dateTime')
        if event_start < week_end:
            week_events.append(bimonth_events[e])
            if event_start < upcoming_end:
                upcoming_events.append(bimonth_events[e])

    upcoming_start_formatted = datetime.datetime.strftime(parse(upcoming_start), format="%A, %b %-d")
    print("\nSession reminders for " + upcoming_start_formatted + ":")

### Send reminder email to students ~2 days in advance
    for event in upcoming_events:
        for student in upcoming_students:
            name = full_name(student)
            if name in event.get('summary'):
                reminder_list.append(name)
                send_reminder_email(event, student, quote)

    # get list of event names for the bimonth
    for e in bimonth_events:
        bimonth_events_list.append(e.get('summary'))

    # get list of event names and durations for the week
    for e in week_events:
        if e['start'].get('dateTime'):
            start = isoparse(e['start'].get('dateTime'))
            end = isoparse(e['end'].get('dateTime'))
            duration = str(end - start)
            (h, m, s) = duration.split(':')
            hours = int(h) + int(m) / 60 + int(s) / 3600
            event_details = [e.get('summary'), hours]
            week_events_list.append(event_details)

    # check for students who should be listed as active
    for student in students:
        name = full_name(student)

        if student.status not in ['active', 'prospective'] and any(name in nest[0] for nest in week_events_list):
            print(name + ' is listed as ' + student.status + ' and is on the schedule.')

    if len(reminder_list) == 0:
        print("No reminders sent.\n")

### send weekly reports
    if day_of_week == "Friday":
        print('\n')
        # Get number of active students, number of sessions, and list of unscheduled students
        for student in active_students:
            name = full_name(student)
            if any(name in nest[0] for nest in week_events_list):
                print(name + " scheduled with " + student.tutor.first_name)
                for x in week_events_list:
                    count = 0
                    hours = 0
                    if name in x[0]:
                        count += 1
                        hours += x[1]
                        if student.tutor_id == 1:
                            scheduled_students.add(name)
                            session_count += count
                            tutoring_hours += hours
                        else:
                            outsourced_scheduled_students.add(name)
                            outsourced_session_count += count
                            outsourced_hours += hours
            elif any(name in nest for nest in bimonth_events_list):
                future_schedule.add(name)
            elif student.tutor_id == 1:
                unscheduled_list.append(name)
            else:
                outsourced_unscheduled_list.append(name)

        for student in paused_students:
            name = full_name(student)
            paused_list.append(name)

        send_weekly_report_email(str(session_count), str(tutoring_hours), str(len(scheduled_students)), \
            future_schedule, unscheduled_list, str(outsourced_session_count), \
            str(outsourced_hours), str(len(outsourced_scheduled_students)), \
            outsourced_unscheduled_list, paused_list, now, quote)

### Generate spreadsheet report
        if not summary_data:
            print('No summary data found.')
            return

        # Get list of students with low hours
        for row in summary_data:
            for s in students:
                if row[0] == full_name(s):
                    if row[1] != s.status.title():
                        status_fixes.append([full_name(s), s.status.title(), row[1]])
            if row[1] == 'Active' and float(row[2]) <= 1.5:
                low_active_students.append([row[0], row[2]])
        
        spreadsheet_data = {'low_active_students': low_active_students}

        send_spreadsheet_report_email(now, spreadsheet_data, status_fixes)
    
    print("\n\n" + quote.json()[0]['q'] + " - " + quote.json()[0]['a'])

### Import Todoist tasks into OnePageCRM
    # todos = requests.get("https://api.todoist.com/rest/v2/tasks", auth='ea82e086fc651c139bda5aa412313e6e8da03b46')

    # current_actions = []
    # new_actions = []
    # position = 0
    # crm_response = {"success": 0, "failure": 0}

    # crm = requests.get("https://app.onepagecrm.com/api/v3/actions?contact_id=6447f2ce7241d14610745821&per_page=100", auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
    # todoist = TodoistAPI("ea82e086fc651c139bda5aa412313e6e8da03b46")

    # for item in crm.json()['data']['actions']:
    #     current_actions.append(item['action']['text'])

    # try:
    #     tasks = todoist.get_tasks(filter='!no date')
    # except Exception as error:
    #     print(error)

    # tasks_sorted = sorted(tasks, key=lambda x: x.due.date)

    # for task in tasks_sorted:
    #     if task.content not in current_actions:
    #         new_action = {
    #         "contact_id": "6447f2ce7241d14610745821",
    #         "assignee_id": app.config['ONEPAGECRM_ID'],
    #         "status": "date",
    #         "text": task.content,
    #         "date": task.due.date,
    #         #"exact_time": round(parse(task.due.date).timestamp()),
    #         "position": position
    #         }
    #         crm_post = requests.post("https://app.onepagecrm.com/api/v3/actions", json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
    #         print(task.content, crm_post)
    #         if crm_post == 201:
    #             crm_response['success'] += 1
    #         else:
    #             crm_response['failure'] += 1
    #     position += 1

    # if (crm_response['success'] + crm_response['failure']) > 0:
    #     print('New tasks found:', crm_response['success'], 'successfully created', \
    #         crm_response['failure'], 'failed.', )


if __name__ == '__main__':
    main()
