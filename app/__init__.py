import os
import sentry_sdk
from flask import Flask
from config import Config
from sqlalchemy import MetaData
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
import logging
from logging.handlers import SMTPHandler, RotatingFileHandler
from flask_bootstrap import Bootstrap
from flask_hcaptcha import hCaptcha
from functools import wraps
from celery import Celery

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db, render_as_batch=True, compare_type=True)
login = LoginManager(app)
login.login_view = 'login'
bootstrap = Bootstrap(app)
hcaptcha = hCaptcha(app)

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend='redis://localhost:6379/0',
        broker='redis://localhost:6379/0'
    )
    celery.conf.update(app.config)
    return celery

celery = make_celery(app)

def full_name(user):
    if user.last_name == '' or user.last_name is None:
        name = user.first_name
    else:
        name = user.first_name + ' ' + user.last_name
    return name

from app import routes, models, errors, tasks
app.config['TEMPLATES_AUTO_RELOAD'] = True
login.login_message = u'Please sign in to access this page.'
