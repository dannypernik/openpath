import os
from flask import Flask, render_template, flash, Markup, redirect, url_for, \
    request, send_from_directory, send_file, make_response, abort
from app import app, db, login, hcaptcha, full_name
from app.utils import is_dark_color, color_svg_white_to_input
from app.forms import InquiryForm, EmailListForm, TestStrategiesForm, SignupForm, LoginForm, \
    StudentForm, ScoreAnalysisForm, TestDateForm, UserForm, RequestPasswordResetForm, \
    ResetPasswordForm, TutorForm, RecapForm, NtpaForm, SATReportForm, ACTReportForm, \
    ReviewForm, OrgSettingsForm, FreeResourcesForm, NominationForm, StudentIntakeForm
from flask_login import current_user, login_user, logout_user, login_required, login_url
from app.models import User, TestDate, UserTestDate, TestScore, Review, Organization
from werkzeug.urls import url_parse
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from app.email import send_contact_email, send_verification_email, send_password_reset_email, \
    send_test_strategies_email, send_score_analysis_email, send_test_registration_email, \
    send_prep_class_email, send_signup_notification_email, send_session_recap_email, \
    send_confirmation_email, send_changed_answers_email, send_schedule_conflict_email, \
    send_ntpa_email, send_fail_mail, send_free_resources_email, send_nomination_email, \
    send_signup_request_email, send_unsubscribe_email
from functools import wraps
import requests
import json
from reminders import get_student_events
from app.score_reader import get_all_data
from app.create_sat_report import check_service_account_access, create_custom_sat_spreadsheet
from app.create_act_report import create_custom_act_spreadsheet
from app.tasks import create_and_send_sat_report_task, create_and_send_act_report_task, \
    style_custom_sat_spreadsheet_task, style_custom_act_spreadsheet_task
import logging
from googleapiclient.errors import HttpError
import traceback
from redis import Redis
from PIL import Image
from pillow_heif import register_heif_opener
from pypdf import PdfReader
import base64
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials


logger = logging.getLogger(__name__)
logging.basicConfig(filename='logs/info.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@app.before_request
def before_request():
    if current_user and current_user.is_authenticated:
        current_user.last_viewed = datetime.utcnow()
        db.session.commit()

def dir_last_updated(folder):
    return str(max(os.path.getmtime(os.path.join(root_path, f))
                   for root_path, dirs, files in os.walk(folder)
                   for f in files))

hello = app.config['HELLO_EMAIL']
phone = app.config['PHONE']

@app.context_processor
def inject_values():
    try:
        if current_user and current_user.is_authenticated:
            current_first_name = current_user.first_name
            current_last_name = current_user.last_name
        else:
            current_first_name = None
            current_last_name = None
    except Exception:
        current_first_name = None
        current_last_name = None
    return dict(
        last_updated=dir_last_updated('app/static'),
        hello=hello,
        phone=phone,
        current_first_name=current_first_name,
        current_last_name=current_last_name
    )

def get_next_page():
    next_page = request.args.get('next')
    if not next_page in app.view_functions:
        next_page = 'start_page'
    return next_page

def admin_required(f):
    @login_required
    @wraps(f)
    def wrap(*args, **kwargs):
        if current_user.is_admin:
            return f(*args, **kwargs)
        else:
            flash('You must have administrator privileges to access this page.', 'error')
            logout_user()
            return redirect(url_for('signin', next=request.endpoint, org=request.view_args.get('org')))
    return wrap

def proper(name):
    try:
        name = name.title()
        return name
    except:
        return name

register_heif_opener()

def convert_heic_to_jpg(heic_path, quality=90):
    """Convert a HEIC image to JPG."""
    try:
        file_prefix = os.path.splitext(heic_path)[0]
        jpg_path = f'{file_prefix}.jpg'
        with Image.open(heic_path) as img:
            rgb_img = img.convert('RGB')
            rgb_img.save(jpg_path, 'JPEG', quality=quality)
        return jpg_path
    except Exception as e:
        print(f"Failed to convert HEIC to JPG: {e}")
        return False

def is_valid_image(file):
    try:
        img = Image.open(file)
        img.verify()  # Verify that it is, indeed, an image
        return True
    except (IOError, SyntaxError):
        return False

def is_valid_pdf(file):
    try:
        reader = PdfReader(file)
        # Attempt to read the first page to ensure it's a valid PDF
        if len(reader.pages) > 0:
            return True
    except Exception:
        return False
    finally:
        file.stream.seek(0)
    return False

def get_image_info(file_path):
    try:
        with Image.open(file_path) as img:
            file_format = img.format
            # content_type = Image.MIME.get(file_format)
            file_extension = file_format.lower()
            if file_extension in ('jpeg', 'mpo'):
                file_extension = 'jpg'
            elif file_extension in ('heif', 'heic'):
                file_extension = 'heic'
            # return content_type, file_extension
            return file_extension
    except Exception as e:
        print(f"Image format error: {e}")
        return None, None
    finally:
        # Reset the file pointer if it's a file-like object
        if hasattr(file_path, 'stream'):
            file_path.stream.seek(0)
        else:
            file_path.seek(0)


def add_user_to_drive_folder(email, folder_id):
    """Add a user as a viewer to a Google Drive folder without sending a notification email."""
    # Authenticate using the Service Account
    credentials = Credentials.from_service_account_file('service_account_key.json')
    service = build('drive', 'v3', credentials=credentials, cache_discovery=False)

    # Create permission
    permission = {
        'type': 'user',
        'role': 'reader',
        'emailAddress': email
    }

    # Add permission to the folder without sending a notification email
    service.permissions().create(
        fileId=folder_id,
        body=permission,
        fields='id',
        sendNotificationEmail=False  # Suppress email notification
    ).execute()


def load_act_test_codes():
    try:
        with open('app/act_test_codes.json') as f:
            codes = json.load(f)
        return [
            (code[0], f"{code[0]} (Form {code[1]})")
            for code in codes if code and code[0].strip() and code[1].strip()
        ]
    except Exception:
        print("Error loading ACT test codes from act_test_codes.json")
        return []


# def validate_altcha_response(token):
#     """Validate Altcha response token."""
#     altcha_secret_key = app.config['ALTCHA_SECRET_KEY']
#     url = "https://us.altcha.org/api/v1/verify"
#     payload = {
#         "secret": altcha_secret_key,
#         "response": token
#     }
#     response = requests.post(url, json=payload)
#     result = response.json()
#     return result.get("success", False)


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
def index():
    form = InquiryForm()
    altcha_site_key = app.config['ALTCHA_SITE_KEY']
    if form.validate_on_submit():
        # altcha_token = request.form.get('altcha-response')
        # if not validate_altcha_response(altcha_token):
        #     flash('Captcha verification failed. Please try again.', 'error')
        #     return redirect(url_for('index', _anchor='home'))
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('index', _anchor='home'))
        user = User(first_name=form.first_name.data, email=form.email.data, phone=form.phone.data)
        message = form.message.data
        subject = form.subject.data
        # new_contact = {
        #     'first_name': user.first_name, 'last_name': 'OPT web form', \
        #     'emails': [{ 'type': 'home', 'value': user.email}], \
        #     'phones': [{ 'type': 'mobile', 'value': user.phone}], \
        #     'tags': ['Website']
        # }
        # crm_contact = requests.post('https://app.onepagecrm.com/api/v3/contacts', json=new_contact, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        # if crm_contact.status_code == 201:
        #     print('crm_contact passes')
        #     new_action = {
        #         'contact_id': crm_contact.json()['data']['contact']['id'],
        #         'assignee_id': app.config['ONEPAGECRM_ID'],
        #         'status': 'asap',
        #         'text': 'Respond to OPT web form',
        #         #'date': ,
        #         #'exact_time': 1526472000,
        #         #'position': 1
        #     }
        #     crm_action = requests.post('https://app.onepagecrm.com/api/v3/actions', json=new_action, auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
        #     print('crm_action:', crm_action)

        email_status = send_contact_email(user, message, subject)
        if email_status == 200:
            conf_status = send_confirmation_email(user.email, message)
            if conf_status == 200:
                flash('Thank you for reaching out! We\'ll be in touch.')
                return redirect(url_for('index', _anchor='home'))
        flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('index.html', form=form, last_updated=dir_last_updated('app/static'), altcha_site_key=altcha_site_key)


@app.route('/team', methods=['GET', 'POST'])
def team():
    team_members = User.query.order_by(User.phone.asc()).filter(User.role.in_(['tutor', 'admin'])).filter_by(status='active')
    return render_template('team.html', title='Our Team', full_name=full_name, team_members=team_members)


@app.route('/mission', methods=['GET', 'POST'])
def mission():
    form = FreeResourcesForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if not user:
            user = User(first_name=form.first_name.data, email=form.email.data.lower())
            try:
                db.session.add(user)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                flash('An error occurred. Please try again later.', 'error')
                logger.error(f"Error adding user: {e}", exc_info=True)

        try:
            folder_id = app.config['RESOURCE_FOLDER_ID']  # Replace with your folder ID
            add_user_to_drive_folder(user.email, folder_id)

            email_status = send_free_resources_email(user)
            if email_status == 200:
                flash('Your free resources are on their way to your inbox!', 'success')
            else:
                flash(Markup('Email failed to send. Please contact <a href="mailto:' + hello + '" target="_blank">' + hello + '</a>'), 'error')
        except Exception as e:
            logger.error(f"Error adding user to Google Drive folder: {e}", exc_info=True)
            flash('An error occurred while granting access to resources. Please try again later.', 'error')
    return render_template('mission.html', title='Our mission', form=form)


@app.route('/nominate', methods=['GET', 'POST'])
def nominate():
    form = NominationForm()
    if form.validate_on_submit():

        form_data = {
            'student_first_name': form.student_first_name.data,
            'student_last_name': form.student_last_name.data,
            'student_email': form.student_email.data,
            'is_anonymous': form.is_anonymous.data,
            'is_self_nomination': form.is_self_nomination.data,
            'is_caregiver_nomination': form.is_caregiver_nomination.data,
            'parent_first_name': form.parent_first_name.data,
            'parent_last_name': form.parent_last_name.data,
            'parent_email': form.parent_email.data,
            'nomination_text': form.nomination_text.data,
        }

        if form_data['is_self_nomination']:
            form_data['contact_email'] = form_data['student_email']
        elif form_data['is_caregiver_nomination']:
            form_data['contact_email'] = form_data['parent_email']
        else:
            form_data['contact_email'] = form_data['nominator_email']
            form_data['nominator_first_name'] = form.nominator_first_name.data
            form_data['nominator_last_name'] = form.nominator_last_name.data
            form_data['nominator_email'] = form.nominator_email.data

        email_status = send_nomination_email(form_data)
        if email_status == 200:
            send_confirmation_email(form_data['contact_email'], form_data['nomination_text'])
            flash('Thank you for your nomination! We will be in touch.')
            return redirect(url_for('index'))
        else:
            flash('An error occurred. Please contact ' + hello, 'error')
            logging.error(f"Error processing nomination. Email status {email_status}")
    return render_template('nominate.html', form=form)


@app.route('/about')
def about():
    return render_template('about.html', title='About')

@app.route('/reviews')
def reviews():
    form = ReviewForm()
    reviews = Review.query.order_by(Review.timestamp.desc()).all()
    if form.validate_on_submit():
        # photo = request.files['photo']
        # photo_path = os.path.join('img/schools/', str(user_id) + '.' + secure_filename(photo.filename).split('.')[-1])
        # photo.save(os.path.join('app/static', photo_path))
        review = Review(text=form.text.data, author=form.author.data, timestamp=datetime.utcnow())
        try:
            db.session.add(review)
            db.session.commit()
            flash('Thank you for your review!')
        except:
            db.session.rollback()
            flash('Review could not be added', 'error')
        return redirect(url_for('reviews'))
    return render_template('reviews.html', title='Reviews', reviews=reviews, form=form)


@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if current_user.is_authenticated:
        flash('You are already signed in.')
        return redirect(url_for('start_page'))
    form = LoginForm()
    signup_form = SignupForm()
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    form = LoginForm()
    signup_form = SignupForm()
    next = get_next_page()
    if signup_form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('signin', next=next))
        email_exists = User.query.filter_by(email=signup_form.email.data.lower()).first()
        if email_exists:
            flash('An account already exists for this email. Try logging in or resetting your password.', 'error')
            return redirect(url_for('signin', next=next))
        user = User(first_name=signup_form.first_name.data, last_name=signup_form.last_name.data, \
            email=signup_form.email.data.lower())
        # user.set_password(signup_form.password.data)
        db.session.add(user)
        db.session.commit()
        # email_status = send_verification_email(user)
        # login_user(user)
        email_status = send_signup_request_email(user, next)
        if email_status == 200:
            flash('Thanks for reaching out! We\'ll be in touch.')
            return redirect(url_for('index'))
        else:
            flash('Signup request email failed to send, please contact ' + hello, 'error')
        return redirect(url_for(next, org=request.view_args.get('org')))
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        flash('You are already signed in.')
        return redirect(url_for('start_page'))
    form = LoginForm()
    signup_form = SignupForm()
    next = get_next_page()
    org = request.args.get('org')

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('signin', next=next))
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and not user.password_hash:
            flash('Please verify your email to set or reset your password.')
            return redirect(url_for('request_password_reset'))
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('signin', next=next))
        login_user(user)
        if not user.is_verified:
            email_status = send_verification_email(user)
            if email_status == 200:
                flash('Please check your inbox to verify your email.')
            else:
                flash('Verification email did not send. Please contact ' + hello, 'error')
        return redirect(url_for(next, org=org))
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('signin'))


@app.route('/start-page')
@login_required
def start_page():
    if current_user.is_admin:
        return redirect(url_for('students'))
    elif current_user.password_hash:
        return redirect(url_for('test_reminders'))
    else:
        return redirect(url_for('set_password'))


@app.route('/verify-email/<token>', methods=['GET', 'POST'])
def verify_email(token):
    logout_user()
    user = User.verify_email_token(token)
    next = get_next_page()
    if user:
        login_user(user)
        user.is_verified = True
        db.session.add(user)
        db.session.commit()
        flash('Thank you for verifying your account.')
        if user.password_hash:
            return redirect(url_for(next, org=request.view_args.get('org')))
        else:
            return redirect(url_for('set_password', token=token, next=next))
    else:
        flash('Your verification link is expired or invalid. Log in to receive a new link.')
        return redirect(url_for('signin'))


@app.route('/unsubscribe', methods=['GET', 'POST'])
def unsubscribe():
    form = RequestPasswordResetForm()  # Reuse an existing form with an email field

    email = request.args.get('email')
    if email:
        form.email.data = email

    if form.validate_on_submit():
        email = form.email.data.lower()
        try:
            # Send an email notification to you
            email_status = send_unsubscribe_email(email)
            if email_status == 200:
                flash('Your request has been received. We will remove you from the SAT resources folder so you don\'t receive update emails.', 'success')
            else:
                flash('Failed to process your request. Please contact us directly.', 'error')
        except Exception as e:
            flash('An error occurred while processing your request. Please try again later.', 'error')
            logger.error(f"Error processing unsubscribe request: {e}", exc_info=True)
        return redirect(url_for('index'))
    return render_template('unsubscribe.html', title='Unsubscribe', form=form)


@app.route('/request-password-reset', methods=['GET', 'POST'])
def request_password_reset():
    form = RequestPasswordResetForm()

    next = get_next_page()
    if request.method == 'GET':
        email = request.args.get('email')
        if email:
            form.email.data = email

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('request_password_reset'))


        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            email_status = send_password_reset_email(user, next)
            if email_status == 200:
                flash('Check your email for instructions to reset your password.')
            else:
                flash('Email failed to send, please contact ' + hello, 'error')
        else:
            flash('Check your email for instructions to reset your password')
        return redirect(url_for('signin'))
    return render_template('request-password-reset.html', title='Reset password', form=form)


@app.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    user = User.verify_email_token(token)
    next = request.args.get('next')
    if not user:
        flash('The password reset link is expired or invalid. Please try again.')
        return redirect(url_for('request_password_reset', next=next))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.is_verified = True
        db.session.commit()
        login_user(user)
        flash('Your password has been saved.')
        if next in app.view_functions:
            return redirect(url_for(next))
        else:
            return redirect(url_for('start_page'))
    return render_template('set-password.html', form=form)


@app.route('/users', methods=['GET', 'POST'])
@admin_required
def users():
    form = UserForm(None)
    roles = User.query.with_entities(User.role).distinct()
    users = User.query.order_by(User.first_name, User.last_name).all()
    parents = User.query.filter_by(role='parent')
    parent_list = [(0,'')]+[(u.id, full_name(u)) for u in parents]
    tutors = User.query.filter_by(role='tutor')
    tutor_list = [(0,'')]+[(u.id, full_name(u)) for u in tutors]
    form.parent_id.choices = parent_list
    form.tutor_id.choices = tutor_list
    if form.validate_on_submit():
        user = User(first_name=form.first_name.data, last_name=form.last_name.data, \
            email=form.email.data.lower(), secondary_email=form.secondary_email.data.lower(), \
            phone=form.phone.data, timezone=form.timezone.data, location=form.location.data, \
            role=form.role.data, status='active', is_admin=False, \
            session_reminders=True, test_reminders=True)
        user.tutor_id=form.tutor_id.data
        user.status=form.status.data
        user.parent_id=form.parent_id.data
        if form.tutor_id.data == 0:
            user.tutor_id=None
        if form.parent_id.data == 0:
            user.parent_id=None
        if form.status.data == 'none':
            user.status=None
        try:
            db.session.add(user)
            db.session.commit()
            flash(user.first_name + ' added')
        except:
            db.session.rollback()
            flash(user.first_name + ' could not be added', 'error')
            return redirect(url_for('users'))
        return redirect(url_for('users'))
    return render_template('users.html', title='Users', form=form, users=users, roles=roles, \
        full_name=full_name, proper=proper)


@app.route('/edit-user/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    form = UserForm(user.email, obj=user)
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.date > datetime.today().date())
    parents = User.query.order_by(User.first_name, User.last_name).filter_by(role='parent')
    parent_list = [(0,'')]+[(u.id, full_name(u)) for u in parents]
    tutors = User.query.order_by(User.first_name, User.last_name).filter_by(role='tutor')
    tutor_list = [(0,'')]+[(u.id, full_name(u)) for u in tutors]
    form.parent_id.choices = parent_list
    form.tutor_id.choices = tutor_list
    registered_tests = []
    interested_tests = []

    if form.validate_on_submit():
        if 'save' in request.form:
            user.first_name=form.first_name.data
            user.last_name=form.last_name.data
            user.email=form.email.data.lower()
            user.phone=form.phone.data
            user.secondary_email=form.secondary_email.data.lower()
            user.timezone=form.timezone.data
            user.location=form.location.data
            user.status=form.status.data
            user.role=form.role.data
            user.title=form.title.data
            user.grad_year=form.grad_year.data
            user.is_admin=form.is_admin.data
            user.session_reminders=form.session_reminders.data
            user.test_reminders=form.test_reminders.data
            if form.tutor_id.data == 0:
                user.tutor_id=None
            else:
                user.tutor_id=form.tutor_id.data
            if form.parent_id.data == 0:
                user.parent_id=None
            else:
                user.parent_id=form.parent_id.data
            if form.grad_year.data == 0:
                user.grad_year=None
            else:
                user.grad_year=form.grad_year.data

            test_selections = request.form.getlist('test_dates')
            for d in upcoming_dates:
                if str(d.id) + '-interested' in test_selections:
                    user.interested_test_date(d)
                elif str(d.id) + '-registered' in test_selections:
                    user.register_test_date(d)
                else:
                    user.remove_test_date(d)
            try:
                db.session.add(user)
                db.session.commit()
                flash(user.first_name + ' updated')
            except:
                db.session.rollback()
                flash(user.first_name + ' could not be updated', 'error')
                return redirect(url_for('users'))
        elif 'delete' in request.form:
            db.session.delete(user)
            db.session.commit()
            flash('Deleted ' + user.first_name)
        else:
            flash('Code error in POST request', 'error')
        if user.role == 'student' or user.role == 'tutor':
            return redirect(url_for(user.role + 's'))
        else:
            return redirect(url_for('users'))
    elif request.method == 'GET':
        form.first_name.data=user.first_name
        form.last_name.data=user.last_name
        form.email.data=user.email
        form.phone.data=user.phone
        form.secondary_email.data=user.secondary_email
        form.timezone.data=user.timezone
        form.location.data=user.location
        form.status.data=user.status
        form.role.data=user.role
        form.title.data=user.title
        form.grad_year.data=user.grad_year
        form.tutor_id.data=user.tutor_id
        form.parent_id.data=user.parent_id
        form.is_admin.data=user.is_admin
        form.test_reminders.data=user.test_reminders

        ##  Determine which option to select in template for each test date
        test_selections = user.get_dates().all()
        for d in upcoming_dates:
            if d in test_selections:
                if user.is_registered(d):
                    registered_tests.append(d.id)
                else:
                    interested_tests.append(d.id)

    return render_template('edit-user.html', title=full_name(user), form=form, user=user, \
        tests=tests, upcoming_dates=upcoming_dates, registered_tests=registered_tests, \
        interested_tests=interested_tests)


@app.route('/students', methods=['GET', 'POST'])
@admin_required
def students():
    form = StudentForm()
    students = User.query.order_by(User.first_name, User.last_name).filter_by(role='student')
    parents = User.query.order_by(User.first_name, User.last_name).filter_by(role='parent')
    parent_list = [(0,'New parent')]+[(u.id, full_name(u)) for u in parents]
    form.parent_id.choices = parent_list
    tutors = User.query.filter_by(role='tutor')
    tutor_list = [(u.id, full_name(u)) for u in tutors]
    form.tutor_id.choices = tutor_list
    status_order = ['prospective', 'active', 'paused', 'inactive']
    statuses = []
    for s in status_order:
        if User.query.filter(User.status == s).first():
            statuses.append(s)
    other_students = User.query.filter((User.role=='student') & (User.status.notin_(statuses)))
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.status != 'past')
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    registered_tests = []
    interested_tests = []

    if form.validate_on_submit():
        student = User(first_name=form.student_name.data, last_name=form.student_last_name.data, \
            email=form.student_email.data.lower(), phone=form.student_phone.data, timezone=form.timezone.data, \
            location=form.location.data, status=form.status.data, tutor_id=form.tutor_id.data, \
            role='student', grad_year=form.grad_year.data, session_reminders=True, test_reminders=True)
        if form.parent_id.data == 0:
            parent = User(first_name=form.parent_name.data, last_name=form.parent_last_name.data, \
                email=form.parent_email.data.lower(), secondary_email=form.secondary_email.data.lower(), \
                phone=form.parent_phone.data, timezone=form.timezone.data, role='parent', \
                session_reminders=True, test_reminders=True)
        else:
            parent = User.query.filter_by(id=form.parent_id.data).first()


        try:
            db.session.add(parent)
            db.session.flush()
            student.parent_id = parent.id
            db.session.add(student)
            db.session.commit()
            test_selections = request.form.getlist('test_dates')
            for d in upcoming_dates:
                if str(d.id) + '-interested' in test_selections:
                    student.interested_test_date(d)
                elif str(d.id) + '-registered' in test_selections:
                    student.register_test_date(d)
        except:
            db.session.rollback()
            flash(student.first_name + ' could not be added', 'error')
            return redirect(url_for('students'))
        flash(student.first_name + ' added')
        return redirect(url_for('students'))
    return render_template('students.html', title='Students', form=form, students=students, \
        statuses=statuses, upcoming_dates=upcoming_dates, tests=tests, other_students=other_students, \
        full_name=full_name, proper=proper)


@app.route('/new-student', methods=['GET', 'POST'])
def new_student():
    form = StudentIntakeForm()

    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.status != 'past')
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    registered_tests = []
    interested_tests = []

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('students'))

        try:
            parent = User.query.filter_by(email=form.parent_email.data.lower()).first()
            if parent:
                parent.first_name = form.parent_first_name.data
                parent.last_name = form.parent_last_name.data
                parent.secondary_email = form.parent_email_2.data.lower()
                parent.phone = form.parent_phone.data
                parent.timezone = form.timezone.data
                parent.role = 'parent'
            else:
                parent = User(first_name=form.parent_first_name.data, last_name=form.parent_last_name.data, \
                    email=form.parent_email.data.lower(), secondary_email=form.parent_email_2.data.lower(), \
                    phone=form.parent_phone.data, timezone=form.timezone.data, role='parent', \
                    session_reminders=True, test_reminders=True)

            student = User.query.filter_by(email=form.student_email.data.lower()).first()
            if student:
                student.first_name = form.student_first_name.data
                student.last_name = form.student_last_name.data
                student.phone = form.student_phone.data
                student.timezone = form.timezone.data
                student.role = 'student'
                student.status = 'active'
                student.grad_year = form.grad_year.data
            else:
                student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
                    email=form.student_email.data.lower(), phone=form.student_phone.data, timezone=form.timezone.data, \
                    status='prospective', role='student', grad_year=form.grad_year.data, session_reminders=True, test_reminders=True)

            db.session.add(parent)
            db.session.flush()
            student.parent_id = parent.id
            db.session.add(student)
            db.session.commit()
            test_selections = request.form.getlist('test_dates')
            for d in upcoming_dates:
                if str(d.id) + '-interested' in test_selections:
                    student.interested_test_date(d)
                elif str(d.id) + '-registered' in test_selections:
                    student.register_test_date(d)

            # email_status = send_new_student_email(student, parent, parent_2)
            # if email_status == 200:
            #     flash('New student form received. Thank you!')
            #     return redirect(url_for('test_dates'))
            # else:
            #     flash(Markup(f'Unexpected error. Please <a href="https://www.openpathtutoring.com#contact?subject=New%20student%20form%20error" target="_blank">contact us</a>'), 'error')
            #     return redirect(url_for('new_student'))
            # flash(student.first_name + ' added')
        except:
            db.session.rollback()
            flash(Markup(f'Unexpected error. Please <a href="https://www.openpathtutoring.com#contact?subject=New%20student%20form%20error" target="_blank">contact us</a>', 'error'))
            return redirect(url_for('new_student'))
    return render_template('new-student.html', title='Students', form=form, upcoming_dates=upcoming_dates, tests=tests)


@app.route('/tutors', methods=['GET', 'POST'])
@admin_required
def tutors():
    form = TutorForm()
    tutors = User.query.order_by(User.id.desc() ).filter_by(role='tutor')
    statuses = User.query.filter_by(role='tutor').with_entities(User.status).distinct()

    if form.validate_on_submit():
        tutor = User(first_name=form.first_name.data, last_name=form.last_name.data, \
            email=form.email.data.lower(), phone=form.phone.data, timezone=form.timezone.data, \
            session_reminders=form.session_reminders.data, test_reminders=form.test_reminders.data, \
            status='active', role='tutor')
        try:
            db.session.add(tutor)
            db.session.commit()
            flash(tutor.first_name + ' added')
        except:
            db.session.rollback()
            flash(tutor.first_name + ' could not be added', 'error')
            return redirect(url_for('tutors'))
        return redirect(url_for('tutors'))
    return render_template('tutors.html', title='Tutors', form=form, tutors=tutors, \
        statuses=statuses, full_name=full_name, proper=proper)


@app.route('/test-dates', methods=['GET', 'POST'])
def test_dates():
    form = TestDateForm()
    main_tests = ['sat', 'act']
    today = datetime.today().date()
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.date >= today)
    upcoming_date_ids = {date.id for date in upcoming_dates}
    upcoming_weekend_filter = (TestDate.test != 'psat') & (TestDate.status != 'school') & (TestDate.date >= today)
    upcoming_weekend_dates = TestDate.query.order_by(TestDate.date).filter(upcoming_weekend_filter)
    other_dates = TestDate.query.order_by(TestDate.date.desc()).filter(~upcoming_weekend_filter)
    upcoming_students = User.query.filter(
        (User.role=='student') & (User.status=='active') | (User.status=='prospective'))
    undecided_students = User.query.filter(~User.test_dates.any(TestDate.id.in_(upcoming_date_ids)) & (User.role=='student') & (User.status=='active') | (User.status=='prospective'))
    if form.validate_on_submit():
        date = TestDate(test=form.test.data, date=form.date.data, reg_date=form.reg_date.data, \
            late_date=form.late_date.data, other_date=form.other_date.data, \
            score_date=form.score_date.data, status=form.status.data)
        try:
            db.session.add(date)
            db.session.commit()
            flash(date.date.strftime('%b %-d') + ' ' + date.test.upper() + ' added')
        except:
            db.session.rollback()
            flash(date.date.strftime('%b %-d') + date.test.upper() + ' could not be added', 'error')
            return redirect(url_for('test_dates'))
        return redirect(url_for('test_dates'))
    return render_template('test-dates.html', title='Test dates', form=form, main_tests=main_tests,
        upcoming_weekend_dates=upcoming_weekend_dates, other_dates=other_dates,
        upcoming_students=upcoming_students, undecided_students=undecided_students)


@app.route('/edit-date/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_date(id):
    form = TestDateForm()
    date = TestDate.query.get_or_404(id)
    students = date.students
    if form.validate_on_submit():
        if 'save' in request.form:
            date.test=form.test.data
            date.date=form.date.data
            date.reg_date=form.reg_date.data
            date.late_date=form.late_date.data
            date.other_date=form.other_date.data
            date.score_date=form.score_date.data
            date.status=form.status.data

            registered_students = request.form.getlist('registered_students')
            for s in students:
                if s in registered_students:
                    s.is_registered = True
                else:
                    s.is_registered = False
            try:
                db.session.add(date)
                db.session.commit()
                flash(date.date.strftime('%b %-d') + ' updated')
            except:
                db.session.rollback()
                flash(date.date.strftime('%b %-d') + ' could not be updated', 'error')
                return redirect(url_for('test_dates'))
        elif 'delete' in request.form:
            db.session.delete(date)
            db.session.commit()
            flash('Deleted ' + date.date.strftime('%b %-d'))
        else:
            flash('Code error in POST request', 'error')
        return redirect(url_for('test_dates'))
    elif request.method == 'GET':
        form.test.data=date.test
        form.date.data=date.date
        form.reg_date.data=date.reg_date
        form.late_date.data=date.late_date
        form.other_date.data=date.other_date
        form.score_date.data=date.score_date
        form.status.data=date.status
    return render_template('edit-date.html', title='Edit date', form=form, date=date, \
        students=students)

@app.route('/recap', methods=['GET', 'POST'])
@admin_required
def recap():
    form = RecapForm()
    students = User.query.order_by(User.first_name, User.last_name).filter(
        (User.role=='student') & (User.status=='active') | (User.status=='prospective'))
    student_list = [(0, 'Student name')] + [(s.id, full_name(s)) for s in students] #[(0,'')] +
    form.students.choices = student_list
    if form.students.data == 0:
        flash('Please select a student', 'error')
    elif form.validate_on_submit():
        user = User.query.get_or_404(form.students.data)
        user.homework = form.homework.data
        user.date = form.date.data
        user.audio = form.audio.data
        events = get_student_events(full_name(user))

        email_status = send_session_recap_email(user, events)
        if email_status == 200:
            flash('Update email sent for ' + user.first_name)
        else:
            flash('Email failed to send', 'error')
        return redirect(url_for('recap'))
    return render_template('recap.html', form=form)


@app.route('/test-reminders', methods=['GET', 'POST'])
def test_reminders():
    form = EmailListForm()
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    today = datetime.today().date()
    reminder_cutoff = today + timedelta(days=5)
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.late_date >= reminder_cutoff)
    imminent_deadlines = TestDate.query.order_by(TestDate.date).filter(
        (TestDate.late_date > today) & (TestDate.late_date <= reminder_cutoff))
    selected_date_ids = []
    selected_date_strs = []
    if current_user.is_authenticated:
        user = User.query.filter_by(id=current_user.id).first()
        selected_dates = user.get_dates().all()
        for d in upcoming_dates:
            if d in selected_dates:
                selected_date_ids.append(d.id)
    if request.method == 'POST':
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('test_reminders'))
        selected_date_ids = request.form.getlist('test_dates')
        if not current_user.is_authenticated:
            user = User.query.filter_by(email=form.email.data).first()
            if not user:
                user = User(first_name=form.first_name.data, last_name='', email=form.email.data.lower())
            if not user.password_hash:   # User does not have password
                email_status = send_password_reset_email(user, 'test_reminders')
            else:   # User has saved password
                flash('An account with this email already exists. Please log in.')
                return redirect(url_for('signin', next='test_reminders'))
        for d in upcoming_dates:
            if str(d.id) in selected_date_ids:
                user.interested_test_date(d)
                selected_date_strs.append(d.date.strftime('%b %-d'))
            else:
                user.remove_test_date(d)
        send_signup_notification_email(user, selected_date_strs)
        try:
            db.session.add(user)
            db.session.commit()
            if current_user.is_authenticated:
                flash('Test dates updated')
            else:
                if email_status == 200:
                    flash('Test dates updated. Please check your inbox to verify your email.')
                else:
                    flash('Verification email did not send. Please contact ' + hello, 'error')
        except:
            db.session.rollback()
            flash('Test dates were not updated, please contact ' + hello, 'error')
        return redirect(url_for('index'))
    return render_template('test-reminders.html', form=form, tests=tests, upcoming_dates=upcoming_dates, \
        imminent_deadlines=imminent_deadlines, selected_date_ids=selected_date_ids)


@app.route('/appamada', methods=['GET', 'POST'])
def appamada():
    form = ScoreAnalysisForm()
    school='Appamada School'
    test='mini SAT'
    submit_text='Send me the score analysis'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('appamada'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_score_analysis_email(student, parent, school)
        if email_status == 200:
            return render_template('score-analysis-submitted.html', email=form.parent_email.data)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('score-analysis-request.html', form=form, school=school, test=test, \
        submit_text=submit_text)


@app.route('/huntington-surrey', methods=['GET', 'POST'])
def huntington_surrey():
    form = ScoreAnalysisForm()
    school='Huntington-Surrey School'
    test='SAT'
    submit_text='Send score analysis'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('huntington_surrey'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_score_analysis_email(student, parent, school)
        if email_status == 200:
            return render_template('score-analysis-submitted.html', email=form.parent_email.data)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('huntington-surrey.html', form=form, school=school, test=test,
        submit_text=submit_text)


@app.route('/ati-austin', methods=['GET', 'POST'])
def ati_austin():
    form = ScoreAnalysisForm()
    school='ATI Austin'
    test='SAT'
    submit_text='Submit'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('ati_austin'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_score_analysis_email(student, parent, school)
        if email_status == 200:
            return render_template('score-analysis-submitted.html', email=form.parent_email.data)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('ati.html', form=form, school=school, test=test,
        submit_text=submit_text)


@app.route('/kaps', methods=['GET', 'POST'])
def kaps():
    form = ScoreAnalysisForm()
    school='Katherine Anne Porter School'
    test='SAT'
    submit_text='Request score analysis'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('kaps'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_prep_class_email(student, parent, school, test)
        if email_status == 200:
            return render_template('registration-confirmed.html', email=form.parent_email.data)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('kaps.html', form=form, school=school, test=test, submit_text=submit_text)


@app.route('/centerville', methods=['GET', 'POST'])
def centerville():
    form = ScoreAnalysisForm()
    school = 'Centerville Elks Soccer'
    test = 'ACT'
    date = 'Saturday, December 3rd, 2022'
    time = '9:30am to 1:00pm'
    location = 'Centerville High School Room West 126'
    contact_info = 'Tom at 513-519-6784'
    submit_text = 'Register'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('centerville'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_test_registration_email(student, parent, school, test, date, time, location, contact_info)
        if email_status == 200:
            return render_template('test-registration-submitted.html', email=parent.email,
            student=student, test=test)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('centerville.html', form=form, school=school, test=test, \
        date=date, time=time, location=location, submit_text=submit_text)


# @app.route('/spartans', methods=['GET', 'POST'])
# def spartans():
#     form = ScoreAnalysisForm()
#     school = 'Spartans Swimming'
#     test = 'ACT, SAT, or PSAT'
#     date = 'Saturday, December 3rd, 2022'
#     time = '9:30am to 1:00pm'
#     location = 'Zoom'
#     contact_info = ''
#     submit_text = 'Register'
#     if form.validate_on_submit():
#         if hcaptcha.verify():
#             pass
#         else:
#             flash('Captcha was unsuccessful. Please try again.', 'error')
#             return redirect(url_for('spartans'))
#         student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
#             grad_year=form.grad_year.data)
#         parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
#         email_status = tbd(student, parent, school, test, date, time, location, contact_info)
#         if email_status == 200:
#             return render_template('test-registration-submitted.html', email=parent.email,
#             student=student, test=test)
#         else:
#             flash('Email failed to send, please contact ' + hello, 'error')
#     return render_template('spartans.html', form=form, school=school, test=test, \
#         date=date, time=time, location=location, submit_text=submit_text)


@app.route('/sat-act-data')
def sat_act_data():
    return render_template('sat-act-data.html', title='SAT & ACT data')


@app.route('/test-strategies', methods=['GET', 'POST'])
def test_strategies():
    form = TestStrategiesForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('test_strategies'))
        relation = form.relation.data
        if relation == 'student':
            student = User(first_name=form.first_name.data, email=form.email.data)
            parent = User(first_name=form.parent_name.data, email=form.parent_email.data)
        elif relation == 'parent':
            parent = User(first_name=form.first_name.data, email=form.email.data)
            student = User(first_name=form.student_name.data)
        email_status = send_test_strategies_email(student, parent, relation)
        if email_status == 200:
            return render_template('test-strategies-sent.html', email=form.email.data, relation=relation)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('test-strategies.html', form=form)


@app.route('/ntpa', methods=['GET', 'POST'])
def ntpa():
    form = NtpaForm()
    if form.validate_on_submit():
        first_name = form.first_name.data
        last_name = form.last_name.data
        biz_name = form.biz_name.data
        email = form.email.data

        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('ntpa'))
        email_status = send_ntpa_email(first_name, last_name, biz_name, email)
        if email_status == 200:
            flash('We\'ve received your request and will be in touch!')
        else:
            flash('Request did not send, please retry or contact ' + hello, 'error')
    return render_template('ntpa.html', form=form)


@app.route('/cal-check', methods=['POST'])
def cal_check():
    if 1 == 0:
        send_schedule_conflict_email(request.json)
    return ('', 200, None)

@app.route('/orgs')
@admin_required
def orgs():
    organizations = Organization.query.all()
    return render_template('orgs.html', organizations=organizations)

@app.route('/new-org')
@admin_required
def new_org():
    return redirect(url_for('org_settings', org='new'))

@app.route('/delete-org/<org_slug>', methods=['POST', 'GET'])
@admin_required
def delete_org(org_slug):
    org = Organization.query.filter_by(slug=org_slug).first_or_404()
    db.session.delete(org)
    db.session.commit()
    flash(f'{org.name} has been deleted.', 'success')
    return redirect(url_for('orgs'))

@app.route('/org-settings/<org>', methods=['GET', 'POST'])
@admin_required
def org_settings(org):
    if org == 'new':
        organization = None
    else:
        organization = Organization.query.filter_by(slug=org).first()
        if not organization:
            flash('Organization not found.', 'error')
            return redirect(url_for('org_settings', org='new'))

    form = OrgSettingsForm()

    partners = User.query.order_by(User.first_name, User.last_name).filter_by(role='partner')
    partner_list = [(0,'New partner')] + [(u.id, full_name(u)) for u in partners]
    form.partner_id.choices = partner_list

    # Prepopulate the form with the organization's data if it's a GET request
    if organization and request.method == 'GET':
        form.org_name.data = organization.name
        form.slug.data = organization.slug
        form.color1.data = organization.color1
        form.color2.data = organization.color2
        form.color3.data = organization.color3
        form.font_color.data = organization.font_color
        form.logo.data = organization.logo_path
        form.partner_id.data = organization.partner_id
        form.sat_ss_id.data = organization.sat_spreadsheet_id
        form.act_ss_id.data = organization.act_spreadsheet_id

    if form.validate_on_submit():
        try:
            if form.partner_id.data == 0:
                partner = User(first_name=form.first_name.data, last_name=form.last_name.data,
                    email=form.email.data.lower(), role='partner',
                    session_reminders=False, test_reminders=False)
                db.session.add(partner)
                db.session.flush()
            else:
                partner = User.query.filter_by(id=form.partner_id.data).first()
                form.first_name.data = partner.first_name
                form.last_name.data = partner.last_name
                form.email.data = partner.email

            if not organization:
                organization = Organization(name=form.org_name.data, slug=form.slug.data)
                db.session.add(organization)
            else:
                organization = Organization.query.filter_by(slug=org).first()

            organization.name = form.org_name.data
            organization.color1 = form.color1.data
            organization.color2 = form.color2.data
            organization.color3 = form.color3.data
            organization.font_color = form.font_color.data
            organization.partner_id = partner.id
            organization.sat_spreadsheet_id = form.sat_ss_id.data
            organization.act_spreadsheet_id = form.act_ss_id.data
            slug = form.slug.data
            slug = ''.join(e for e in slug if e.isalnum() or e == '-').replace(' ', '-').lower()
            organization.slug = slug

            # Save the uploaded logo file
            logo_file = form.logo.data
            if logo_file:
                # Ensure the upload directory exists
                upload_dir = os.path.join(app.static_folder, 'img/orgs')
                os.makedirs(upload_dir, exist_ok=True)

                # Save the file with a secure filename
                filename = secure_filename(f"{slug}.{logo_file.filename.split('.')[-1]}")
                logo_path = os.path.join(upload_dir, filename)
                logo_file.save(logo_path)

                # Store the relative path in the database
                organization.logo_path = f"img/orgs/{filename}"

            organization_data = {
                'name': organization.name,
                'logo_path': organization.logo_path,
                'sat_ss_id': organization.sat_spreadsheet_id,
                'act_ss_id': organization.act_spreadsheet_id,
                'color1': organization.color1,
                'color2': organization.color2,
                'color3': organization.color3,
                'font_color': organization.font_color,
            }

            # Create partner logo
            partner_logos_dir = os.path.join(app.static_folder, 'img/orgs/partner-logos')
            os.makedirs(partner_logos_dir, exist_ok=True)
            if is_dark_color(organization.color1):
                organization_data['partner_logo_path'] = 'img/logo-header.png'
            else:
                svg_path = os.path.join(app.static_folder, 'img/logo-header.svg')
                # Ensure the partner_logos directory exists
                organization_data['partner_logo_path'] = f'img/orgs/partner-logos/{organization.slug}.png'
                static_output_path = os.path.join(app.static_folder, 'img/orgs/partner-logos', f'{organization.slug}.png')
                color_svg_white_to_input(svg_path, organization.font_color, static_output_path)
                print(f'Created partner logo at {static_output_path}')

            if not form.sat_ss_id.data:
                organization.sat_spreadsheet_id = create_custom_sat_spreadsheet(organization)
                organization_data['sat_ss_id'] = organization.sat_spreadsheet_id

            style_custom_sat_spreadsheet_task.delay(organization_data)

            if not form.act_ss_id.data:
                organization.act_spreadsheet_id = create_custom_act_spreadsheet(organization)
                organization_data['act_ss_id'] = organization.act_spreadsheet_id
            style_custom_act_spreadsheet_task.delay(organization_data)

            db.session.commit()

            flash(Markup(f'Custom \
                <a href="https://docs.google.com/spreadsheets/d/{organization.sat_spreadsheet_id}" target="_blank">\
                    SAT spreadsheet</a> and \
                <a href="https://docs.google.com/spreadsheets/d/{organization.act_spreadsheet_id}" target="_blank">\
                    ACT spreadsheet</a> updated successfully'), 'success')
            return redirect(url_for('org_settings', org=slug))
        except Exception as e:
            flash(f"Error creating custom spreadsheet: {e}", 'error')

    return render_template('org-settings.html', form=form, organization=organization)


@app.route('/pay')
def pay():
    return redirect('https://link.waveapps.com/4yu6up-ne82sd')

@app.route('/download/<filename>')
def download_file (filename):
    path = os.path.join(app.static_folder, 'files/')
    return send_from_directory(path, filename, as_attachment=False)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.static_folder), 'img/favicons/favicon.ico')

@app.route('/manifest.webmanifest')
def webmanifest():
    return send_from_directory(os.path.join(app.static_folder), 'img/favicons/manifest.webmanifest')

@app.route('/robots.txt')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])

@app.route('/sitemap')
@app.route('/sitemap/')
@app.route('/sitemap.xml')
def sitemap():
    '''
        Route to dynamically generate a sitemap of your website/application.
        lastmod and priority tags omitted on static pages.
        lastmod included on dynamic content such as blog posts.
    '''
    #from urllib.parse import urlparse

    host_components = url_parse(request.host_url)
    host_base = host_components.scheme + '://' + host_components.netloc

    # Static routes with static content
    static_urls = list()
    for rule in app.url_map.iter_rules():
        if not str(rule).startswith('/admin') and not str(rule).startswith('/user'):
            if 'GET' in rule.methods and len(rule.arguments) == 0:
                url = {
                    'loc': f'{host_base}{str(rule)}'
                }
                static_urls.append(url)

    # # Dynamic routes with dynamic content
    # dynamic_urls = list()
    # blog_posts = Post.objects(published=True)
    # for post in blog_posts:
    #     url = {
    #         'loc': f'{host_base}/blog/{post.category.name}/{post.url}',
    #         'lastmod': post.date_published.strftime('%Y-%m-%dT%H:%M:%SZ')
    #         }
    #     dynamic_urls.append(url)

    xml_sitemap = render_template('sitemap/sitemap.xml', static_urls=static_urls, host_base=host_base) #dynamic_urls=dynamic_urls)
    response = make_response(xml_sitemap)
    response.headers['Content-Type'] = 'application/xml'

    return response


@app.route('/score-report', methods=['GET', 'POST'])
@app.route('/sat-report', methods=['GET', 'POST'])
def sat_report():
    form = SATReportForm()
    return handle_sat_report(form, 'sat-report.html')


@app.route('/act-report', methods=['GET', 'POST'])
@login_required
def act_report():
    form = ACTReportForm()
    return handle_act_report(form, 'act-report.html')


@app.route('/<org>')
def partner_page(org):
    organization = Organization.query.filter_by(slug=org).first_or_404()
    # Convert the organization object to a dictionary
    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'slug': organization.slug,
    }
    return render_template('partner-page.html', title=organization.name, organization=organization_dict)


@app.route('/<org>/sat', methods=['GET', 'POST'])
def custom_sat_report(org):
    form = SATReportForm()
    organization = Organization.query.filter_by(slug=org).first_or_404()
    print(f'organization.slug: {organization.slug}')

    # Convert the organization object to a dictionary
    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'slug': organization.slug,
        'spreadsheet_id': organization.sat_spreadsheet_id,
    }
    return handle_sat_report(form, 'org-sat-report.html', organization=organization_dict)


@app.route('/<org>/act', methods=['GET', 'POST'])
@login_required
def custom_act_report(org):
    form = ACTReportForm()
    organization = Organization.query.filter_by(slug=org).first_or_404()

    # Convert the organization object to a dictionary
    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'slug': organization.slug,
        'spreadsheet_id': organization.act_spreadsheet_id,
    }
    return handle_act_report(form, 'org-act-report.html', organization=organization_dict)


def handle_sat_report(form, template_name, organization=None):
    hcaptcha_key = os.environ.get('HCAPTCHA_SITE_KEY')

    if request.method == 'GET':
        ss_id = request.args.get('ssId')
        if ss_id:
            form.spreadsheet_url.data = ss_id
        email = request.args.get('email')
        if email:
            form.email.data = email

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

        uploads_folder_path = 'app/private/sat/uploads'
        json_folder_path = 'app/private/sat/json'
        reports_folder_path = 'app/private/sat/reports'

        if not os.path.exists(uploads_folder_path):
            os.makedirs(uploads_folder_path)
        if not os.path.exists(json_folder_path):
            os.makedirs(json_folder_path)
        if not os.path.exists(reports_folder_path):
            os.makedirs(reports_folder_path)

        if form.spreadsheet_url.data:
            try:
                student_ss_full_url = form.spreadsheet_url.data
                student_ss_base_url = student_ss_full_url.split('?')[0]
                if '/d/' in student_ss_base_url:
                    student_ss_id = student_ss_base_url.split('/d/')[1].split('/')[0]
                else:
                    student_ss_id = student_ss_base_url
            except:
                flash('Invalid Google Sheet URL', 'error')
                return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)
        else:
            student_ss_id = None

        report_file = request.files['report_file']
        details_file = request.files['details_file']

        if not (is_valid_pdf(report_file) and is_valid_pdf(details_file)):
            flash('Only PDF files are allowed', 'error')
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

        report_file_path = os.path.join(uploads_folder_path, form.email.data + ' CB report.pdf')
        details_file_path = os.path.join(uploads_folder_path, form.email.data + ' CB details.pdf')

        report_file.save(report_file_path)
        details_file.save(details_file_path)

        try:
            score_data = get_all_data(report_file_path, details_file_path)
            logging.info(f"Score data: {score_data}")
            score_data['email'] = form.email.data.lower()
            score_data['student_ss_id'] = student_ss_id

            if organization:
                org = Organization.query.filter_by(slug=organization['slug']).first()
                admin = User.query.filter_by(organization_id=org.id).first()
                score_data['admin_email'] = admin.email
            else:
                score_data['admin_email'] = None

            filename = score_data['student_name'] + ' ' + score_data['date'] + ' ' + score_data['test_display_name']
            os.rename(report_file_path, os.path.join(uploads_folder_path, filename + ' CB report.pdf'))
            os.rename(details_file_path, os.path.join(uploads_folder_path, filename + ' CB details.pdf'))
            json_file_path = os.path.join(json_folder_path, filename + '.json')

            with open(json_file_path, "w") as json_file:
                json.dump(score_data, json_file, indent=2)

            # test = TestScore(test_code=score_data['test_code'], date=score_data['date'], rw_score=score_data['rw_score'],
            #     m_score=score_data['m_score'], total_score=score_data['total_score'], json_path=json_file_path,
            #     type='practice', user_id=user.id)

            # db.session.add(test)
            # db.session.commit()

            logger.debug(f"Score data being sent: {json.dumps(score_data, indent=2)}")

            if student_ss_id:
                has_access = check_service_account_access(student_ss_id)
                if not has_access:
                    flash(Markup('Please share <a href="https://docs.google.com/spreadsheets/d/' + student_ss_id + '/edit?usp=sharing" target="_blank">your spreadsheet</a> with score-reports@sat-score-reports.iam.gserviceaccount.com for answers to be added there.'))
                    logging.error('Service account does not have access to student spreadsheet')
                    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

            create_and_send_sat_report_task.delay(score_data, organization_dict=organization)

            if len(score_data['answer_key_mismatches']) > 0:
                send_changed_answers_email(score_data)

            if organization:
                return_route = url_for('custom_sat_report', org=organization['slug'])
                flash(Markup(f'Your answers have been submitted successfully.<br> \
                Your score analysis should arrive in your inbox or spam folder in the next 5 minutes.<br> \
                <a href="{return_route}">Submit another test</a>'), 'success')
                return redirect(url_for('index'))
            else:
                return_route = url_for('sat_report')
                return render_template('score-report-sent.html', return_route=return_route)
        except ValueError as ve:
            if 'Test unavailable' in str(ve):
                flash('Practice ' + score_data['test_display_name'] + ' is not yet available. We are working to add them soon.', 'error')
            elif 'Missing math modules' in str(ve):
                flash(Markup('Error reading Score Details PDF. Make sure you click "All" above the answer table before saving the page. See the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a> for more details.'), 'error')
            elif 'missing RW questions' in str(ve):
                flash(Markup('Error reading Score Details PDF. Make sure your browser window is wide enough so that "Reading and Writing" displays on one line in your answers table. See the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a> for more details.'), 'error')
            elif 'missing Math questions' in str(ve):
                flash(Markup('Error reading Score Details PDF. Make sure the file includes 27 questions per Reading & Writing module and 22 questions per Math module. See the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a> for more details.'), 'error')
            elif 'PDF too narrow' in str(ve):
                flash('Score Details error: Page too narrow. Ensure "Reading and Writing" displays on single line in answer table.', 'error')
            elif 'date or test code mismatch' in str(ve):
                flash(Markup('Please confirm that the test date and practice test number match on both PDFs.'), 'error')
            elif 'insufficient questions answered' in str(ve):
                flash(Markup('Test not attempted. At least 5 questions must be answered on Reading & Writing or Math to generate a score report.'), 'error')
            logger.error(f"Error generating score report: {ve}", exc_info=True)
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)
        except FileNotFoundError as fe:
            if 'Score Report PDF does not match expected format' in str(fe):
                flash(Markup('Score Report PDF does not match expected format. Please follow the <a href="#" data-bs-toggle="modal" data-bs-target="#report-modal">instructions</a> carefully and <a href="https://www.openpathtutoring.com#contact" target="_blank">contact us</a> if you need assistance.'), 'error')
            elif 'Score Details PDF does not match expected format' in str(fe):
                flash(Markup('Score Details PDF does not match expected format. Please follow the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a> carefully and <a href="https://www.openpathtutoring.com#contact" target="_blank">contact us</a> if you need assistance.'), 'error')
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)
        except Exception as e:
            logger.error(f"Unexpected error generating score report: {e}", exc_info=True)
            email = send_fail_mail('Cannot generate score report', traceback.format_exc(), form.email.data.lower())
            if email == 200:
                flash('Unexpected error. Our team has been notified and will be in touch.', 'error')
            else:
                flash(Markup('Unexpected error. If the problem persists, <a href="https://www.openpathtutoring.com#contact" target="_blank">contact us</a> for assistance.'), 'error')
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)
    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)


def handle_act_report(form, template_name, organization=None):
    hcaptcha_key = os.environ.get('HCAPTCHA_SITE_KEY')
    form.test_code.choices = load_act_test_codes()

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

        try:
            act_uploads_path = 'app/private/act/uploads'
            act_reports_path = 'app/private/act/reports'

            if not os.path.exists(act_uploads_path):
                os.makedirs(act_uploads_path)
            if not os.path.exists(act_reports_path):
                os.makedirs(act_reports_path)

            user = User(first_name=form.first_name.data, last_name=form.last_name.data, email=form.email.data.lower())

            answer_img = request.files['answer_img']
            date = datetime.today().date().strftime('%Y-%m-%d')

            file_extension = get_image_info(answer_img)
            answer_sheet_filename = secure_filename(f"{user.first_name} {user.last_name} ACT {form.test_code.data} answer sheet {date}.{file_extension}")
            answer_img_path = os.path.join(act_uploads_path, answer_sheet_filename)
            # answer_img.stream.seek(0)  # Reset file pointer to the beginning
            answer_img.save(answer_img_path)

            if file_extension == 'heic':
                answer_img_path = convert_heic_to_jpg(answer_img_path)
            print(answer_img_path)

            if not is_valid_image(answer_img):
                flash('Please upload an image (jpg, png, webp, or heic)', 'error')
                return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

            score_data = {}
            score_data['answer_img_path'] = answer_img_path
            score_data['act_uploads_path'] = act_uploads_path
            score_data['act_reports_path'] = act_reports_path
            score_data['test_code'] = form.test_code.data
            score_data['test_display_name'] = f'ACT {score_data["test_code"]}'
            score_data['student_name'] = f"{user.first_name} {user.last_name}"
            score_data['email'] = form.email.data.lower()
            score_data['student_responses'] = {}
            score_data['date'] = date

            score_data['admin_email'] = None
            if organization:
                org = Organization.query.filter_by(slug=organization['slug']).first()
                admin = User.query.filter_by(organization_id=org.id).first()
                score_data['admin_email'] = admin.email

            score_data['student_ss_id'] = None
            if form.spreadsheet_url.data:
                try:
                    student_ss_full_url = form.spreadsheet_url.data
                    student_ss_base_url = student_ss_full_url.split('?')[0]
                    if '/d/' in student_ss_base_url:
                        score_data['student_ss_id'] = student_ss_base_url.split('/d/')[1].split('/')[0]
                    else:
                        score_data['student_ss_id'] = student_ss_base_url

                except:
                    flash('Invalid Google Sheet URL', 'error')
                    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

                has_access = check_service_account_access(score_data['student_ss_id'])
                if not has_access:
                    flash(Markup('Please share <a href="https://docs.google.com/spreadsheets/d/' + score_data['student_ss_id'] + '/edit?usp=sharing" target="_blank">your spreadsheet</a> with score-reports@sat-score-reports.iam.gserviceaccount.com for answers to be added there.'), 'error')
                    logging.error('Service account does not have access to student spreadsheet')
                    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

            create_and_send_act_report_task.delay(score_data, organization)

            if organization:
                return_route = url_for('custom_act_report', org=organization['slug'])
                flash(Markup(f'Your answer sheet has been submitted successfully.<br> \
                Your score analysis should arrive in your inbox or spam folder in the next 5 minutes.<br> \
                <a href="{return_route}">Submit another test</a>'), 'success')
                return redirect(url_for('index'))
            else:
                return_route = url_for('act_report')
                return render_template('score-report-sent.html', return_route=return_route)

        except Exception as e:
            logger.error(f"Error sending ACT report email: {e}", exc_info=True)
            flash(f'Failed to send answer sheet. Please contact {hello}.', 'error')
    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)


@app.route('/admin-files/<path:filename>')
@admin_required
def admin_download(filename):
    private_folder = os.path.join(app.root_path, 'private')
    file_path = os.path.join(private_folder, filename)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True)


def TemplateRenderer(app):
    def register_template_endpoint(name, endpoint):
        @app.route('/' + name, endpoint=endpoint)
        def route_handler():
            title = name.replace('-', ' ').capitalize()
            return render_template(name + '.html', title=title)
    return register_template_endpoint

endpoints = []
for r in app.url_map._rules:
    endpoints.append(r.endpoint)

template_list = []
for f in os.listdir('app/templates'):
    if f.endswith('html') and not f.startswith('_'):
        template_list.append(f[0:-5])

register_template_endpoint = TemplateRenderer(app)
for path in template_list:
    endpoint = path.replace('-','_')
    if endpoint not in endpoints:
        register_template_endpoint(path, endpoint)