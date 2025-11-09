import os
from app import celery
from app.create_sat_report import create_sat_score_report, send_sat_pdf_report, \
  sat_answers_to_student_ss, style_custom_sat_spreadsheet
from app.create_act_report import create_act_score_report, send_act_pdf_report, \
  act_answers_to_student_ss, process_act_answer_img, style_custom_act_spreadsheet
from app.email import send_task_fail_mail
import logging
import resource
# from app.new_student_folders import create_test_prep_folder


class MyTaskBaseClass(celery.Task):
    autoretry_for = (Exception,)
    retry_backoff = 10
    retry_kwargs = {'max_retries': 3}
    # acks_late = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
      logging.info(f'Retry #{self.request.retries + 1} for task {task_id} due to: {exc}')

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # exc (Exception) - The exception raised by the task.
        # args (Tuple) - Original arguments for the task that failed.
        # kwargs (Dict) - Original keyword arguments for the task that failed.
        logging.error(f'Task {task_id} raised exception: {exc}')
        score_data = args[0] if args else kwargs.get('score_data')
        if not score_data:
          logging.error("Score data is missing. Cannot send failure email.")
          return
        if self.request.retries >= self.max_retries:
          send_task_fail_mail(score_data, exc, task_id, args, kwargs, einfo)

@celery.task(name='app.tasks.create_and_send_sat_report_task', bind=True, base=MyTaskBaseClass)
def create_and_send_sat_report_task(self, score_data, organization_dict=None):
  try:
    if organization_dict:
      logging.info(f"SAT report started for {score_data['student_name']} via {organization_dict['name']}")
    else:
      logging.info(f"SAT report started for {score_data['student_name']} by {score_data['email']}")

    mem_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    ss_copy_id, score_data_updated = create_sat_score_report(score_data, organization_dict)

    mem_post_report = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    score_report_mem = mem_post_report - mem_start
    logging.info(f"Score report used {score_report_mem:.2f} MB of memory")

    if score_data_updated['student_ss_id']:
      logging.info(f"SAT student ss: https://docs.google.com/spreadsheets/d/{score_data['student_ss_id']}")
      score_data_updated = sat_answers_to_student_ss(score_data_updated)
      post_ss_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
      student_ss_mem = post_ss_mem - mem_post_report
      logging.info(f"Student SS import used {student_ss_mem:.2f} MB of memory")

    send_sat_pdf_report(ss_copy_id, score_data_updated)

  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    raise e


@celery.task(name='app.tasks.create_and_send_act_report_task', bind=True, base=MyTaskBaseClass)
def create_and_send_act_report_task(self, score_data, organization_dict=None):
  try:
    if organization_dict:
      logging.info(f"ACT report started for {score_data['student_name']} via {organization_dict['name']}")
    else:
      logging.info(f"ACT report started for {score_data['student_name']} by {score_data['email']}")

    score_data = process_act_answer_img(score_data)

    mem_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    ss_copy_id, score_data = create_act_score_report(score_data, organization_dict)

    mem_post_report = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    score_report_mem = mem_post_report - mem_start
    logging.info(f"Score report used {score_report_mem:.2f} MB of memory")

    if score_data['student_ss_id']:
      logging.info(f"Student ACT ss: https://docs.google.com/spreadsheets/d/{score_data['student_ss_id']}")
      score_data = act_answers_to_student_ss(score_data)
      post_ss_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
      student_ss_mem = post_ss_mem - mem_post_report
      logging.info(f"Student SS import used {student_ss_mem:.2f} MB of memory")

    send_act_pdf_report(ss_copy_id, score_data)

  except Exception as e:
    logging.error(f'Error creating and sending ACT report: {e}')
    raise e


@celery.task(name='app.tasks.style_custom_sat_spreadsheet_task', bind=True, base=MyTaskBaseClass)
def style_custom_sat_spreadsheet_task(self, organization_data):
  try:
    logging.info(f"Styling SAT spreadsheet for {organization_data['name']}")
    style_custom_sat_spreadsheet(organization_data)
  except Exception as e:
    logging.error(f'Error styling SAT spreadsheet: {e}')
    raise e


@celery.task(name='app.tasks.style_custom_act_spreadsheet_task', bind=True, base=MyTaskBaseClass)
def style_custom_act_spreadsheet_task(self, organization_data):
  try:
    logging.info(f"Styling ACT spreadsheet for {organization_data['name']}")
    style_custom_act_spreadsheet(organization_data)
  except Exception as e:
    logging.error(f'Error styling ACT spreadsheet: {e}')
    raise e

@celery.task(name='app.tasks.create_test_prep_folder_task', bind=True, base=MyTaskBaseClass)
def create_test_prep_folder_task(self, student_name):
  try:
    logging.info(f"Creating test prep folder for {student_data.get('student_name', 'unknown student')}")
    create_test_prep_folder(student_data)
  except Exception as e:
    logging.error(f'Error creating test prep folder: {e}')
    raise e