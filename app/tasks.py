import os
from app import celery
from app.create_report import create_sat_score_report, send_pdf_score_report, send_answers_to_student_ss, check_service_account_access
from app.email import send_task_fail_mail, send_report_submitted_email
import logging

class MyTaskBaseClass(celery.Task):
    autoretry_for = (Exception,)
    retry_backoff = 10
    retry_kwargs = {'max_retries': 7}

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # exc (Exception) - The exception raised by the task.
        # args (Tuple) - Original arguments for the task that failed.
        # kwargs (Dict) - Original keyword arguments for the task that failed.
        logging.error(f'Task {task_id} raised exception: {exc}')
        send_task_fail_mail(exc, task_id, args, kwargs, einfo)

@celery.task(name='app.tasks.create_and_send_sat_report_task', bind=True, base=MyTaskBaseClass)
def create_and_send_sat_report_task(self, score_data):
  try:
    spreadsheet_id, score_data_updated = create_sat_score_report(score_data)
    send_pdf_score_report(spreadsheet_id, score_data)
    logging.info('SAT report created and sent')

    student_ss_id = score_data['student_ss_id']
    if student_ss_id:
      has_access = check_service_account_access(student_ss_id)
      if has_access:
        send_answers_to_student_ss(score_data_updated)

  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    raise e