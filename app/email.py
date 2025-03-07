from threading import Thread
from app import app, full_name
from mailjet_rest import Client
from flask import render_template, url_for
import re
import datetime
from zoneinfo import ZoneInfo
from dateutil.parser import parse
import requests
import json


def get_quote():
    try:
        quote = requests.get('https://zenquotes.io/api/today')
        message = quote.json()[0]['q']
        author = quote.json()[0]['a']
        header = 'Random inspirational quote of the day'
    except requests.exceptions.RequestException:
        message = 'We don\'t have to do all of it alone. We were never meant to.'
        author = 'Brene Brown'
        header = ''
    return message, author, header

message, author, quote_header = get_quote()


def send_contact_email(user, message, subject):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'Open Path Tutoring: ' + subject + ' from ' + user.first_name,
                'ReplyTo': { 'Email': user.email },
                'TextPart': render_template('email/inquiry-form.txt',
                                         user=user, message=message),
                'HTMLPart': render_template('email/inquiry-form.html',
                                         user=user, message=message)
            }
        ]
    }

    new_contact = {
        'first_name': user.first_name, 'last_name': 'OPT contact form', \
        'emails': [{ 'type': 'home', 'value': user.email}], \
        'phones': [{ 'type': 'mobile', 'value': user.phone}], \
        'tags': ['Website']
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        print('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        print('crm_action:', crm_action)

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print('Contact email sent from ' + user.email)
    else:
        print('Contact email from ' + user.email + ' failed with code ' + result.status_code)
    return result.status_code


def send_confirmation_email(user, message):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': user.email
                    }
                ],
                'Subject': 'Email confirmation + a quote from Brene Brown',
                'TextPart': render_template('email/confirmation.txt',
                                         user=user, message=message),
                'HTMLPart': render_template('email/confirmation.html',
                                         user=user, message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Confirmation email sent to ' + user.email)
    else:
        print('Confirmation email to ' + user.email + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_reminder_email(event, student, tutor):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    cc_email = []
    reply_email = []
    if student.parent:
        parent = student.parent
        if parent.session_reminders:
            cc_email.append({ 'Email': parent.email })
            if parent.secondary_email:
                cc_email.append({ 'Email': parent.secondary_email })

    if tutor:
        reply_email = tutor.email
        if tutor.session_reminders:
            cc_email.append({ 'Email': tutor.email })
    if not reply_email:
        reply_email = app.config['MAIL_USERNAME']

    dt = datetime.datetime

    start_time_utc = event['event']['start'].get('dateTime')
    end_time_utc = event['event']['end'].get('dateTime')

    student_tz = ZoneInfo(student.timezone)
    start_obj_tz = parse(start_time_utc).astimezone(student_tz)
    end_obj_tz = parse(end_time_utc).astimezone(student_tz)

    start_date = dt.strftime(start_obj_tz, format='%A, %b %-d')
    start_time = dt.strftime(start_obj_tz, format='%-I:%M%p').lower()
    end_time = dt.strftime(end_obj_tz, format='%-I:%M%p').lower()
    timezone = dt.strftime(end_obj_tz, format=' %Z')

    if 'practice sat' in event['event'].get('summary').lower():
        event_type = 'practice SAT'
    elif 'practice act' in event['event'].get('summary').lower():
        event_type = 'practice ACT'
    elif 'test prep class' in event['event'].get('summary').lower():
        event_type = 'test prep class'
    else:
        event_type = 'session'

    location = event['event'].get('location')
    warnings = []
    warnings_str = ''

    if location != student.location:
        warnings.append('Event location != DB location')
    if location is None:
        location = student.location
        warnings.append('Event location missing')
    if warnings.__len__() > 0:
        warnings_str = '(' + (', ').join(warnings) + ')'

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                        'Email': student.email
                        }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': reply_email },
                    'Subject': 'Reminder for ' + event_type + ' on ' + start_date + ' at ' + start_time + ' ' + timezone,
                    'HTMLPart': render_template('email/reminder-email.html', student=student, \
                        tutor=tutor, start_date=start_date, start_time=start_time, \
                        end_time=end_time, location=location, timezone=timezone, \
                        quote_header=quote_header, message=message, author=author, event_type=event_type),
                    'TextPart': render_template('email/reminder-email.txt', student=student, \
                        tutor=tutor, start_date=start_date, start_time=start_time, \
                        end_time=end_time, location=location, timezone=timezone, \
                        quote_header=quote_header, message=message, author=author, event_type=event_type)
                }
            ]
        }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        msg = full_name(student) + ' ' + start_time + timezone + ' ' + warnings_str
    else:
        msg = 'Error for ' + student.first_name + '\'s reminder email with code ' + str(result.status_code) + ' ' + result.reason
    return msg


def send_session_recap_email(student, events):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    cc_email = []
    if student.parent:
        parent = student.parent
        if parent.session_reminders:
            cc_email.append({ 'Email': parent.email })
            if parent.secondary_email:
                cc_email.append({ 'Email': parent.secondary_email })

    if student.tutor:
        tutor = student.tutor
        if tutor.session_reminders:
            cc_email.append({ 'Email': tutor.email })

        reply_email = tutor.email
        if reply_email == '':
            reply_email = app.config['MAIL_USERNAME']

    tz_difference = student.timezone - tutor.timezone

    dt = datetime.datetime


    session_date = dt.strftime(student.date, format='%A, %b %-d')

    if student.timezone == -2:
        timezone = 'Pacific'
    elif student.timezone == -1:
        timezone = 'Mountain'
    elif student.timezone == 0:
        timezone = 'Central'
    elif student.timezone == 1:
        timezone = 'Eastern'
    else:
        timezone = 'your'

    event_details = []
    alerts = []
    location = None
    for event in events:
        start_time = event['start'].get('dateTime')
        start_date = dt.strftime(parse(start_time), format='%A, %b %-d')
        start_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', start_time)
        start_offset = dt.strptime(start_time_formatted, '%Y-%m-%dT%H:%M:%S%z') + datetime.timedelta(hours = tz_difference)
        end_time = event['end'].get('dateTime')
        end_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', end_time)
        end_offset = dt.strptime(end_time_formatted, '%Y-%m-%dT%H:%M:%S%z') + datetime.timedelta(hours = tz_difference)
        start_display = dt.strftime(start_offset, '%-I:%M%p').lower()
        end_display = dt.strftime(end_offset, '%-I:%M%p').lower()

        event_details.append({
            'date': start_date,
            'start': start_display,
            'end': end_display,
        })

        if location == None:
            location = event.get('location')
        elif location != event.get('location'):
            alerts.append('Location mismatch error for ' + full_name(student) + ' on ' + start_date)

    if alerts.__len__() > 0:
        send_notification_email(alerts)

    warnings = []
    warnings_str = ''

    if location != student.location:
        warnings.append('Event location != DB location')
    if location is None:
        location = student.location
        warnings.append('Event location missing')
    if warnings.__len__() > 0:
        warnings_str = '(' + (', ').join(warnings) + ')'
    if 'http' in location:
        location = '<a href=\'' + location + '\'>' + location + '<a>'

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': student.email
                    }
                ],
                'Cc': cc_email,
                'ReplyTo': { 'Email': reply_email },
                'Subject': 'Session recap for ' + session_date,
                'HTMLPart': render_template('email/recap-email.html', student=student, event_details=event_details),
                'TextPart': render_template('email/recap-email.txt', student=student, event_details=event_details)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print(student.first_name, student.last_name, start_display, timezone, warnings_str)
    else:
        print('Error for ' + student.first_name + '\'s session update email with code', result.status_code, result.reason)
    return result.status_code


def send_notification_email(alerts):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'Open Path Tutoring notification',
                'TextPart': render_template('email/notification-email.txt', alerts=alerts),
                'HTMLPart': render_template('email/notification-email.html', alerts=alerts)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Notification email sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Notification email to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_registration_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent_id:
            if user.parent.test_reminders:
                cc_email.append({ 'Email': user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ 'Email': user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ 'Email': user.tutor.email })

        td = test_date.date.strftime('%B %-d')
        reg_dl = test_date.reg_date.strftime('%A, %B %-d')
        reg_dl_day = test_date.reg_date.strftime('%A')

        if test_date.late_date is not None:
            late_dl = test_date.late_date.strftime('%A, %B %-d')
        else:
            late_dl = None

        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': app.config['MAIL_USERNAME'] },
                    'Subject': 'Registration deadline for the ' + td + ' ' + test_date.test.upper() + ' is this ' + reg_dl_day,
                    'HTMLPart': render_template('email/registration-reminder.html', \
                        user=user, test_date=test_date, td=td, reg_dl=reg_dl, late_dl=late_dl),
                    'TextPart': render_template('email/registration-reminder.txt', \
                        user=user, test_date=test_date, td=td, reg_dl=reg_dl, late_dl=late_dl)
                }
            ]
        }

        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            msg = 'Registration reminder for ' + td + ' ' + test_date.test.upper() + ' sent to ' + full_name(user)
        else:
            msg = 'Error for ' + user.first_name + '\'s registration reminder with code ' + str(result.status_code) + ' ' + result.reason
        return msg


def send_late_registration_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent:
            if user.parent.test_reminders:
                cc_email.append({ 'Email': user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ 'Email': user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ 'Email': user.tutor.email })

        td = test_date.date.strftime('%B %-d')
        late_dl = test_date.late_date.strftime('%A, %B %-d')
        late_dl_day = test_date.late_date.strftime('%A')

        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': app.config['MAIL_USERNAME'] },
                    'Subject': 'Late registration deadline for the ' + td + ' ' + test_date.test.upper() + ' is this ' + late_dl_day,
                    'HTMLPart': render_template('email/late-registration-reminder.html', \
                        user=user, test_date=test_date, td=td, late_dl=late_dl),
                    'TextPart': render_template('email/late-registration-reminder.txt', \
                        user=user, test_date=test_date, td=td, late_dl=late_dl)
                }
            ]
        }

        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            msg = 'Late registration reminder for ' + td + ' ' + test_date.test.upper() + ' sent to ' + full_name(user)
        else:
            msg = 'Error for ' + user.first_name + '\'s late registration reminder with code ' + str(result.status_code) + ' ' + result.reason
        return msg


def send_test_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent:
            if user.parent.test_reminders:
                cc_email.append({ 'Email': user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ 'Email': user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ 'Email': user.tutor.email })

        td = test_date.date.strftime('%B %-d')
        td_day = test_date.date.strftime('%A')

        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': app.config['MAIL_USERNAME'] },
                    'Subject': 'Things to remember for your ' + test_date.test.upper() + ' on ' + td_day + ', ' + td,
                    'HTMLPart': render_template('email/test-reminders.html', \
                        user=user, test_date=test_date, td=td),
                    'TextPart': render_template('email/test-reminders.txt', \
                        user=user, test_date=test_date, td=td)
                }
            ]
        }

        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            msg = td + ' ' + test_date.test.upper() + ' reminder sent to ' + full_name(user)
        else:
            msg = 'Error for ' + user.first_name + '\'s test reminder with code ' + str(result.status_code) + ' ' + result.reason
        return msg


def send_signup_notification_email(user, dates):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    date_series = ', '.join(dates)

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': user.first_name + ' signed up for test reminders',
                'TextPart': render_template('email/signup-notification.txt', user=user,
                    date_series=date_series)
            }
        ]
    }

    new_contact = {
        'first_name': user.first_name, 'last_name': 'OPT test reminders form', \
        'emails': [{ 'type': 'home', 'value': user.email}], \
        'phones': [{ 'type': 'mobile', 'value': user.phone}], \
        'tags': ['Website']
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        print('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        print('crm_action:', crm_action)

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print('Signup notification email sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Signup notification email to ' + app.config['MAIL_USERNAME'] + ' failed with code ' + result.status_code)
    return result.status_code


def send_verification_email(user, page=None):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    token = user.get_email_verification_token()

    purpose = ''
    if page == 'test_reminders':
        purpose = ' to get test reminders'

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': user.email
                    }
                ],
                'Subject': 'Please verify your email address' + purpose,
                'TextPart': render_template('email/verification-email.txt',
                                         user=user, token=token),
                'HTMLPart': render_template('email/verification-email.html',
                                         user=user, token=token)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print('Verification email sent to ' + user.email)
    else:
        print('Verification email to ' + user.email + ' failed with code ' + result.status_code)
    return result.status_code


def send_password_reset_email(user, page=None):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    token = user.get_email_verification_token()
    if user.password_hash == None:
        pw_type = 'set'
    else:
        pw_type = 'reset'

    purpose = ''
    if page == 'test_reminders':
        purpose = ' to get test reminders'

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': user.email
                    }
                ],
                'Subject': pw_type.title() + ' your password' + purpose,
                'TextPart': render_template('email/reset-password.txt', \
                                         user=user, token=token, pw_type=pw_type),
                'HTMLPart': render_template('email/reset-password.html', \
                                         user=user, token=token, pw_type=pw_type)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Password reset email sent to ' + user.email)
    else:
        print('Password reset email to ' + user.email + ' failed to send with code ' + str(result.status_code), result.reason)
    return result.status_code


def send_test_strategies_email(student, parent, relation):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    filename = 'SAT-ACT-strategies.pdf'

    to_email = []
    if relation == 'student':
        to_email.append({ 'Email': student.email })
    to_email.append({ 'Email': parent.email })

    link = 'https://www.openpathtutoring.com/download/' + filename

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': to_email,
                'Bcc': [{'Email': app.config['MAIL_USERNAME']}],
                'Subject': '10 Strategies to Master the SAT & ACT',
                'HTMLPart': render_template('email/test-strategies.html', relation=relation, student=student, parent=parent, link=link),
                'TextPart': render_template('email/test-strategies.txt', relation=relation, student=student, parent=parent, link=link)
            }
        ]
    }

    new_contact = {
        'first_name': user.first_name, 'last_name': 'OPT test strategies form', \
        'emails': [{ 'type': 'home', 'value': user.email}], \
        'phones': [{ 'type': 'mobile', 'value': user.phone}], \
        'tags': ['Website']
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        print('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        print('crm_action:', crm_action)

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print('Top 10 email failed to send with code ' + str(result.status_code), result.reason)
    return result.status_code


def send_test_registration_email(student, parent, school, test, date, time, location, contact_info):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'Bcc': [{'Email': app.config['MAIL_USERNAME']}],
                'Subject': full_name(student) + ' is registered for the practice ACT on ' + date,
                'TextPart': render_template('email/test-registration-email.txt',
                            student=student, parent=parent, school=school, test=test, \
                            date=date, time=time, location=location, contact_info=contact_info),
                'HTMLPart': render_template('email/test-registration-email.html',
                            student=student, parent=parent, school=school, test=test, \
                            date=date, time=time, location=location, contact_info=contact_info)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print('Test registration email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_prep_class_email(student, parent, school, test, time, location, cost):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'Bcc': [{'Email': app.config['MAIL_USERNAME']}],
                'Subject': full_name(student) + ' is registered for ' + test + ' Study Club',
                'TextPart': render_template('email/prep-class-email.txt',
                            student=student, parent=parent, school=school, test=test, \
                            time=time, location=location),
                'HTMLPart': render_template('email/prep-class-email.html',
                            student=student, parent=parent, school=school, test=test, \
                            time=time, location=location, cost=cost)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print('Prep class email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_score_analysis_email(student, parent, school):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'ReplyTo': { 'Email': parent.email },
                'Bcc': [{'Email': app.config['MAIL_USERNAME']}],
                'Subject': 'Score analysis request received',
                'TextPart': render_template('email/score-analysis-email.txt',
                                         student=student, parent=parent, school=school),
                'HTMLPart': render_template('email/score-analysis-email.html',
                                         student=student, parent=parent, school=school)
            }
        ]
    }

    new_contact = {
        'first_name': parent.first_name, 'last_name': 'OPT score analysis form',
        'emails': [{ 'type': 'home', 'value': parent.email}],
        'lead_source_id': 'advertisement',
        'lead_source': 'Practice test'
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        print('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        print('crm_action:', crm_action)

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print('Score analysis confirmation email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_tutor_email(tutor, low_scheduled_students, unscheduled_students, other_scheduled_students,
    paused_students, unregistered_students, undecided_students):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    my_low_students = []
    action_str = None
    for s in low_scheduled_students:
        if full_name(tutor) in s['tutors']:
            my_low_students.append(s)

    my_unscheduled_students = []
    for s in unscheduled_students:
        if full_name(tutor) in s['tutors']:
            my_unscheduled_students.append(s)

    my_scheduled_students = []
    for s in other_scheduled_students:
        if full_name(tutor) in s['tutors']:
            my_scheduled_students.append(s)

    my_paused_students = []
    for s in paused_students:
        if tutor.id == s.tutor_id:
            my_paused_students.append(full_name(s))

    paused_student_list = ', '.join(my_paused_students)

    if len(my_low_students) > 0:
        action_str = ' - One or more scheduled students need hours'
    elif len(unscheduled_students) > 0:
        action_str = ' - One or more active students not scheduled'
    elif len(my_paused_students) > 0:
        action_str = ' - Action requested'
    else:
        action_str = ''

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['ADMIN_EMAIL'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                        'Email': tutor.email
                        }
                    ],
                    'Subject': 'OPT weekly report' + action_str,
                    'HTMLPart': render_template('email/tutor-email.html', tutor=tutor,
                        my_low_students=my_low_students, my_scheduled_students=my_scheduled_students,
                        my_unscheduled_students=my_unscheduled_students, paused_student_list=paused_student_list,
                        full_name=full_name)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        msg = 'Tutor email sent to ' + full_name(tutor)
    else:
        msg = 'Tutor email to ' + full_name(tutor) + ' failed to send with code ' + result.status_code + ' ' + result.reason
    return msg


def send_weekly_report_email(messages, status_updates, my_session_count, my_tutoring_hours,
    other_session_count, other_tutoring_hours, low_scheduled_students, unscheduled_students,
    paused_students, tutors_attention, weekly_data, add_students_to_data, cc_sessions,
    unregistered_students, undecided_students, now):

    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    dt = datetime.datetime
    start = (now + datetime.timedelta(hours=40)).isoformat() + 'Z'
    start_date = dt.strftime(parse(start), format='%b %-d')
    end = (now + datetime.timedelta(days=6, hours=40)).isoformat() + 'Z'
    end_date = dt.strftime(parse(end), format='%b %-d')

    paused = []
    for s in paused_students:
        paused.append(full_name(s))
    paused_str = (', ').join(paused)

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': app.config['MAIL_USERNAME']
                        },
                    ],
                    'Subject': 'reminders.py succeeded - Admin tutoring report',
                    'HTMLPart': render_template('email/weekly-report-email.html',
                        messages=messages, status_updates=status_updates, my_tutoring_hours=my_tutoring_hours,
                        my_session_count=my_session_count, other_tutoring_hours=other_tutoring_hours,
                        other_session_count=other_session_count, unscheduled_students=unscheduled_students,
                        paused_str=paused_str, tutors_attention=tutors_attention, cc_sessions=cc_sessions,
                        message=message, author=author, weekly_data=weekly_data,
                        add_students_to_data=add_students_to_data, full_name=full_name)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('\nWeekly report email sent.')
    else:
        print('\nWeekly report email error:', str(result.status_code), result.reason, '\n')
    return result.status_code


def send_script_status_email(name, messages, status_updates, low_scheduled_students, unscheduled_students,
    other_scheduled_students, tutors_attention, add_students_to_data, cc_sessions, unregistered_students,
    undecided_students, result, exception=''):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    quote, author, header = get_quote()

    unregistered = []
    for s in unregistered_students:
        unregistered.append(full_name(s))
    unregistered_str = (', ').join(unregistered)

    undecided = []
    for s in undecided_students:
        undecided.append(full_name(s))
    undecided_str = (', ').join(undecided)

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': name + ' ' + result,
                    'HTMLPart': render_template('email/script-status-email.html',
                        messages=messages, status_updates=status_updates,
                        low_scheduled_students=low_scheduled_students, unscheduled_students=unscheduled_students,
                        tutors_attention=tutors_attention, add_students_to_data=add_students_to_data,
                        cc_sessions=cc_sessions, unregistered_str=unregistered_str, undecided_str=undecided_str,
                        exception=exception, quote=quote, author=author)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('\nScript status email sent.')
    else:
        print('Script status email error:', str(result.status_code), result.reason, '\n')
    return result.status_code



def send_schedule_conflict_email(message):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'Schedule conflict email',
                'TextPart': render_template('email/schedule-conflict.txt',
                                        message=message),
                'HTMLPart': render_template('email/schedule-conflict.html',
                                        message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Schedule conflict email sent to ' + user.email)
    else:
        print('Schedule conflict email to ' + user.email + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_ntpa_email(first_name, last_name, biz_name, email):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': app.config['MAIL_USERNAME']
                    }
                ],
                'ReplyTo': { 'Email': email },
                'Subject': 'Test analysis folder requested',
                'HTMLPart': render_template('email/ntpa-email.html', first_name=first_name, \
                    last_name=last_name, biz_name=biz_name, email=email)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('NTPA email sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('NTPA email to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_report_submitted_email(score_data):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': app.config['MAIL_USERNAME']
                        }
                    ],
                    'ReplyTo': { 'Email': score_data['email'] },
                    'Subject': 'Score report submitted for ' + score_data['student_name'],
                    'TextPart': render_template('email/report-submitted-email.txt', score_data=score_data),
                    'HTMLPart': render_template('email/report-submitted-email.html', score_data=score_data),
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Report submitted email sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Report submitted email to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_score_report_email(score_data, base64_blob):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': score_data['email']
                        }
                    ],
                    'Subject': score_data['test_display_name'] + ' Score Analysis for ' + score_data['student_name'],
                    'TextPart': render_template('email/score-report-email.txt', score_data=score_data),
                    'HTMLPart': render_template('email/score-report-email.html', score_data=score_data),
                    'Attachments': [
                        {
                            'ContentType': 'application/pdf',
                            'Filename': f"Score Analysis for {score_data['student_name']} - {score_data['date']} - {score_data['test_display_name']}.pdf",
                            'Base64Content': base64_blob
                        }
                    ]
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Score report email sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Score report email to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_fail_mail(subject, error='unknown error', data=None):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': 'Error: ' + subject,
                    'TextPart': render_template('email/fail-mail.txt', data=data, error=error),
                    'HTMLPart': render_template('email/fail-mail.html', data=data, error=error)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Fail mail sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Fail mail to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_task_fail_mail(exc, task_id, args, kwargs, einfo):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': 'Error with task ' + task_id,
                    'HTMLPart': render_template('email/task-fail-mail.html', exc=exc, \
                        task_id=task_id, args=args, kwargs=kwargs, einfo=einfo)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print('Task fail mail sent to ' + app.config['MAIL_USERNAME'])
    else:
        print('Task fail mail to ' + app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code