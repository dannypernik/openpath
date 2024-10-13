from celery import Celery
from app.create_report import create_sat_score_report, send_pdf_score_report, delete_spreadsheet

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
def create_and_send_sat_report(score_data):
    spreadsheet_id = create_sat_score_report(score_data)
    send_pdf_score_report(spreadsheet_id, score_data)
    delete_spreadsheet(spreadsheet_id)