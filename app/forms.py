from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, PasswordField, TextAreaField, \
    SubmitField, IntegerField, RadioField, SelectField, validators, FileField
from wtforms.fields import DateField, EmailField, TelField
from flask_wtf.file import FileRequired, FileAllowed
from wtforms.validators import ValidationError, InputRequired, DataRequired, \
    Email, EqualTo, Length, Optional
from app.models import User, TestDate, UserTestDate, TestScore
from datetime import datetime
import json


def validate_email(self, email):
    if not email.data:
        return
    user = User.query.filter_by(email=email.data).first()
    if user is not None:
        raise ValidationError('An account already exists for ' + user.email + '.')


class InquiryForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name', 'autocomplete': 'given-name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name', 'autocomplete': 'family-name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address', 'autocomplete': 'email'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    phone = TelField('Phone number', render_kw={'placeholder': 'Phone number', 'autocomplete': 'tel'})
    subject = StringField('Subject', render_kw={'placeholder': 'Subject'}, default='Message')
    message = TextAreaField('Message', render_kw={'placeholder': 'Message'}, \
        validators=[InputRequired()])
    role = RadioField('I am a', choices=[('parent','Parent'),('student','Student'),('tutor','Tutor'),('other','Other')], \
        default='parent', validators=[InputRequired()])
    submit = SubmitField('Submit')


class EmailListForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    submit = SubmitField()


class SignupForm(FlaskForm):
    signup_email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    reason = TextAreaField('Reason', render_kw={'placeholder': 'Reason for requesting an account', 'rows': '3'},
        validators=[InputRequired(), Length(max=300)])
    signup_submit = SubmitField('Sign up')


class LoginForm(FlaskForm):
    login_email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    password = PasswordField('Password', render_kw={'placeholder': 'Password'}, \
        validators=[InputRequired()])
    remember_me = BooleanField('Remember me')
    login_submit = SubmitField('Log in')


class RequestPasswordResetForm(FlaskForm):
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    submit = SubmitField('Request password reset')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Password', render_kw={'placeholder': 'New password'}, \
        validators=[DataRequired()])
    password2 = PasswordField('Repeat Password', render_kw={'placeholder': 'Verify password'}, \
        validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset password')


class UserForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'})
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    phone = StringField('Phone', render_kw={'placeholder': 'Phone'})
    secondary_email = StringField('Secondary email', render_kw={'placeholder': 'Secondary email'})
    timezone = StringField('Timezone', render_kw={'placeholder': 'Timezone'}, \
        validators=[InputRequired()])
    location = StringField('Location', render_kw={'placeholder': 'Location'})
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2026', '2026 (Senior)'), \
        ('2027', '2027 (Junior)'), ('2028', '2028 (Sophomore)'), ('2029', '2029 (Freshman)'), \
        ('school', 'Grade school'), ('college', 'College'), ('adult', 'Adult')])
    status = SelectField('Status', choices=[('none','None'),('active', 'Active'), \
        ('prospective','Prospective'),('paused','Paused'),('inactive','Inactive')])
    role = SelectField('Role', choices=[('student', 'Student'),('parent', 'Parent'), \
        ('tutor','Tutor'),('admin','Admin'),('partner','Partner')])
    title = StringField('Title', render_kw={'placeholder': 'Title'})
    tutor_id = SelectField('Tutor', coerce=int)
    parent_id = SelectField('Parent', coerce=int)
    is_admin = BooleanField('Admin')
    session_reminders = BooleanField('Session reminders')
    test_reminders = BooleanField('Test reminders')
    submit = SubmitField('Save')

    def __init__(self, original_email, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        self.original_email = original_email

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user is not None:
                raise ValidationError('An account already exists for ' + user.email + '.')


class NewStudentForm(FlaskForm):
    student_first_name = StringField('Student first name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    student_last_name = StringField('Student last name', render_kw={'placeholder': 'Last name'})
    pronouns = StringField('Preferred pronouns', render_kw={'placeholder': 'Pronouns'})
    student_email = EmailField('Student Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    student_phone = TelField('Student phone', render_kw={'placeholder': 'Phone'})
    timezone = StringField('Timezone', render_kw={'placeholder': 'Timezone'}, validators=[InputRequired()])
    location = StringField('Location', render_kw={'placeholder': 'Location'})
    school = StringField('School', render_kw={'placeholder': 'School'})
    grad_year = StringField('HS Graduation year', render_kw={'placeholder': 'Grad year'})
    parent_select = SelectField('Parent', coerce=int)
    parent_first_name = StringField('Parent first name', render_kw={'placeholder': 'First name'})
    parent_last_name = StringField('Parent last name', render_kw={'placeholder': 'Last name'})
    parent_email = EmailField('Parent Email address', render_kw={'placeholder': 'Email address'})
    parent_phone = TelField('Parent phone', render_kw={'placeholder': 'Phone'})
    parent2_first_name = StringField('2nd parent first name', render_kw={'placeholder': 'First name'})
    parent2_last_name = StringField('2nd parent last name', render_kw={'placeholder': 'Last name'})
    parent2_email = EmailField('2nd parent email address', render_kw={'placeholder': 'Email address'})
    parent2_phone = TelField('2nd parent phone', render_kw={'placeholder': 'Phone'})
    tutor_select = SelectField('Tutor', coerce=int)
    status = SelectField('Status', choices=[('prospective','Prospective'), ('active', 'Active'), \
        ('paused','Paused'),('inactive','Inactive')])
    subject = StringField('Primary subject', render_kw={'placeholder': 'Subject'})
    create_student_folder = BooleanField('Create folder', default=True)
    notes = TextAreaField('Additional notes (optional)', render_kw={'placeholder': 'Personality, learning style, strengths/opportunities, etc', 'rows': '4'})
    submit = SubmitField()


class TutorForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    phone = StringField('Phone', render_kw={'placeholder': 'Phone'})
    timezone = StringField('Timezone', render_kw={'placeholder': 'Timezone'}, \
        validators=[InputRequired()])
    session_reminders = BooleanField('Session reminders')
    test_reminders = BooleanField('Test reminders')
    submit = SubmitField('Save')


class TestDateForm(FlaskForm):
    test = SelectField('Test', render_kw={'placeholder': 'Test'}, choices=[('sat','SAT'),('act','ACT'),('psat','PSAT')], \
        validators=[InputRequired()])
    date = DateField('Test date', format='%Y-%m-%d', validators=[InputRequired()])
    reg_date = DateField('Registration deadline', format='%Y-%m-%d', validators=(validators.Optional(),))
    late_date = DateField('Late deadline', format='%Y-%m-%d', validators=(validators.Optional(),))
    other_date = DateField('Other deadline', format='%Y-%m-%d', validators=(validators.Optional(),))
    score_date = DateField('Score release date', format='%Y-%m-%d', validators=(validators.Optional(),))
    status = SelectField('Status', choices=[('confirmed','Confirmed'),('unconfirmed','Unconfirmed'), \
        ('school','School day'),('past','Past')])
    submit = SubmitField('Save')


class RecapForm(FlaskForm):
    students = SelectField('Student name', coerce=int, validators=[InputRequired()])
    date = DateField('Session date', format='%Y-%m-%d', default=datetime.today, validators=[InputRequired()])
    homework = TextAreaField('Homework', render_kw={'placeholder': 'Homework', 'rows': '3'}, \
        validators=[InputRequired()])
    audio = StringField('Audio recap link', render_kw={'placeholder': 'Audio recap link'})
    submit = SubmitField('Send')


class NtpaForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    biz_name = StringField('Business name', render_kw={'placeholder': 'Business name (optional)'})
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    submit = SubmitField('Submit')


class TestStrategiesForm(FlaskForm):
    first_name = StringField('Your first name', render_kw={'placeholder': 'Your first name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    relation = RadioField('I am a:', choices=[('parent','Parent'),('student','Student')], \
        validators=[InputRequired()])
    parent_name = StringField('Parent\'s name', render_kw={'placeholder': 'Parent\'s name'})
    parent_email = EmailField('Parent\'s email', render_kw={'placeholder': 'Parent\'s email'})
    student_name = StringField('Student\'s name', render_kw={'placeholder': 'Student\'s name'})
    #pronouns = RadioField('Student\'s preferred pronouns:', choices=[('he','He/him'),('she','She/her'),('they','They/them')], \
    #    validators=[InputRequired()])
    submit = SubmitField('Send me 10 Strategies to Master the SAT & ACT')


class ScoreAnalysisForm(FlaskForm):
    student_first_name = StringField('Student first name', render_kw={'placeholder': 'Student first name'}, \
        validators=[InputRequired()])
    student_last_name = StringField('Student last name', render_kw={'placeholder': 'Student last name'}, \
        validators=[InputRequired()])
    grad_year = SelectField('Graduation year', choices=[(None, 'Graduation year'), ('2026', '2026 (Senior)'), \
        ('2027', '2027 (Junior)'), ('2028', '2028 (Sophomore)'), ('2029', '2029 (Freshman)'), \
        ('graduated', 'Graduated'), ('school', 'Grade school')])
    parent_first_name = StringField('Parent first name', render_kw={'placeholder': 'Parent first name'}, \
        validators=[InputRequired()])
    parent_last_name = StringField('Parent last name', render_kw={'placeholder': 'Parent last name'}, \
        validators=[InputRequired()])
    parent_email = EmailField('Parent email address', render_kw={'placeholder': 'Parent email'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    submit = SubmitField()


class ReportSubmittedSignupForm(FlaskForm):
    sat_ss_id = StringField('SAT spreadsheet ID', render_kw={'placeholder': 'SAT spreadsheet ID'})
    act_ss_id = StringField('ACT spreadsheet ID', render_kw={'placeholder': 'ACT spreadsheet ID'})
    submit = SubmitField()


class SATReportForm(FlaskForm):
    email = EmailField('Email address', render_kw={'placeholder': 'Required'})
    report_file = FileField('Score Report PDF', render_kw={'placeholder': 'Score Report PDF'}, \
        validators=[FileRequired('PDF upload error'), FileAllowed(['pdf'], 'PDF files only. Please see the <a href="#" data-bs-toggle="modal" data-bs-target="#report-modal">instructions</a>')])
    details_file = FileField('Score Details PDF', render_kw={'placeholder': 'Score Details PDF'}, \
        validators=[FileRequired('PDF upload error'), FileAllowed(['pdf'], 'PDF files only. Please see the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a>')])
    spreadsheet_url = StringField('Student spreadsheet URL or ID', render_kw={'placeholder': 'Optional'})
    submit = SubmitField()


class ACTReportForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'Student first name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Student last name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'})
    test_code = SelectField('Test code', choices=[], validators=[InputRequired()])
    is_scaled_down = BooleanField('Use scaled-down scoring')
    answer_img = FileField('Photo of answer sheet', render_kw={'placeholder': 'Photo of answer sheet'}, \
        validators=[FileRequired('Answer sheet photo required'), FileAllowed(['jpg', 'jpeg', 'png', 'heic', 'webp', 'tif'], 'Images only please (jpg, png, heic, webp, or tif)')])
    spreadsheet_url = StringField('Student spreadsheet URL or ID', render_kw={'placeholder': 'Optional'})
    submit = SubmitField()


class ReviewForm(FlaskForm):
    text = TextAreaField('Review', render_kw={'placeholder': 'Review'}, \
        validators=[InputRequired()])
    author = StringField('Author', render_kw={'placeholder': 'Author'}, \
        validators=[InputRequired()])
    photo = FileField('Photo', render_kw={'placeholder': 'Photo'}, \
        validators=[FileAllowed(['jpg', 'jpeg', 'png'])])
    submit = SubmitField()

class OrgSettingsForm(FlaskForm):
    org_name = StringField('Organization name', render_kw={'placeholder': 'Organization name'}, \
    validators=[InputRequired()])
    slug = StringField('Organization slug', render_kw={'placeholder': 'Organization slug'}, \
        validators=[InputRequired()])
    role = SelectField('Org role', choices=[('school','School'), ('iec','IEC'), ('tutoring','Tutoring company')])
    partner_id = SelectField('Partner', coerce=int)
    first_name = StringField('Partner first name', render_kw={'placeholder': 'Partner first name'})
    last_name = StringField('Partner last name', render_kw={'placeholder': 'Partner last name'})
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'})
    color1 = StringField('Primary color', render_kw={'placeholder': '#ffffff'}, \
        validators=[InputRequired()])
    color2 = StringField('Secondary color', render_kw={'placeholder': '#ffffff'}, \
        validators=[InputRequired()])
    color3 = StringField('Tertiary color', render_kw={'placeholder': '#ffffff'}, \
        validators=[InputRequired()])
    font_color = StringField('Font color', render_kw={'placeholder': '#ffffff'}, \
        validators=[InputRequired()])
    logo = FileField('Logo', validators=[FileAllowed(['png', 'jpg', 'jpeg', 'webp'], 'Images only please (png, jpg, jpeg, webp)')])
    copy_ss_logo = BooleanField('Copy logo for spreadsheets?')
    ss_logo = FileField('Spreadsheet logo', validators=[FileAllowed(['png', 'jpg', 'jpeg', 'webp'], 'Images only please (png, jpg, jpeg, webp)')])
    sat_ss_id = StringField('SAT template spreadsheet ID', render_kw={'placeholder': 'SAT template spreadsheet ID'})
    act_ss_id = StringField('ACT template spreadsheet ID', render_kw={'placeholder': 'ACT template spreadsheet ID'})
    is_private = BooleanField('Make organization private')
    save = SubmitField()

class FreeResourcesForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    submit = SubmitField('Get free access')

class NominationForm(FlaskForm):
    student_first_name = StringField('Student first name', render_kw={'placeholder': 'First name'}, validators=[DataRequired()])
    student_last_name = StringField('Student last name', render_kw={'placeholder': 'Last name'}, validators=[DataRequired()])
    student_email = StringField('Student email', render_kw={'placeholder': 'Email'}, validators=[DataRequired(), Email()])
    parent_first_name = StringField('Parent first name', render_kw={'placeholder': 'First name'}, validators=[DataRequired()])
    parent_last_name = StringField('Parent last name', render_kw={'placeholder': 'Last name'}, validators=[DataRequired()])
    parent_email = StringField('Parent Email', render_kw={'placeholder': 'Email'}, validators=[DataRequired(), Email()])
    nominator_first_name = StringField('Your first name', render_kw={'placeholder': 'First name'})
    nominator_last_name = StringField('Your last name', render_kw={'placeholder': 'Last name'})
    nominator_email = StringField('Your email', render_kw={'placeholder': 'Email'})
    nomination_text = TextAreaField(
        'Nomination text',
        render_kw={'placeholder': 'Why does this student deserve a test prep scholarship?', 'rows': '5'},
        validators=[DataRequired()]
    )
    is_anonymous = BooleanField('Do not share my name with the student or parent')
    is_self_nomination = BooleanField('I am nominating myself')
    is_caregiver_nomination = BooleanField('I am the student\'s parent or guardian')
    submit = SubmitField('Submit')
