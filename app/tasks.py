import os
from celery import Celery
from app.create_report import create_sat_score_report, send_pdf_score_report, delete_spreadsheet
import logging


info_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs/info.log')
logging.basicConfig(filename=info_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
def create_and_send_sat_report(score_data):
    spreadsheet_id = create_sat_score_report(score_data)
    send_pdf_score_report(spreadsheet_id, score_data)
    delete_spreadsheet(spreadsheet_id)