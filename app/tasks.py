import os
import logging
import resource
from celery import chain

from app import celery
from app.create_sat_report import create_sat_score_report, send_sat_pdf_report, \
    sat_answers_to_student_ss, style_custom_sat_spreadsheet, \
    update_sat_org_logo, update_sat_partner_logo
from app.create_act_report import create_act_score_report, send_act_pdf_report, \
    act_answers_to_student_ss, process_act_answer_img, style_custom_act_spreadsheet, \
    update_act_org_logo, update_act_partner_logo
from app.new_student_folders import create_test_prep_folder, create_folder
from app.models import User
from app.helpers import full_name
from app.email import send_task_fail_mail, send_new_student_email
from app.utils import create_crm_action, color_svg_white_to_input


class MyTaskBaseClass(celery.Task):
    autoretry_for = (Exception,)
    retry_backoff = 10
    retry_kwargs = {'max_retries': 3}

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logging.info(f'Retry #{self.request.retries + 1} for task {task_id} due to: {exc}')

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logging.error(f'Task {task_id} raised exception: {exc}')
        score_data = args[0] if args else kwargs.get('score_data')
        if not score_data:
            logging.error("Score data is missing. Cannot send failure email.")
            return
        if self.request.retries >= self.max_retries:
            send_task_fail_mail(score_data, exc, task_id, args, kwargs, einfo)


class SsUpdateTaskClass(celery.Task):
    autoretry_for = (Exception,)
    retry_backoff = 10
    retry_kwargs = {'max_retries': 3}
    acks_late = True
    reject_on_worker_lost = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logging.info(f'Retry #{self.request.retries + 1} for task {task_id} due to: {exc}')

    def on_failure(self, exc, task_id, args, kwargs, einfo):
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
    logging.info(f"SAT score report used {score_report_mem:.2f} MB of memory")

    send_sat_pdf_report(ss_copy_id, score_data_updated)

    return score_data_updated

  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    raise e

@celery.task(name='app.tasks.send_sat_answers_to_ss_task', bind=True, base=SsUpdateTaskClass)
def send_sat_answers_to_ss_task(self, score_data):
  mem_post_report = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

  if score_data['student_ss_id']:
    logging.info(f"SAT student ss: https://docs.google.com/spreadsheets/d/{score_data['student_ss_id']}")
    score_data = sat_answers_to_student_ss(score_data)
    post_ss_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    student_ss_mem = post_ss_mem - mem_post_report
    logging.info(f"SAT student SS import used {student_ss_mem:.2f} MB of memory")

  return score_data


@celery.task(name='app.tasks.sat_report_workflow_task', bind=True, base=MyTaskBaseClass)
def sat_report_workflow_task(self, score_data, organization_dict=None):
  chain(
    create_and_send_sat_report_task.s(score_data),
    send_sat_answers_to_ss_task.s()
  ).apply_async()


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
    logging.info(f"ACT score report used {score_report_mem:.2f} MB of memory")

    send_act_pdf_report(ss_copy_id, score_data)

    return score_data

  except Exception as e:
    logging.error(f'Error creating and sending ACT report: {e}')
    raise e


@celery.task(name='app.tasks.send_act_answers_to_ss_task', bind=True, base=SsUpdateTaskClass)
def send_act_answers_to_ss_task(self, score_data):
  mem_post_report = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

  if score_data['student_ss_id']:
    logging.info(f"Student ACT ss: https://docs.google.com/spreadsheets/d/{score_data['student_ss_id']}")
    score_data = act_answers_to_student_ss(score_data)
    post_ss_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    student_ss_mem = post_ss_mem - mem_post_report
    logging.info(f"ACT student SS import used {student_ss_mem:.2f} MB of memory")

  return score_data


@celery.task(name='app.tasks.act_report_workflow_task', bind=True, base=MyTaskBaseClass)
def act_report_workflow_task(self, score_data, organization_dict=None):
  chain(
    create_and_send_act_report_task.s(score_data),
    send_act_answers_to_ss_task.s()
  ).apply_async()


@celery.task(name='app.tasks.style_custom_spreadsheets_task', bind=True, base=MyTaskBaseClass)
def style_custom_spreadsheets_task(self, organization_data):
  try:
    if organization_data['ss_logo_path']:
      logging.info(f"Adding org logo to {organization_data['name']} spreadsheets")
      update_sat_org_logo(organization_data)
      update_act_org_logo(organization_data)

    if organization_data['is_style_updated']:
      if not os.path.exists(organization_data['partner_logo_path']):
        logging.info(f"Creating partner logo for {organization_data['name']}")
        output_path = os.path.join(organization_data['static_path'], organization_data['partner_logo_path'])
        color_svg_white_to_input(organization_data['svg_path'], organization_data['logo_color'], output_path)

      logging.info(f"Adding partner logo to {organization_data['name']} spreadsheets")
      update_sat_partner_logo(organization_data)
      update_act_partner_logo(organization_data)

      logging.info(f"Styling SAT spreadsheet for {organization_data['name']}")
      style_custom_sat_spreadsheet(organization_data)
      logging.info(f"Styling ACT spreadsheet for {organization_data['name']}")
      style_custom_act_spreadsheet(organization_data)
  except Exception as e:
    logging.error(f'Error styling SAT spreadsheet: {e}')
    send_task_fail_mail(organization_data, e, self.request.id, [organization_data], {}, None)
    raise e


@celery.task(name='app.tasks.new_student_task', bind=True)
def new_student_task(self, contact_data):
  try:
    student = contact_data['student']
    parent = contact_data['parent']
    test_type = student.get('subject', '').lower()

    crm_data = {
      'first_name': parent.get('first_name'),
      'last_name': parent.get('last_name'),
      'email': parent.get('email'),
      'phone': parent.get('phone', ''),
      'company_name': student.get('last_name', '')
    }

    try:
      contact_data['folder_id'] = create_folder(f'{full_name(student)} (Incomplete)')
      logging.info(f"Test prep folder initiated for {student.get('first_name', 'student')} {student.get('last_name', '')}")
    except Exception as e:
      logging.error(f'Test prep folder failed to initiate for {full_name(student)}: {e}')
      contact_data['folder_id'] = None

    send_new_student_email(contact_data)
    create_crm_action(crm_data, f'Scheduling/followup for {student.get("first_name", "")}')

    if contact_data.get('create_folder'):
      logging.info(f"Creating test prep folder for {full_name(student)}")
      folder_link = create_test_prep_folder(contact_data, test_type, contact_data.get('folder_id'))
    else:
      folder_link = None

    return folder_link

  except Exception as e:
    logging.error(f'Error creating test prep folder: {e}')
    send_task_fail_mail(contact_data, e, self.request.id, [contact_data], {}, None)
    raise e