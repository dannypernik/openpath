"""Auth blueprint routes for authentication."""

from flask import render_template, flash, redirect, url_for, request, current_app
from flask_login import current_user, login_user, logout_user, login_required

from app.blueprints.auth import auth_bp
from app.extensions import db, hcaptcha
from app.helpers import full_name, get_next_page
from app.forms import SignupForm, LoginForm, RequestPasswordResetForm, ResetPasswordForm
from app.models import User
from app.email import send_verification_email, send_password_reset_email


@auth_bp.route('/signin', methods=['GET', 'POST'])
def signin():
    next = get_next_page()
    if current_user.is_authenticated:
        flash('You are already signed in.')
        return redirect(url_for('auth.start_page'))
    form = LoginForm()
    signup_form = SignupForm()
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    form = LoginForm()
    signup_form = SignupForm()
    next = get_next_page()
    hello = current_app.config['HELLO_EMAIL']
    if signup_form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('auth.signin', next=next))
        email_exists = User.query.filter_by(email=signup_form.email.data.lower()).first()
        if email_exists:
            flash('An account already exists for this email. Try logging in or resetting your password.', 'error')
            return redirect(url_for('auth.signin', next=next))
        user = User(first_name=signup_form.first_name.data, last_name=signup_form.last_name.data,
                    email=signup_form.email.data.lower())
        db.session.add(user)
        db.session.commit()
        from app.email import send_signup_request_email
        email_status = send_signup_request_email(user, next)
        if email_status == 200:
            flash('Thanks for reaching out! We\'ll be in touch.')
            return redirect(url_for('index'))
        else:
            flash('Signup request email failed to send, please contact ' + hello, 'error')
        return redirect(url_for(next, org=request.view_args.get('org')))
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        flash('You are already signed in.')
        return redirect(url_for('auth.start_page'))
    form = LoginForm()
    signup_form = SignupForm()
    next = get_next_page()
    org = request.args.get('org')
    hello = current_app.config['HELLO_EMAIL']

    if form.validate_on_submit():
        if hcaptcha.verify():
            pass
        else:
            flash('Captcha was unsuccessful. Please try again.', 'error')
            return redirect(url_for('auth.signin', next=next))
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and not user.password_hash:
            flash('Please verify your email to set or reset your password.')
            return redirect(url_for('auth.request_password_reset'))
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('auth.signin', next=next))
        login_user(user)
        if not user.is_verified:
            email_status = send_verification_email(user)
            if email_status == 200:
                flash('Please check your inbox to verify your email.')
            else:
                flash('Verification email did not send. Please contact ' + hello, 'error')
        return redirect(url_for(next, org=org))
    return render_template('signin.html', title='Sign in', form=form, signup_form=signup_form)


@auth_bp.route('/logout')
def logout():
    logout_user()
    next = get_next_page()
    return redirect(url_for('auth.signin', next=next))


@auth_bp.route('/start-page')
@login_required
def start_page():
    if current_user.is_admin:
        return redirect(url_for('admin.students'))
    elif current_user.password_hash:
        return redirect(url_for('test_reminders'))
    else:
        return redirect(url_for('auth.set_password'))


@auth_bp.route('/verify-email/<token>', methods=['GET', 'POST'])
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
            return redirect(url_for('auth.set_password', token=token, next=next))
    else:
        flash('Your verification link is expired or invalid. Log in to receive a new link.')
        return redirect(url_for('auth.signin'))


@auth_bp.route('/unsubscribe', methods=['GET', 'POST'])
def unsubscribe():
    from app.email import send_unsubscribe_email
    import logging
    logger = logging.getLogger(__name__)

    form = RequestPasswordResetForm()

    email = request.args.get('email')
    if email:
        form.email.data = email

    if form.validate_on_submit():
        email = form.email.data.lower()
        try:
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


@auth_bp.route('/request-password-reset', methods=['GET', 'POST'])
def request_password_reset():
    form = RequestPasswordResetForm()
    hello = current_app.config['HELLO_EMAIL']

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
            return redirect(url_for('auth.request_password_reset'))

        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            email_status = send_password_reset_email(user, next)
            if email_status == 200:
                flash('Check your email for instructions to reset your password.')
            else:
                flash('Email failed to send, please contact ' + hello, 'error')
        else:
            flash('Check your email for instructions to reset your password')
        return redirect(url_for('auth.signin'))
    return render_template('request-password-reset.html', title='Reset password', form=form)


@auth_bp.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    user = User.verify_email_token(token)
    next = request.args.get('next')
    if not user:
        flash('The password reset link is expired or invalid. Please try again.')
        return redirect(url_for('auth.request_password_reset', next=next))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.is_verified = True
        db.session.commit()
        login_user(user)
        flash('Your password has been saved.')
        if next in current_app.view_functions:
            return redirect(url_for(next))
        else:
            return redirect(url_for('auth.start_page'))
    return render_template('set-password.html', form=form)
