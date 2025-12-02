import os
from app import app
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
import datetime

# Constants
SOURCE_FOLDER_ID = '1rz0xXMvtklwUuvGTkqs9cuNfQyY7-8-s'
PARENT_FOLDER_ID = '1_qQNYnGPFAePo8UE5NfX72irNtZGF5kF'
SERVICE_ACCOUNT_JSON = 'service_account_key2.json'
SERVICE_ACCOUNT_EMAIL = 'score-reports@sat-score-reports.iam.gserviceaccount.com'
SAT_DATA_SS_ID = app.config['SAT_DATA_SS_ID']
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

# Authenticate and initialize services
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
sheets_service = build('sheets', 'v4', credentials=creds, cache_discovery=False)


def create_test_prep_folder(student_name, test_type='all'):
    """Create a test prep folder and copy/link files."""
    new_folder_id = create_folder(f"{student_name}", PARENT_FOLDER_ID)

    query = f"'{SOURCE_FOLDER_ID}' in parents and trashed=false"
    items = drive_service.files().list(q=query, fields='files(id, name)').execute().get('files', [])

    for item in items:
        copy_item(item['id'], item['name'], new_folder_id, test_type, student_name)

    sat_files, act_files = link_sheets(new_folder_id, student_name, test_type)

    print(f"Folder created successfully: {new_folder_id}")


def create_folder(folder_name, parent_folder_id):
    """Create a new folder in Google Drive."""
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }
    folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')

def copy_item(item_id, new_name, new_folder_id, test_type='all', student_name=None):
    """Copy a file or folder in Google Drive."""
    item = drive_service.files().get(fileId=item_id, fields='id, name, mimeType, shortcutDetails').execute()
    mime_type = item['mimeType']

    if mime_type == 'application/vnd.google-apps.folder':
        if new_name == 'Student':
            test_type_label = test_type.upper() if test_type != 'all' else 'Test'
            new_name = f'{student_name} {test_type_label} prep'
        # If the item is a folder, create a new folder and copy its contents
        new_folder_id = create_folder(new_name, new_folder_id)
        query = f"'{item_id}' in parents and trashed=false"
        items = drive_service.files().list(q=query, fields='files(id, name)').execute().get('files', [])
        for sub_item in items:
            copy_item(sub_item['id'], sub_item['name'], new_folder_id, test_type, student_name)
        return new_folder_id
    elif mime_type == 'application/vnd.google-apps.shortcut':
        # Copy the shortcut itself
        shortcut_metadata = {
            'name': new_name,
            'mimeType': 'application/vnd.google-apps.shortcut',
            'parents': [new_folder_id],
            'shortcutDetails': {
                'targetId': item['shortcutDetails']['targetId']
            }
        }
        copied_shortcut = drive_service.files().create(body=shortcut_metadata, fields='id').execute()
        return copied_shortcut.get('id')
    else:
        # If the item is a file, rename and copy it
        if student_name and '- template' in new_name.lower():
            base = new_name.split('-')[0].strip()
            new_name = f"{base} - {student_name}"

        file_metadata = {
            'name': new_name,
            'parents': [new_folder_id]
        }
        copied_file = drive_service.files().copy(fileId=item_id, body=file_metadata).execute()

        # Trash files that don't match the test type
        if test_type and test_type.lower() in ['sat', 'act']:
            if test_type.lower() == 'sat' and 'act' in new_name.lower():
                drive_service.files().update(fileId=copied_file['id'], body={'trashed': True}).execute()
            elif test_type.lower() == 'act' and 'sat' in new_name.lower():
                drive_service.files().update(fileId=copied_file['id'], body={'trashed': True}).execute()

        return copied_file.get('id')


def update_admin_spreadsheet(admin_ss_id, student_ss_id, student_name, test_type):
    """Update spreadsheet data."""
    drive_service.permissions().create(
        fileId=admin_ss_id,
        body={'type': 'user', 'role': 'writer', 'emailAddress': SERVICE_ACCOUNT_EMAIL}
    ).execute()

    if admin_ss_id:
        # Get the sheet ID of the sheet named 'Student responses'
        sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute()
        sheets = sheet_metadata.get('sheets', [])
        responses_sheet_id = None
        for sheet in sheets:
            sheet_name = sheet.get('properties', {}).get('title')
            if sheet_name == 'Student responses':
                responses_sheet_id = sheet.get('properties', {}).get('sheetId')
            elif sheet_name == 'Rev sheet backend':
                rev_sheet_id = sheet.get('properties', {}).get('sheetId')

        if responses_sheet_id is None:
            raise ValueError("Sheet named 'Student responses' not found.")

        requests = [
            {
                'updateCells': {
                    'range': {
                    'sheetId': responses_sheet_id,
                    'startRowIndex': 0,
                    'endRowIndex': 1,
                    'startColumnIndex': 1,
                    'endColumnIndex': 2
                    },
                    'rows': [
                    {
                        'values': [
                            {'userEnteredValue': {'stringValue': student_ss_id}}
                        ]
                    }
                    ],
                    'fields': 'userEnteredValue'
                }
            }
        ]

        if test_type.lower() == 'sat':
            requests.append(
                {
                    'updateCells': {
                        'range': {
                            'sheetId': rev_sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': 2,
                            'startColumnIndex': 10,
                            'endColumnIndex': 11
                        },
                        'rows': [
                            {
                                'values': [
                                    {'userEnteredValue': {'stringValue': student_name}}
                                ]
                            }
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
            )
        elif test_type.lower() == 'act':
            requests.append(
                {
                    'updateCells': {
                        'range': {
                            'sheetId': responses_sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1,
                            'startColumnIndex': 6,
                            'endColumnIndex': 7
                        },
                        'rows': [
                            {
                                'values': [
                                    {'userEnteredValue': {'stringValue': student_name}}
                                ]
                            }
                        ],
                        'fields': 'userEnteredValue'
                    }
                }
            )
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=admin_ss_id,
            body={'requests': requests}
        ).execute()

def link_sheets(folder_id, student_name, test_type='all'):
    """Link sheets and update data."""

    files = get_all_files(folder_id)

    sat_files = {}
    act_files = {}

    for file in files:
        file_name = file['name'].lower()
        file_id = file['id']

        if 'student answer sheet' in file_name:
            if 'sat' in file_name and test_type != 'act':
                sat_files['student'] = file_id
                add_editor(drive_service, sat_files.get('student'), SERVICE_ACCOUNT_EMAIL)
                make_public_view(drive_service, sat_files.get('student'))
                update_sat_student_spreadsheet(sheets_service, sat_files, student_name)
            elif 'act' in file_name and test_type != 'sat':
                act_files['student'] = file_id
                add_editor(drive_service, act_files.get('student'), SERVICE_ACCOUNT_EMAIL)
                make_public_view(drive_service, act_files.get('student'))
        elif 'answer analysis' in file_name:
            if 'sat' in file_name and test_type != 'act':
                sat_files['admin'] = file_id
                add_editor(drive_service, sat_files.get('admin'), SERVICE_ACCOUNT_EMAIL)
                remove_sat_protections(sheets_service, sat_files.get('admin'))
                add_student_sheet_to_rev_data(sheets_service, sat_files.get('admin'), student_name)
            elif 'act' in file_name and test_type != 'sat':
                act_files['admin'] = file_id
                add_editor(drive_service, act_files.get('admin'), SERVICE_ACCOUNT_EMAIL)

    if 'student' in sat_files and 'admin' in sat_files:
        update_admin_spreadsheet(sat_files['admin'], sat_files['student'], student_name, 'sat')
    if 'student' in act_files and 'admin' in act_files:
        update_admin_spreadsheet(act_files['admin'], act_files['student'], student_name, 'act')

    return sat_files, act_files


# Recursively get all files in folder_id and nested subfolders
def get_all_files(folder_id):
    all_files = []
    query = f"'{folder_id}' in parents and trashed=false"
    items = drive_service.files().list(q=query, fields='files(id, name, mimeType)').execute().get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            # Recursively get files from subfolder
            all_files.extend(get_all_files(item['id']))
        else:
            all_files.append(item)

    return all_files


def add_editor(drive_service, file_id: str, editor_email: str):
    # Add editor (user)
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "writer", "emailAddress": editor_email},
            fields="id",
            sendNotificationEmail=False,
        ).execute()
    except HttpError as e:
        # permission may already exist
        logger.debug("Could not add editor %s to %s: %s", editor_email, file_id, e)


def make_public_view(drive_service, file_id: str):
    # Make file viewable by anyone
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
    except HttpError as e:
        logger.debug("Could not set anyone permission for %s: %s", file_id, e)


def remove_sat_protections(sheets_service, admin_ss_id):
    """Remove protections from SAT admin spreadsheet."""
    test_codes = get_sat_test_codes(sheets_service)
    test_codes.extend(['Reading & Writing', 'Math', 'SLT Uniques'])
    protected_sheets = []
    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute()
    sheets = sheet_metadata.get('sheets', [])
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') in test_codes:
            protected_sheets.append(sheet)
    for sheet in protected_sheets:
        for protection in sheet.get('protectedRanges', []):
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=admin_ss_id,
                body={
                    'requests': [
                        {
                            'deleteProtectedRange': {
                                'protectedRangeId': protection['protectedRangeId']
                            }
                        }
                    ]
                }
            ).execute()


def get_sat_test_codes(sheets_service):
    """Retrieve SAT test codes from the SAT data spreadsheet."""
    # Get all sheets in the spreadsheet
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=SAT_DATA_SS_ID).execute()
    sheets = spreadsheet.get('sheets', [])

    # Filter sheets that start with 'Practice test data updated' and find the alphabetically last one
    matching_sheets = [
        sheet['properties']['title']
        for sheet in sheets
        if sheet['properties']['title'].startswith('Practice test data updated')
    ]

    if not matching_sheets:
        raise ValueError("No sheet found starting with 'Practice test data updated'")

    # Sort by date extracted from the sheet name
    def extract_date(sheet_name):
        # Extract date string like "08/2025" from "Practice test data updated 08/2025"
        date_str = sheet_name.split('updated ')[-1]
        try:
            return datetime.datetime.strptime(date_str, '%m/%Y')
        except ValueError:
            # If date parsing fails, return a very old date so it appears first
            return datetime.datetime(1900, 1, 1)

    latest_sheet = max(matching_sheets, key=extract_date)

    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SAT_DATA_SS_ID,
        range=f'{latest_sheet}!A2:A'
    ).execute()

    values = result.get('values', [])
    test_codes = list(set(row[0] for row in values if row))
    print(test_codes)
    return test_codes


def update_sat_student_spreadsheet(sheets_service, sat_files, student_name):
    """Update student spreadsheet with student name."""
    # Get the sheet ID of the sheet named 'Student info'
    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=sat_files.get('student')).execute()
    sheets = sheet_metadata.get('sheets', [])
    student_info_sheet_id = None
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') == 'Question bank data':
            qb_sheet_id = sheet.get('properties', {}).get('sheetId')
            break

    if qb_sheet_id is None:
        raise ValueError("Sheet named 'Question bank data' not found.")
    # Update cell B2 with student_name
    requests = [
        {
            'updateCells': {
                'range': {
                    'sheetId': qb_sheet_id,
                    'startRowIndex': 1,
                    'endRowIndex': 2,
                    'startColumnIndex': 20,
                    'endColumnIndex': 21
                },
                'rows': [
                    {
                        'values': [
                            {'userEnteredValue': {'stringValue': student_name}}
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        },
        {
            'updateCells': {
                'range': {
                    'sheetId': qb_sheet_id,
                    'startRowIndex': 3,
                    'endRowIndex': 4,
                    'startColumnIndex': 20,
                    'endColumnIndex': 21
                },
                'rows': [
                    {
                        'values': [
                            {'userEnteredValue': {'stringValue': sat_files.get('admin')}}
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        }
    ]

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=sat_files.get('student'),
        body={'requests': requests}
    ).execute()


def add_student_sheet_to_rev_data(sheets_service, admin_ss_id, student_name):
    """Add student answer sheet link to Rev sheet backend."""
    # Get the sheet ID of the sheet named 'Rev sheet backend'
    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute()
    sheets = sheet_metadata.get('sheets', [])
    rev_sheet_id = None
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') == 'Rev sheet backend':
            rev_sheet_id = sheet.get('properties', {}).get('sheetId')
            break

    if rev_sheet_id is None:
        raise ValueError("Sheet named 'Rev sheet backend' not found.")

    # Get the value from U3
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=admin_ss_id,
        range='Rev sheet backend!U3'
    ).execute()

    rev_data_id = result.get('values', [[]])[0][0] if result.get('values') else ''

    # Copy 'Template' sheet and rename it to student_name
    template_sheet_id = None
    rev_data_metadata = sheets_service.spreadsheets().get(spreadsheetId=rev_data_id).execute()
    rev_data_sheets = rev_data_metadata.get('sheets', [])
    for sheet in rev_data_sheets:
        sheet_name = sheet.get('properties', {}).get('title')
        if sheet_name == 'Template':
            template_sheet_id = sheet.get('properties', {}).get('sheetId')
            break

    if template_sheet_id is None:
        raise ValueError("Sheet named 'Template' not found in Rev data spreadsheet.")

    # Copy the Template sheet
    copy_request = {
        'duplicateSheet': {
            'sourceSheetId': template_sheet_id,
            'newSheetName': student_name
        }
    }

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=rev_data_id,
        body={'requests': [copy_request]}
    ).execute()
