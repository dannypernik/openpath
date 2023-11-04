from threading import Thread
from app import app
from mailjet_rest import Client
from flask import render_template, url_for
import re
import datetime
from dateutil.parser import parse
import requests


def get_quote():
    try:
        quote = requests.get("https://zenquotes.io/api/today")

        message = quote.json()[0]['q']
        author = quote.json()[0]['a']
        quote_header = "Random inspirational quote of the day:"
    except requests.exceptions.RequestException:
        message = "We don't have to do all of it alone. We were never meant to."
        author = "Brene Brown"
        quote_header = ""
    return message, author, quote_header

message, author, quote_header = get_quote()


def send_contact_email(user, message, subject):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": app.config['MAIL_USERNAME']
                    }
                ],
                "Subject": "Open Path Tutoring: " + subject + " from " + user.first_name,
                "ReplyTo": { "Email": user.email },
                "TextPart": render_template('email/inquiry-form.txt',
                                         user=user, message=message),
                "HTMLPart": render_template('email/inquiry-form.html',
                                         user=user, message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print("Contact email sent from " + user.email)
    else:
        print("Contact email from " + user.email + " failed with code " + result.status_code)
    return result.status_code


def send_confirmation_email(user, message):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": user.email
                    }
                ],
                "Subject": "Email confirmation + a quote from Brene Brown",
                "TextPart": render_template('email/confirmation.txt',
                                         user=user, message=message),
                "HTMLPart": render_template('email/confirmation.html',
                                         user=user, message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("Confirmation email sent to " + user.email)
    else:
        print("Confirmation email to " + user.email + " failed to send with code " + result.status_code, result.reason)
    return result.status_code


def send_reminder_email(event, student):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    cc_email = []
    if student.parent:
        parent = student.parent
        if parent.session_reminders:
            cc_email.append({ "Email": parent.email })
            if parent.secondary_email:
                cc_email.append({ "Email": parent.secondary_email })

    if student.tutor:
        tutor = student.tutor
        if tutor.session_reminders:
            cc_email.append({ "Email": tutor.email })
    
        reply_email = tutor.email
        if reply_email == '':
            reply_email = app.config['MAIL_USERNAME']
    
    tz_difference = student.timezone - tutor.timezone

    dt = datetime.datetime
    start_time = event['start'].get('dateTime')
    start_date = dt.strftime(parse(start_time), format="%A, %b %-d")
    start_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', start_time)
    start_offset = dt.strptime(start_time_formatted, "%Y-%m-%dT%H:%M:%S%z") + datetime.timedelta(hours = tz_difference)
    end_time = event['end'].get('dateTime')
    end_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', end_time)
    end_offset = dt.strptime(end_time_formatted, "%Y-%m-%dT%H:%M:%S%z") + datetime.timedelta(hours = tz_difference)
    start_display = dt.strftime(start_offset, "%-I:%M%p").lower()
    end_display = dt.strftime(end_offset, "%-I:%M%p").lower()

    if student.timezone == -2:
        timezone = "Pacific"
    elif student.timezone == -1:
        timezone = "Mountain"
    elif student.timezone == 0:
        timezone = "Central"
    elif student.timezone == 1:
        timezone = "Eastern"
    else:
        timezone = "your"

    if 'practice sat' in event.get('summary').lower():
        event_type = 'practice SAT'
    elif 'practice act' in event.get('summary').lower():
        event_type = 'practice ACT'
    elif 'test prep class' in event.get('summary').lower():
        event_type = 'test prep class'
    else:
        event_type = 'tutoring session'

    location = event.get('location')
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
                    "From": {
                        "Email": app.config['MAIL_USERNAME'],
                        "Name": "Open Path Tutoring"
                    },
                    "To": [
                        {
                        "Email": student.email
                        }
                    ],
                    "Cc": cc_email,
                    "ReplyTo": { "Email": reply_email },
                    "Subject": "Reminder for " + event_type + " on " + start_date + " at " + start_display + " " + timezone,
                    "HTMLPart": render_template('email/reminder-email.html', student=student, \
                        tutor=tutor, start_date=start_date, start_display=start_display, \
                        end_display=end_display, timezone=timezone, location=location,
                        quote_header=quote_header, message=message, author=author, event_type=event_type),
                    "TextPart": render_template('email/reminder-email.txt', student=student, \
                        tutor=tutor, start_date=start_date, start_display=start_display, \
                        end_display=end_display, timezone=timezone, location=location,
                        quote_header=quote_header, message=message, author=author, event_type=event_type)
                }
            ]
        }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print(student.first_name, student.last_name, start_display, timezone, warnings_str)
    else:
        print("Error for " + student.first_name + "\'s reminder email with code " + str(result.status_code), result.reason)
    return result.status_code


def send_session_recap_email(student, events):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    cc_email = []
    if student.parent:
        parent = student.parent
        if parent.session_reminders:
            cc_email.append({ "Email": parent.email })
            if parent.secondary_email:
                cc_email.append({ "Email": parent.secondary_email })

    if student.tutor:
        tutor = student.tutor
        if tutor.session_reminders:
            cc_email.append({ "Email": tutor.email })
    
        reply_email = tutor.email
        if reply_email == '':
            reply_email = app.config['MAIL_USERNAME']
    
    tz_difference = student.timezone - tutor.timezone

    dt = datetime.datetime
    

    session_date = dt.strftime(student.date, format="%A, %b %-d")

    if student.timezone == -2:
        timezone = "Pacific"
    elif student.timezone == -1:
        timezone = "Mountain"
    elif student.timezone == 0:
        timezone = "Central"
    elif student.timezone == 1:
        timezone = "Eastern"
    else:
        timezone = "your"
    
    event_details = []
    alerts = []
    location = None
    for event in events:
        start_time = event['start'].get('dateTime')
        start_date = dt.strftime(parse(start_time), format="%A, %b %-d")
        start_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', start_time)
        start_offset = dt.strptime(start_time_formatted, "%Y-%m-%dT%H:%M:%S%z") + datetime.timedelta(hours = tz_difference)
        end_time = event['end'].get('dateTime')
        end_time_formatted = re.sub(r'([-+]\d{2}):(\d{2})(?:(\d{2}))?$', r'\1\2\3', end_time)
        end_offset = dt.strptime(end_time_formatted, "%Y-%m-%dT%H:%M:%S%z") + datetime.timedelta(hours = tz_difference)
        start_display = dt.strftime(start_offset, "%-I:%M%p").lower()
        end_display = dt.strftime(end_offset, "%-I:%M%p").lower()
        
        event_details.append({
            'date': start_date,
            'start': start_display,
            'end': end_display,
        })

        if location == None:
            location = event.get('location')
        elif location != event.get('location'):
            alerts.append('Location mismatch error for ' + student.first_name + ' ' + student.last_name + ' on ' + start_date)

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
    if "http" in location:
        location = '<a href=\"' + location + '\">' + location + '<a>'

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": student.email
                    }
                ],
                "Cc": cc_email,
                "ReplyTo": { "Email": reply_email },
                "Subject": "Session recap for " + session_date,
                "HTMLPart": render_template('email/recap-email.html', student=student, event_details=event_details),
                "TextPart": render_template('email/recap-email.txt', student=student, event_details=event_details)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print(student.first_name, student.last_name, start_display, timezone, warnings_str)
    else:
        print("Error for " + student.first_name + "\'s session update email with code", result.status_code, result.reason)
    return result.status_code


def send_notification_email(alerts):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": app.config['MAIL_USERNAME']
                    }
                ],
                "Subject": 'Open Path Tutoring notification',
                "TextPart": render_template('email/notification-email.txt', alerts=alerts),
                "HTMLPart": render_template('email/notification-email.html', alerts=alerts)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("Notification email sent to " + app.config['MAIL_USERNAME'])
    else:
        print("Notification email to " + app.config['MAIL_USERNAME'] + " failed to send with code " + result.status_code, result.reason)
    return result.status_code


def send_registration_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent_id:
            if user.parent.test_reminders:
                cc_email.append({ "Email": user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ "Email": user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ "Email": user.tutor.email })

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
                    "From": {
                        "Email": app.config['MAIL_USERNAME'],
                        "Name": "Open Path Tutoring"
                    },
                    "To": [
                        { "Email": user.email }
                    ],
                    "Cc": cc_email,
                    "ReplyTo": { "Email": app.config['MAIL_USERNAME'] },
                    "Subject": "Registration deadline for the " + td + " " + test_date.test.upper() + " is this " + reg_dl_day,
                    "HTMLPart": render_template('email/registration-reminder.html', \
                        user=user, test_date=test_date, td=td, reg_dl=reg_dl, late_dl=late_dl),
                    "TextPart": render_template('email/registration-reminder.txt', \
                        user=user, test_date=test_date, td=td, reg_dl=reg_dl, late_dl=late_dl)
                }
            ]
        }
        
        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            print("Registration reminder for", td, test_date.test.upper(), "sent to", user.first_name, user.last_name)
        else:
            print("Error for " + user.first_name + "\'s registration reminder with code " + str(result.status_code), result.reason)
        return result.status_code


def send_late_registration_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent:
            if user.parent.test_reminders:
                cc_email.append({ "Email": user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ "Email": user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ "Email": user.tutor.email })

        td = test_date.date.strftime('%B %-d')
        late_dl = test_date.late_date.strftime('%A, %B %-d')
        late_dl_day = test_date.late_date.strftime('%A')

        data = {
            'Messages': [
                {
                    "From": {
                        "Email": app.config['MAIL_USERNAME'],
                        "Name": "Open Path Tutoring"
                    },
                    "To": [
                        { "Email": user.email }
                    ],
                    "Cc": cc_email,
                    "ReplyTo": { "Email": app.config['MAIL_USERNAME'] },
                    "Subject": "Late registration deadline for the " + td + " " + test_date.test.upper() + " is this " + late_dl_day,
                    "HTMLPart": render_template('email/late-registration-reminder.html', \
                        user=user, test_date=test_date, td=td, late_dl=late_dl),
                    "TextPart": render_template('email/late-registration-reminder.txt', \
                        user=user, test_date=test_date, td=td, late_dl=late_dl)
                }
            ]
        }
        
        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            print("Late registration reminder for", td, test_date.test.upper(), "sent to", user.first_name, user.last_name)
        else:
            print("Error for " + user.first_name + "\'s late registration reminder with code " + str(result.status_code), result.reason)
        return result.status_code


def send_test_reminder_email(user, test_date):
    with app.app_context():
        api_key = app.config['MAILJET_KEY']
        api_secret = app.config['MAILJET_SECRET']
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')

        cc_email = []
        if user.parent:
            if user.parent.test_reminders:
                cc_email.append({ "Email": user.parent.email })
            if user.parent.secondary_email:
                cc_email.append({ "Email": user.parent.secondary_email })
        if user.tutor:
            if user.tutor.test_reminders:
                cc_email.append({ "Email": user.tutor.email })

        td = test_date.date.strftime('%B %-d')
        td_day = test_date.date.strftime('%A')

        data = {
            'Messages': [
                {
                    "From": {
                        "Email": app.config['MAIL_USERNAME'],
                        "Name": "Open Path Tutoring"
                    },
                    "To": [
                        { "Email": user.email }
                    ],
                    "Cc": cc_email,
                    "ReplyTo": { "Email": app.config['MAIL_USERNAME'] },
                    "Subject": "Things to remember for your " + test_date.test.upper() + " on " + td_day + ", " + td,
                    "HTMLPart": render_template('email/test-reminders.html', \
                        user=user, test_date=test_date, td=td),
                    "TextPart": render_template('email/test-reminders.txt', \
                        user=user, test_date=test_date, td=td)
                }
            ]
        }
        
        result = mailjet.send.create(data=data)

        if result.status_code == 200:
            print(td, test_date.test.upper(), "reminder sent to", user.first_name, user.last_name)
        else:
            print("Error for " + user.first_name + "\'s test reminder with code " + str(result.status_code), result.reason)
        return result.status_code


def send_signup_notification_email(user, dates):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    date_series = ', '.join(dates)

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": app.config['MAIL_USERNAME']
                    }
                ],
                "Subject": user.first_name + " signed up for test reminders",
                "TextPart": render_template('email/signup-notification.txt', user=user,
                    date_series=date_series)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print("Signup notification email sent to " + app.config['MAIL_USERNAME'])
    else:
        print("Signup notification email to " + app.config['MAIL_USERNAME'] + " failed with code " + result.status_code)
    return result.status_code


def send_verification_email(user, page=None):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    token = user.get_email_verification_token()

    purpose = ""
    if page == 'test_reminders':
        purpose = " to get test reminders"

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": user.email
                    }
                ],
                "Subject": "Please verify your email address" + purpose,
                "TextPart": render_template('email/verification-email.txt',
                                         user=user, token=token),
                "HTMLPart": render_template('email/verification-email.html',
                                         user=user, token=token)
            }
        ]
    }

    result = mailjet.send.create(data=data)

    if result.status_code == 200:
        print("Verification email sent to " + user.email)
    else:
        print("Verification email to " + user.email + " failed with code " + result.status_code)
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
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": user.email
                    }
                ],
                "Subject": pw_type.title() + ' your password' + purpose,
                "TextPart": render_template('email/reset-password.txt', \
                                         user=user, token=token, pw_type=pw_type),
                "HTMLPart": render_template('email/reset-password.html', \
                                         user=user, token=token, pw_type=pw_type)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("Password reset email sent to " + user.email)
    else:
        print("Password reset email to " + user.email + " failed to send with code " + str(result.status_code), result.reason)
    return result.status_code


def send_test_strategies_email(student, parent, relation):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    filename = 'SAT-ACT-strategies.pdf'

    to_email = []
    if relation == 'student':
        to_email.append({ "Email": student.email })
    to_email.append({ "Email": parent.email })

    link = "https://www.openpathtutoring.com/download/" + filename

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": to_email,
                "Bcc": [{"Email": app.config['MAIL_USERNAME']}],
                "Subject": "10 Strategies to Master the SAT & ACT",
                "HTMLPart": render_template('email/test-strategies.html', relation=relation, student=student, parent=parent, link=link),
                "TextPart": render_template('email/test-strategies.txt', relation=relation, student=student, parent=parent, link=link)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print("Top 10 email failed to send with code " + str(result.status_code), result.reason)
    return result.status_code


def send_test_registration_email(student, parent, school, test, date, time, location, contact_info):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": parent.email
                    }
                ],
                "Bcc": [{"Email": app.config['MAIL_USERNAME']}],
                "Subject": student.first_name + " " + student.last_name + " is registered for the practice ACT on " + date,
                "TextPart": render_template('email/test-registration-email.txt',
                            student=student, parent=parent, school=school, test=test, \
                            date=date, time=time, location=location, contact_info=contact_info),
                "HTMLPart": render_template('email/test-registration-email.html',
                            student=student, parent=parent, school=school, test=test, \
                            date=date, time=time, location=location, contact_info=contact_info)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print("Test registration email failed to send with code", result.status_code, result.reason)
    return result.status_code


def send_prep_class_email(student, parent, school, test, time, location, cost):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": parent.email
                    }
                ],
                "Bcc": [{"Email": app.config['MAIL_USERNAME']}],
                "Subject": student.first_name + " " + student.last_name + " is registered for " + test + " Study Club",
                "TextPart": render_template('email/prep-class-email.txt',
                            student=student, parent=parent, school=school, test=test, \
                            time=time, location=location),
                "HTMLPart": render_template('email/prep-class-email.html',
                            student=student, parent=parent, school=school, test=test, \
                            time=time, location=location, cost=cost)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print("Prep class email failed to send with code", result.status_code, result.reason)
    return result.status_code


def send_score_analysis_email(student, parent, school):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": parent.email
                    }
                ],
                "Bcc": [{"Email": app.config['MAIL_USERNAME']}],
                "Subject": "Score analysis request received",
                "TextPart": render_template('email/score-analysis-email.txt',
                                         student=student, parent=parent, school=school),
                "HTMLPart": render_template('email/score-analysis-email.html',
                                         student=student, parent=parent, school=school)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print(result.json())
    else:
        print("Score analysis confirmation email failed to send with code", result.status_code, result.reason)
    return result.status_code


def send_weekly_report_email(scheduled_session_count, scheduled_hours, scheduled_student_count, \
    future_list, unscheduled_list, outsourced_session_count, outsourced_hours, \
    outsourced_scheduled_student_count, outsourced_unscheduled_list, \
    paused, now):

    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    dt = datetime.datetime
    start = (now + datetime.timedelta(hours=40)).isoformat() + 'Z'
    start_date = dt.strftime(parse(start), format="%b %-d")
    end = (now + datetime.timedelta(days=7, hours=40)).isoformat() + 'Z'
    end_date = dt.strftime(parse(end), format="%b %-d")
    future_students = ', '.join(future_list)
    if future_students == '':
        future_students = "None"
    unscheduled_students = ', '.join(unscheduled_list)
    if unscheduled_students == '':
        unscheduled_students = "None"
    outsourced_unscheduled_students = ', '.join(outsourced_unscheduled_list)
    if outsourced_unscheduled_students == '':
        outsourced_unscheduled_students = "None"
    paused_students = ', '.join(paused)
    if paused_students == '':
        paused_students = "None"

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": app.config['MAIL_USERNAME']
                    },
                    {
                    "Email": app.config['MOM_EMAIL']
                    },
                    {
                    "Email": app.config['DAD_EMAIL']
                    }
                ],
                "Subject": "Weekly tutoring report for " + start_date + " to " + end_date,
                "HTMLPart": "A total of " + scheduled_hours + " hours (" + scheduled_session_count + " sessions) " + \
                    "are scheduled with Danny for " + scheduled_student_count + " students next week. <br/><br/>" + \
                    "An additional " + outsourced_hours + " hours (" + outsourced_session_count + " sessions) " + \
                    "are scheduled with other tutors for " + outsourced_scheduled_student_count + " students. " + \
                    "<br/><br/>Unscheduled active students for Danny: " + unscheduled_students + \
                    "<br/>Unscheduled active students for other tutors: " + outsourced_unscheduled_students + \
                    "<br/>Active students scheduled after next week: " + future_students + \
                    "<br/>Paused students: " + paused_students + \
                    "<br/><br/><br/>" + quote_header + '<br/>"' + message + '"' + "<br/>&ndash; " + author
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("\nWeekly report email sent.")
    else:
        print("Weekly report email error:", str(result.status_code), result.reason, "\n")
    return result.status_code


def send_admin_report_email(now, admin_data, status_fixes, students_not_in_db):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    dt = datetime.datetime
    start = (now + datetime.timedelta(hours=40)).isoformat() + 'Z'
    start_date = dt.strftime(parse(start), format="%b %-d")
    end = (now + datetime.timedelta(days=7, hours=40)).isoformat() + 'Z'
    end_date = dt.strftime(parse(end), format="%b %-d")

    low_active_students = []
    student_statuses = []

    weekly_data = admin_data['weekly_data']

    for s in admin_data['low_active_students']:
        low_active_students.append(str(s[0]) + ": " + str(s[1]) + ' hrs')

    for s in status_fixes:
        student_statuses.append(s[0] + ' is listed as ' + s[1] + ' in the database and ' + \
            s[2] + ' in the spreadsheet.')
    
    not_in_db = (', ').join(students_not_in_db)
    student_fix_list = '\n'.join(student_statuses)
    
    with app.app_context():
        data = {
            'Messages': [
                {
                    "From": {
                        "Email": app.config['MAIL_USERNAME'],
                        "Name": "Open Path Tutoring"
                    },
                    "To": [
                        {
                        "Email": app.config['MAIL_USERNAME']
                        }
                    ],
                    "Subject": "Admin data report for " + start_date + " to " + end_date,
                    "HTMLPart": render_template('email/admin-email.html', low_active_students=low_active_students, \
                        student_fix_list=student_fix_list, not_in_db=not_in_db, weekly_data=weekly_data)
                }
            ]
        }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("Admin report email sent.\n")
    else:
        print("Admin report email error:", str(result.status_code), result.reason, "\n")
    return result.status_code


def send_schedule_conflict_email(message):
    api_key = app.config['MAILJET_KEY']
    api_secret = app.config['MAILJET_SECRET']
    mailjet = Client(auth=(api_key, api_secret), version='v3.1')

    data = {
        'Messages': [
            {
                "From": {
                    "Email": app.config['MAIL_USERNAME'],
                    "Name": "Open Path Tutoring"
                },
                "To": [
                    {
                    "Email": app.config['MAIL_USERNAME']
                    }
                ],
                "Subject": "Schedule conflict email",
                "TextPart": render_template('email/schedule-conflict.txt',
                                        message=message),
                "HTMLPart": render_template('email/schedule-conflict.html',
                                        message=message)
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code == 200:
        print("Schedule conflict email sent to " + user.email)
    else:
        print("Schedule conflict email to " + user.email + " failed to send with code " + result.status_code, result.reason)
    return result.status_code