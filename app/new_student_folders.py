import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

# Constants
SERVICE_ACCOUNT_JSON = 'path/to/service_account.json'
SERVICE_ACCOUNT_EMAIL = 'score-reports@sat-score-reports.iam.gserviceaccount.com'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

# Authenticate and initialize services
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

def create_folder(parent_folder_id, folder_name):
    """Create a new folder in Google Drive."""
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }
    folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')

def copy_file(file_id, new_name, parent_folder_id):
    """Copy a file in Google Drive."""
    file_metadata = {
        'name': new_name,
        'parents': [parent_folder_id]
    }
    copied_file = drive_service.files().copy(fileId=file_id, body=file_metadata).execute()
    return copied_file.get('id')

def update_spreadsheet(sheet_id, student_name, admin_sheet_id=None):
    """Update spreadsheet data."""
    # Add editor permissions
    drive_service.permissions().create(
        fileId=sheet_id,
        body={'type': 'user', 'role': 'writer', 'emailAddress': SERVICE_ACCOUNT_EMAIL}
    ).execute()

    # Update specific ranges in the spreadsheet
    if admin_sheet_id:
        requests = [
            {
                'updateCells': {
                    'range': {
                        'sheetId': admin_sheet_id,
                        'startRowIndex': 0,
                        'endRowIndex': 1,
                        'startColumnIndex': 0,
                        'endColumnIndex': 1
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
        ]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={'requests': requests}
        ).execute()

def link_sheets(folder_id, student_name, prep_type='all'):
    """Link sheets and update data."""
    query = f"'{folder_id}' in parents and trashed=false"
    files = drive_service.files().list(q=query, fields='files(id, name)').execute().get('files', [])

    for file in files:
        file_name = file['name'].lower()
        file_id = file['id']

        if 'student answer sheet' in file_name:
            update_spreadsheet(file_id, student_name)
        elif 'answer analysis' in file_name:
            update_spreadsheet(file_id, student_name)

def create_test_prep_folder(source_folder_id, parent_folder_id, student_name, prep_type='all'):
    """Create a test prep folder and copy/link files."""
    # Create the new folder
    new_folder_id = create_folder(parent_folder_id, f"{student_name} {prep_type.upper()} prep")

    # Copy files from the source folder
    query = f"'{source_folder_id}' in parents and trashed=false"
    files = drive_service.files().list(q=query, fields='files(id, name)').execute().get('files', [])

    for file in files:
        file_name = file['name']
        new_name = f"{student_name} {file_name}" if 'template' in file_name.lower() else file_name
        copy_file(file['id'], new_name, new_folder_id)

    # Link sheets and update data
    link_sheets(new_folder_id, student_name, prep_type)

    print(f"Folder created successfully: {new_folder_id}")

# Example usage
if __name__ == '__main__':
    source_folder_id = 'SOURCE_FOLDER_ID'
    parent_folder_id = 'PARENT_FOLDER_ID'
    student_name = 'John Doe'
    prep_type = 'sat'  # or 'act' or 'all'

    create_test_prep_folder(source_folder_id, parent_folder_id, student_name, prep_type)