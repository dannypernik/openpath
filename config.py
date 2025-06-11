import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') is not None
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    ALTCHA_SITE_KEY = os.environ.get('ALTCHA_SITE_KEY')
    ALTCHA_SECRET_KEY = os.environ.get('ALTCHA_SECRET_KEY')
    HCAPTCHA_SITE_KEY = os.environ.get('HCAPTCHA_SITE_KEY')
    HCAPTCHA_SECRET_KEY = os.environ.get('HCAPTCHA_SECRET_KEY')
    MAILJET_KEY = os.environ.get('MAILJET_KEY')
    MAILJET_SECRET = os.environ.get('MAILJET_SECRET')
    # MOM_EMAIL = os.environ.get('MOM_EMAIL')
    # DAD_EMAIL = os.environ.get('DAD_EMAIL')
    ADMINS = [os.environ.get('ADMINS')]
    HELLO_EMAIL = os.environ.get('HELLO_EMAIL')
    PHONE = os.environ.get('PHONE')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
    ONEPAGECRM_ID = os.environ.get('ONEPAGECRM_ID')
    ONEPAGECRM_PW = os.environ.get('ONEPAGECRM_PW')
    TODOIST_ID = os.environ.get('TODOIST_ID')
    GAS_DEPLOYMENT_ID = os.environ.get('GAS_DEPLOYMENT_ID')
    SCORE_REPORT_SS_ID = os.environ.get('SCORE_REPORT_SS_ID')
    RESOURCE_FOLDER_ID = os.environ.get('RESOURCE_FOLDER_ID')