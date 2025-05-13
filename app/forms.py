from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, PasswordField, TextAreaField, \
    SubmitField, IntegerField, RadioField, SelectField, validators, FileField
from wtforms.fields import DateField, EmailField, ColorField
from flask_wtf.file import FileRequired, FileAllowed
from wtforms.validators import ValidationError, InputRequired, DataRequired, \
    Email, EqualTo, Length
from app.models import User, TestDate, UserTestDate, TestScore
from datetime import datetime


def validate_email(self, email):
    user = User.query.filter_by(email=email.data).first()
    if user is not None:
        raise ValidationError('An account already exists for ' + user.email + '.')


class InquiryForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    phone = StringField('Phone number (optional)', render_kw={'placeholder': 'Phone number (optional)'})
    subject = StringField('Subject', render_kw={'placeholder': 'Subject'}, default='Message')
    message = TextAreaField('Message', render_kw={'placeholder': 'Message'}, \
        validators=[InputRequired()])
    submit = SubmitField('Submit')


class EmailListForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    submit = SubmitField()


class SignupForm(FlaskForm):
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    password = PasswordField('Password', render_kw={'placeholder': 'Password'}, \
        validators=[InputRequired()])
    password2 = PasswordField('Repeat Password', render_kw={'placeholder': 'Repeat Password'}, \
        validators=[InputRequired(), EqualTo('password',message='Passwords do not match.')])
    submit = SubmitField('Sign up')


class LoginForm(FlaskForm):
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    password = PasswordField('Password', render_kw={'placeholder': 'Password'}, \
        validators=[InputRequired()])
    remember_me = BooleanField('Remember me')
    submit = SubmitField('Log in')


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


# def get_tutors():
#     return User.query.filter_by(role='tutor')

# def get_parents():
#     return User.query.filter_by(role='parent')

# def full_name(User):
#     return User.first_name + ' ' + User.last_name


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
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2025', '2025 (Senior)'), \
        ('2026', '2026 (Junior)'), ('2027', '2027 (Sophomore)'), ('2028', '2028 (Freshman)'), \
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


class StudentForm(FlaskForm):
    student_name = StringField('Student first name', render_kw={'placeholder': 'Student first name'}, \
        validators=[InputRequired()])
    student_last_name = StringField('Student last name', render_kw={'placeholder': 'Student last name'})
    student_email = EmailField('Student Email address', render_kw={'placeholder': 'Student Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address'), \
            validate_email])
    student_phone = StringField('Student phone', render_kw={'placeholder': 'Student phone'})
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2025', '2025 (Senior)'), \
        ('2026', '2026 (Junior)'), ('2027', '2027 (Sophomore)'), ('2028', '2028 (Freshman)'), \
        ('college', 'College'), ('school', 'Grade school')])
    parent_id = SelectField('Parent', coerce=int)
    parent_name = StringField('Parent first name', render_kw={'placeholder': 'Parent first name'})
    parent_last_name = StringField('Parent last name', render_kw={'placeholder': 'Parent last name'})
    parent_email = EmailField('Parent Email address', render_kw={'placeholder': 'Parent Email address'})
    secondary_email = EmailField('Parent email 2', render_kw={'placeholder': 'Parent email 2'})
    parent_phone = StringField('Parent phone', render_kw={'placeholder': 'Parent phone'})
    timezone = StringField('Timezone', render_kw={'placeholder': 'Timezone'}, \
        validators=[InputRequired()])
    location = StringField('Location', render_kw={'placeholder': 'Location'})
    status = SelectField('Status', choices=[('active', 'Active'),('prospective','Prospective'), \
        ('paused','Paused'),('inactive','Inactive')])
    tutor_id = SelectField('Tutor', coerce=int)
    submit = SubmitField('Save')


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
    student_first_name = StringField('Student\'s first name', render_kw={'placeholder': 'Student\'s first name'}, \
        validators=[InputRequired()])
    student_last_name = StringField('Student\'s last name', render_kw={'placeholder': 'Student\'s last name'}, \
        validators=[InputRequired()])
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2025', '2025 (Senior)'), \
        ('2026', '2026 (Junior)'), ('2027', '2027 (Sophomore)'), ('2028', '2028 (Freshman)'), \
        ('college', 'College'), ('school', 'Grade school')])
    school = StringField('School', render_kw={'placeholder': 'Student\'s school'}, \
        validators=[InputRequired()])
    parent_first_name = StringField('Parent\'s first name', render_kw={'placeholder': 'Parent\'s first name'}, \
        validators=[InputRequired()])
    parent_email = EmailField('Parent\'s email address', render_kw={'placeholder': 'Parent\'s email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    submit = SubmitField()


class SATReportForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    # test_code = SelectField('Bluebook test number', choices=[(None, 'Bluebook test number'), ('sat1','SAT 1'),
    #     ('sat2','SAT 2'), ('sat3','SAT 3'), ('sat4','SAT 4'), ('sat5','SAT 5'), ('sat6','SAT 6'), \
    #     ('psat1','PSAT 1'), ('psat2','PSAT 2')], validators=[InputRequired()])
    # rw_score = IntegerField('Reading & Writing score', render_kw={'placeholder': 'Reading & Writing score'}, \
    #     validators=[InputRequired()])
    # m_score = IntegerField('Math score', render_kw={'placeholder': 'Math score'}, \
    #     validators=[InputRequired()])
    report_file = FileField('Score Report PDF', render_kw={'placeholder': 'Score Report PDF'}, \
        validators=[FileRequired('PDF upload error'), FileAllowed(['pdf'], 'PDF files only. Please see the <a href="#" data-bs-toggle="modal" data-bs-target="#report-modal">instructions</a>.')])
    details_file = FileField('Score Details PDF', render_kw={'placeholder': 'Score Details PDF'}, \
        validators=[FileRequired('PDF upload error'), FileAllowed(['pdf'], 'PDF files only. Please see the <a href="#" data-bs-toggle="modal" data-bs-target="#details-modal">instructions</a>.')])
    spreadsheet_url = StringField('Student spreadsheet URL', render_kw={'placeholder': 'Optional'})
    submit = SubmitField()


class ACTReportForm(FlaskForm):
    first_name = StringField('First name', render_kw={'placeholder': 'First name'}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={'placeholder': 'Last name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message='Please enter a valid email address')])
    test_code = SelectField('Test code', choices=[(None, 'Test code (Form number)'), \
        ('202206','202206 (Form E26)'), ('202212','202212 (Form F07)'),
        ('202304','202304 (Form F11)'), ('202306','202306 (Form F12)'), ('202309','202309 (Form G01)'), \
        ('202404','202404 (Form G19)'), ('202406','202406 (Form G20)')],
         validators=[InputRequired()])
    answer_img = FileField('Photo of answer sheet', render_kw={'placeholder': 'Photo of answer sheet'}, \
        validators=[FileRequired('Answer sheet photo required'), FileAllowed(['jpg', 'jpeg', 'png', 'webp', 'heic'], 'Images only please (jpg, png, webp, or heic)')])
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
    org_id = SelectField('Organization', coerce=int)
    org_name = StringField('Organization name', render_kw={'placeholder': 'Organization name'}, \
    validators=[InputRequired()])
    partner_id = SelectField('Partner', coerce=int)
    first_name = StringField('Partner first name', render_kw={'placeholder': 'Partner first name'})
    last_name = StringField('Partner last name', render_kw={'placeholder': 'Partner last name'})
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'})
    color1 = ColorField('Primary color', render_kw={'placeholder': 'Primary color'}, \
        validators=[InputRequired()])
    color2 = ColorField('Secondary color', render_kw={'placeholder': 'Secondary color'}, \
        validators=[InputRequired()])
    color3 = ColorField('Tertiary color', render_kw={'placeholder': 'Tertiary color'}, \
        validators=[InputRequired()])
    logo = FileField('Logo', validators=[FileAllowed(['png', 'jpg', 'jpeg'], 'Images only please (png, jpg, jpeg)')])
    submit = SubmitField('Save')
