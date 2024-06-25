from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, PasswordField, TextAreaField, \
    SubmitField, IntegerField, RadioField, SelectField, validators
from wtforms.fields.html5 import DateField, EmailField
from wtforms.validators import ValidationError, InputRequired, DataRequired, \
    Email, EqualTo, Length
from app.models import User, TestDate, UserTestDate
from datetime import datetime


def validate_email(self, email):
    user = User.query.filter_by(email=email.data).first()
    if user is not None:
        raise ValidationError('An account already exists for ' + user.email + '.')


class InquiryForm(FlaskForm):
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address")])
    phone = StringField('Phone number (optional)', render_kw={"placeholder": "Phone number (optional)"})
    subject = StringField('Subject', render_kw={'placeholder': 'Subject'}, default='Message')
    message = TextAreaField('Message', render_kw={"placeholder": "Message"}, \
        validators=[InputRequired()])
    submit = SubmitField('Submit')


class EmailListForm(FlaskForm):
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address"), \
            validate_email])
    submit = SubmitField()


class SignupForm(FlaskForm):
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address"), \
            validate_email])
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={"placeholder": "Last name"}, \
        validators=[InputRequired()])
    password = PasswordField('Password', render_kw={"placeholder": "Password"}, \
        validators=[InputRequired()])
    password2 = PasswordField('Repeat Password', render_kw={"placeholder": "Repeat Password"}, \
        validators=[InputRequired(), EqualTo('password',message="Passwords do not match.")])
    submit = SubmitField('Sign up')


class LoginForm(FlaskForm):
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address")])
    password = PasswordField('Password', render_kw={"placeholder": "Password"}, \
        validators=[InputRequired()])
    remember_me = BooleanField('Remember me')
    submit = SubmitField('Log in')


class RequestPasswordResetForm(FlaskForm):
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address")])
    submit = SubmitField('Request password reset')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Password', render_kw={"placeholder": "New password"}, \
        validators=[DataRequired()])
    password2 = PasswordField('Repeat Password', render_kw={"placeholder": "Verify password"}, \
        validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset password')


# def get_tutors():
#     return User.query.filter_by(role='tutor')

# def get_parents():
#     return User.query.filter_by(role='parent')

# def full_name(User):
#     return User.first_name + " " + User.last_name


class UserForm(FlaskForm):
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={"placeholder": "Last name"})
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address")])
    phone = StringField('Phone', render_kw={"placeholder": "Phone"})
    secondary_email = StringField('Secondary email', render_kw={"placeholder": "Secondary email"})
    timezone = IntegerField('Timezone', render_kw={"placeholder": "Timezone"}, \
        validators=[InputRequired()])
    location = StringField('Location', render_kw={"placeholder": "Location"})
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2025', '2025 (Senior)'), \
        ('2026', '2026 (Junior)'), ('2027', '2027 (Sophomore)'), ('2028', '2028 (Freshman)'), \
        ('college', 'College'), ('school', 'Grade school')])
    status = SelectField('Status', choices=[('none','None'),('active', 'Active'), \
        ('prospective','Prospective'),('paused','Paused'),('inactive','Inactive')])
    role = SelectField('Role', choices=[('student', 'Student'),('parent', 'Parent'), \
        ('tutor','Tutor'),('admin','Admin')])
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
    student_name = StringField('Student first name', render_kw={"placeholder": "Student first name"}, \
        validators=[InputRequired()])
    student_last_name = StringField('Student last name', render_kw={"placeholder": "Student last name"})
    student_email = EmailField('Student Email address', render_kw={"placeholder": "Student Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address"), \
            validate_email])
    student_phone = StringField('Student phone', render_kw={"placeholder": "Student phone"})
    grad_year = SelectField('Grad year', choices=[(None, 'Grad year'), ('2025', '2025 (Senior)'), \
        ('2026', '2026 (Junior)'), ('2027', '2027 (Sophomore)'), ('2028', '2028 (Freshman)'), \
        ('college', 'College'), ('school', 'Grade school')])
    parent_id = SelectField('Parent', coerce=int)
    parent_name = StringField('Parent first name', render_kw={"placeholder": "Parent first name"})
    parent_last_name = StringField('Parent last name', render_kw={"placeholder": "Parent last name"})
    parent_email = EmailField('Parent Email address', render_kw={"placeholder": "Parent Email address"})
    secondary_email = EmailField('Parent email 2', render_kw={"placeholder": "Parent email 2"})
    parent_phone = StringField('Parent phone', render_kw={"placeholder": "Parent phone"})
    timezone = StringField('Timezone', render_kw={"placeholder": "Timezone"}, \
        validators=[InputRequired()])
    location = StringField('Location', render_kw={"placeholder": "Location"})
    status = SelectField('Status', choices=[('active', 'Active'),('prospective','Prospective'), \
        ('paused','Paused'),('inactive','Inactive')])
    tutor_id = SelectField('Tutor', coerce=int)
    submit = SubmitField('Save')


class TutorForm(FlaskForm):
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={"placeholder": "Last name"}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address"), \
            validate_email])
    phone = StringField('Phone', render_kw={"placeholder": "Phone"})
    timezone = StringField('Timezone', render_kw={"placeholder": "Timezone"}, \
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
    homework = TextAreaField('Homework', render_kw={"placeholder": "Homework", 'rows': '3'}, \
        validators=[InputRequired()])
    audio = StringField('Audio recap link', render_kw={'placeholder': 'Audio recap link'})
    submit = SubmitField('Send')


class NtpaForm(FlaskForm):
    first_name = StringField('First name', render_kw={"placeholder": "First name"}, \
        validators=[InputRequired()])
    last_name = StringField('Last name', render_kw={"placeholder": "Last name"}, \
        validators=[InputRequired()])
    biz_name = StringField('Business name', render_kw={"placeholder": "Business name (optional)"})
    email = EmailField('Email address', render_kw={"placeholder": "Email address"}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address"), \
            validate_email])
    submit = SubmitField('Submit')    


class TestStrategiesForm(FlaskForm):
    first_name = StringField('Your first name', render_kw={'placeholder': 'Your first name'}, \
        validators=[InputRequired()])
    email = EmailField('Email address', render_kw={'placeholder': 'Email address'}, \
        validators=[InputRequired(), Email(message="Please enter a valid email address")])
    relation = RadioField('I am a:', choices=[('parent','Parent'),('student','Student')], \
        validators=[InputRequired()])
    parent_name = StringField('Parent\'s name', render_kw={'placeholder': 'Parent\'s name'})
    parent_email = EmailField('Parent\'s email', render_kw={'placeholder': 'Parent\'s email'})
    student_name = StringField('Student\'s name', render_kw={'placeholder': 'Student\'s name'})
    #pronouns = RadioField('Student\'s preferred pronouns:', choices=[("he","He/him"),("she","She/her"),("they","They/them")], \
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