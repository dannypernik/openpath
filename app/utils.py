import os
import re
import logging
import requests
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse as dateparse
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from app.extensions import db
from app.models import TestDate
import tempfile
import subprocess
from io import BytesIO
import base64
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)

USAGE_SHEET_ID = '1XyemzCWeDqhZg8dX8A0qMIUuBqCx1aIopD1qpmwUmw4'
USAGE_SHEET_RANGE = 'Data!A3:G'
ALL_SCOPES = [
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/spreadsheets',
  'https://www.googleapis.com/auth/documents'
]

def generate_drive_token(client_secrets: str, output_name: str = 'token_drive.json'):
    """Run OAuth flow to generate token_drive.json for Drive API access."""
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, ALL_SCOPES)
    creds = flow.run_local_server(port=0)   # opens browser
    with open(output_name, 'w') as f:
        f.write(creds.to_json())
    print(f'Saved {output_name}')


def load_google_credentials(service_account_json: str,
                            token_path: str = '',
                            client_secrets: str = '',
                            prefer_user: bool = False,
                            scopes: list = ALL_SCOPES):
    """
    Return credentials object. If `prefer_user` is True try user token first,
    refreshing if needed. Otherwise fall back to the service account.
    """

    # Try user creds
    if prefer_user and os.path.exists(token_path):
        try:
            creds = UserCredentials.from_authorized_user_file(token_path, scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
        except Exception:
            logger.exception("Failed loading/refreshing user credentials from %s", token_path)

    # Fallback to service account
    try:
        return ServiceAccountCredentials.from_service_account_file(service_account_json, scopes=scopes)
    except Exception:
        logger.exception("Failed loading service account credentials from %s", service_account_json)
        raise


def get_week_start_and_end(date_yyyymmddd=None):
    """Returns the start and end of the week for the given date."""
    if date_yyyymmddd:
        try:
            date = datetime.strptime(date_yyyymmddd, '%Y%m%d').date()
        except ValueError:
            raise ValueError("Invalid date format. Use YYYYMMDD.")
    else:
        date = datetime.now(timezone.utc).date()

    if date.weekday() == 0:
        week_start = date - timedelta(days=7)
    else:
        week_start = date - timedelta(days=date.weekday())
    week_end = week_start + timedelta(days=7)
    return week_start, week_end

def parse_celery_worker_log(log_path, week_start=None, week_end=None):
    """
    Parse celery_worker_error.log for SAT/ACT report task stats for the given week.
    Returns a dict: { 'sat': {'success': X, 'failure': Y, 'retry': Z}, 'act': {...} }
    """
    if not os.path.isfile(log_path):
        raise FileNotFoundError(f"Log file not found: {log_path}")

    if week_start is None or week_end is None:
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=7)

    lost_stats = parse_worker_lost_errors(log_path, week_start, week_end)


    # Patterns for task names and statuses
    patterns = {
      'sat': {
        'success': re.compile(r'Task app\.tasks\.sat_report_workflow_task\[.*\] succeeded'),
        'retry': re.compile(r'Retrying #\d+.*app\.tasks\.sat_report_workflow_task'),
      },
      'act': {
        'success': re.compile(r'Task app\.tasks\.act_report_workflow_task\[.*\] succeeded'),
        'retry': re.compile(r'Retrying #\d+.*app\.tasks\.act_report_workflow_task'),
      }
    }

    stats = {
        'sat': {'success': 0, 'failure': 0, 'retry': 0},
        'act': {'success': 0, 'failure': 0, 'retry': 0}
    }

    # Parse log lines
    with open(log_path, 'r') as f:
        for line in f:
            # Extract date from log line (assumes format: [YYYY-MM-DD ...)
            m = re.match(r'\[(\d{4}-\d{2}-\d{2})', line)
            if not m:
                continue
            log_date = datetime.strptime(m.group(1), '%Y-%m-%d').date()
            if not (week_start <= log_date < week_end):
                continue

            for task in ['sat', 'act']:
                for status in ['success', 'retry']:
                    if patterns[task][status].search(line):
                        stats[task][status] += 1

    # Set failure counts from lost_stats
    stats['sat']['failure'] = lost_stats.get('app.tasks.sat_report_workflow_task', 0)
    stats['act']['failure'] = lost_stats.get('app.tasks.act_report_workflow_task', 0)

    return stats


def parse_worker_lost_errors(log_path, week_start=None, week_end=None):
    """
    Returns a dict with counts of WorkerLostError per task for the given week.
    """
    from collections import defaultdict

    if week_start is None or week_end is None:
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=7)

    lost_counts = defaultdict(int)
    with open(log_path, 'r') as f:
        lines = list(f)
        for i, line in enumerate(lines):
            # Only look for WorkerLostError lines
            if 'billiard.exceptions.WorkerLostError' in line:
                # Look backward for the most recent task received line within the same day
                search_idx = i
                found_task = None
                while search_idx >= 0:
                    prev_line = lines[search_idx]
                    # Extract date from log line
                    m_date = re.match(r'\[(\d{4}-\d{2}-\d{2})', prev_line)
                    if m_date:
                        log_date = datetime.strptime(m_date.group(1), '%Y-%m-%d').date()
                        if not (week_start <= log_date < week_end):
                            break  # Stop if we go past the week
                    m_prev_task = re.search(r'Task (app\.tasks\.[\w_]+)\[.*\] received', prev_line)
                    if m_prev_task:
                        found_task = m_prev_task.group(1)
                        break
                    search_idx -= 1
                if found_task:
                    lost_counts[found_task] += 1
    return dict(lost_counts)


def batch_update_weekly_usage(date_yyyymmddd=None):
    """
    Parse celery_worker_error.log for the current week and update the usage sheet
    with stats for SAT/ACT (success, failure, retry) for the week.
    """

    week_start, week_end = get_week_start_and_end(date_yyyymmddd)

    stats = parse_celery_worker_log('/var/log/celery_worker_error.log', week_start, week_end)

    sat_success = stats['sat'].get('success', '')
    sat_failure = stats['sat'].get('failure', '')
    sat_retry   = stats['sat'].get('retry', '')
    act_success = stats['act'].get('success', '')
    act_failure = stats['act'].get('failure', '')
    act_retry   = stats['act'].get('retry', '')

    # Conditionally load credentials
    sa_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service_account_key2.json')
    should_init_google = (
        not os.getenv('TESTING', '').lower() in ('1', 'true')
        and not os.getenv('CI')
        and os.path.exists(sa_path)
    )

    if not should_init_google:
        print('Skipping Google Sheets update: TESTING/CI or missing service account file')
        return stats

    creds = ServiceAccountCredentials.from_service_account_file(
        sa_path,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    result = sheet.values().get(spreadsheetId=USAGE_SHEET_ID, range=USAGE_SHEET_RANGE).execute()
    values = result.get('values', [])

    row_idx = None
    for i, row in enumerate(values):
        if row and row[0] == week_start.isoformat():
            row_idx = i
            break
    if row_idx is None:
        new_row = [week_start.isoformat()] + ['0'] * 6
        values.append(new_row)
        row_idx = len(values) - 1
        print("Added new row for this week")
    else:
        print(f"Updating existing row at index {row_idx}")

    values[row_idx][1] = str(sat_success)
    values[row_idx][2] = str(sat_retry)
    values[row_idx][3] = str(sat_failure)
    values[row_idx][4] = str(act_success)
    values[row_idx][5] = str(act_retry)
    values[row_idx][6] = str(act_failure)

    sheet.values().update(
        spreadsheetId=USAGE_SHEET_ID,
        range=USAGE_SHEET_RANGE,
        valueInputOption='RAW',
        body={'values': values}
    ).execute()

    return stats


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')  # Remove the '#' character
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def is_dark_color(rgb):
    """
    Determines if a color is 'dark' based on its luma value.
    Accepts an RGB tuple (r, g, b) or a hex color string.
    """
    if isinstance(rgb, str):
        rgb = hex_to_rgb(rgb)

    r, g, b = rgb
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b  # ITU-R BT.709
    return luma < 205


def color_svg_white_to_input(svg_path, input_color, output_path):
    """
    Replace all white fills and strokes in an SVG file with the input color and save as PNG.

    Args:
        svg_path (str): Path to the SVG file.
        input_color (str): The color to replace white with (e.g., "#FF5733").
        output_path (str): The file path to save the resulting PNG.
    """
    input_color = input_color.lstrip('#')

    with open(svg_path, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    # Replace white fills and strokes in various SVG attribute formats
    svg_content = re.sub(r'fill\s*=\s*["\']?(#fff(?:fff)?|#FFF(?:FFF)?|white)["\']?', f'fill="#{input_color}"', svg_content, flags=re.IGNORECASE)
    svg_content = re.sub(r'stroke\s*=\s*["\']?(#fff(?:fff)?|#FFF(?:FFF)?|white)["\']?', f'stroke="#{input_color}"', svg_content, flags=re.IGNORECASE)
    svg_content = re.sub(r'fill\s*:\s*(#fff(?:fff)?|#FFF(?:FFF)?|white)', f'fill:#{input_color}', svg_content, flags=re.IGNORECASE)
    svg_content = re.sub(r'stroke\s*:\s*(#fff(?:fff)?|#FFF(?:FFF)?|white)', f'stroke:#{input_color}', svg_content, flags=re.IGNORECASE)

    # Write modified SVG to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.svg') as tmp_svg:
        tmp_svg.write(svg_content.encode('utf-8'))
        tmp_svg_path = tmp_svg.name

    def svg_to_png_with_rsvg(svg_path, output_path):
        subprocess.run(['rsvg-convert', '-f', 'png', '-o', output_path, svg_path])

    svg_to_png_with_rsvg(tmp_svg_path, output_path)

    # Clean up temporary SVG file
    os.remove(tmp_svg_path)


def generate_vcard(contacts):
    vcards = ''
    for contact in contacts:
        vcard = f"""BEGIN:VCARD
VERSION:3.0
N:{contact.get('last_name', '')};{contact.get('first_name', '')};;;
FN:{contact.get('first_name', '')} {contact.get('last_name', '')}
EMAIL:{contact.get('email', '')}
ORG:{contact.get('role', '').title()}
TEL;TYPE=CELL:{contact.get('phone', '')}
NOTE:Timezone: {contact.get('timezone', '')}
END:VCARD
"""
        vcards += vcard

    vcard_bytes = vcards.strip().encode('utf-8')
    vcard_base64 = base64.b64encode(vcard_bytes).decode('utf-8')
    return vcard_base64


def create_crm_action(contact_data: dict, action_text: str):
    '''Create a contact and an associated action in OnePageCRM.

        Args:
            contact_data (dict): Dictionary with contact details.
                Required keys: first_name, last_name, emails [{type:home, value}].
                Optional keys: company_name, phones [{type:mobile, value}].
            action_text (str): Text for the action to be created.
    '''
    try:
        existing_email_matches = requests.get(
            f'https://app.onepagecrm.com/api/v3/contacts?email={contact_data.get("email")}&page=1&per_page=10',
            auth=(os.getenv('ONEPAGECRM_ID'), os.getenv('ONEPAGECRM_PW'))
        )

        if existing_email_matches.status_code == 200 and len(existing_email_matches.json()['data']['contacts']) > 0:
            is_existing_contact = True

            contact = existing_email_matches.json()['data']['contacts'][0].get('contact', {})
            contact_id = contact.get('id')
            contact['first_name'] = contact_data.get('first_name', contact.get('first_name')  )
            contact['last_name'] = contact_data.get('last_name', contact.get('last_name'))
            contact['tags'] = list(set(contact.get('tags', []) + ['Parent']))

            if contact_data.get('company_name'):
                contact['company_name'] = contact_data.get('company_name', contact.get('company_name'))
            if contact_data.get('phone'):
                contact['phones'] = [{'type': 'mobile', 'value': contact_data.get('phone')}]

            requests.put(
                f'https://app.onepagecrm.com/api/v3/contacts/{contact_id}',
                json=contact,
                auth=(os.getenv('ONEPAGECRM_ID'), os.getenv('ONEPAGECRM_PW'))
            )

            logging.info('Contact already exists in OnePageCRM.')

        else:
            # New contact
            is_existing_contact = False
            contact = {
                'first_name': contact_data.get('first_name', ''),
                'last_name': contact_data.get('last_name', ''),
                'company_name': contact_data.get('company_name', ''),
                'emails': [{'type': 'home', 'value': contact_data.get('email')}],
                'phones': [{'type': 'mobile', 'value': contact_data.get('phone')}],
                'tags': ['Parent']
            }

            crm_contact = requests.post(
                'https://app.onepagecrm.com/api/v3/contacts',
                json=contact,
                auth=(os.getenv('ONEPAGECRM_ID'), os.getenv('ONEPAGECRM_PW'))
            )

            if crm_contact.status_code == 201:
                logging.info('CRM contact created successfully.')
                contact_id = crm_contact.json()['data']['contact']['id']
            else:
                logging.error(f'Failed to create CRM contact: {crm_contact.text}')
                return False

        new_action = {
            'contact_id': contact_id,
            'assignee_id': os.getenv('ONEPAGECRM_ID'),
            'status': 'asap',
            'text': action_text
        }

        crm_action = requests.post(
            'https://app.onepagecrm.com/api/v3/actions',
            json=new_action,
            auth=(os.getenv('ONEPAGECRM_ID'), os.getenv('ONEPAGECRM_PW'))
        )

        if crm_action.status_code == 201:
            logging.info(f'CRM action created successfully.')
            return True
        else:
            logging.info(f'Failed to create CRM action: {crm_action.text}')
            return False

    except Exception as e:
        logging.error(f'Error creating CRM contact and action: {e}', exc_info=True)
        raise


def format_timezone(tz_str):
    """Format timezone string for display."""
    if 'New_York' in tz_str:
        return 'Eastern'
    if 'Chicago' in tz_str:
        return 'Central'
    if 'Denver' in tz_str:
        return 'Mountain'
    if 'Los_Angeles' in tz_str:
        return 'Pacific'
    else:
        return tz_str


def add_test_dates_from_ss():
    """Import test dates from the configured spreadsheet into the TestDate table."""
    # Initialize Sheets API client
    sa_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service_account_key2.json')
    if not os.path.exists(sa_path):
        print('Service account file not found, skipping sheet import')
        return
    creds = ServiceAccountCredentials.from_service_account_file(
        sa_path,
        scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
    )
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
    if not SPREADSHEET_ID:
        print('Spreadsheet ID not found, skipping sheet import')
        return

    # --- SAT table (new layout) ---
    # Read columns: A (test date), B (reg), C (late reg), D (duplicate test date), E (score release)
    sat_a = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Test dates!A2:A10').execute().get('values', [])
    sat_b = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Test dates!B2:B10').execute().get('values', [])
    sat_c = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Test dates!C2:C10').execute().get('values', [])
    sat_d = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Test dates!D2:D10').execute().get('values', [])
    sat_e = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range='Test dates!E2:E10').execute().get('values', [])

    # normalize to lists of strings (may be nested lists from API)
    def cell_str(cell_list, idx):
        try:
            return cell_list[idx][0].strip()
        except Exception:
            return ''

    def sanitize_cell(s):
        if not s:
            return ''
        # replace newlines and stray text like 'Register'
        s = s.replace('\n', ' ').replace('\r', ' ').replace('Register', '')
        s = s.replace('"', '').strip()
        return s

    # helper to extract date substring and parse flexibly
    def extract_date(s):
        if not s:
            return None
        s = sanitize_cell(s)
        # Try common patterns first
        for fmt in ('%b. %d, %Y', '%b %d, %Y', '%B %d, %Y'):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
        # Avoid fuzzy-parsing long instructional text (e.g. "30 days before...")
        # Only attempt fuzzy parse if the string contains a month name/abbr
        month_regex = r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b'
        if re.search(month_regex, s, re.IGNORECASE):
            try:
                return dateparse(s, fuzzy=True).date()
            except Exception:
                return None
        return None

    max_rows = max(len(sat_a), len(sat_b), len(sat_c), len(sat_d), len(sat_e))
    for i in range(max_rows):
        a_raw = cell_str(sat_a, i)
        b_raw = cell_str(sat_b, i)
        c_raw = cell_str(sat_c, i)
        d_raw = cell_str(sat_d, i)
        e_raw = cell_str(sat_e, i)



        a_clean = sanitize_cell(a_raw)
        d_clean = sanitize_cell(d_raw)

        # prefer A for test date, fallback to D if A empty
        test_date = extract_date(a_clean) or extract_date(d_clean)
        if not test_date:
            continue

        reg_deadline = extract_date(b_raw)
        late_deadline = extract_date(c_raw)

        # score release: only add if E present and A and D match (both parse and equal)
        score_release = None
        if e_raw:
            e_date = extract_date(e_raw)
            a_dt = extract_date(a_clean)
            d_dt = extract_date(d_clean)
            cond = bool(e_date and a_dt and d_dt and a_dt == d_dt)
            if cond:
                # ensure year alignment: if e_date earlier than test_date, maybe belongs to next year
                if e_date < test_date:
                    # try bump year (dateutil handled fuzzy; here we skip complex year logic)
                    pass
                score_release = e_date

        # Upsert into DB with structured logging
        existing = TestDate.query.filter_by(test='sat', date=test_date).first()
        if existing:
            changes = {}
            if existing.reg_date != reg_deadline:
                changes['reg_date'] = {'old': existing.reg_date, 'new': reg_deadline}
                existing.reg_date = reg_deadline
            if existing.late_date != late_deadline:
                changes['late_date'] = {'old': existing.late_date, 'new': late_deadline}
                existing.late_date = late_deadline
            if existing.score_date != score_release:
                changes['score_date'] = {'old': existing.score_date, 'new': score_release}
                existing.score_date = score_release
            if changes:
                logger.info('Updated SAT TestDate id=%s date=%s changes=%s', getattr(existing, 'id', None), test_date, changes)
            else:
                logger.debug('SAT TestDate id=%s date=%s no changes', getattr(existing, 'id', None), test_date)
        else:
            new_td = TestDate(
                test='sat',
                date=test_date,
                reg_date=reg_deadline,
                late_date=late_deadline,
                score_date=score_release,
                status='confirmed'
            )
            db.session.add(new_td)
            logger.info('Created SAT TestDate date=%s reg=%s late=%s score=%s', test_date, reg_deadline, late_deadline, score_release)
        db.session.commit()
        logger.debug('Committed SAT TestDate for date=%s', test_date)

    # Fetch ACT dates
    act_result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Test dates!A12:E28'
    ).execute()
    act_values = act_result.get('values', [])

    # Process ACT dates
    for row in act_values:
        if len(row) >= 1 and row[0]:
            test_date_str = row[0].replace('*', '').strip()
            try:
                test_date = datetime.strptime(test_date_str, '%B %d, %Y').date()
            except ValueError:
                continue

            reg_deadline = None
            late_deadline = None
            score_release = None

            if len(row) >= 2 and row[1]:
                try:
                    reg_deadline = datetime.strptime(f"{row[1]}, {test_date.year}", '%B %d, %Y').date()
                    if reg_deadline > test_date:
                        reg_deadline = datetime.strptime(f"{row[1]}, {test_date.year - 1}", '%B %d, %Y').date()
                except ValueError:
                    pass

            if len(row) >= 3 and row[2]:
                try:
                    late_deadline = datetime.strptime(f"{row[2]}, {test_date.year}", '%B %d, %Y').date()
                    if late_deadline > test_date:
                        late_deadline = datetime.strptime(f"{row[2]}, {test_date.year - 1}", '%B %d, %Y').date()
                except ValueError:
                    pass

            if len(row) >= 5 and row[4]:
                try:
                    score_release = datetime.strptime(f"{row[4]}, {test_date.year}", '%B %d, %Y').date()
                    if score_release < test_date:
                        score_release = datetime.strptime(f"{row[4]}, {test_date.year + 1}", '%B %d, %Y').date()
                except ValueError:
                    pass

            # SQLAlchemy upsert for ACT with structured logging
            existing = TestDate.query.filter_by(test='act', date=test_date).first()
            if existing:
                changes = {}
                if existing.reg_date != reg_deadline:
                    changes['reg_date'] = {'old': existing.reg_date, 'new': reg_deadline}
                    existing.reg_date = reg_deadline
                if existing.late_date != late_deadline:
                    changes['late_date'] = {'old': existing.late_date, 'new': late_deadline}
                    existing.late_date = late_deadline
                if existing.score_date != score_release:
                    changes['score_date'] = {'old': existing.score_date, 'new': score_release}
                    existing.score_date = score_release
                if changes:
                    logger.info('Updated ACT TestDate id=%s date=%s changes=%s', getattr(existing, 'id', None), test_date, changes)
                else:
                    logger.debug('ACT TestDate id=%s date=%s no changes', getattr(existing, 'id', None), test_date)
            else:
                new_td = TestDate(
                    test='act',
                    date=test_date,
                    reg_date=reg_deadline,
                    late_date=late_deadline,
                    score_date=score_release,
                    status='confirmed'
                )
                db.session.add(new_td)
                logger.info('Created ACT TestDate date=%s reg=%s late=%s score=%s', test_date, reg_deadline, late_deadline, score_release)
            db.session.commit()

    logger.info('Test dates successfully added/updated from spreadsheet')