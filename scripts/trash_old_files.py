import datetime
import logging
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Configure logging
LOG_FILE = '/var/log/trash_old_files.log'  # Update this path if needed
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

SERVICE_ACCOUNT_JSON = 'service_account_key2.json'  # Update with the correct path

def trash_old_files(folder_id):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    try:
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30))
        cutoff_iso = cutoff.isoformat().replace('+00:00', 'Z')
        query = f"'{folder_id}' in parents and trashed=false and modifiedTime < '{cutoff_iso}'"
        files = drive_service.files().list(q=query, fields='files(id, name)').execute().get('files', [])

        logging.info(f"Found {len(files)} files to trash in folder {folder_id}")
        for file in files:
            file_id = file['id']
            drive_service.files().update(fileId=file_id, body={'trashed': True}).execute()
            logging.info(f"Trashed file: {file['name']} (ID: {file_id})")
        logging.info("Trashing complete")
    except Exception as e:
        logging.error(f'Error in trash_old_files: {e}')
        raise

if __name__ == '__main__':
    # Replace 'YOUR_FOLDER_ID' with the actual folder ID
    trash_old_files('15tJsdeOx_HucjIb6koTaafncTj-e6FO6')