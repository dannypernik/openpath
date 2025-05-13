import os
from app import celery
# from celery.signals import worker_process_shutdown, worker_shutdown
from app.create_report import create_sat_score_report, send_pdf_score_report, send_answers_to_student_ss
from app.email import send_report_submitted_email, send_task_fail_mail, send_fail_mail
# from io import StringIO
import logging
import resource

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
def create_and_send_sat_report_task(self, score_data, organization_dict=None):
  try:
    print(f"Organization Dict in Celery Task: {organization_dict}")
    mem_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    spreadsheet_id, score_data_updated = create_sat_score_report(score_data, organization_dict)
    mem_post_report = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    score_report_mem = mem_post_report - mem_start
    logging.info(f"Score report used {score_report_mem:.2f} MB of memory")
    if score_data_updated['student_ss_id']:
      score_data_updated = send_answers_to_student_ss(score_data_updated)
    post_ss_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    student_ss_mem = post_ss_mem - mem_post_report
    logging.info(f"Student SS import used {student_ss_mem:.2f} MB of memory")


    send_pdf_score_report(spreadsheet_id, score_data_updated)

  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    raise e