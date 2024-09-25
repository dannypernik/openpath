import os.path
import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token2.json.
SCOPES = [
  'https://www.googleapis.com/auth/script.send_mail',
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/script.external_request',
  'https://www.googleapis.com/auth/spreadsheets',
  'https://www.googleapis.com/auth/script.container.ui'
]


def create_sat_score_report(score_data):
  """Calls the Apps Script API."""
  creds = None
  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists("token2.json"):
    creds = Credentials.from_authorized_user_file("token2.json", SCOPES)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          "credentials2.json", SCOPES
      )
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open("token2.json", "w") as token:
      token.write(creds.to_json())

    creds_expiry_tz_aware = creds.expiry.replace(tzinfo=datetime.timezone.utc)
    if creds_expiry_tz_aware - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(seconds=360):
      creds.refresh(Request())

  try:
    service = build("script", "v1", credentials=creds)

    # Call the Apps Script API
    # Create a new project
    request = {
      'function': 'createSatScoreReport',
      'parameters': [
        '104w631_Qo1667eBO_FdAOYHf4xqnpk7BgQOD_rdm37o',
        score_data,
      ],
      'devMode': True
    }
    deployment_id = 'AKfycbx8soq5OE6-pxKE0_UCvHotAhlfqPXlWmvuqzlitKbMiYyHpQ1KFNSLCje5weZkWHy6BA' # app.config['GAS_DEPLOYMENT_ID']

    # Make the API request.
    response = service.scripts().run(scriptId=deployment_id, body=request).execute()
    if "error" in response:
      # The API executed, but the script returned an error.
      # Extract the first (and only) set of error details. The values of
      # this object are the script's 'errorMessage' and 'errorType', and
      # a list of stack trace elements.
      error = response["error"]["details"][0]
      print(f"Script error message: {0}.{format(error['errorMessage'])}")

      if "scriptStackTraceElements" in error:
        # There may not be a stacktrace if the script didn't start
        # executing.
        print("Script error stacktrace:")
        for trace in error["scriptStackTraceElements"]:
          print(f"\t{0}: {1}.{format(trace['function'], str(trace['lineNumber']))}")
    else:
      # The structure of the result depends upon what the Apps Script
      # function returns. Here, the function returns an Apps Script
      # Object with String keys and values, and so the result is
      # treated as a Python dictionary (folder_set).
      result = response["response"].get("result", {})
      print(result)

  except HttpError as error:
    # The API encountered a problem before the script started executing.
    print(f"An error occurred: {error}")
    print(error.content)