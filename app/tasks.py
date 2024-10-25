import os
from app import celery
from app.create_report import create_sat_score_report, send_pdf_score_report
from app.email import send_fail_mail, send_task_fail_mail, send_report_submitted_email
import logging

# class MyTaskBaseClass(celery.Task):
#     def on_failure(self, exc, task_id, args, kwargs, einfo):
#         # exc (Exception) - The exception raised by the task.
#         # args (Tuple) - Original arguments for the task that failed.
#         # kwargs (Dict) - Original keyword arguments for the task that failed.
#         send_task_fail_mail(exc, task_id, args, kwargs, einfo)

@celery.task(name='app.tasks.create_and_send_sat_report', bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={'max_retries': 7})
def create_and_send_sat_report(self, score_data):
  try:
    spreadsheet_id = create_sat_score_report(score_data)
    send_pdf_score_report(spreadsheet_id, score_data)
    print('SAT report created and sent')
  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    raise e

@celery.task(name='app.tasks.send_report_submitted_task', bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={'max_retries': 7})
def send_report_submitted_task(self, score_data):
  try:
    send_report_submitted_email(score_data)
    logging.info('Report submitted email sent')
  except Exception as e:
    logging.error(f'Error sending report submitted email: {e}')
    raise e