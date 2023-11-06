import os
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from google.oauth2.credentials import Credentials
import requests
import uuid


basedir = os.path.abspath(os.path.dirname(__file__))
SCOPES = 'https://www.googleapis.com/auth/calendar/readonly'

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
service = build('calendar', 'v3', credentials=creds)


## TESTING callback receiver: 
eventcollect = {
    'id': str(uuid.uuid1()),
    'type': "web_hook",
    "address": "https://openpathtutoring.com/cal-check"
}

check = service.events().watch(calendarId='primary', body=eventcollect).execute()

print(check)