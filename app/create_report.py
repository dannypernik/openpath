import os
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
logging.basicConfig(filename=info_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

pp = pprint.PrettyPrinter(indent=2, width=100)

# Constants
SHEET_ID = '104w631_Qo1667eBO_FdAOYHf4xqnpk7BgQOD_rdm37o'  # Your spreadsheet ID
SCORE_REPORT_FOLDER_ID = '15tJsdeOx_HucjIb6koTaafncTj-e6FO6'  # Your score report folder ID
SERVICE_ACCOUNT_JSON = 'service_account_key2.json'  # Path to your service account JSON file

# Function to create SAT score report
def create_sat_score_report(score_data):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/script.external_request']
    )

    try:
        # Create the Sheets API service
        service = build('sheets', 'v4', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)

        # Create a copy of the file
        ss_copy = drive_service.files().copy(fileId=SHEET_ID, body={'parents': [SCORE_REPORT_FOLDER_ID]}).execute()
        ss_copy_id = ss_copy.get('id')

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
            elif sheet['properties']['title'] == 'Practice test data':
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
                                            'sortOrder': 'DESCENDING'
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
        batch_update_request = {
            'requests': requests
        }

        # Process score data
        total_questions = {
            'rw_modules': {'questions': 27, 'prepend_rows': 4},
            'm_modules': {'questions': 22, 'prepend_rows': 35}
        }

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
            batch_update_request = {
                'requests': requests
            }

        # Execute first batch update request
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()

        # After setting test code and difficulty, get values from the answer sheet
        answer_sheet_range = f'Answers!C1:AM57'  # Adjust range as needed
        answer_data = service.spreadsheets().values().get(spreadsheetId=ss_copy_id, range=answer_sheet_range).execute()
        answer_values = answer_data.get('values', [])

        # Reset batch requests
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
                batch_update_request = {
                    'requests': requests
                }

                x += 1


        # Set RW and Math scores
        for sub in [['rw_score', 5], ['m_score', 8]]:
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

            # Add the request to the batch update request
            batch_update_request = {
                'requests': requests
            }

        request = {
            # NTPA design
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
                                'userEnteredValue': {
                                    'stringValue': 'Score Analysis for ' + score_data['student_name']
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
            #         'startColumnIndex': 2,
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
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=ss_copy_id,
            body=batch_update_request
        ).execute()


        if not score_data['has_omits']:
            requests = []
            requests.append({
                'updateDimensionProperties': {
                    "range": {
                        "sheetId": analysis_sheet_id,
                        "dimension": 'COLUMNS',
                        "startIndex": 7,
                        "endIndex": 8
                    },
                    "properties": {
                        "hiddenByUser": True,
                    },
                    "fields": 'hiddenByUser',
                }
            })

            requests.append({
                'updateDimensionProperties': {
                    "range": {
                        "sheetId": analysis_sheet_id,
                        "dimension": 'ROWS',
                        "startIndex": 70,
                        "endIndex": 76
                    },
                    "properties": {
                        "hiddenByUser": True,
                    },
                    "fields": 'hiddenByUser',
                }
            })

            batch_update_request = {'requests': requests}
            response = service.spreadsheets().batchUpdate(
                spreadsheetId=ss_copy_id,
                body=batch_update_request
            ).execute()

        print(ss_copy_id)


        # # Set difficulty values
        # service.spreadsheets().values().update(
        #     spreadsheetId=ss_copy_id,
        #     range=f'{answer_sheet_id}!M5',
        #     valueInputOption='RAW',
        #     body={'values': [[3 if score_data['is_rw_hard'] else 2]]}
        # ).execute()

        # service.spreadsheets().values().update(
        #     spreadsheetId=ss_copy_id,
        #     range=f'{answer_sheet_id}!M36',
        #     valueInputOption='RAW',
        #     body={'values': [[3 if score_data['is_m_hard'] else 2]]}
        # ).execute()

        # # Set additional info
        # test_name = score_data['test_code'].upper()
        # test_display_name = f'{test_name[:test_name.index('SAT') + 3]} {test_name[test_name.index('SAT') + 3:]}'
        # service.spreadsheets().values().update(
        #     spreadsheetId=ss_copy_id,
        #     range=f'{answer_sheet_id}!B1',
        #     valueInputOption='RAW',
        #     body={'values': [[f'Bluebook Practice {test_display_name}']]}
        # ).execute()

        # # Update analysis sheet
        # analysis_range = f'{analysis_sheet_id}!C5'
        # service.spreadsheets().values().update(
        #     spreadsheetId=ss_copy_id,
        #     range=analysis_range,
        #     valueInputOption='RAW',
        #     body={'values': [[f'SAT Score Analysis for {score_data['student_name']}']]}
        # ).execute()

        # # Update pivot table
        # # Define the spreadsheet ID and the sheet ID where the pivot table is located
        # spreadsheet_id = ss_copy_id
        # pivot_sheet_name = 'Test analysis'  # Replace with your sheet ID containing the pivot table

        # # Define the field to filter (index of the column in your data)
        # filter_criteria = {
        #     'visibleValues': [test_name],  # Add the values to filter for
        # }

        # # Define the request to update the pivot table
        # # Get the sheet ID of the sheet named 'Test analysis'
        # sheets = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        # sheet_id = None
        # for sheet in sheets['sheets']:
        #     if sheet['properties']['title'] == 'Test analysis':
        #         sheet_id = sheet['properties']['sheetId']
        #     break

        # if sheet_id is None:
        #     print('Sheet 'Test analysis' not found')
        #     return

        # # Define the request to update the pivot table
        # request = {
        #     'updateCells': {
        #     'range': {
        #         'sheetId': sheet_id,
        #         'startRowIndex': 6,  # Assuming the pivot table starts at row 0
        #         'startColumnIndex': 1,  # Assuming the pivot table starts at column 0
        #     },
        #     'rows': [
        #         {
        #         'values': [
        #             {
        #             'pivotTable': {
        #                 'source': {
        #                 'sheetId': sheet_id,
        #                 'startRowIndex': 1,  # Data range starts from row 1
        #                 'startColumnIndex': 0,  # Data range starts from column 0
        #                 'endRowIndex': 100,  # Adjust according to your data
        #                 'endColumnIndex': 10  # Adjust according to your data
        #                 },
        #                 'criteria': {  # Add your filter criteria here
        #                 '1': {  # Column index 1 is being filtered
        #                     'visibleValues': [testName]
        #                 }
        #                 }
        #             }
        #             }
        #         ]
        #         }
        #     ],
        #     'fields': 'pivotTable.criteria'  # Specify that you are updating the filter criteria
        #     }
        # }

        # # Make the request to update the pivot table
        # batch_update_request = {
        #     'requests': [request]
        # }

        # response = service.spreadsheets().batchUpdate(
        #     spreadsheetId=spreadsheet_id,
        #     body=batch_update_request
        # ).execute()

        # print(response)

        # # Generate and send the PDF score report
        # send_pdf_score_report(ss_copy_id, score_data)

        # print(f'{test_name} Score report created for {score_data['student_name']} ({ss_copy_id})')

    except HttpError as error:
        print(f'An error occurred in create_sat_score_report: {error}')
        send_fail_mail(score_data, 'score_data', error)
        raise

    return ss_copy_id

# Function to send PDF score report
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
            pdf_name = f"Score Analysis for {score_data['student_name']} - {score_data['date']} - {score_data['test_display_name']}.pdf"
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
            print(f"PDF report sent to {score_data['email']}")
        else:
            print(f'Failed to fetch PDF: {response.content}')

    except HttpError as error:
        print(f'An error occurred: {error}')
        send_fail_mail(score_data, 'score_data', error)
        raise


def delete_spreadsheet(spreadsheet_id):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,  # Path to your service account JSON file
        scopes=['https://www.googleapis.com/auth/drive']
    )

    try:
        # Create the Drive API service
        drive_service = build('drive', 'v3', credentials=creds)

        # Delete the spreadsheet
        drive_service.files().delete(fileId=spreadsheet_id).execute()
        print(f'Spreadsheet {spreadsheet_id} deleted')

    except HttpError as error:
        print(f'An error occurred: {error}')
        send_fail_mail(spreadsheet_id, 'delete_spreadsheet(id)', error)
        raise


# def create_and_send_sat_report(score_data):
#     try:
#         spreadsheet_id = create_sat_score_report(score_data)
#         send_pdf_score_report(spreadsheet_id, score_data)
#         delete_spreadsheet(spreadsheet_id)
#     except Exception as e:
#         print(f'An error occurred in create_and_send_sat_report: {e}')
#         send_fail_mail(score_data, 'create_and_send_sat_report(score_data)', e)
#         raise