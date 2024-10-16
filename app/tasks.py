import os
from app import celery
from app.create_report import create_sat_score_report, send_pdf_score_report
from app.email import send_fail_mail
import logging
# import cProfile
# import pstats


# info_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/info.log')
# logging.basicConfig(filename=info_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# app = Celery('tasks', broker='redis://localhost:6379/0')
# app.conf.result_backend = 'redis://localhost:6379/0'

@celery.task(name='app.tasks.create_and_send_sat_report')
def create_and_send_sat_report(score_data):
  try:
    # profiler = cProfile.Profile()
    # profiler.enable()
    spreadsheet_id = create_sat_score_report(score_data)
    send_pdf_score_report(spreadsheet_id, score_data)
    print('SAT report created and sent')
  except Exception as e:
    logging.error(f'Error creating and sending SAT report: {e}')
    send_fail_mail(score_data, 'create_and_send_sat_report(score_data)', e)
    raise e
  # finally:
    # profiler.disable()
    # profile_output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/profile_stats.txt')
    # with open(profile_output_path, 'w') as f:
    #     stats = pstats.Stats(profiler, stream=f).sort_stats('cumtime')
    #     stats.print_stats(10)  # Print the top 10 functions by cumulative time

# @celery.task(name='app.tasks.send_sat_report_task')
# def send_sat_report_task(spreadsheet_id, score_data):
#   try:
#     # profiler = cProfile.Profile()
#     # profiler.enable()
#     send_pdf_score_report(spreadsheet_id, score_data)
#   except Exception as e:
#     logging.error(f'Error creating and sending SAT report: {e}')
#     send_fail_mail(score_data, 'create_and_send_sat_report(score_data)', e)
#     raise e
#   # finally:
#   #   profiler.disable()
#   #   profile_output_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/profile_stats.txt')
#   #   with open(profile_output_path, 'w') as f:
#   #       stats = pstats.Stats(profiler, stream=f).sort_stats('cumtime')
#   #       stats.print_stats(10)  # Print the top 10 functions by cumulative time

