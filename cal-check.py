import os.path
from reminders import get_events_and_data

basedir = os.path.abspath(os.path.dirname(__file__))
#load_dotenv(os.path.join(basedir, '.env'))

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly']

bimonth_events, summary_data = get_events_and_data()

for e in bimonth_events:
  e_start = isoparse(bimonth_events[e]['start'].get('dateTime'))
  e_end = isoparse(bimonth_events[e]['end'].get('dateTime'))
  if e_start < prev_end:
    print('conflict')

  prev_start = e_start
  prev_end = e_end