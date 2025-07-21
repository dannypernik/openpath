import os
import re
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

USAGE_SHEET_ID = '1XyemzCWeDqhZg8dX8A0qMIUuBqCx1aIopD1qpmwUmw4'
USAGE_SHEET_RANGE = 'Data!A3:G'  # Adjust as needed

def get_week_start_and_end(date=None):
    """Returns the start and end of the week for the given date."""
    if date is None:
        date = datetime.utcnow().date()
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
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=7)

    lost_stats = parse_worker_lost_errors(log_path, week_start, week_end)


    # Patterns for task names and statuses
    patterns = {
      'sat': {
        'success': re.compile(r'Task app\.tasks\.create_and_send_sat_report_task\[.*\] succeeded'),
        'retry': re.compile(r'Retrying #\d+.*app\.tasks\.create_and_send_sat_report_task'),
      },
      'act': {
        'success': re.compile(r'Task app\.tasks\.create_and_send_act_report_task\[.*\] succeeded'),
        'retry': re.compile(r'Retrying #\d+.*app\.tasks\.create_and_send_act_report_task'),
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
    stats['sat']['failure'] = lost_stats.get('app.tasks.create_and_send_sat_report_task', 0)
    stats['act']['failure'] = lost_stats.get('app.tasks.create_and_send_act_report_task', 0)

    return stats


def parse_worker_lost_errors(log_path, week_start=None, week_end=None):
    """
    Returns a dict with counts of WorkerLostError per task for the given week.
    """
    from collections import defaultdict

    if week_start is None or week_end is None:
        today = datetime.utcnow().date()
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


def batch_update_weekly_usage():
    """
    Parse celery_worker_error.log for the current week and update the usage sheet
    with stats for SAT/ACT (success, failure, retry) for the week.
    """
    week_start, week_end = get_week_start_and_end()

    stats = parse_celery_worker_log('/var/log/celery_worker_error.log', week_start, week_end)

    sat_success = stats['sat'].get('success', '')
    sat_failure = stats['sat'].get('failure', '')
    sat_retry   = stats['sat'].get('retry', '')
    act_success = stats['act'].get('success', '')
    act_failure = stats['act'].get('failure', '')
    act_retry   = stats['act'].get('retry', '')

    creds = Credentials.from_service_account_file(
        'service_account_key2.json',
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