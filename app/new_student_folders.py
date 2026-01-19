import os
import logging
from flask import current_app
from app.helpers import full_name, hello_email
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials as UserCredentials
import app.utils as utils
import datetime
import time
import random

logger = logging.getLogger(__name__)

# Constants
SOURCE_FOLDER_ID = '1rz0xXMvtklwUuvGTkqs9cuNfQyY7-8-s'
PARENT_FOLDER_ID = '1_qQNYnGPFAePo8UE5NfX72irNtZGF5kF'
STUDENT_NOTES_DOC_ID = '1CBxl8hdrFUDLGSLKAi-gHWAsWwKNnf6ktKMIZ_CsNkE'
SERVICE_ACCOUNT_JSON = 'service_account_key2.json'
SERVICE_ACCOUNT_EMAIL = 'score-reports@sat-score-reports.iam.gserviceaccount.com'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/documents']
TOKEN = 'token_tpa.json'
CLIENT_SECRETS = 'credentials_tpa.json'


def get_sat_data_ss_id():
    """Get SAT data spreadsheet ID from config at runtime."""
    return current_app.config['SAT_DATA_SS_ID']

creds = None
drive_service = None
sheets_service = None
docs_service = None

if not (os.environ.get("TESTING") == "true" or os.environ.get("CI") == "true"):
    # Authenticate and initialize services
    creds = utils.load_google_credentials(SERVICE_ACCOUNT_JSON, TOKEN, CLIENT_SECRETS, prefer_user=True, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    sheets_service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    docs_service = build('docs', 'v1', credentials=creds, cache_discovery=False)


def execute_with_retries(request_callable, max_retries=6, base_backoff=1, max_backoff=64):
    """Execute a Google API request callable with exponential backoff on quota errors.

    request_callable should be a zero-arg function that performs the request (eg: lambda: req.execute()).
    """
    backoff = base_backoff
    for attempt in range(1, max_retries + 1):
        try:
            return request_callable()
        except HttpError as e:
            # Inspect response content for quota reasons
            content = ''
            try:
                content = e.content.decode('utf-8') if hasattr(e, 'content') and isinstance(e.content, (bytes, bytearray)) else str(e.content)
            except Exception:
                content = str(e)

            # If this looks like a rate/quota issue, back off and retry
            if ('userRateLimitExceeded' in content) or ('rateLimitExceeded' in content) or ('sharingRateLimitExceeded' in content) or (getattr(e, 'resp', None) is not None and getattr(e.resp, 'status', None) in (429, 403)):
                sleep_time = min(max_backoff, backoff) + random.random()
                logger.warning("Drive/Sheets API quota error; backing off %.1fs (attempt %d/%d): %s", sleep_time, attempt, max_retries, content[:200])
                time.sleep(sleep_time)
                backoff *= 2
                continue
            # Not a quota error we can retry — re-raise
            raise
    # If we exhausted retries, raise the last exception
    return request_callable()


def create_folder(folder_name, parent_folder_id=PARENT_FOLDER_ID):
    """Create a new folder in Google Drive."""
    if drive_service is None:
        logger.warning('Cannot create folder: Google Drive service not initialized')
        return None

    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }
    folder = execute_with_retries(lambda: drive_service.files().create(body=folder_metadata, fields='id').execute())
    return folder.get('id')


def create_test_prep_folder(contact_data: dict, test_type='sat/act', new_folder_id=None):
    """Create a test prep folder and copy/link files."""
    student_name = full_name(contact_data.get('student', {}))

    if not new_folder_id:
        new_folder_id = create_folder(f"{student_name} (Incomplete)")

    query = f"'{SOURCE_FOLDER_ID}' in parents and trashed=false"
    items = execute_with_retries(lambda: drive_service.files().list(q=query, fields='files(id, name)').execute()).get('files', [])

    file_ids = {}
    for item in items:
        copy_item(item['id'], item['name'], new_folder_id, test_type, file_ids, student_name)
        # small pacing delay to avoid bursts that trigger per-user rate limits
        time.sleep(0.05)
    logger.info(f"Folder copied successfully. Linking sheets for {student_name}.")

    link_sheets(new_folder_id, contact_data, file_ids, test_type)
    logger.info(f"Sheets linked. Updating homework spreadsheet.")

    update_homework_ss(file_ids, contact_data)
    logger.info(f"Homework spreadsheet updated for {student_name}.")

    execute_with_retries(lambda: drive_service.files().update(
        fileId=new_folder_id,
        body={'name': student_name}
    ).execute())

    new_folder_link = f'https://drive.google.com/drive/u/0/folders/{new_folder_id}'

    return new_folder_link


def create_academic_folder(contact_data: dict, subject, new_folder_id=None):
    """Create an academic folder and copy/link files."""
    student = contact_data.get('student', {})
    student_name = full_name(student)

    if not new_folder_id:
        new_folder_id = create_folder(f"{student_name} (Incomplete)")

    # Create a subfolder named "{student_name} {subject.title()}" inside the new academic folder
    subject_folder_name = f"{student_name} {subject.title()}"
    subject_folder_id = create_folder(subject_folder_name, new_folder_id)

    # Copy the student notes doc into the new folder
    notes_metadata = {
        'name': f"_Admin notes - {student_name}",
        'parents': [new_folder_id]
    }
    copied_notes = execute_with_retries(lambda: drive_service.files().copy(
        fileId=STUDENT_NOTES_DOC_ID,
        body=notes_metadata
    ).execute())
    copied_notes_id = copied_notes.get('id')

    parent_info = ''
    if contact_data.get('parent'):
        parent = contact_data.get('parent', {})
        parent_info = f"{parent.get('first_name', '')} {parent.get('last_name', '')} ({parent.get('email', 'email')}, {parent.get('phone', 'phone')})\n"
    if contact_data.get('parent2'):
        parent2 = contact_data.get('parent2', {})
        parent_info += f"{parent2.get('first_name', '')} {parent2.get('last_name', '')} ({parent2.get('email', 'email')}, {parent2.get('phone', 'phone')})\n"

    interested_dates = ''
    if contact_data.get('interested_dates'):
        for date in contact_data.get('interested_dates', []):
            checkmark = '✓' if date.get('is_registered') else ''
            interested_dates += f"{date.get('date')} {date.get('test').upper()} {checkmark}\n"

    text_pairs = [
        {'find_text': 'studentName', 'replace_text': student_name},
        {'find_text': 'pronouns', 'replace_text': student.get('pronouns', '')},
        {'find_text': 'studentEmail', 'replace_text': student.get('email', '')},
        {'find_text': 'studentPhone', 'replace_text': student.get('phone', '')},
        {'find_text': 'schoolName', 'replace_text': student.get('school', '')},
        {'find_text': 'gradYear', 'replace_text': str(student.get('grad_year', ''))},
        {'find_text': 'timezone', 'replace_text': student.get('timezone', '')},
        {'find_text': 'tutorName', 'replace_text': full_name(contact_data.get('tutor', {}))},
        {'find_text': 'parentInfo', 'replace_text': parent_info},
        {'find_text': 'testType', 'replace_text': subject.replace('-', ' ').title()},
        {'find_text': 'interestedDates', 'replace_text': interested_dates},
        {'find_text': 'formNotes', 'replace_text': contact_data.get('notes', ' ')}
    ]

    replace_text_in_doc(docs_service, copied_notes_id, text_pairs)

    execute_with_retries(lambda: drive_service.files().update(
        fileId=new_folder_id,
        body={'name': student_name}
    ).execute())

    new_folder_link = f'https://drive.google.com/drive/u/0/folders/{new_folder_id}'
    return new_folder_link


def copy_item(item_id, new_name, new_folder_id, test_type='sat/act', file_ids=None, student_name=None):
    """Copy a file or folder in Google Drive.

    `file_ids` is a dict passed by the caller and updated in-place with keys
    like 'sat_student', 'sat_admin', 'homework', etc.
    """
    if file_ids is None:
        file_ids = {}

    item = execute_with_retries(lambda: drive_service.files().get(fileId=item_id, fields='id, name, mimeType, shortcutDetails').execute())
    mime_type = item['mimeType']

    if mime_type == 'application/vnd.google-apps.folder':
        if new_name == 'Student':
            test_type_label = test_type.upper() if test_type != 'sat/act' else 'Test'
            new_name = f'{student_name} {test_type_label} prep'
        # If the item is a folder, create a new folder and copy its contents
        new_folder_id = create_folder(new_name, new_folder_id)
        query = f"'{item_id}' in parents and trashed=false"
        items = execute_with_retries(lambda: drive_service.files().list(q=query, fields='files(id, name)').execute()).get('files', [])
        for sub_item in items:
            copy_item(sub_item['id'], sub_item['name'], new_folder_id, test_type, file_ids, student_name)
            time.sleep(0.02)
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
        copied_shortcut = execute_with_retries(lambda: drive_service.files().create(body=shortcut_metadata, fields='id').execute())
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
        copied_file = execute_with_retries(lambda: drive_service.files().copy(fileId=item_id, body=file_metadata).execute())
        new_id = copied_file.get('id')
        name_lower = new_name.lower()

        if mime_type == 'application/vnd.google-apps.spreadsheet':
            if 'student answer sheet' in name_lower:
                if 'sat' in name_lower and test_type != 'act':
                    file_ids['sat_student'] = new_id
                elif 'act' in name_lower and test_type != 'sat':
                    file_ids['act_student'] = new_id
            elif 'answer analysis' in name_lower:
                if 'sat' in name_lower and test_type != 'act':
                    file_ids['sat_admin'] = new_id
                elif 'act' in name_lower and test_type != 'sat':
                    file_ids['act_admin'] = new_id
            elif 'homework' in name_lower:
                file_ids['homework'] = new_id
        elif mime_type == 'application/vnd.google-apps.document':
            if 'admin notes' in name_lower:
                file_ids['notes'] = new_id

        # Trash files that don't match the test type
        if test_type and test_type.lower() in ['sat', 'act']:
            if test_type.lower() == 'sat' and 'act' in new_name.lower():
                execute_with_retries(lambda: drive_service.files().update(fileId=copied_file['id'], body={'trashed': True}).execute())
            elif test_type.lower() == 'act' and 'sat' in new_name.lower():
                execute_with_retries(lambda: drive_service.files().update(fileId=copied_file['id'], body={'trashed': True}).execute())

        return copied_file.get('id')


def update_admin_spreadsheet(admin_ss_id, student_ss_id, student_name, test_type):
    """Update spreadsheet data."""
    execute_with_retries(lambda: drive_service.permissions().create(
        fileId=admin_ss_id,
        body={'type': 'user', 'role': 'writer', 'emailAddress': SERVICE_ACCOUNT_EMAIL}
    ).execute())

    if admin_ss_id:
        # Get the sheet ID of the sheet named 'Student responses'
        sheet_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute())
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
        execute_with_retries(lambda: sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=admin_ss_id,
            body={'requests': requests}
        ).execute())

def link_sheets(folder_id, contact_data, file_ids, test_type='sat/act'):
    """Link sheets and update data."""
    student = contact_data.get('student', {})
    student_name = full_name(student)

    if test_type != 'act':
        if file_ids.get('sat_student'):
            add_editor(drive_service, file_ids.get('sat_student'), [SERVICE_ACCOUNT_EMAIL])
            make_public_view(drive_service, file_ids.get('sat_student'))
            update_sat_student_spreadsheet(sheets_service, file_ids, student_name)

        if file_ids.get('sat_admin'):
            add_editor(drive_service, file_ids.get('sat_admin'), [SERVICE_ACCOUNT_EMAIL, hello_email()])
            remove_sat_protections(sheets_service, file_ids.get('sat_admin'))
            add_student_sheet_to_rev_data(sheets_service, file_ids.get('sat_admin'), student_name)

    elif test_type != 'sat':
        if file_ids.get('act_student'):
            add_editor(drive_service, file_ids.get('act_student'), [SERVICE_ACCOUNT_EMAIL])
            make_public_view(drive_service, file_ids.get('act_student'))

        if file_ids.get('act_admin'):
            add_editor(drive_service, file_ids.get('act_admin'), [SERVICE_ACCOUNT_EMAIL, hello_email()])

    if file_ids.get('homework'):
        add_editor(drive_service, file_ids.get('homework'), [hello_email()])

    if file_ids.get('notes'):
        add_editor(drive_service, file_ids.get('notes'), [SERVICE_ACCOUNT_EMAIL])

    parent_info = ''
    if contact_data.get('parent'):
        parent = contact_data.get('parent', {})
        parent_info = f"{parent.get('first_name', '')} {parent.get('last_name', '')} ({parent.get('email', 'email')}, {parent.get('phone', 'phone')})\n"
    if contact_data.get('parent2'):
        parent2 = contact_data.get('parent2', {})
        parent_info += f"{parent2.get('first_name', '')} {parent2.get('last_name', '')} ({parent2.get('email', 'email')}, {parent2.get('phone', 'phone')})\n"

    interested_dates = ''
    if contact_data.get('interested_dates'):
        for date in contact_data.get('interested_dates', []):
            checkmark = '✓' if date.get('is_registered') else ''
            interested_dates += f"{date.get('date')} {date.get('test').upper()} {checkmark}\n"


    text_pairs = [
        {'find_text': 'studentName', 'replace_text': student_name},
        {'find_text': 'pronouns', 'replace_text': student.get('pronouns', '')},
        {'find_text': 'studentEmail', 'replace_text': student.get('email', '')},
        {'find_text': 'studentPhone', 'replace_text': student.get('phone', '')},
        {'find_text': 'schoolName', 'replace_text': student.get('school', '')},
        {'find_text': 'gradYear', 'replace_text': str(student.get('grad_year', ''))},
        {'find_text': 'timezone', 'replace_text': student.get('timezone', '')},
        {'find_text': 'tutorName', 'replace_text': full_name(contact_data.get('tutor', {}))},
        {'find_text': 'parentInfo', 'replace_text': parent_info},
        {'find_text': 'testType', 'replace_text': test_type.upper()},
        {'find_text': 'interestedDates', 'replace_text': interested_dates},
        {'find_text': 'formNotes', 'replace_text': contact_data.get('notes', ' ')}
    ]

    replace_text_in_doc(docs_service, file_ids.get('notes'), text_pairs)

    if file_ids.get('sat_admin') and file_ids.get('sat_student'):
        update_admin_spreadsheet(file_ids.get('sat_admin'), file_ids.get('sat_student'), student_name, 'sat')
    if file_ids.get('act_admin') and file_ids.get('act_student'):
        update_admin_spreadsheet(file_ids.get('act_admin'), file_ids.get('act_student'), student_name, 'act')

    return file_ids


def update_homework_ss(file_ids, contact_data):
    """Update homework spreadsheet with student and contact information."""

    homework_ss_id = file_ids.get('homework')
    if not homework_ss_id:
        return

    # Get the sheet ID of the 'Info' sheet
    sheet_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=homework_ss_id).execute())
    sheets = sheet_metadata.get('sheets', [])
    info_sheet_id = None
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') == 'Info':
            info_sheet_id = sheet.get('properties', {}).get('sheetId')
            break

    if info_sheet_id is None:
        raise ValueError("Sheet named 'Info' not found in homework spreadsheet.")

    # Prepare the batch update requests
    requests = []

    # Student info
    student = contact_data.get('student', {})
    if student:
        # C4: Student first name, D4: Student last name
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 3,
                    'endRowIndex': 4,
                    'startColumnIndex': 2,
                    'endColumnIndex': 4
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': student.get('first_name', '')}},
                        {'userEnteredValue': {'stringValue': student.get('last_name', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

        # C5: Student email
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 4,
                    'endRowIndex': 5,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': student.get('email', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

        # C17: Grad year
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 16,
                    'endRowIndex': 17,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': str(student.get('grad_year', ''))}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    # Parent info
    parent = contact_data.get('parent', {})
    if parent:
        # C7: Parent first name, D7: Parent last name
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 6,
                    'endRowIndex': 7,
                    'startColumnIndex': 2,
                    'endColumnIndex': 4
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': parent.get('first_name', '')}},
                        {'userEnteredValue': {'stringValue': parent.get('last_name', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

        # C8: Parent email
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 7,
                    'endRowIndex': 8,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': parent.get('email', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    # Parent2 info (if present)
    parent2 = contact_data.get('parent2')
    if parent2:
        # C10: Parent2 first name, D10: Parent2 last name
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 9,
                    'endRowIndex': 10,
                    'startColumnIndex': 2,
                    'endColumnIndex': 4
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': parent2.get('first_name', '')}},
                        {'userEnteredValue': {'stringValue': parent2.get('last_name', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

        # C11: Parent2 email
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 10,
                    'endRowIndex': 11,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': parent2.get('email', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    # Tutor info
    tutor = contact_data.get('tutor', {})
    if tutor:
        # C13: Tutor first name, D13: Tutor last name
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 12,
                    'endRowIndex': 13,
                    'startColumnIndex': 2,
                    'endColumnIndex': 4
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': tutor.get('first_name', '')}},
                        {'userEnteredValue': {'stringValue': tutor.get('last_name', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

        # C14: Tutor email
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 13,
                    'endRowIndex': 14,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': tutor.get('email', '')}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    # C19: SAT student sheet ID (if present)
    if file_ids.get('sat_student'):
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 18,
                    'endRowIndex': 19,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': file_ids['sat_student']}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    # C20: ACT student sheet ID (if present)
    if file_ids.get('act_student'):
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': info_sheet_id,
                    'startRowIndex': 19,
                    'endRowIndex': 20,
                    'startColumnIndex': 2,
                    'endColumnIndex': 3
                },
                'rows': [{
                    'values': [
                        {'userEnteredValue': {'stringValue': file_ids['act_student']}}
                    ]
                }],
                'fields': 'userEnteredValue'
            }
        })

    if requests:
        execute_with_retries(lambda: sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=homework_ss_id,
            body={'requests': requests}
        ).execute())


# Recursively get all files in folder_id and nested subfolders
def get_all_files(folder_id):
    if drive_service is None:
        logger.warning('Cannot get files: Google Drive service not initialized')
        return []

    all_files = []
    query = f"'{folder_id}' in parents and trashed=false"
    items = execute_with_retries(lambda: drive_service.files().list(q=query, fields='files(id, name, mimeType)').execute()).get('files', [])

    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            # Recursively get files from subfolder
            all_files.extend(get_all_files(item['id']))
        else:
            all_files.append(item)

    return all_files


def add_editor(drive_service, file_id: str, editor_emails: list):
    # Add editor (user)
    try:
        for editor_email in editor_emails:
            execute_with_retries(lambda: drive_service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "writer", "emailAddress": editor_email},
            fields="id",
            sendNotificationEmail=False,
        ).execute())
    except HttpError as e:
        # permission may already exist
        logger.debug("Could not add editor %s to %s: %s", editor_email, file_id, e)


def make_public_view(drive_service, file_id: str):
    # Make file viewable by anyone
    try:
        execute_with_retries(lambda: drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute())
    except HttpError as e:
        logger.debug("Could not set anyone permission for %s: %s", file_id, e)


def remove_sat_protections(sheets_service, admin_ss_id):
    """Remove protections from SAT admin spreadsheet."""
    if sheets_service is None:
        logger.warning('Cannot remove SAT protections: Google Sheets service not initialized')
        return

    test_codes = get_sat_test_codes(sheets_service)
    test_codes.extend(['Reading & Writing', 'Math', 'SLT Uniques'])
    protected_sheets = []
    sheet_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute())
    sheets = sheet_metadata.get('sheets', [])
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') in test_codes:
            protected_sheets.append(sheet)
    for sheet in protected_sheets:
        for protection in sheet.get('protectedRanges', []):
            execute_with_retries(lambda: sheets_service.spreadsheets().batchUpdate(
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
            ).execute())


def get_sat_test_codes(sheets_service):
    """Retrieve SAT test codes from the SAT data spreadsheet."""
    sat_data_ss_id = get_sat_data_ss_id()
    # Get all sheets in the spreadsheet
    spreadsheet = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=sat_data_ss_id).execute())
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

    result = execute_with_retries(lambda: sheets_service.spreadsheets().values().get(
        spreadsheetId=sat_data_ss_id,
        range=f'{latest_sheet}!A2:A'
    ).execute())

    values = result.get('values', [])
    test_codes = list(set(row[0] for row in values if row))

    return test_codes


def update_sat_student_spreadsheet(sheets_service, ss_ids, student_name):
    """Update student spreadsheet with student name."""
    if sheets_service is None:
        logger.warning('Cannot update SAT student spreadsheet: Google Sheets service not initialized')
        return

    # Get the sheet ID of the sheet named 'Student info'
    sheet_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=ss_ids.get('sat_student')).execute())
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
                            {'userEnteredValue': {'stringValue': ss_ids.get('sat_admin')}}
                        ]
                    }
                ],
                'fields': 'userEnteredValue'
            }
        }
    ]

    execute_with_retries(lambda: sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=ss_ids.get('sat_student'),
        body={'requests': requests}
    ).execute())


def add_student_sheet_to_rev_data(sheets_service, admin_ss_id, student_name):
    """Add student answer sheet link to Rev sheet backend."""
    if sheets_service is None:
        logger.warning('Cannot add student sheet to rev data: Google Sheets service not initialized')
        return

    # Get the sheet ID of the sheet named 'Rev sheet backend'
    sheet_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=admin_ss_id).execute())
    sheets = sheet_metadata.get('sheets', [])
    rev_sheet_id = None
    for sheet in sheets:
        if sheet.get('properties', {}).get('title') == 'Rev sheet backend':
            rev_sheet_id = sheet.get('properties', {}).get('sheetId')
            break

    if rev_sheet_id is None:
        raise ValueError("Sheet named 'Rev sheet backend' not found.")

    # Get the value from U3
    result = execute_with_retries(lambda: sheets_service.spreadsheets().values().get(
        spreadsheetId=admin_ss_id,
        range='Rev sheet backend!U3'
    ).execute())

    rev_data_id = result.get('values', [[]])[0][0] if result.get('values') else ''

    # Copy 'Template' sheet and rename it to student_name
    template_sheet_id = None
    rev_data_metadata = execute_with_retries(lambda: sheets_service.spreadsheets().get(spreadsheetId=rev_data_id).execute())
    rev_data_sheets = rev_data_metadata.get('sheets', [])
    for sheet in rev_data_sheets:
        sheet_name = sheet.get('properties', {}).get('title')
        if sheet_name == 'Template':
            template_sheet_id = sheet.get('properties', {}).get('sheetId')
        if sheet_name == student_name:
            logger.warning("Student rev data sheet already exists")
            return

    if template_sheet_id is None:
        raise ValueError("Sheet named 'Template' not found in Rev data spreadsheet.")

    # Copy the Template sheet
    copy_request = {
        'duplicateSheet': {
            'sourceSheetId': template_sheet_id,
            'newSheetName': student_name
        }
    }

    execute_with_retries(lambda: sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=rev_data_id,
        body={'requests': [copy_request]}
    ).execute())


def replace_text_in_doc(docs_service, doc_id: str, text_pairs):
    """Replace text in a Google Doc.

    Accepts either:
      - a dict mapping find_text -> replace_text, or
      - a list of dicts like [{'find_text': 'A', 'replace_text': 'B'}, ...]

    Uses the Docs API `replaceAllText` requests and returns the batchUpdate result.
    """
    requests = []

    # Normalize input to an iterator of (find_text, replace_text)
    if isinstance(text_pairs, dict):
        pairs = text_pairs.items()
    elif isinstance(text_pairs, list):
        def _iter_list(lst):
            for entry in lst:
                if not isinstance(entry, dict):
                    continue
                # support a few possible key names
                find = entry.get('find_text') or entry.get('find') or entry.get('findText')
                replace = entry.get('replace_text') or entry.get('replace') or entry.get('replaceText')
                yield (find, replace)
        pairs = _iter_list(text_pairs)
    else:
        raise TypeError('text_pairs must be a dict or list of dicts')

    for find_text, replace_text in pairs:
        if not find_text or not replace_text:
            continue
        requests.append({
            "replaceAllText": {
                "containsText": {
                    "text": find_text,
                    "matchCase": True
                },
                "replaceText": replace_text or ''
            }
        })

    if not requests:
        return None

    body = {'requests': requests}
    # Use the retry wrapper for Docs calls as well
    return execute_with_retries(lambda: docs_service.documents().batchUpdate(documentId=doc_id, body=body).execute())