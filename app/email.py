from threading import Thread
from flask import render_template, url_for, current_app
from app.helpers import full_name
from app.utils import generate_vcard
from mailjet_rest import Client
import re
import datetime
from zoneinfo import ZoneInfo
from dateutil.parser import parse
import requests
import json
import logging


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
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
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

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        logging.info('Contact email sent from ' + user.email)
    else:
        logging.info('Contact email from ' + user.email + ' failed with code ' + result.status_code)
    return result.status_code


def send_confirmation_email(user_email, message):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': user_email
                    }
                ],
                'Subject': 'Email confirmation + a quote from Brene Brown',
                'TextPart': render_template('email/confirmation-email.txt', message=message),
                'HTMLPart': render_template('email/confirmation-email.html', message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Confirmation email sent to ' + user_email)
    else:
        logging.info('Confirmation email to ' + user_email + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_unsubscribe_email(email):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'Unsubscribe request from ' + email,
                'HTMLPart': render_template('email/unsubscribe-email.html', email=email)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Confirmation email sent to ' + email)
    else:
        logging.info('Confirmation email to ' + email + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_reminder_email(event, student, tutor):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    cc_email = []
    reply_email = []
    if student.parent:
        parent = student.parent
        if parent.email and parent.session_reminders:
            cc_email.append({ 'Email': parent.email })
            if parent.secondary_email:
                cc_email.append({ 'Email': parent.secondary_email })

    if tutor:
        reply_email = tutor.email
        if tutor.session_reminders:
            cc_email.append({ 'Email': tutor.email })
    if not reply_email:
        reply_email = current_app.config['MAIL_USERNAME']

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

    location = event['event'].get('location').strip()
    warnings = []
    warnings_str = ''

    if location != student.location:
        warnings.append('Event location != DB location')
        warnings.append('Event location missing')
    if not location:
        location = tutor.location
    if warnings.__len__() > 0:
        warnings_str = '(' + (', ').join(warnings) + ')'

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
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
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
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
            reply_email = current_app.config['MAIL_USERNAME']

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
                    'Email': current_app.config['MAIL_USERNAME'],
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
        logging.info(student.first_name, student.last_name, start_display, timezone, warnings_str)
    else:
        logging.info('Error for ' + student.first_name + '\'s session update email with code', result.status_code, result.reason)
    return result.status_code


def send_notification_email(alerts):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
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
        logging.info('Notification email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Notification email to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_registration_reminder_email(user, test_date):
    with current_app.app_context():
        api_key = current_app.config['MAILJET_KEY']
        api_secret = current_app.config['MAILJET_SECRET']
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
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': current_app.config['MAIL_USERNAME'] },
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
    with current_app.app_context():
        api_key = current_app.config['MAILJET_KEY']
        api_secret = current_app.config['MAILJET_SECRET']
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
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': current_app.config['MAIL_USERNAME'] },
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
    with current_app.app_context():
        api_key = current_app.config['MAILJET_KEY']
        api_secret = current_app.config['MAILJET_SECRET']
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
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        { 'Email': user.email }
                    ],
                    'Cc': cc_email,
                    'ReplyTo': { 'Email': current_app.config['MAIL_USERNAME'] },
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
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    date_series = ', '.join(dates)

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
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

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        logging.info('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': current_app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))
        logging.info('crm_action:', crm_action)

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        logging.info('Signup notification email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Signup notification email to ' + current_app.config['MAIL_USERNAME'] + ' failed with code ' + result.status_code)
    return result.status_code


def send_signup_request_email(user, next):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': user.first_name + ' requested an account',
                'HTMLPart': render_template('email/signup-request-email.html',
                    user=user, next=next)
            }
        ]
    }

    new_contact = {
        'first_name': user.first_name, 'last_name': user.last_name, \
        'emails': [{ 'type': 'home', 'value': user.email}], \
        'phones': [{ 'type': 'mobile', 'value': user.phone}], \
        'tags': ['Website', next]
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        logging.info('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': current_app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))
        logging.info('crm_action:', crm_action)

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        logging.info('Signup notification email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Signup notification email to ' + current_app.config['MAIL_USERNAME'] + ' failed with code ' + result.status_code)
    return result.status_code


def send_verification_email(user, page=None):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    token = user.get_email_verification_token()

    purpose = ''
    if page == 'test_reminders':
        purpose = ' to get test reminders'

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
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
        logging.info('Verification email sent to ' + user.email)
    else:
        logging.info('Verification email to ' + user.email + ' failed with code ' + result.status_code)
    return result.status_code


def send_password_reset_email(user, next=None):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    token = user.get_email_verification_token()
    if user.password_hash == None:
        pw_type = 'set'
    else:
        pw_type = 'reset'

    purpose = ''
    if next == 'test_reminders':
        purpose = ' to get test reminders'

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': user.email
                    }
                ],
                'Subject': pw_type.title() + ' your password' + purpose,
                'TextPart': render_template('email/reset-password-email.txt', \
                                         user=user, token=token, pw_type=pw_type, next=next),
                'HTMLPart': render_template('email/reset-password-email.html', \
                                         user=user, token=token, pw_type=pw_type, next=next)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Password reset email sent to ' + user.email)
    else:
        logging.info('Password reset email to ' + user.email + ' failed to send with code ' + str(result.status_code), result.reason)
    return result.status_code


def send_test_strategies_email(student, parent, relation):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
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
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': to_email,
                'Bcc': [{'Email': current_app.config['MAIL_USERNAME']}],
                'Subject': '10 Strategies to Master the SAT & ACT',
                'HTMLPart': render_template('email/test-strategies.html', relation=relation, student=student, parent=parent, link=link),
                'TextPart': render_template('email/test-strategies.txt', relation=relation, student=student, parent=parent, link=link)
            }
        ]
    }

    new_contact = {
        'first_name': parent.first_name, 'last_name': 'OPT test strategies form', \
        'emails': [{ 'type': 'home', 'value': parent.email}], \
        'phones': [{ 'type': 'mobile', 'value': parent.phone}], \
        'tags': ['Website']
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        logging.info('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': current_app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))
        logging.info('crm_action:', crm_action)

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info(result.json())
    else:
        logging.info('Top 10 email failed to send with code ' + str(result.status_code), result.reason)
    return result.status_code


def send_test_registration_email(student, parent, school, test, date, time, location, contact_info):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'Bcc': [{'Email': current_app.config['MAIL_USERNAME']}],
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
        logging.info(result.json())
    else:
        logging.info('Test registration email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_prep_class_email(student, parent, school, test, time, location, cost):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'Bcc': [{'Email': current_app.config['MAIL_USERNAME']}],
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
        logging.info(result.json())
    else:
        logging.info('Prep class email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_score_analysis_email(student, parent, school):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': parent.email
                    }
                ],
                'ReplyTo': { 'Email': parent.email },
                'Bcc': [{'Email': current_app.config['MAIL_USERNAME']}],
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

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        logging.info('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': current_app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to OPT web form',
            #'date': ,
            #'exact_time': 1526472000,
            #'position': 1
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))
        logging.info('crm_action:', crm_action)

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info(result.json())
    else:
        logging.info('Score analysis confirmation email failed to send with code', result.status_code, result.reason)
    return result.status_code


def send_tutor_email(tutor, low_scheduled_students, unscheduled_students, other_scheduled_students,
    paused_students, unregistered_students, undecided_students):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
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

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['ADMIN_EMAIL'],
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

    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
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

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': current_app.config['MAIL_USERNAME']
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
        logging.info('\nWeekly report email sent.')
    else:
        logging.info('\nWeekly report email error:', str(result.status_code), result.reason, '\n')
    return result.status_code


def send_script_status_email(name, messages, status_updates, low_scheduled_students, unscheduled_students,
    other_scheduled_students, tutors_attention, add_students_to_data, cc_sessions, unregistered_students,
    undecided_students, payments_due, result, exception=''):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
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

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': current_app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': name + ' ' + result,
                    'HTMLPart': render_template('email/script-status-email.html',
                        messages=messages, status_updates=status_updates,
                        low_scheduled_students=low_scheduled_students, unscheduled_students=unscheduled_students,
                        tutors_attention=tutors_attention, add_students_to_data=add_students_to_data,
                        cc_sessions=cc_sessions, unregistered_str=unregistered_str, undecided_str=undecided_str,
                        payments_due=payments_due, exception=exception, quote=quote, author=author)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('\nScript status email sent.')
    else:
        logging.info('Script status email error:', str(result.status_code), result.reason, '\n')
    return result.status_code


def send_new_student_email(contact_data):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    student = contact_data['student']
    parent = contact_data['parent']
    parent2 = contact_data.get('parent2', None)
    interested_tests = contact_data.get('interested_tests', [])
    notes = contact_data.get('notes', '')
    folder_id = contact_data.get('folder_id', None)

    contacts = [student, parent]
    if parent2:
        contacts.append(parent2)

    vcards_base64 = generate_vcard(contacts)

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                        'Email': current_app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'New student added: ' + full_name(student),
                'HTMLPart': render_template('email/new-student-email.html',
                    student=student, parent=parent, parent2=parent2, interested_tests=interested_tests,
                    full_name=full_name, notes=notes, folder_id=folder_id),
                'Attachments': [
                    {
                        'ContentType': 'text/vcard',
                        'Filename': f"{full_name(student)}.vcf",
                        'Base64Content': vcards_base64
                    }
                ]
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('New student email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('New student email to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code

def send_schedule_conflict_email(message):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
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
        logging.info('Schedule conflict email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Schedule conflict email to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_ntpa_email(first_name, last_name, biz_name, email):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
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
        logging.info('NTPA email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('NTPA email to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_free_resources_email(user):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    resource_folder_url = 'https://drive.google.com/drive/folders/' + current_app.config['RESOURCE_FOLDER_ID']

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                        'Email': user.email
                    },
                    {
                        'Email': current_app.config['MAIL_USERNAME']
                    }
                ],
                'ReplyTo': { 'Email': user.email },
                'Subject': 'Free resources for SAT & ACT prep',
                'HTMLPart': render_template('email/free-resources-email.html', user=user, resource_folder_url=resource_folder_url),
                'TextPart': render_template('email/free-resources-email.txt', user=user, resource_folder_url=resource_folder_url)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Free resources email sent to ' + user.email)
    else:
        logging.info('Free resources email to ' + user.email + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_nomination_email(form_data):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                'From': {
                    'Email': current_app.config['MAIL_USERNAME'],
                    'Name': 'Open Path Tutoring'
                },
                'To': [
                    {
                    'Email': current_app.config['MAIL_USERNAME']
                    }
                ],
                'Subject': 'Nomination received for ' + form_data['student_first_name'] + ' ' + form_data['student_last_name'],
                'ReplyTo': { 'Email': form_data['contact_email'] },
                'HTMLPart': render_template('email/nomination-form-email.html', form_data=form_data)
            }
        ]
    }


    new_contact = {
        'first_name': form_data['parent_first_name'] if form_data['parent_first_name'] else form_data['student_first_name'], \
        'last_name': form_data['parent_last_name'] if form_data['parent_last_name'] else form_data['student_last_name'], \
        'emails': [
            {
                'type': 'home',
                'value': form_data['parent_email'] if form_data['parent_email'] else form_data['student_email']
            }
        ], \
        'tags': ['Nominated']
    }

    crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))

    if crm_contact.status_code == 201:
        logging.info('crm_contact passes')
        new_action = {
            'contact_id': crm_contact.json()['data']['contact']['id'],
            'assignee_id': current_app.config['ONEPAGECRM_ID'],
            'status': 'asap',
            'text': 'Respond to nomination form',
        }
        crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(current_app.config['ONEPAGECRM_ID'], current_app.config['ONEPAGECRM_PW']))
        logging.info('crm_action:', crm_action)

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        logging.info('Nomination email sent ')
    else:
        logging.info('Nomination email failed with code ' + result.status_code)
    return result.status_code


def send_score_report_email(score_data, pdf_base64, conf_img_base64=None):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    to_email = []
    cc_email = []
    bcc_email = []
    if score_data['admin_email']:
        bcc_email.append({ 'Email': current_app.config.get('ADMIN_EMAIL') })

        if score_data['email']:
            to_email.append({ 'Email': score_data['email'] })
            cc_email.append({ 'Email': score_data['admin_email'] })
        else:
            to_email.append({ 'Email': score_data['admin_email'] })
    else:
        to_email.append({ 'Email': score_data['email'] })

    attachments = []

    if conf_img_base64:
        attachments.append({
            'ContentType': 'image/jpeg',
            'Filename': f"Verification image for {score_data['student_name']} - {score_data['date']} - {score_data['test_display_name']}.jpg",
            'Base64Content': conf_img_base64
        })

    attachments.append({
        'ContentType': 'application/pdf',
        'Filename': f"Score Analysis for {score_data['student_name']} - {score_data['date']} - {score_data['test_display_name']}.pdf",
        'Base64Content': pdf_base64
    })


    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': to_email,
                    'Cc': cc_email,
                    'Bcc': bcc_email,
                    'Subject': score_data['test_display_name'] + ' Score Analysis for ' + score_data['student_name'],
                    'TextPart': render_template('email/score-report-email.txt', score_data=score_data, int=int),
                    'HTMLPart': render_template('email/score-report-email.html', score_data=score_data, int=int),
                    'Attachments': attachments
                }
            ]
        }

    result = mailjet.send.create(data=data)
    return result.status_code


def send_changed_answers_email(score_data):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': current_app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': 'Changed answers for ' + score_data['test_display_name'],
                    'HTMLPart': render_template('email/changed-answers-email.html', score_data=score_data, int=int)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Changed answer email sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Changed answer email to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_fail_mail(subject, error='unknown error', data=None):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': current_app.config['MAIL_USERNAME']
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
        logging.info('Fail mail sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Fail mail to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code


def send_task_fail_mail(task_data, exc, task_id, args, kwargs, einfo):
    api_key = current_app.config['MAILJET_KEY']
    api_secret = current_app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    with current_app.app_context():
        data = {
            'Messages': [
                {
                    'From': {
                        'Email': current_app.config['MAIL_USERNAME'],
                        'Name': 'Open Path Tutoring'
                    },
                    'To': [
                        {
                            'Email': current_app.config['MAIL_USERNAME']
                        }
                    ],
                    'Subject': 'Error with task ' + task_id,
                    'HTMLPart': render_template('email/task-fail-mail.html', task_data=task_data, \
                        exc=exc, task_id=task_id, args=args, kwargs=kwargs, einfo=einfo)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        logging.info('Task fail mail sent to ' + current_app.config['MAIL_USERNAME'])
    else:
        logging.info('Task fail mail to ' + current_app.config['MAIL_USERNAME'] + ' failed to send with code ' + result.status_code, result.reason)
    return result.status_code