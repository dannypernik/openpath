import os
from app import app
from app.email import send_score_report_email
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
import requests
import pprint
import base64
import logging

info_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/info.log')
logging.basicConfig(filename=info_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
        logging.FileHandler('logs/info.log'),
        logging.StreamHandler()
    ])

pp = pprint.PrettyPrinter(indent=2, width=100)

# Constants
SHEET_ID = app.config['SCORE_REPORT_SS_ID'] # Your spreadsheet ID
SCORE_REPORT_FOLDER_ID = '15tJsdeOx_HucjIb6koTaafncTj-e6FO6'  # Your score report folder ID
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


def create_sat_score_report(score_data):
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

        # Create a copy of the file
        ss_copy = drive_service.files().copy(fileId=SHEET_ID, body={'parents': [SCORE_REPORT_FOLDER_ID]}).execute()
        logging.info(SHEET_ID)
        ss_copy_id = ss_copy.get('id')
        logging.info(f'Created copy of {SHEET_ID} as {ss_copy_id}')

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
                    'startColumnIndex': 1,
                    'endColumnIndex': 4
                },
                'rows': [
                    {
                        'values': [
                            {
                                'userEnteredValue': {
                                    'stringValue': 'Bluebook Practice ' + score_data['test_display_name']
                                }
                            },
                            {
                                'userEnteredValue': {
                                    'stringValue': ''
                                }
                            },
                            {
                                'userEnteredValue': {
                                    'stringValue': score_data['test_code'].upper()
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
                    'startRowIndex': 4,
                    'endRowIndex': 5,
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
                                                'userEnteredValue': '=or(Subject=A11,Subject=A12)'
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

        # Add the request to the batch update request
        # batch_update_request = {
        #     'requests': requests
        # }

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
                    if number['is_correct'] and number['student_answer'] != '-':
                        student_answer = answer_values[row_idx][col_idx + 1]
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

                # Add the request to the batch update request
                # batch_update_request = {
                #     'requests': requests
                # }

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

        # # Add the request to the batch update request
        # batch_update_request = {
        #     'requests': requests
        # }

        request = {
            # NTPA design
            'updateCells': {
                'range': {
                    'sheetId': analysis_sheet_id,
                    'startRowIndex': 1,
                    'endRowIndex': 4,
                    'startColumnIndex': 1,
                    'endColumnIndex': 4
                },
                'rows': [
                    {
                        'values': [
                            {
                                'userEnteredValue': {
                                    'stringValue': 'SAT Score Analysis for ' + score_data['student_name']
                                }
                            }
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
            # OPT design
            # 'updateCells': {
            #     'range': {
            #         'sheetId': analysis_sheet_id,
            #         'startRowIndex': 4,
            #         'endRowIndex': 5,
            #         'startC3lumnIndex': 2,
            #         'endColumnIndex': 3
            #     },
            #     'rows': [
            #         {
            #             'values': [
            #                 {
            #                     'userEnteredValue': {
            #                         'stringValue': 'SAT Score Analysis for ' + score_data['student_name']
            #                     }
            #                 }
            #             ]
            #         }
            #     ],
            #     'fields': 'userEnteredValue'
            # }
        }
        requests.append(request)

        # Add the request to the batch update request
        batch_update_request = {
            'requests': requests
        }

        # Execute the batch update request
        logging.info('Starting batch update')
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()
        logging.info('Batch update complete')

        # Hide 'Data' sheet
        requests.append({
            'updateSheetProperties': {
            'properties': {
                'sheetId': data_sheet_id,
                'hidden': True
            },
            'fields': 'hidden'
            }
        })

        batch_update_request = {'requests': requests}
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()

        logging.info('ss_copy_id: ' + ss_copy_id)
        print('ss_copy_id: ' + ss_copy_id)
        # logging.info(score_data)

        return ss_copy_id
    except Exception:
        logging.error(f'Error in create_sat_score_report: {Exception}')
        raise


def send_pdf_score_report(spreadsheet_id, score_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/drive']
    )
    creds.refresh(Request())

    try:
        # Create the Drive API service
        drive_service = build('drive', 'v3', credentials=creds)

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
            file_path = f'app/static/files/scores/pdf/{pdf_name}'

            # Save the PDF content to a file
            with open(file_path, 'wb') as f:
                f.write(response.content)

            # Create PDF in Drive
            file_metadata = {
                'name': pdf_name,
                'parents': [SCORE_REPORT_FOLDER_ID],
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
            message = f"Please find the score report for {score_data['test_code'].upper()} attached."
            send_score_report_email(score_data, base64_blob)
            logging.info(f"PDF report sent to {score_data['email']}")
            # drive_service.files().update(fileId=spreadsheet_id, body={'trashed': True}).execute()
            # drive_service.files().update(fileId=file.get('id'), body={'trashed': True}).execute()
            # logging.info(f'Spreadsheet {spreadsheet_id} and PDF moved to trash')

        else:
            logging.error(f'Failed to fetch PDF: {response.content}')
    except Exception:
        logging.error(f'Error in send_pdf_score_report: {Exception}')
        raise


def send_answers_to_student_ss(score_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/script.external_request']
    )

    try:
        student_ss_id = score_data['student_ss_id']

        # Create the Sheets API service
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)

        ss = service.spreadsheets().get(spreadsheetId=student_ss_id).execute()
        student_sheets = ss.get('sheets', [])
        # pp.pprint(ss)

        student_answer_sheet_id = None
        for sheet in student_sheets:
            if sheet['properties']['title'] == score_data['test_code'].upper():
                student_answer_sheet_id = sheet['properties']['sheetId']
                break
        logging.info('student_answer_sheet_id: ' + str(student_answer_sheet_id))

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
        student_answer_data = service.spreadsheets().values().get(spreadsheetId=student_ss_id, range=student_answer_sheet_range).execute()
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

        logging.info('Starting student sheet batch update')
        batch_update_request = {'requests': requests}
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=student_ss_id,
            body=batch_update_request
        ).execute()

        logging.info('student_ss_id: ' + student_ss_id)
    except Exception:
        logging.error(f'Error in send_answers_to_student_ss: {Exception}')
        raise