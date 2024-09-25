import os
from flask import Flask, render_template, flash, Markup, redirect, url_for, \
    request, send_from_directory, send_file, make_response
from app import app, db, login, hcaptcha, full_name
from app.forms import InquiryForm, EmailListForm, TestStrategiesForm, SignupForm, LoginForm, \
    StudentForm, ScoreAnalysisForm, TestDateForm, UserForm, RequestPasswordResetForm, \
    ResetPasswordForm, TutorForm, RecapForm, NtpaForm, ScoreReportForm
from flask_login import current_user, login_user, logout_user, login_required, login_url
from app.models import User, TestDate, UserTestDate, TestScore
from werkzeug.urls import url_parse
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from app.email import send_contact_email, send_verification_email, send_password_reset_email, \
    send_test_strategies_email, send_score_analysis_email, send_test_registration_email, \
    send_prep_class_email, send_signup_notification_email, send_session_recap_email, \
    send_confirmation_email, send_schedule_conflict_email, send_ntpa_email
from functools import wraps
import requests
import json
from reminders import get_student_events
from score_reader import get_student_answers, mod_difficulty_check
from score_reports import create_sat_score_report

@app.before_request
def before_request():
    if current_user.is_authenticated:
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
    return dict(last_updated=dir_last_updated('app/static'), hello=hello, phone=phone)

def admin_required(f):
    @login_required
    @wraps(f)
    def wrap(*args, **kwargs):
        if current_user.is_admin:
            return f(*args, **kwargs)
        else:
            flash('You must have administrator privileges to access this page.', 'error')
            logout_user()
            return redirect(login_url('signin', next_url=request.url))
    return wrap

def proper(name):
    try:
        name = name.title()
        return name
    except:
        return name


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
def index():
    form = InquiryForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
            conf_status = send_confirmation_email(user, message)
            if conf_status == 200:
                flash('Please check ' + user.email + ' for a confirmation email. Thank you for reaching out!')
                return redirect(url_for('index', _anchor='home'))
        flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('index.html', form=form, last_updated=dir_last_updated('app/static'))


@app.route('/about')
def about():
    return render_template('about.html', title='About')

@app.route('/reviews')
def reviews():
    return render_template('reviews.html', title='Reviews')


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
    next = request.args.get('next')
    if signup_form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('signin', next=next))
        email_exists = User.query.filter_by(email=signup_form.email.data.lower()).first()
        if email_exists:
            flash('An account already exists for this email. Try logging in or resetting your password.', 'error')
            return redirect(url_for('signin', next=next))
        user = User(first_name=signup_form.first_name.data, last_name=signup_form.last_name.data, \
            email=signup_form.email.data.lower())
        user.set_password(signup_form.password.data)
        db.session.add(user)
        db.session.commit()
        email_status = send_verification_email(user)
        login_user(user)
        if email_status == 200:
            flash('Welcome! Please check your inbox to verify your email.')
        else:
            flash('Verification email failed to send, please contact ' + hello, 'error')
        if not next or url_parse(next).netloc != '':
            return redirect(url_for('start_page'))
        return redirect(next)
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        flash('You are already signed in.')
        return redirect(url_for('start_page'))
    form = LoginForm()
    signup_form = SignupForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
        next = request.args.get('next')
        if not next or url_parse(next).netloc != '':
            return redirect(url_for('start_page'))
        return redirect(next)
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
    if user:
        login_user(user)
        user.is_verified = True
        db.session.add(user)
        db.session.commit()
        flash('Thank you for verifying your account.')
        if user.password_hash:
            return redirect(url_for('start_page'))
        else:
            return redirect(url_for('set_password', token=token))
    else:
        flash('Your verification link is expired or invalid. Log in to receive a new link.')
        return redirect(url_for('signin'))


@app.route('/request-password-reset', methods=['GET', 'POST'])
def request_password_reset():
    form = RequestPasswordResetForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('request_password_reset'))
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            email_status = send_password_reset_email(user)
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
    if not user:
        flash('The password reset link is expired or invalid. Please try again.')
        return redirect(url_for('request_password_reset'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.is_verified = True
        db.session.commit()
        login_user(user)
        flash('Your password has been saved.')
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
        statuses=statuses, full_name=full_name, proper=proper, )


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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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


@app.route('/sat', methods=['GET', 'POST'])
def sat():
    form = EmailListForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('sat'))
        email_exists = User.query.filter_by(email=form.email.data.lower()).first()
        if email_exists:
            flash('An account already exists for this email. Try logging in or resetting your password.', 'error')
            return redirect(url_for('signin'))
        user = User(first_name=form.first_name.data, email=form.email.data.lower())
        try:
            db.session.add(user)
            db.session.commit()
        except:
            db.session.rollback()
            flash('User was not saved, please contact ' + hello, 'error')
        email_status = send_contact_email(user, 'Interested in Digital SAT app', 'Digital SAT inquiry')
        if email_status == 200:
            verification_status = send_verification_email(user)
            if verification_status == 200:
                flash('Please check your inbox to verify your email.')
                return redirect(url_for('sat'))
        flash('Verification email did not send, please contact ' + hello, 'error')
    return render_template('sat.html', form=form)


@app.route('/griffin', methods=['GET', 'POST'])
def griffin():
    form = ScoreAnalysisForm()
    school='Griffin School'
    test='ACT'
    submit_text='Send me the score analysis'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('griffin'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_score_analysis_email(student, parent, school)
        if email_status == 200:
            return render_template('score-analysis-submitted.html', email=form.parent_email.data)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('griffin.html', form=form, school=school, test=test, \
        submit_text=submit_text)


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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('kaps'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = send_prep_class_email(student, parent, school, test, time, location, cost)
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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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


@app.route('/spartans', methods=['GET', 'POST'])
def spartans():
    form = ScoreAnalysisForm()
    school = 'Spartans Swimming'
    test = 'ACT, SAT, or PSAT'
    date = 'Saturday, December 3rd, 2022'
    time = '9:30am to 1:00pm'
    location = 'Zoom'
    contact_info = ''
    submit_text = 'Register'
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('spartans'))
        student = User(first_name=form.student_first_name.data, last_name=form.student_last_name.data, \
            grad_year=form.grad_year.data)
        parent = User(first_name=form.parent_first_name.data, email=form.parent_email.data)
        email_status = tbd(student, parent, school, test, date, time, location, contact_info)
        if email_status == 200:
            return render_template('test-registration-submitted.html', email=parent.email,
            student=student, test=test)
        else:
            flash('Email failed to send, please contact ' + hello, 'error')
    return render_template('spartans.html', form=form, school=school, test=test, \
        date=date, time=time, location=location, submit_text=submit_text)


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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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
            flash('A computer has questioned your humanity. Please try again.', 'error')
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


@app.route('/score-report', methods=['GET', 'POST'])
def score_report():
    form = ScoreReportForm()
    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('A computer has questioned your humanity. Please try again.', 'error')
            return redirect(url_for('score_report'))

        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            user.email = form.email.data.lower()
            user.first_name = form.first_name.data
            user.last_name = form.last_name.data
        else:
            user = User(first_name=form.first_name.data, last_name=form.last_name.data, email=form.email.data.lower())

        db.session.add(user)
        db.session.flush()

        pdf_folder_path = 'app/static/files/scores/pdf'
        json_folder_path = 'app/static/files/scores/json'
        full_name = user.first_name + ' ' + user.last_name

        score_details_file = request.files['score_details_file']
        score_details_file_path = os.path.join(pdf_folder_path, full_name + '.pdf')
        score_details_file.save(score_details_file_path)
        score_data = get_student_answers(score_details_file_path)
        score_data['student_name'] = full_name
        score_data['email'] = user.email
        score_data['rw_score'] = form.rw_score.data
        score_data['m_score'] = form.m_score.data

        if not os.path.exists(pdf_folder_path):
            os.makedirs(pdf_folder_path)

        if not os.path.exists(json_folder_path):
            os.makedirs(json_folder_path)

        filename = full_name + ' ' + score_data['date'] + ' ' + score_data['test_code']
        os.rename(score_details_file_path, os.path.join(pdf_folder_path, filename + '.pdf'))
        with open(os.path.join(json_folder_path, filename + '.json'), "w") as json_file:
            json.dump(score_data, json_file, indent=2)

        test = TestScore(test_code=score_data['test_code'], date=score_data['date'], rw_score=form.rw_score.data,
            m_score=form.m_score.data, total_score=form.rw_score.data + form.m_score.data,
            json_path=os.path.join('app/static/files/scores/json', filename + '.json'),
            type='practice', user_id=user.id)

        db.session.add(test)
        db.session.commit()

        score_data['is_rw_hard'], score_data['is_m_hard'] = mod_difficulty_check(score_data)

        try:
            create_sat_score_report(score_data)
        except:
            flash('Score report could not be generated', 'error')
            return redirect(url_for('score_report'))
        flash('Success! Your score report should arrive to your inbox in the next 5 minutes.')
    return render_template('score-report.html', form=form)


@app.route('/pay')
def pay():
    return redirect('https://link.waveapps.com/4yu6up-ne82sd')

@app.route('/download/<filename>')
def download_file (filename):
    path = os.path.join(app.root_path, 'static/files/')
    return send_from_directory(path, filename, as_attachment=False)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'img/favicons/favicon.ico')

@app.route('/manifest.webmanifest')
def webmanifest():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'img/favicons/manifest.webmanifest')

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