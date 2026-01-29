"""Main blueprint routes for public-facing pages."""

import os
import json
import logging
import traceback
import base64
from datetime import datetime, timedelta, timezone

from markupsafe import Markup
from flask import (
    render_template, flash, redirect, url_for, g,
    request, send_from_directory, send_file, make_response, abort, current_app
)
from flask_login import current_user, login_required
from urllib.parse import urlparse as url_parse
from werkzeug.utils import secure_filename
from PIL import Image
from pillow_heif import register_heif_opener
from pypdf import PdfReader
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from app.blueprints.main import main_bp
from app.extensions import db, hcaptcha
from app.helpers import full_name, dir_last_updated, hello_email, private_login_check
from app.forms import (
    InquiryForm, EmailListForm, TestStrategiesForm, TestDateForm,
    ScoreAnalysisForm, ReviewForm, FreeResourcesForm, NominationForm,
    SATReportForm, ACTReportForm, NtpaForm, NewStudentForm
)
from app.models import User, TestDate, UserTestDate, TestScore, Review, Organization
from app.email import (
    send_contact_email, send_test_strategies_email, send_score_analysis_email,
    send_test_registration_email, send_prep_class_email, send_signup_notification_email,
    send_confirmation_email, send_unexpected_data_email, send_ntpa_email, send_fail_mail,
    send_free_resources_email, send_nomination_email, send_new_student_email
)
from app.score_reader import get_all_data
from app.create_sat_report import (
    check_service_account_access, create_custom_sat_spreadsheet,
    update_sat_org_logo, update_sat_partner_logo
)
from app.create_act_report import create_custom_act_spreadsheet, update_act_org_logo
from app.tasks import sat_report_workflow_task, act_report_workflow_task, new_student_task
from app.utils import is_dark_color, format_timezone

logger = logging.getLogger(__name__)

register_heif_opener()

def convert_heic_to_jpg(heic_path, quality=100):
    """Convert a HEIC image to JPG."""
    try:
        file_prefix = os.path.splitext(heic_path)[0]
        jpg_path = f'{file_prefix}.jpg'
        with Image.open(heic_path) as img:
            rgb_img = img.convert('RGB')
            rgb_img.save(jpg_path, 'JPEG', quality=quality)
        logger.info(f"Converted HEIC to JPG: {jpg_path}")
        return jpg_path
    except Exception as e:
        logger.error(f"Failed to convert HEIC to JPG: {e}")
        return False


def is_valid_image(file):
    try:
        img = Image.open(file)
        img.verify()
        return True
    except (IOError, SyntaxError):
        return False


def is_valid_pdf(file):
    try:
        reader = PdfReader(file)
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
            file_extension = file_format.lower()
            if file_extension in ('jpeg', 'mpo'):
                file_extension = 'jpg'
            elif file_extension in ('heif', 'heic'):
                file_extension = 'heic'
            return file_extension
    except Exception as e:
        logger.error(f"Image format error: {e}")
        return None, None
    finally:
        if hasattr(file_path, 'stream'):
            file_path.stream.seek(0)
        else:
            file_path.seek(0)


def add_user_to_drive_folder(email, folder_id):
    """Add a user as a viewer to a Google Drive folder."""
    credentials = Credentials.from_service_account_file('service_account_key.json')
    service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    permission = {
        'type': 'user',
        'role': 'reader',
        'emailAddress': email
    }
    service.permissions().create(
        fileId=folder_id,
        body=permission,
        fields='id',
        sendNotificationEmail=False
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


@main_bp.before_app_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_viewed = datetime.now(timezone.utc)
        db.session.commit()
    g.hello = hello_email()


@main_bp.app_context_processor
def inject_values():
    try:
        if current_user.is_authenticated:
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
        hello=(getattr(g, 'hello', None) or hello_email()),
        phone=current_app.config['PHONE'],
        current_first_name=current_first_name,
        current_last_name=current_last_name
    )


@main_bp.route('/', methods=['GET', 'POST'])
@main_bp.route('/index', methods=['GET', 'POST'])
def index():
    import time
    start_time = time.time()
    form = InquiryForm()
    # altcha_site_key = current_app.config['ALTCHA_SITE_KEY']
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('main.index', _anchor='home'))

        email = form.email.data.lower().strip()

        user = User.query.filter_by(email=email).first()
        if user:
            user.first_name = form.first_name.data
            user.last_name = form.last_name.data
            user.phone = form.phone.data
            user.role = form.role.data
        else:
            user = User(
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                email=email,
                phone=form.phone.data,
                role=form.role.data
            )
            db.session.add(user)

        db.session.commit()

        message = form.message.data
        subject = form.subject.data

        email_status = send_contact_email(user, message, subject)

        # try:
        #     new_contact = {
        #         'first_name': user.first_name,
        #         'last_name': user.last_name,
        #         'emails': [{'type': 'home', 'value': user.email}],
        #         'phones': [{'type': 'mobile', 'value': user.phone}],
        #         'tags': ['Website']
        #     }

        #     create_crm_contact_and_action(new_contact, f'Respond to {subject.lower()}')
        # except:
        #     logger.error('Error creating CRM contact and action', exc_info=True)
        #     send_fail_mail('Error creating CRM contact and action', traceback.format_exc())
        #     pass

        if email_status == 200:
            conf_status = send_confirmation_email(user.email, message)
            if conf_status == 200:
                if user.role == 'parent' or user.role == 'student':
                    flash('Your message has been received. Thank you for reaching out!')
                    return redirect(url_for('main.new_student', id=user.id))
                else:
                    flash('Thank you for reaching out! We\'ll be in touch.')
                    return redirect(url_for('main.index', _anchor='home'))
        flash('Email failed to send, please contact ' + g.hello, 'error')
    return render_template('index.html', form=form, last_updated=dir_last_updated('app/static'))#, altcha_site_key=altcha_site_key)


@main_bp.route('/team', methods=['GET', 'POST'])
def team():
    team_members = User.query.order_by(User.phone.asc()).filter(User.role.in_(['tutor', 'admin'])).filter_by(status='active')
    return render_template('team.html', title='Our Team', full_name=full_name, team_members=team_members)


@main_bp.route('/mission', methods=['GET', 'POST'])
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
            folder_id = current_app.config['RESOURCE_FOLDER_ID']
            add_user_to_drive_folder(user.email, folder_id)

            email_status = send_free_resources_email(user)
            if email_status == 200:
                flash('Your free resources are on their way to your inbox!', 'success')
            else:
                flash(Markup(f'Email failed to send. Please contact <a href="mailto:{g.hello}" target="_blank">{g.hello}</a>'), 'error')
        except Exception as e:
            logger.error(f"Error adding user to Google Drive folder: {e}", exc_info=True)
            flash('An error occurred while granting access to resources. Please try again later.', 'error')
    return render_template('mission.html', title='Our mission', form=form)


@main_bp.route('/nominate', methods=['GET', 'POST'])
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
            form_data['contact_email'] = form.nominator_email.data
            form_data['nominator_first_name'] = form.nominator_first_name.data
            form_data['nominator_last_name'] = form.nominator_last_name.data
            form_data['nominator_email'] = form.nominator_email.data

        email_status = send_nomination_email(form_data)
        if email_status == 200:
            send_confirmation_email(form_data['contact_email'], form_data['nomination_text'])
            flash('Thank you for your nomination! We will be in touch.')
            return redirect(url_for('main.index'))
        else:
            flash(f'An error occurred. Please contact {g.hello}', 'error')
            logging.error(f"Error processing nomination. Email status {email_status}")
    return render_template('nominate.html', form=form)


@main_bp.route('/about')
def about():
    return render_template('about.html', title='About')


@main_bp.route('/reviews')
def reviews():
    form = ReviewForm()
    reviews = Review.query.order_by(Review.timestamp.desc()).all()
    if form.validate_on_submit():
        review = Review(text=form.text.data, author=form.author.data, timestamp=datetime.now(timezone.utc))
        try:
            db.session.add(review)
            db.session.commit()
            flash('Thank you for your review!')
        except:
            db.session.rollback()
            flash('Review could not be added', 'error')
        return redirect(url_for('main.reviews'))
    return render_template('reviews.html', title='Reviews', reviews=reviews, form=form)


@main_bp.route('/test-dates', methods=['GET', 'POST'])
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
        (User.role == 'student') & (User.status == 'active') | (User.status == 'prospective'))
    undecided_students = User.query.filter(~User.test_dates.any(TestDate.id.in_(upcoming_date_ids)) & (User.role == 'student') & (User.status == 'active') | (User.status == 'prospective'))
    if form.validate_on_submit():
        date = TestDate(
            test=form.test.data,
            date=form.date.data,
            reg_date=form.reg_date.data,
            late_date=form.late_date.data,
            other_date=form.other_date.data,
            score_date=form.score_date.data,
            status=form.status.data
        )
        try:
            db.session.add(date)
            db.session.commit()
            flash(date.date.strftime('%b %-d') + ' ' + date.test.upper() + ' added')
        except:
            db.session.rollback()
            flash(date.date.strftime('%b %-d') + date.test.upper() + ' could not be added', 'error')
            return redirect(url_for('main.test_dates'))
        return redirect(url_for('main.test_dates'))
    return render_template('test-dates.html', title='Test dates', form=form, main_tests=main_tests,
                           upcoming_weekend_dates=upcoming_weekend_dates, other_dates=other_dates,
                           upcoming_students=upcoming_students, undecided_students=undecided_students)


@main_bp.route('/test-reminders', methods=['GET', 'POST'])
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
            return redirect(url_for('main.test_reminders'))
        selected_date_ids = request.form.getlist('test_dates')
        if not current_user.is_authenticated:
            user = User.query.filter_by(email=form.email.data).first()
            if not user:
                user = User(first_name=form.first_name.data, last_name='', email=form.email.data.lower())
            if not user.password_hash:
                from app.email import send_password_reset_email
                email_status = send_password_reset_email(user, 'main.test_reminders')
            else:
                flash('An account with this email already exists. Please log in.')
                return redirect(url_for('auth.signin', next='main.test_reminders'))
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
                    flash(f'Verification email did not send. Please contact {g.hello}', 'error')
        except:
            db.session.rollback()
            flash(f'Test dates were not updated, please contact {g.hello}', 'error')
        return redirect(url_for('main.index'))
    return render_template('test-reminders.html', form=form, tests=tests, upcoming_dates=upcoming_dates,
                           imminent_deadlines=imminent_deadlines, selected_date_ids=selected_date_ids)


@main_bp.route('/ati-austin', methods=['GET', 'POST'])
def ati_austin():
    form = ScoreAnalysisForm()
    school = 'ATI Austin'
    test = 'SAT'
    submit_text = 'Submit'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('ati_austin'))
        student = User(
            first_name=form.student_first_name.data,
            last_name=form.student_last_name.data,
            grad_year=form.grad_year.data
        )
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_score_analysis_email(student, parent, school)
        if email_status == 200:
            return render_template('score-analysis-submitted.html', email=form.parent_email.data)
        else:
            flash(f'Email failed to send, please contact {g.hello}', 'error')
    return render_template('ati.html', form=form, school=school, test=test, submit_text=submit_text)


@main_bp.route('/kaps', methods=['GET', 'POST'])
def kaps():
    form = ScoreAnalysisForm()
    school = 'Katherine Anne Porter School'
    test = 'SAT'
    submit_text = 'Request score analysis'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('main.kaps'))
        student = User(
            first_name=form.student_first_name.data,
            last_name=form.student_last_name.data,
            grad_year=form.grad_year.data
        )
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_prep_class_email(student, parent, school, test)
        if email_status == 200:
            return render_template('registration-confirmed.html', email=form.parent_email.data)
        else:
            flash(f'Email failed to send, please contact {g.hello}', 'error')
    return render_template('kaps.html', form=form, school=school, test=test, submit_text=submit_text)


@main_bp.route('/centerville', methods=['GET', 'POST'])
def centerville():
    form = ScoreAnalysisForm()
    school = 'Centerville Elks Soccer'
    test = 'ACT'
    date = 'Saturday, December 3rd, 2022'
    time = '9:30am to 1:00pm'
    location = 'Centerville High School Room West 126'
    contact_info = 'Tom at ###-###-####'
    submit_text = 'Register'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('main.centerville'))
        student = User(
            first_name=form.student_first_name.data,
            last_name=form.student_last_name.data,
            grad_year=form.grad_year.data
        )
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_test_registration_email(student, parent, school, test, date, time, location, contact_info)
        if email_status == 200:
            return render_template('test-registration-submitted.html', email=parent.email, student=student, test=test)
        else:
            flash(f'Email failed to send, please contact {g.hello}', 'error')
    return render_template('centerville.html', form=form, school=school, test=test,
                           date=date, time=time, location=location, submit_text=submit_text)


@main_bp.route('/sat-act-data')
def sat_act_data():
    return render_template('sat-act-data.html', title='SAT & ACT data')


@main_bp.route('/test-strategies', methods=['GET', 'POST'])
def test_strategies():
    form = TestStrategiesForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('main.test_strategies'))
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
            flash(f'Email failed to send, please contact {g.hello}', 'error')
    return render_template('test-strategies.html', form=form)


@main_bp.route('/ntpa', methods=['GET', 'POST'])
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
            return redirect(url_for('main.ntpa'))
        email_status = send_ntpa_email(first_name, last_name, biz_name, email)
        if email_status == 200:
            flash('We\'ve received your request and will be in touch!')
        else:
            flash(f'Request did not send, please retry or contact {g.hello}', 'error')
    return render_template('ntpa.html', form=form)


@main_bp.route('/new-student', methods=['GET', 'POST'])
def new_student():
    form = NewStudentForm()

    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.date >= datetime.today().date())
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    parents = User.query.order_by(User.first_name, User.last_name).filter_by(role='parent')
    parent_list = [(0, 'New parent')] + [(u.id, full_name(u)) for u in parents]
    form.parent_select.choices = parent_list
    tutors = User.query.filter_by(role='tutor')
    tutor_list = [(u.id, full_name(u)) for u in tutors]
    form.tutor_select.choices = tutor_list

    if request.method == 'GET':
        user_id = request.args.get('id')
        user = None
        if user_id:
            user = User.query.filter_by(id=int(user_id)).first()

        if user:
            # If the user is a parent, prefill parent fields and set parent_id
            if user.role == 'parent':
                form.parent_first_name.data = user.first_name
                form.parent_last_name.data = user.last_name
                form.parent_email.data = user.email
                form.parent_phone.data = user.phone
                form.timezone.data = user.timezone
            # If the user is a student, prefill student fields
            elif user.role == 'student':
                form.student_first_name.data = user.first_name
                form.student_last_name.data = user.last_name
                form.student_email.data = user.email
                form.student_phone.data = user.phone
                form.pronouns.data = user.pronouns
                form.timezone.data = user.timezone

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('admin.students'))

        try:
            parent = User.query.filter_by(email=form.parent_email.data.lower()).first()
            if parent:
                parent.first_name = form.parent_first_name.data
                parent.last_name = form.parent_last_name.data
                parent.email = form.parent_email.data.lower()
                parent.secondary_email = form.parent2_email.data.lower()
                parent.phone = form.parent_phone.data
                parent.timezone = form.timezone.data
                parent.role = 'parent'
            else:
                parent = User(
                    first_name=form.parent_first_name.data,
                    last_name=form.parent_last_name.data,
                    email=form.parent_email.data.lower(),
                    secondary_email=form.parent2_email.data.lower(),
                    phone=form.parent_phone.data,
                    timezone=form.timezone.data,
                    role='parent',
                    session_reminders=True,
                    test_reminders=True
                )
                db.session.add(parent)

            tutor = User.query.filter_by(id=form.tutor_select.data).first()
            student = User.query.filter_by(email=form.student_email.data.lower()).first()
            if student:
                student.first_name = form.student_first_name.data
                student.last_name = form.student_last_name.data
                student.pronouns = form.pronouns.data
                student.email = form.student_email.data.lower()
                student.phone = form.student_phone.data
                student.timezone = form.timezone.data
                student.status = form.status.data
                student.role = 'student'
                student.grad_year = form.grad_year.data
                student.subject = form.subject.data
                student.tutor_id = form.tutor_select.data
            else:
                student = User(
                    first_name=form.student_first_name.data,
                    last_name=form.student_last_name.data,
                    pronouns=form.pronouns.data,
                    email=form.student_email.data.lower(),
                    phone=form.student_phone.data,
                    timezone=form.timezone.data,
                    status=form.status.data,
                    role='student',
                    grad_year=form.grad_year.data,
                    subject=form.subject.data,
                    tutor_id=form.tutor_select.data,
                    session_reminders=True,
                    test_reminders=True
                )
                db.session.add(student)

            db.session.flush()
            student.parent_id = parent.id

            if form.parent2_email.data:
                parent2 = User.query.filter_by(email=form.parent2_email.data.lower()).first()
                if parent2:
                    parent2.first_name = form.parent2_first_name.data
                    parent2.last_name = form.parent2_last_name.data
                    parent2.email = form.parent2_email.data.lower()
                    parent2.phone = form.parent2_phone.data
                    parent2.timezone = form.timezone.data
                    parent2.role = 'parent'
                else:
                    parent2 = User(
                        first_name=form.parent2_first_name.data,
                        last_name=form.parent2_last_name.data,
                        email=form.parent2_email.data.lower(),
                        phone=form.parent2_phone.data,
                        timezone=form.timezone.data,
                        role='parent',
                        session_reminders=True,
                        test_reminders=True
                    )
                    db.session.add(parent2)
            else:
                parent2 = None

            db.session.commit()

            test_selections = request.form.getlist('test_dates')
            if current_user.is_authenticated and current_user.is_admin:
                # Admin view: process select dropdowns (interested/registered/none)
                for d in upcoming_dates:
                    if str(d.id) + '-interested' in test_selections:
                        student.interested_test_date(d)
                    elif str(d.id) + '-registered' in test_selections:
                        student.register_test_date(d)
            else:
                # Regular user view: process checkboxes for interested dates only
                for d in upcoming_dates:
                    if str(d.id) in test_selections:
                        student.interested_test_date(d)

            timezone = format_timezone(student.timezone)

            contact_data = {
                'student': {
                    'first_name': student.first_name,
                    'last_name': student.last_name,
                    'pronouns': student.pronouns,
                    'email': student.email,
                    'phone': request.form.get('student_phone_formatted'),
                    'timezone': timezone,
                    'subject': student.subject,
                    'grad_year': student.grad_year,
                    'status': student.status
                },
                'parent': {
                    'first_name': parent.first_name,
                    'last_name': parent.last_name,
                    'email': parent.email,
                    'phone': request.form.get('parent_phone_formatted'),
                    'timezone': timezone
                } if parent else None,
                'parent2': {
                    'first_name': parent2.first_name,
                    'last_name': parent2.last_name,
                    'email': parent2.email,
                    'phone': request.form.get('parent2_phone_formatted'),
                    'timezone': timezone
                } if parent2 else None,
                'tutor': {
                    'first_name': tutor.first_name,
                    'last_name': tutor.last_name,
                    'email': tutor.email,
                    'phone': request.form.get('tutor_phone_formatted')
                } if tutor else None,
                'notes': form.notes.data
            }

            contact_data['interested_dates'] = []
            for test_date in student.get_dates():
                contact_data['interested_dates'].append({
                    'test': test_date.test,
                    'date': test_date.date,
                    'is_registered': student.is_registered(test_date)
                })

            contact_data['interested_dates'].sort(key=lambda x: x['date'])
            for date in contact_data['interested_dates']:
                date['date'] = date['date'].strftime('%b %d')

            if form.create_student_folder.data:
                contact_data['create_folder'] = True
            else:
                contact_data['create_folder'] = False

            new_student_task.delay(contact_data)

            # email_status = send_new_student_email(contact_data)
            # if email_status == 200:
            flash('New student information received. Thank you!')
            if current_user.is_authenticated and current_user.role == 'admin':
                return redirect(url_for('admin.students'))
            else:
                return redirect(url_for('main.index'))
            # else:
            #     flash(Markup('Email failed to send. Please <a href="https://www.openpathtutoring.com#contact?subject=New%20student%20form%20error" target="_blank">contact us</a>'), 'error')
            #     return redirect(url_for('main.new_student'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating new student: {e}", exc_info=True)
            flash(Markup('Unexpected error. Please <a href="https://www.openpathtutoring.com#contact?subject=New%20student%20form%20error" target="_blank">contact us</a>'), 'error')
            return redirect(url_for('main.new_student'))
    return render_template('new-student.html', title='Students', form=form, upcoming_dates=upcoming_dates, tests=tests, tutors=tutors, full_name=full_name, parents=parents)


@main_bp.route('/pay')
def pay():
    return redirect('https://link.waveapps.com/4yu6up-ne82sd')


@main_bp.route('/download/<filename>')
def download_file(filename):
    path = os.path.join(current_app.static_folder, 'files/')
    return send_from_directory(path, filename, as_attachment=False)


@main_bp.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(current_app.static_folder), 'img/favicons/favicon.ico')


@main_bp.route('/manifest.webmanifest')
def webmanifest():
    return send_from_directory(os.path.join(current_app.static_folder), 'img/favicons/manifest.webmanifest')


@main_bp.route('/robots.txt')
def static_from_root():
    return send_from_directory(current_app.static_folder, request.path[1:])


@main_bp.route('/sitemap')
@main_bp.route('/sitemap/')
@main_bp.route('/sitemap.xml')
def sitemap():
    host_components = url_parse(request.host_url)
    host_base = host_components.scheme + '://' + host_components.netloc

    static_urls = list()
    for rule in current_app.url_map.iter_rules():
        if not str(rule).startswith('/admin') and not str(rule).startswith('/user'):
            if 'GET' in rule.methods and len(rule.arguments) == 0:
                url = {'loc': f'{host_base}{str(rule)}'}
                static_urls.append(url)

    xml_sitemap = render_template('sitemap/sitemap.xml', static_urls=static_urls, host_base=host_base)
    response = make_response(xml_sitemap)
    response.headers['Content-Type'] = 'application/xml'

    return response


@main_bp.route('/score-report', methods=['GET', 'POST'])
@main_bp.route('/sat-report', methods=['GET', 'POST'])
def sat_report():
    form = SATReportForm()
    return handle_sat_report(form, 'sat-report.html')


@main_bp.route('/act-report', methods=['GET', 'POST'])
def act_report():
    form = ACTReportForm()
    return handle_act_report(form, 'act-report.html')


@main_bp.route('/<org>')
@private_login_check
def partner_page(org):
    organization = Organization.query.filter_by(slug=org).first_or_404()
    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'ss_logo_path': organization.ss_logo_path,
        'slug': organization.slug,
        'spreadsheet_id': organization.sat_spreadsheet_id,
        'color1': organization.color1,
        'color2': organization.color2,
        'color3': organization.color3,
        'font_color': organization.font_color
    }

    if is_dark_color(organization.color1):
        organization_dict['color1_contrast'] = '#ffffff'
    else:
        organization_dict['color1_contrast'] = organization.font_color

    if is_dark_color(organization.color2):
        organization_dict['color2_contrast'] = '#ffffff'
    else:
        organization_dict['color2_contrast'] = organization.font_color

    if is_dark_color(organization.color3):
        organization_dict['color3_contrast'] = '#ffffff'
    else:
        organization_dict['color3_contrast'] = organization.font_color

    return render_template('partner-page.html', title=organization.name, organization=organization_dict)


@main_bp.route('/<org>/sat', methods=['GET', 'POST'])
@private_login_check
def custom_sat_report(org):
    form = SATReportForm()
    organization = Organization.query.filter_by(slug=org).first_or_404()
    print(f'organization.slug: {organization.slug}')

    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'ss_logo_path': organization.ss_logo_path,
        'slug': organization.slug,
        'spreadsheet_id': organization.sat_spreadsheet_id,
        'color1': organization.color1,
        'color2': organization.color2,
        'color3': organization.color3,
        'font_color': organization.font_color
    }

    if is_dark_color(organization.color1):
        organization_dict['color1_contrast'] = '#ffffff'
    else:
        organization_dict['color1_contrast'] = organization.font_color

    if is_dark_color(organization.color2):
        organization_dict['color2_contrast'] = '#ffffff'
    else:
        organization_dict['color2_contrast'] = organization.font_color

    if is_dark_color(organization.color3):
        organization_dict['color3_contrast'] = '#ffffff'
    else:
        organization_dict['color3_contrast'] = organization.font_color

    return handle_sat_report(form, 'org-sat-report.html', organization=organization_dict)


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
                admin = User.query.filter(User.id == org.partner_id).first()
                score_data['admin_email'] = admin.email
            else:
                score_data['admin_email'] = None

            filename = score_data['student_name'] + ' ' + score_data['date'] + ' ' + score_data['test_display_name']
            os.rename(report_file_path, os.path.join(uploads_folder_path, filename + ' CB report.pdf'))
            os.rename(details_file_path, os.path.join(uploads_folder_path, filename + ' CB details.pdf'))
            json_file_path = os.path.join(json_folder_path, filename + '.json')

            with open(json_file_path, "w") as json_file:
                json.dump(score_data, json_file, indent=2)

            if student_ss_id:
                has_access = check_service_account_access(student_ss_id)
                if not has_access:
                    flash(Markup('Please share <a href="https://docs.google.com/spreadsheets/d/' + student_ss_id + '/edit?usp=sharing" target="_blank">your spreadsheet</a> with score-reports@sat-score-reports.iam.gserviceaccount.com for answers to be added there.'))
                    logging.error('Service account does not have access to student spreadsheet')
                    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

            sat_report_workflow_task.delay(score_data, organization_dict=organization)

            if len(score_data['answer_key_mismatches']) > 0 or len(score_data['missing_data']) > 0:
                send_unexpected_data_email(score_data)

            if organization:
                return_route = url_for('main.custom_sat_report', org=organization['slug'])
                flash(Markup(f'Your answers have been submitted successfully.<br> \
                Your score analysis should arrive in your inbox or spam folder in the next 5 minutes.<br> \
                <a href="{return_route}">Submit another test</a>'), 'success')
                return redirect(url_for('main.index'))
            else:
                return_route = url_for('main.sat_report')
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


@main_bp.route('/<org>/act', methods=['GET', 'POST'])
@private_login_check
def custom_act_report(org):
    form = ACTReportForm()
    organization = Organization.query.filter_by(slug=org).first_or_404()

    organization_dict = {
        'name': organization.name,
        'logo_path': organization.logo_path,
        'ss_logo_path': organization.ss_logo_path,
        'slug': organization.slug,
        'spreadsheet_id': organization.act_spreadsheet_id,
        'color1': organization.color1,
        'color2': organization.color2,
        'color3': organization.color3,
        'font_color': organization.font_color
    }

    if is_dark_color(organization.color1):
        organization_dict['color1_contrast'] = '#ffffff'
    else:
        organization_dict['color1_contrast'] = organization.font_color

    if is_dark_color(organization.color2):
        organization_dict['color2_contrast'] = '#ffffff'
    else:
        organization_dict['color2_contrast'] = organization.font_color

    if is_dark_color(organization.color3):
        organization_dict['color3_contrast'] = '#ffffff'
    else:
        organization_dict['color3_contrast'] = organization.font_color

    return handle_act_report(form, 'org-act-report.html', organization=organization_dict)


def handle_act_report(form, template_name, organization=None):
    hcaptcha_key = os.environ.get('HCAPTCHA_SITE_KEY')

    if request.method == 'GET':
        ss_id = request.args.get('ssId')
        if ss_id:
            form.spreadsheet_url.data = ss_id
        email = request.args.get('email')
        if email:
            form.email.data = email

    if current_user.is_authenticated:
        form.test_code.choices = load_act_test_codes()
    else:
        form.test_code.choices = [
            ["2025MC1", "Practice Test 1 (Form 25MC1)"],
            ["2025MC5", "Practice Test 2 (Form 25MC5)"]
        ]

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
            answer_img_filename = secure_filename(f"{user.first_name} {user.last_name} ACT {form.test_code.data} answer sheet {date}.{file_extension}")
            answer_img_path = os.path.join(act_uploads_path, answer_img_filename)
            answer_img.save(answer_img_path)
            logging.info(f"Saved answer image to {answer_img_path}")

            if file_extension == 'heic':
                answer_img_path = convert_heic_to_jpg(answer_img_path)

            if not is_valid_image(answer_img):
                flash('Please upload an image (jpg, png, webp, or heic)', 'error')
                return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)

            score_data = {}
            score_data['answer_img_path'] = answer_img_path
            score_data['answer_img_filename'] = answer_img_filename
            score_data['act_uploads_path'] = act_uploads_path
            score_data['act_reports_path'] = act_reports_path
            score_data['test_code'] = form.test_code.data
            score_data['test_display_name'] = f'ACT {score_data["test_code"]}'
            score_data['student_name'] = f"{user.first_name} {user.last_name}"
            score_data['email'] = form.email.data.lower()
            score_data['student_responses'] = {}
            score_data['date'] = date
            score_data['is_enhanced'] = form.test_code.data > '202502'
            score_data['is_scaled_down'] = form.is_scaled_down.data

            score_data['admin_email'] = None
            if organization:
                org = Organization.query.filter_by(slug=organization['slug']).first()
                admin = User.query.filter(User.id == org.partner_id).first()
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

            act_report_workflow_task.delay(score_data, organization_dict=organization)

            if organization:
                return_route = url_for('main.custom_act_report', org=organization['slug'])
                flash(Markup(f'Your answer sheet has been submitted successfully.<br> \
                Your score analysis should arrive in your inbox or spam folder in the next 5 minutes.<br> \
                <a href="{return_route}">Submit another test</a>'), 'success')
                return redirect(url_for('main.index'))
            else:
                return_route = url_for('act_report')
                return render_template('score-report-sent.html', return_route=return_route)

        except Exception as e:
            logger.error(f"Error sending ACT report email: {e}", exc_info=True)
            flash(f'Failed to send answer sheet. Please contact {g.hello}.', 'error')
    return render_template(template_name, form=form, hcaptcha_key=hcaptcha_key, organization=organization)
