import os
from flask import current_app
from app.utils import is_dark_color, hex_to_rgb, color_svg_white_to_input
from app.email import send_score_report_email
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from flask import url_for
import requests
import pprint
import base64
import logging

logger = logging.getLogger(__name__)

pp = pprint.PrettyPrinter(indent=2, width=100)


def get_static_url(filename):
    """Get URL for static file."""
    return url_for('static', filename=filename)


def get_sheet_id():
    return current_app.config['SAT_REPORT_SS_ID']


def get_org_sheet_id():
    return current_app.config['ORG_SAT_REPORT_SS_ID']


def get_org_folder_id():
    return current_app.config['get_org_folder_id()']


# Constants
SAT_REPORT_FOLDER_ID = '15tJsdeOx_HucjIb6koTaafncTj-e6FO6'  # Your score report folder ID
SERVICE_ACCOUNT_JSON = 'service_account_key2.json'  # Path to your service account JSON file

total_questions = {
    'rw_modules': {'questions': 27, 'prepend_rows': 4},
    'm_modules': {'questions': 22, 'prepend_rows': 35}
}

def check_service_account_access(spreadsheet_id):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    try:
        # Create the Sheets API service
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)

        # Try to get the spreadsheet
        service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        logging.info(f'Service account has access to edit spreadsheet {spreadsheet_id}')
        return True
    except HttpError as e:
        logging.error(f'Service account does not have access to edit spreadsheet {spreadsheet_id}: {e}')
        return False


def create_sat_score_report(score_data, organization_dict=None):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/script.external_request']
    )
    try:
        # Create the Sheets API service
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        # Create a copy of the spreadsheet
        file_id = organization_dict['spreadsheet_id'] if organization_dict else get_sheet_id()
        ss_copy = drive_service.files().copy(
            fileId=file_id,
            body={
            'parents': [SAT_REPORT_FOLDER_ID],
            'name': f"{score_data['test_code'].upper()} Score Analysis for {score_data['student_name']} - {score_data['date'].replace('-', '.')}.pdf"
            }
        ).execute()
        ss_copy_id = ss_copy.get('id')
        logging.info(f'ss_copy: https://docs.google.com/spreadsheets/d/{ss_copy_id} (copied from {file_id})')

        ss = service.spreadsheets().get(spreadsheetId=ss_copy_id).execute()
        sheets = ss.get('sheets', [])
        # pp.pprint(ss)

        answer_sheet_id = None
        analysis_sheet_id = None
        for sheet in sheets:
            if sheet['properties']['title'] == 'Answers':
                answer_sheet_id = sheet['properties']['sheetId']
            elif sheet['properties']['title'] == 'Test analysis':
                analysis_sheet_id = sheet['properties']['sheetId']
            elif sheet['properties']['title'] == 'Data':
                data_sheet_id = sheet['properties']['sheetId']

        requests = []
        # Set test code
        request = {
            'updateCells': {
                'range': {
                    'sheetId': answer_sheet_id,
                    'startRowIndex': 0,
                    'endRowIndex': 1,
                    'startColumnIndex': 0,
                    'endColumnIndex': 2
                },
                'rows': [
                    {
                        'values': [
                            {
                                'userEnteredValue': {
                                    'stringValue': score_data['test_code'].upper()
                                }
                            },
                            {
                                'userEnteredValue': {
                                    'stringValue': 'Bluebook Practice ' + score_data['test_display_name']
                                }
                            }
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        }
        requests.append(request)

        # Add the request to the batch update request
        batch_update_request = {
            'requests': requests
        }

        # Update pivot table filter on the analysis sheet
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': analysis_sheet_id,
                    'startRowIndex': 6,
                    'endRowIndex': 7,
                    'startColumnIndex': 1,
                    'endColumnIndex': 2
                },
                'rows': [
                    {
                        'values': [
                            {
                                'pivotTable': {
                                    'source': {
                                        'sheetId': data_sheet_id,
                                        'startRowIndex': 0,
                                        'endRowIndex': 10000,
                                        'startColumnIndex': 0,
                                        'endColumnIndex': 12
                                    },
                                    'rows': [
                                        {
                                            'sourceColumnOffset': 0,
                                            'showTotals': True,
                                            'sortOrder': 'ASCENDING'
                                        },
                                        {
                                            'sourceColumnOffset': 1,
                                            'showTotals': False,
                                            'sortOrder': 'DESCENDING'
                                        },
                                        {
                                            'sourceColumnOffset': 6,
                                            'showTotals': True,
                                            'sortOrder': 'DESCENDING',
                                            "valueBucket": {}
                                        },
                                        {
                                            'sourceColumnOffset': 7,
                                            'showTotals': True,
                                            'sortOrder': 'DESCENDING',
                                            "valueBucket": {}
                                        }
                                    ],
                                    'columns': [
                                        {
                                            'sourceColumnOffset': 11,
                                            'showTotals': False,
                                            'sortOrder': 'ASCENDING'
                                        }
                                    ],
                                    'values': [
                                        {
                                            'summarizeFunction': 'COUNTA',
                                            'sourceColumnOffset': 4
                                        }
                                    ],
                                    'criteria': {
                                        '0': {
                                            'visibleValues': [
                                                score_data['test_code'].upper()
                                            ]
                                        },
                                        '1': {
                                            'visibleValues': [
                                                'Reading & Writing',
                                                'Math'
                                            ],
                                            'condition': {
                                            'type': 'CUSTOM_FORMULA',
                                            'values': [
                                                {
                                                'userEnteredValue': '=or(Subject=A12,Subject=A13)'
                                                }
                                            ]
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    }
                ],
                'fields': 'pivotTable'
            }
        })

        if score_data['is_rw_hard']:
            rw_difficulty = 3
        else:
            rw_difficulty = 2
        if score_data['is_m_hard']:
            m_difficulty = 3
        else:
            m_difficulty = 2

        for cat in [
            {
                'mod': 'rw_modules',
                'difficulty': rw_difficulty,
            },
            {
                'mod': 'm_modules',
                'difficulty': m_difficulty
            }
        ]:
            request = {
                'updateCells': {
                    'range': {
                        'sheetId': answer_sheet_id,
                        'startRowIndex': total_questions[cat['mod']]['prepend_rows'],
                        'endRowIndex': total_questions[cat['mod']]['prepend_rows'] + 1,
                        'startColumnIndex': 12,
                        'endColumnIndex': 12 + 1
                    },
                    'rows': [
                        {
                            'values': [
                                {
                                    'userEnteredValue': {
                                        'numberValue': cat['difficulty']
                                    }
                                }
                            ]
                        }
                    ],
                    'fields': 'userEnteredValue'
                }
            }
            requests.append(request)

            # Add the request to the batch update request
            # batch_update_request = {
            #     'requests': requests
            # }

        # Execute first batch update request
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()

        # After setting test code and difficulty, get values from the answer sheet
        answer_sheet_range = f'Answers!C1:J57'  # Adjust range as needed
        answer_data = service.spreadsheets().values().get(spreadsheetId=ss_copy_id, range=answer_sheet_range).execute()
        answer_values = answer_data.get('values', [])

        requests = []
        x = 0
        mod_answers = []
        for sub in ['rw_modules', 'm_modules']:
            for mod in range(1, 3):
                section = []
                for n in range(1, total_questions[sub]['questions'] + 1):
                    # Update the answer sheet with the response
                    row_idx = n + total_questions[sub]['prepend_rows'] - 1
                    col_idx = (mod - 1) * 6

                    # Needed str(mod) and str(n) with celery worker
                    number = score_data['answers'][sub][str(mod)][str(n)]
                    # Update answers in score_data to match spreadsheet key
                    if number['is_correct'] and number['student_answer'] != '-':
                        student_answer = answer_values[row_idx][col_idx + 1]
                        number['student_answer'] = student_answer
                    else:
                        student_answer = number['student_answer']

                    section.append(student_answer)
                mod_answers.append(section)
                request = {
                    'updateCells': {
                        'range': {
                            'sheetId': answer_sheet_id,
                            'startRowIndex': total_questions[sub]['prepend_rows'],
                            'endRowIndex': total_questions[sub]['prepend_rows'] + total_questions[sub]['questions'],
                            'startColumnIndex': col_idx + 2,
                            'endColumnIndex': col_idx + 3
                        },
                        'rows': [
                            {
                                'values': [
                                    {
                                        'userEnteredValue': {
                                            'stringValue': str(mod_answers[x][row])
                                        }
                                    }
                                ]
                            }
                            for row in range(total_questions[sub]['questions'])
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
                requests.append(request)

                x += 1


        # Set RW and Math scores
        for sub in [['rw_score', 5], ['m_score', 8]]:
            if (sub[0] == 'rw_score' and score_data['rw_questions_answered'] >= 5) or (sub[0] == 'm_score' and score_data['m_questions_answered'] >= 5):
                request = {
                    'updateCells': {
                        'range': {
                            'sheetId': answer_sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1,
                            'startColumnIndex': sub[1],
                            'endColumnIndex': sub[1] + 1
                        },
                        'rows': [
                            {
                                'values': [
                                    {
                                        'userEnteredValue': {
                                            'numberValue': score_data[sub[0]]
                                        }
                                    }
                                ]
                            }
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
                requests.append(request)
            else:
                request = {
                    'updateCells': {
                        'range': {
                            'sheetId': answer_sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1,
                            'startColumnIndex': sub[1],
                            'endColumnIndex': sub[1] + 1
                        },
                        'rows': [
                            {
                                'values': [
                                    {
                                        'userEnteredValue': {
                                            'stringValue': 'Omitted'
                                        }
                                    }
                                ]
                            }
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
                requests.append(request)

        # Hide RW rows if omitted
        if score_data['rw_questions_answered'] < 5:
            request = {
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': answer_sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': 1,
                        'endIndex': 32
                    },
                    'properties': {
                        'hiddenByUser': True
                    },
                    'fields': 'hiddenByUser'
                }
            }
            requests.append(request)

        # Hide Math rows if omitted
        if score_data['m_questions_answered'] < 5:
            request = {
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': answer_sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': 32,
                        'endIndex': 57
                    },
                    'properties': {
                        'hiddenByUser': True
                    },
                    'fields': 'hiddenByUser'
                }
            }
            requests.append(request)

        # Set test completion date
        request = {
            'updateCells': {
                'range': {
                    'sheetId': answer_sheet_id,
                    'startRowIndex': 75,
                    'endRowIndex': 76,
                    'startColumnIndex': 1,
                    'endColumnIndex': 2
                },
                'rows': [
                    {
                        'values': [
                            {
                                'userEnteredValue': {
                                    'stringValue': 'Test completed on ' + score_data['date']
                                }
                            }
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        }
        requests.append(request)

        if organization_dict:
            title_row = 5 # Row B6 if custom organization
        else:
            title_row = 1 # Row B2 if default template
        request = {
            'updateCells': {
                'range': {
                    'sheetId': analysis_sheet_id,
                    'startRowIndex': title_row,
                    'endRowIndex': title_row + 1,
                    'startColumnIndex': 1,
                    'endColumnIndex': 2
                },
                'rows': [
                    {
                        'values': [
                            {
                                'userEnteredValue': {
                                    'stringValue': f"{score_data['test_code'].upper()} Score Analysis for {score_data['student_name']}"
                                }
                            }
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        }
        requests.append(request)


        # Hide 'Data' sheet
        request = {
            'updateSheetProperties': {
            'properties': {
                'sheetId': data_sheet_id,
                'hidden': True
            },
            'fields': 'hidden'
            }
        }

        requests.append(request)

        # Add the request to the batch update request
        batch_update_request = {
            'requests': requests
        }

        # Execute the batch update request
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()
        logging.info('Batch update complete')

        return ss_copy_id, score_data
    except Exception:
        logging.error(f'Error in create_sat_score_report: {Exception}')
        raise


def send_sat_pdf_report(spreadsheet_id, score_data):
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
        url_params = '&size=letter&portrait=true&fitw=true&fzr=false&top_margin=0.25&bottom_margin=0.25&left_margin=0.25&right_margin=0.25&printnotes=false&sheetnames=false&printtitle=false&pagenumbers=false'

        # Create full URL
        full_url = url_base + url_ext + url_params

        # Fetch the PDF
        response = requests.get(full_url, headers={
            'Authorization': f'Bearer {creds.token}'
        })

        # Handle response
        if response.status_code == 200:
            pdf_name = f"SAT Score Analysis for {score_data['student_name']} - {score_data['date']} - {score_data['test_display_name']}.pdf"
            file_path = f'app/private/sat/reports/{pdf_name}'

            # Save the PDF content to a file
            with open(file_path, 'wb') as f:
                f.write(response.content)

            # Create PDF in Drive
            file_metadata = {
                'name': pdf_name,
                'parents': [SAT_REPORT_FOLDER_ID],
                'mimeType': 'application/pdf'
            }

            media = MediaFileUpload(file_path, mimetype='application/pdf')

            file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            # file_id = file.get('id')
            # Read the PDF file as a blob
            with open(file_path, 'rb') as f:
                blob = f.read()

            base64_blob = base64.b64encode(blob).decode('utf-8')

            # Send email with PDF attachment
            send_score_report_email(score_data, base64_blob)
            logging.info(f"PDF report sent to {score_data['email']}")
        else:
            logging.error(f'Failed to fetch PDF: {response.content}')
    except Exception:
        logging.error(f'Error in send_sat_pdf_report: {Exception}')
        raise


def sat_answers_to_student_ss(score_data):
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

        # Process score data
        if score_data['is_rw_hard']:
            rw_difficulty = 3
        else:
            rw_difficulty = 2
        if score_data['is_m_hard']:
            m_difficulty = 3
        else:
            m_difficulty = 2

        # After setting test code and difficulty, get values from the answer sheet
        student_answer_sheet_range = f'{score_data["test_code"].upper()}!A1:L57'  # Adjust range as needed
        student_answer_data = service.spreadsheets().values().get(spreadsheetId=score_data['student_ss_id'], range=student_answer_sheet_range).execute()
        student_answer_values = student_answer_data.get('values', [])

        completed_subjects = []
        if score_data['rw_questions_answered'] >= 5:
            completed_subjects.append('rw_modules')
        if score_data['m_questions_answered'] >= 5:
            completed_subjects.append('m_modules')

        # Reset batch requests
        x = 0
        requests = []
        mod_answers = []
        for sub in completed_subjects:
            for mod in range(1, 3):
                section = []
                for n in range(1, total_questions[sub]['questions'] + 1):
                    # Update the answer sheet with the response
                    row_idx = n + total_questions[sub]['prepend_rows'] - 1
                    if sub == 'rw_modules':
                        col_idx = (mod - 1) * 4 * (rw_difficulty - 1) + 2
                    elif sub == 'm_modules':
                        col_idx = (mod - 1) * 4 * (m_difficulty - 1) + 2

                    # Needed str(mod) and str(n) with celery worker
                    number = score_data['answers'][sub][str(mod)][str(n)]
                    # if number['is_correct'] and number['student_answer'] != '-':
                    #     student_answer = student_answer_values[row_idx][col_idx + 1]
                    # else:
                    # Answers are not modified based on answer key
                    student_answer = number['student_answer']

                    section.append(student_answer)
                mod_answers.append(section)
                request = {
                    'updateCells': {
                        'range': {
                            'sheetId': student_answer_sheet_id,
                            'startRowIndex': total_questions[sub]['prepend_rows'],
                            'endRowIndex': total_questions[sub]['prepend_rows'] + total_questions[sub]['questions'],
                            'startColumnIndex': col_idx,
                            'endColumnIndex': col_idx + 1
                        },
                        'rows': [
                            {
                                'values': [
                                    {
                                        'userEnteredValue': {
                                            'stringValue': str(mod_answers[x][row])
                                        }
                                    }
                                ]
                            }
                            for row in range(total_questions[sub]['questions'])
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
                requests.append(request)

                # Add the request to the batch update request
                # batch_update_request = {
                #     'requests': requests
                # }

                x += 1


        # Set RW and Math scores
        for sub in [['rw_score', 6], ['m_score', 8]]:
            if (sub[0] == 'rw_score' and 'rw_modules' in completed_subjects) or (sub[0] == 'm_score' and 'm_modules' in completed_subjects):
                request = {
                    'updateCells': {
                    'range': {
                        'sheetId': student_answer_sheet_id,
                        'startRowIndex': 0,
                        'endRowIndex': 1,
                        'startColumnIndex': sub[1],
                        'endColumnIndex': sub[1] + 1
                    },
                    'rows': [
                        {
                        'values': [
                            {
                            'userEnteredValue': {
                                'numberValue': score_data[sub[0]]
                            }
                            }
                        ]
                        }
                    ],
                    'fields': 'userEnteredValue'
                }
            }
            requests.append(request)


        # If RW completed, set RW completion date
        if 'rw_modules' in completed_subjects:
            request = {
                'updateCells': {
                    'range': {
                        'sheetId': student_answer_sheet_id,
                        'startRowIndex': 1,
                        'endRowIndex': 2,
                        'startColumnIndex': 2,
                        'endColumnIndex': 4
                    },
                    'rows': [
                        {
                            'values': [
                                {
                                    'userEnteredValue': {
                                        'stringValue': 'Completed on:'
                                    }
                                },
                                {
                                    'userEnteredValue': {
                                        'stringValue': score_data['date']
                                    }
                                }
                            ]
                        }
                    ],
                    'fields': 'userEnteredValue'
                }
            }
            requests.append(request)


        # If Math completed, set Math completion date
        if 'm_modules' in completed_subjects:
            request = {
                'updateCells': {
                    'range': {
                        'sheetId': student_answer_sheet_id,
                        'startRowIndex': 32,
                        'endRowIndex': 33,
                        'startColumnIndex': 2,
                        'endColumnIndex': 4
                    },
                    'rows': [
                        {
                            'values': [
                                {
                                    'userEnteredValue': {
                                        'stringValue': 'Completed on:'
                                    }
                                },
                                {
                                    'userEnteredValue': {
                                        'stringValue': score_data['date']
                                    }
                                }
                            ]
                        }
                    ],
                    'fields': 'userEnteredValue'
                }
            }
            requests.append(request)

        batch_update_request = {'requests': requests}
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=score_data['student_ss_id'],
            body=batch_update_request
        ).execute()

        logging.info('Student spreadsheet updated')

        return score_data

    except Exception:
        logging.error(f'Error in sat_answers_to_student_ss: {Exception}')
        raise


def create_custom_sat_spreadsheet(organization):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

    # Step 1: Copy the default template
    file_copy = drive_service.files().copy(
        fileId=get_org_sheet_id(),
        body={
            'parents': [get_org_folder_id()],
            'name': f'{organization.name} SAT Template'}
    ).execute()
    ss_copy_id = file_copy.get('id')

    return ss_copy_id


def style_custom_sat_spreadsheet(organization_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    ss_copy_id = organization_data['sat_ss_id']
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    ss_copy = service.spreadsheets().get(spreadsheetId=ss_copy_id).execute()
    sheets = ss_copy.get('sheets', [])
    logging.info(f'ss_copy_id: https://docs.google.com/spreadsheets/d/{ss_copy_id} (copied from {get_sheet_id()})')

    answer_sheet_id = None
    analysis_sheet_id = None
    for sheet in sheets:
        if sheet['properties']['title'] == 'Answers':
            answer_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Test analysis':
            analysis_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Data':
            data_sheet_id = sheet['properties']['sheetId']

    rgb_color1 = hex_to_rgb(organization_data['color1'])
    rgb_color2 = hex_to_rgb(organization_data['color2'])
    rgb_color3 = hex_to_rgb(organization_data['color3'])
    rgb_font_color = hex_to_rgb(organization_data['font_color'])

    if is_dark_color(rgb_color1):
        rgb_text1 = (255, 255, 255)
    else:
        rgb_text1 = rgb_font_color

    requests = []

    # Set text color and font family for B1:L77 in Answers sheet
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": answer_sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 77,
                "startColumnIndex": 1,
                "endColumnIndex": 12
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "foregroundColor": {
                            "red": rgb_font_color[0] / 255,
                            "green": rgb_font_color[1] / 255,
                            "blue": rgb_font_color[2] / 255
                        },
                        "fontFamily": "Montserrat"
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat(foregroundColor, fontFamily)"
        }
    })

    # Set text color and font family for A1:K84 in Analysis sheet
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": analysis_sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 84,
                "startColumnIndex": 1,
                "endColumnIndex": 11
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "foregroundColor": {
                            "red": rgb_font_color[0] / 255,
                            "green": rgb_font_color[1] / 255,
                            "blue": rgb_font_color[2] / 255
                        },
                        "fontFamily": "Montserrat"
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat(foregroundColor, fontFamily)"
        }
    })

    # Set header background colors and text format for A1:K8 in Analysis sheet
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 8,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": rgb_text1[0] / 255,
                                "green": rgb_text1[1] / 255,
                                "blue": rgb_text1[2] / 255
                            },
                            "fontSize": 13,
                            "bold": True,
                            "fontFamily": "Montserrat"
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor, textFormat)"
            }
        }
    )

    # Set text color of pivot table filter cell (B7) to rgb_color1
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": analysis_sheet_id,
                "startRowIndex": 6,  # B7
                "endRowIndex": 7,
                "startColumnIndex": 1,
                "endColumnIndex": 2
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "foregroundColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat.foregroundColor"
        }
    })

    # Set total score label font size
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": analysis_sheet_id,
                "startRowIndex": 1,  # E2
                "endRowIndex": 2,
                "startColumnIndex": 4,
                "endColumnIndex": 5
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "fontSize": 14
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat.fontSize"
        }
    })

    # Set total score font size
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": analysis_sheet_id,
                "startRowIndex": 2,  # E3 (row index starts at 0)
                "endRowIndex": 3,
                "startColumnIndex": 4,  # E (column index starts at 0)
                "endColumnIndex": 5
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "fontSize": 30
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat.fontSize"
        }
    })

    # Set analysis table header font size
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": analysis_sheet_id,
                "startRowIndex": 6,
                "endRowIndex": 8,
                "startColumnIndex": 0,
                "endColumnIndex": 11
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {
                        "fontSize": 10
                    }
                }
            },
            "fields": "userEnteredFormat.textFormat.fontSize"
        }
    })

    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 8,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            }
        }
    )

    # Set footer background colors and text format for A82:K84 in Analysis sheet
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 81,
                    "endRowIndex": 84,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": rgb_text1[0] / 255,
                                "green": rgb_text1[1] / 255,
                                "blue": rgb_text1[2] / 255
                            },
                            "fontSize": 10,
                            "bold": True,
                            "fontFamily": "Montserrat"
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor, textFormat)"
            }
        }
    )

    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 81,            # A82:K84
                    "endRowIndex": 84,
                    "startColumnIndex": 0,
                    "endColumnIndex": 11
                },
                "top": {
                    "style": "SOLID",
                    "width": 2,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            }
        }
    )

    # Set header background colors, text format, and borders for B2:L4 in answer sheet
    requests.append(
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
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": rgb_text1[0] / 255,
                                "green": rgb_text1[1] / 255,
                                "blue": rgb_text1[2] / 255
                            },
                            "fontSize": 10,
                            "bold": True,
                            "fontFamily": "Montserrat"
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor, textFormat)"
            }
        }
    )
    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 4,
                    "startColumnIndex": 1,
                    "endColumnIndex": 12
                },
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            }
        }
    )

    # Set header background colors, text format, and borders for B33:L35 in answer sheet
    requests.append(
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
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": rgb_text1[0] / 255,
                                "green": rgb_text1[1] / 255,
                                "blue": rgb_text1[2] / 255
                            },
                            "fontSize": 10,
                            "bold": True,
                            "fontFamily": "Montserrat"
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor, userEnteredFormat.textFormat"
            }
        }
    )
    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 32,
                    "endRowIndex": 35,
                    "startColumnIndex": 1,
                    "endColumnIndex": 12
                },
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            }
        }
    )

    # Set footer background colors, text format, and borders for A75:M77 in answer sheet
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 74,
                    "endRowIndex": 77,
                    "startColumnIndex": 0,
                    "endColumnIndex": 13
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": rgb_text1[0] / 255,
                                "green": rgb_text1[1] / 255,
                                "blue": rgb_text1[2] / 255
                            },
                            "fontSize": 10,
                            "bold": True,
                            "fontFamily": "Montserrat"
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor, textFormat)"
            }
        }
    )
    requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": answer_sheet_id,
                    "startRowIndex": 74,
                    "endRowIndex": 77,
                    "startColumnIndex": 0,
                    "endColumnIndex": 13
                },
                "top": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "bottom": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "left": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerHorizontal": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                },
                "innerVertical": {
                    "style": "SOLID",
                    "width": 1,
                    "colorStyle": {
                        "rgbColor": {
                            "red": rgb_color1[0] / 255,
                            "green": rgb_color1[1] / 255,
                            "blue": rgb_color1[2] / 255
                        }
                    }
                }
            }
        }
    )

    # Execute batch update
    service.spreadsheets().batchUpdate(
        spreadsheetId=ss_copy_id,
        body={"requests": requests}
    ).execute()

    # Update conditional formatting rules
    # Fetch current conditional formatting rules
    current_rules = service.spreadsheets().get(
        spreadsheetId=ss_copy_id,
        fields='sheets.conditionalFormats'
    ).execute()

    analysis_conditional_formats = []
    analysis_conditional_indices = []

    for sheet in current_rules.get('sheets', []):
        cond_formats = sheet.get('conditionalFormats')
        if cond_formats:
            for idx, rule in enumerate(cond_formats):
                if rule.get('ranges', [{}])[0].get('sheetId') == analysis_sheet_id:
                    analysis_conditional_formats.append(rule)
                    analysis_conditional_indices.append(idx)
            break

    updated_requests = []

    # Filter only boolean rules
    boolean_rules = [
        (idx, rule) for idx, rule in zip(analysis_conditional_indices, analysis_conditional_formats)
        if 'booleanRule' in rule
    ]

    # Iterate over the boolean rules and update based on their index
    for boolean_idx, (rule_idx, rule) in enumerate(boolean_rules):
        if 'booleanRule' in rule:
            # Determine the new background color and text color based on the rule's index
            if boolean_idx == 0:  # First boolean rule
                new_bg_color = {
                    'red': rgb_color1[0] / 255,
                    'green': rgb_color1[1] / 255,
                    'blue': rgb_color1[2] / 255
                }
                text_rgb = (255, 255, 255) if is_dark_color(rgb_color1) else rgb_font_color
            elif boolean_idx == 1:  # Second boolean rule
                new_bg_color = {
                    'red': rgb_color2[0] / 255,
                    'green': rgb_color2[1] / 255,
                    'blue': rgb_color2[2] / 255
                }
                text_rgb = (255, 255, 255) if is_dark_color(rgb_color2) else rgb_font_color
            elif boolean_idx == 2:  # Third boolean rule
                new_bg_color = {
                    'red': rgb_color3[0] / 255,
                    'green': rgb_color3[1] / 255,
                    'blue': rgb_color3[2] / 255
                }
                text_rgb = (255, 255, 255) if is_dark_color(rgb_color3) else rgb_font_color
            else:
                # Skip updating rules beyond the first three
                continue

            # Update the rule's background color
            rule['booleanRule']['format']['backgroundColor'] = new_bg_color
            rule['booleanRule']['format']['backgroundColorStyle'] = {
                'rgbColor': new_bg_color
            }
            # Preserve original font weight (bold) if present
            original_text_format = rule['booleanRule']['format'].get('textFormat', {})
            is_bold = original_text_format.get('bold', False)
            # Update the rule's text color and keep font weight
            rule['booleanRule']['format']['textFormat'] = {
                'foregroundColor': {
                    'red': text_rgb[0] / 255,
                    'green': text_rgb[1] / 255,
                    'blue': text_rgb[2] / 255
                },
                'bold': is_bold
            }

            # Add the update request
            updated_requests.append({
                "updateConditionalFormatRule": {
                    "sheetId": analysis_sheet_id,
                    "index": rule_idx,
                    "rule": rule
                }
            })

    # Execute the batch update if there are any updates
    if updated_requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body={"requests": updated_requests}
        ).execute()

    return ss_copy_id


def update_sat_org_logo(organization_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    sat_ss_id = organization_data['sat_ss_id']
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    ss_copy = service.spreadsheets().get(spreadsheetId=sat_ss_id).execute()
    sheets = ss_copy.get('sheets', [])
    logging.info(f'ss_copy_id: https://docs.google.com/spreadsheets/d/{sat_ss_id} (copied from {get_sheet_id()})')

    answer_sheet_id = None
    analysis_sheet_id = None
    for sheet in sheets:
        if sheet['properties']['title'] == 'Answers':
            answer_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Test analysis':
            analysis_sheet_id = sheet['properties']['sheetId']

    requests = []

    # Step 4: Add the logo to cell B2
    if organization_data['logo_path']:
        # Insert image in cell B2 (row 1, column 1) of analysis sheet using the =IMAGE() formula
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2
                },
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "formulaValue": f'=IMAGE("https://www.openpathtutoring.com/static/{organization_data["logo_path"]}")'
                                }
                            }
                        ]
                    }
                ],
                "fields": "userEnteredValue"
            }
        })

    if requests:
        # Execute batch update
        service.spreadsheets().batchUpdate(
            spreadsheetId=sat_ss_id,
            body={"requests": requests}
        ).execute()


def update_sat_partner_logo(organization_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    sat_ss_id = organization_data['sat_ss_id']
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    ss_copy = service.spreadsheets().get(spreadsheetId=sat_ss_id).execute()
    sheets = ss_copy.get('sheets', [])
    logging.info(f'ss_copy_id: https://docs.google.com/spreadsheets/d/{sat_ss_id} (copied from {get_sheet_id()})')

    answer_sheet_id = None
    analysis_sheet_id = None
    for sheet in sheets:
        if sheet['properties']['title'] == 'Answers':
            answer_sheet_id = sheet['properties']['sheetId']
        elif sheet['properties']['title'] == 'Test analysis':
            analysis_sheet_id = sheet['properties']['sheetId']

    requests = []

    # Add partner logo to cell I82
    if organization_data['partner_logo_path']:
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": analysis_sheet_id,
                    "startRowIndex": 81,
                    "endRowIndex": 82,
                    "startColumnIndex": 8,
                    "endColumnIndex": 9
                },
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "formulaValue": f'=IMAGE("https://www.openpathtutoring.com/static/{organization_data["partner_logo_path"]}")'
                                }
                            }
                        ]
                    }
                ],
                "fields": "userEnteredValue"
            }
        })

    if requests:
        # Execute batch update
        service.spreadsheets().batchUpdate(
            spreadsheetId=sat_ss_id,
            body={"requests": requests}
        ).execute()