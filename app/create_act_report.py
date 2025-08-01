import os
from app import app
from app.email import send_score_report_email
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from graderclient import GraderClient
from werkzeug.utils import secure_filename
import json
import logging
import requests
import base64


# Constants
TEMPLATE_SS_ID = app.config['ACT_REPORT_SS_ID'] # Your spreadsheet ID
ACT_REPORT_FOLDER_ID = '1di1PnSgL4J9oyGQGjUKfg_eRhKSht3WD'  # Your score report folder ID
ORG_FOLDER_ID = '1E9oLuQ9pTcTxA2gGuVN_ookpDYZn0fAm'  # Your organization folder ID
SERVICE_ACCOUNT_JSON = 'service_account_key2.json'  # Path to your service account JSON file
ACT_DATA_SS_ID = app.config['ACT_DATA_SS_ID']  # Your ACT data spreadsheet ID

all_subjects = ['english', 'math', 'reading', 'science']
completed_subjects = []
sub_data = {
  'english': {'col': 2, 'max_len': 75},
  'math': {'col': 6, 'max_len': 60},
  'reading': {'col': 10, 'max_len': 40},
  'science': {'col': 14, 'max_len': 40}
}

def get_act_test_codes():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON)
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    result = service.spreadsheets().values().get(
      spreadsheetId=ACT_DATA_SS_ID,
      range="'Test designations'!E2:I"
    ).execute()
    values = result.get('values', [])
    # Only include rows where col G is "Yes", col E (test_code) and col I (form_code) are present
    codes = [
      [v[0].strip(), v[4].strip()]
      for v in values
      if v and len(v) >= 5 and v[0].strip() and v[4].strip() and v[2].strip().lower() == "yes"
    ]
    with open('app/act_test_codes.json', 'w') as f:
      json.dump(codes, f)
    return codes


def process_act_answer_img(score_data):
  url = "http://50.28.85.57"
  oauth = "h5Kafh-egN3HyfEjpbKfg2VU"
  gc = GraderClient(url, oauth)

  upload_response, uri = gc.upload_image(score_data['answer_img_path'])
  gc.uri = uri

  # process the image to extract the image
  process_response, uri = gc.process_image()

  # download the answers as json, you need to specify the destination file
  json_filename = secure_filename(f"{score_data['student_name']} {score_data['date']} {score_data['test_display_name']} answers.json")
  json_path = os.path.join(score_data['act_uploads_path'], json_filename)
  download_ma_response, path = gc.download_marked_answers(json_path)

  # download the confirmation image, you need to specify the destination file
  confirmation_filename = secure_filename(f"{score_data['student_name']} {score_data['date']} {score_data['test_display_name']} confirmation.jpg")
  confirmation_path = os.path.join(score_data['act_reports_path'], confirmation_filename)
  download_ci_response, path = gc.download_confirmation_image(confirmation_path)

  # Open the JSON file saved at json_path
  with open(json_path, "r") as j:
    json_data = json.load(j)

  score_data['student_responses']['english'] = json_data['e']
  score_data['student_responses']['math'] = json_data['m']
  score_data['student_responses']['reading'] = json_data['r']
  score_data['student_responses']['science'] = json_data['s']

  return score_data


def create_act_score_report(score_data, organization_dict):
  """
  Copies a template spreadsheet and fills in answers from json_data.
  - "e" answers go to B5:B79 (Answers sheet)
  - "m" answers go to F5:F64
  - "r" answers go to J5:J44
  - "s" answers go to N5:N44
  - test_code goes to B1
  If answer is blank, writes "-"
  """
  # Authenticate
  creds = Credentials.from_service_account_file(
      SERVICE_ACCOUNT_JSON,
      scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
  )
  drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
  sheets_service = build('sheets', 'v4', credentials=creds, cache_discovery=False)

  # 1. Copy the template spreadsheet
  if organization_dict and organization_dict['spreadsheet_id']:
    file_id = organization_dict['spreadsheet_id']
  else:
    file_id = TEMPLATE_SS_ID
  ss_copy = drive_service.files().copy(
      fileId=file_id,
      body={
        'parents': [ACT_REPORT_FOLDER_ID],
        'name': f'{score_data["student_name"]} {score_data["test_display_name"]} Score Analysis - {score_data["date"]}'
      }
  ).execute()

  ss_copy_id = ss_copy.get('id')
  logging.info(f'ss_copy_id: {ss_copy_id} (copied from {file_id})')

  ss = sheets_service.spreadsheets().get(spreadsheetId=ss_copy_id).execute()
  sheets = ss.get('sheets', [])
  # pp.pprint(ss)

  answer_sheet_id = None
  analysis_sheet_id = None
  for sheet in sheets:
      if sheet['properties']['title'] == 'Answers':
          answer_sheet_id = sheet['properties']['sheetId']
      elif sheet['properties']['title'] == 'Test analysis':
          analysis_sheet_id = sheet['properties']['sheetId']
      elif sheet['properties']['title'] == 'Test analysis 2':
          analysis2_sheet_id = sheet['properties']['sheetId']
      elif sheet['properties']['title'] == 'Data':
          data_sheet_id = sheet['properties']['sheetId']

  # 2. Prepare the data for batchUpdate
  score_data['completed_subjects'] = []
  def prep_range(col, start_row, subject, max_len):
      answers = score_data['student_responses'][subject]
      values = []
      omit_count = 0
      for i in range(max_len):
          val = answers.get(str(i+1), "-")
          if not val:
              val = "-"
              omit_count += 1
          values.append([val])

      if max_len - omit_count > 10:
        score_data['completed_subjects'].append(subject)
        # Convert col number to letter
        col_letter = chr(64 + col)
        return {
            'range': f'Answers!{col_letter}{start_row}:{col_letter}{start_row + max_len - 1}',
            'values': values
        }
      return None

  data = []
  for sub in all_subjects:
    result = prep_range(sub_data[sub]['col'], 5, sub, sub_data[sub]['max_len'])
    if result:
        data.append(result)

  # 2b. Transfer answer data to the spreadsheet
  sheets_service.spreadsheets().values().batchUpdate(
    spreadsheetId=ss_copy_id,
    body={
      'valueInputOption': 'USER_ENTERED',
      'data': data
    }
  ).execute()

  requests = []

  # Add student name to analysis sheet
  if organization_dict:
      title_row = 5 # Row B6 if custom organization
  else:
      title_row = 2 # Row B3 if default template

  request = {
      'updateCells': {
          'range': {
              'sheetId': analysis_sheet_id,
              'startRowIndex': title_row,
              'endRowIndex': title_row + 1,
              'startColumnIndex': 1,  # Column B (column index starts at 0)
              'endColumnIndex': 2
          },
          'rows': [
              {
                  'values': [
                      {
                          'userEnteredValue': {
                              'stringValue': f"ACT Score Analysis for {score_data['student_name']}"
                          }
                      }
                  ]
              }
          ],
          'fields': 'userEnteredValue'
      }
  }
  requests.append(request)

  # Add test code to answer sheet
  test_code = score_data['test_code']
  if str(test_code).isdigit():
    value_field = {'numberValue': int(test_code)}
  else:
    value_field = {'stringValue': str(test_code)}
  request = {
    'updateCells': {
      'range': {
        'sheetId': answer_sheet_id,
        'startRowIndex': 0,
        'endRowIndex': 1,
        'startColumnIndex': 1,
        'endColumnIndex': 2
      },
      'rows': [
        {
          'values': [
            {
              'userEnteredValue': value_field
            }
          ]
        }
      ],
      'fields': 'userEnteredValue'
    }
  }
  requests.append(request)

  hide_requests = []

  if not any(sub in score_data['completed_subjects'] for sub in ['english', 'math']):
      hide_requests.append({
          "updateSheetProperties": {
              "properties": {
                  "sheetId": analysis_sheet_id,
                  "hidden": True
              },
              "fields": "hidden"
          }
      })

  if not any(sub in score_data['completed_subjects'] for sub in ['reading', 'science']):
      hide_requests.append({
          "updateSheetProperties": {
              "properties": {
                  "sheetId": analysis2_sheet_id,
                  "hidden": True
              },
              "fields": "hidden"
          }
      })

  # Add these to your requests list before the batchUpdate
  requests.extend(hide_requests)

  batch_update_request = {
    'requests': requests
  }

  # 3. Batch update the sheet
  sheets_service.spreadsheets().batchUpdate(
      spreadsheetId=ss_copy_id,
      body=batch_update_request
  ).execute()

  # Filter Data sheet to show only Incorrect and Omitted questions
  filter_request = {
    "setBasicFilter": {
      "filter": {
        "range": {
          "sheetId": data_sheet_id,
          "startRowIndex": 0,
          "startColumnIndex": 0,
          "endColumnIndex": 9  # Adjust if your data has more columns
        },
        "criteria": {
          8: {  # Assuming column L (index 11) is "Status" or similar
            "condition": {
              "type": "CUSTOM_FORMULA",
              "values": [
                {"userEnteredValue": '=or(I2="Incorrect", I2="Omitted")'}
              ]
            }
          }
        }
      }
    }
  }
  sheets_service.spreadsheets().batchUpdate(
    spreadsheetId=ss_copy_id,
    body={"requests": [filter_request]}
  ).execute()

  return ss_copy_id, score_data


def send_act_pdf_report(spreadsheet_id, score_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/drive']
    )
    creds.refresh(Request())

    try:
      # Create the Drive API service
      drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

      # Prepare URL for PDF export
      url_base = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/'
      url_ext = 'export?exportFormat=pdf&format=pdf'   # export as pdf
      url_params = '&size=letter&portrait=true&fitw=true&fzr=true&top_margin=0.25&bottom_margin=0.25&left_margin=0.25&right_margin=0.25&printnotes=false&sheetnames=false&printtitle=false&pagenumbers=false'

      # Create full URL
      full_url = url_base + url_ext + url_params

      # Fetch the PDF
      response = requests.get(full_url, headers={
          'Authorization': f'Bearer {creds.token}'
      })

      # Handle response
      if response.status_code == 200:
          pdf_name = f"ACT Score Analysis for {score_data['student_name']} {score_data['date']} {score_data['test_display_name']}.pdf"
          file_path = os.path.join(score_data['act_reports_path'], secure_filename(pdf_name))
          print(file_path)
          # Save the PDF content to a file
          with open(file_path, 'wb') as f:
              f.write(response.content)

          # Create PDF in Drive
          file_metadata = {
              'name': pdf_name,
              'parents': [ACT_REPORT_FOLDER_ID],
              'mimeType': 'application/pdf'
          }

          media = MediaFileUpload(file_path, mimetype='application/pdf')

          file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
          # file_id = file.get('id')
          # Read the PDF file as a blob
          with open(file_path, 'rb') as f:
              blob = f.read()

          print(blob[:20])  # Print the first 20 bytes of the blob

          base64_blob = base64.b64encode(blob).decode('utf-8')

          print(base64_blob[:100])  # Print the first 100 characters of the base64 string

          # Send email with PDF attachment
          send_score_report_email(score_data, base64_blob)
          logging.info(f"PDF report sent to {score_data['email']}")
      else:
          logging.error(f'Failed to fetch PDF: {response.content}')
    except Exception:
      logging.error(f'Error in send_pdf_score_report: {Exception}')
      raise

# WIP
def act_answers_to_student_ss(score_data):
  creds = service_account.Credentials.from_service_account_file(
      SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
      scopes=['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive',
              'https://www.googleapis.com/auth/script.external_request']
  )

  try:
    # Create the Sheets API service
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)

    ss = service.spreadsheets().get(spreadsheetId=score_data['student_ss_id']).execute()
    student_sheets = ss.get('sheets', [])
    # pp.pprint(ss)

    student_answer_sheet_id = None
    for sheet in student_sheets:
        if sheet['properties']['title'] == score_data['test_code'].upper():
            student_answer_sheet_id = sheet['properties']['sheetId']
            break

    score_data['test_sheet_id'] = str(student_answer_sheet_id)
    logging.info('https://docs.google.com/spreadsheets/d/' + score_data['student_ss_id'] + '/edit?gid=' + score_data['test_sheet_id'])

    # After setting test code and difficulty, get values from the answer sheet
    student_answer_sheet_range = f'{score_data["test_code"].upper()}!A1:P79'  # Adjust range as needed
    student_answer_data = service.spreadsheets().values().get(spreadsheetId=score_data['student_ss_id'], range=student_answer_sheet_range).execute()
    student_answer_values = student_answer_data.get('values', [])

    # Reset batch requests
    requests = []

    for sub in score_data['completed_subjects']:
      col = sub_data[sub]['col']
      max_len = sub_data[sub]['max_len']
      answers = score_data['student_responses'][sub]
      values = []
      for i in range(max_len):
        val = answers.get(str(i+1), "-")
        values.append([{'userEnteredValue': {'stringValue': val}}])
        requests.append({
        'updateCells': {
          'range': {
          'sheetId': student_answer_sheet_id,
          'startRowIndex': 4,
          'endRowIndex': 4 + max_len,
          'startColumnIndex': col - 1,
          'endColumnIndex': col
          },
          'rows': [{'values': v} for v in values],
          'fields': 'userEnteredValue'
        }
        })
    # for sub in completed_subjects:


    # TODO Set subject scores

    # TODO Set submission date

    batch_update_request = {'requests': requests}
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=score_data['student_ss_id'],
        body=batch_update_request
    ).execute()

    logging.info('Student spreadsheet updated')

    return score_data

  except Exception:
    logging.error(f'Error in act_answers_to_student_ss: {Exception}')
    raise

# WIP
def create_custom_act_spreadsheet(organization):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    sheets_service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

    # Step 1: Copy the default template
    file_copy = drive_service.files().copy(
        fileId=SHEET_ID,
        body={
            'parents': [ORG_FOLDER_ID],
            'name': f'{organization.name} Template'}
    ).execute()
    ss_copy_id = file_copy.get('id')
    ss_copy = sheets_service.spreadsheets().get(spreadsheetId=ss_copy_id).execute()
    sheets = ss_copy.get('sheets', [])
    logging.info(f'ss_copy_id: {ss_copy_id} (copied from {SHEET_ID})')

    answer_sheet_id = None
    analysis_sheet_id = None
    for sheet in sheets:
        if sheet['properties']['title'] == 'Answers':
            answer_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Test analysis':
            analysis_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Data':
            data_sheet_id = sheet['properties']['sheetId']

    print(ss_copy_id)

    # Step 2: Update header colors (A1:K7) and set borders
    requests = [
        {
            "updateBorders": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 7,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                }
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 7,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 4,
                    "startColumnIndex": 1,
                    "endColumnIndex": 12
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 32,
                    "endRowIndex": 35,
                    "startColumnIndex": 1,
                    "endColumnIndex": 12
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": hex_to_rgb(organization.color1)[0] / 255,
                            "green": hex_to_rgb(organization.color1)[1] / 255,
                            "blue": hex_to_rgb(organization.color1)[2] / 255
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        }
    ]

    # Step 4: Add the logo to cell B2
    # if organization.logo_path:
    #     logo_url = f"https://www.openpathtutoring.com{get_static_url(organization.logo_path)}"  # Replace with your actual domain
    #     requests.append({
    #         "updateCells": {
    #         "range": {
    #             "sheetId": analysis_sheet_id,
    #             "startRowIndex": 1,  # Row B2
    #             "endRowIndex": 2,
    #             "startColumnIndex": 1,  # Column B2
    #             "endColumnIndex": 2
    #         },
    #         "rows": [
    #             {
    #             "values": [
    #                 {
    #                 "userEnteredValue": {
    #                     "formulaValue": f'=IMAGE("{logo_url}")'
    #                 }
    #                 }
    #             ]
    #             }
    #         ],
    #         "fields": "userEnteredValue"
    #         }
    #     })

    # Execute batch update
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=ss_copy_id,
        body={"requests": requests}
    ).execute()

    # Step 3: Update conditional formatting rules
    for sheet in sheets:
        if sheet['properties']['sheetId'] == analysis_sheet_id:
            for rule in sheet.get('conditionalFormats', []):
                if 'booleanRule' in rule:
                    bg_color = rule['booleanRule']['format']['backgroundColor']
                    if bg_color == {'red': 28/255, 'green': 77/255, 'blue': 101/255}:  # #1c4d65
                        rule['booleanRule']['format']['backgroundColor'] = {
                            'red': hex_to_rgb(organization.color1)[0] / 255,
                            'green': hex_to_rgb(organization.color1)[1] / 255,
                            'blue': hex_to_rgb(organization.color1)[2] / 255
                        }
                    elif bg_color == {'red': 255/255, 'green': 168/255, 'blue': 116/255}:  # #ffa874
                        rule['booleanRule']['format']['backgroundColor'] = {
                            'red': hex_to_rgb(organization.color2)[0] / 255,
                            'green': hex_to_rgb(organization.color2)[1] / 255,
                            'blue': hex_to_rgb(organization.color2)[2] / 255
                        }
                    elif bg_color == {'red': 196/255, 'green': 240/255, 'blue': 247/255}:  # #c4f0f7
                        rule['booleanRule']['format']['backgroundColor'] = {
                            'red': hex_to_rgb(organization.color3)[0] / 255,
                            'green': hex_to_rgb(organization.color3)[1] / 255,
                            'blue': hex_to_rgb(organization.color3)[2] / 255
                        }
            break

    return ss_copy_id