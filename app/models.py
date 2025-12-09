from datetime import datetime
from time import time
import jwt
from flask import current_app
from app.extensions import db, login
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


class UserTestDate(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    test_date_id = db.Column(db.Integer, db.ForeignKey('test_date.id'), primary_key=True)
    is_registered = db.Column(db.Boolean, default=False)
    users = db.relationship('User', backref=db.backref('planned_tests', lazy='dynamic'))
    test_dates = db.relationship('TestDate', backref=db.backref('users_interested'))


class TestScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(16))
    test_code = db.Column(db.String(8))
    rw_score = db.Column(db.Integer)
    m_score = db.Column(db.Integer)
    total_score = db.Column(db.Integer)
    type = db.Column(db.String(24))
    json_path = db.Column(db.String(128))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(32), index=True)
    last_name = db.Column(db.String(32), index=True)
    email = db.Column(db.String(64), unique=True, index=True)
    phone = db.Column(db.String(32), index=True)
    secondary_email = db.Column(db.String(64))
    password_hash = db.Column(db.String(128))
    timezone = db.Column(db.String(32))
    location = db.Column(db.String(128))
    title = db.Column(db.String(128))
    status = db.Column(db.String(24), default='active', index=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    students = db.relationship('User',
        backref=db.backref('tutor', lazy='joined', remote_side=[id]),
        primaryjoin=(id == tutor_id),
        foreign_keys=[tutor_id])
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    children = db.relationship('User',
        primaryjoin=(id == parent_id),
        backref=db.backref('parent', lazy='joined', remote_side=[id]),
        foreign_keys=[parent_id],
        post_update=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    last_viewed = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(24), index=True)
    school = db.Column(db.String(64))
    grad_year = db.Column(db.String(16))
    subject = db.Column(db.String(64))
    is_admin = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    session_reminders = db.Column(db.Boolean, default=True)
    test_reminders = db.Column(db.Boolean, default=True)
    test_dates = db.relationship(
        'UserTestDate',
        foreign_keys=[UserTestDate.user_id],
        backref=db.backref('user', lazy='joined'),
        lazy='select',
        cascade='all, delete-orphan')
    test_scores = db.relationship('TestScore',
        foreign_keys=[TestScore.user_id],
        backref=db.backref('user', lazy='joined'),
        lazy='dynamic',
        cascade='all, delete-orphan')

    def __repr__(self):
        return '<User {}>'.format(self.email)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_email_verification_token(self, expires_in=3600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256')

    def interested_test_date(self, test_date):
        t = UserTestDate.query.filter_by(user_id=self.id, test_date_id=test_date.id).first()
        if t:
            t.is_registered = False
        else:
            t = UserTestDate(user_id=self.id, test_date_id=test_date.id, is_registered=False)
            db.session.add(t)
        db.session.commit()

    def remove_test_date(self, test_date):
        f = UserTestDate.query.filter_by(user_id=self.id, test_date_id=test_date.id).first()
        if f:
            db.session.delete(f)
            db.session.commit()

    def register_test_date(self, test_date):
        t = UserTestDate.query.filter_by(user_id=self.id, test_date_id=test_date.id).first()
        if not t:
            t = UserTestDate(user_id=self.id, test_date_id=test_date.id, is_registered=True)
            db.session.add(t)
        else:
            if not t.is_registered:
                t.is_registered = True
        db.session.commit()

    def is_testing(self, test_date):
        return self.test_dates.filter(
            UserTestDate.test_date_id == test_date.id).count() > 0

    def is_registered(self, test_date):
        return UserTestDate.query.filter_by(
            user_id=self.id, test_date_id=test_date.id, is_registered=True
        ).count() > 0

    def get_dates(self):
        return TestDate.query.join(
                UserTestDate, (UserTestDate.test_date_id == TestDate.id)
            ).filter(UserTestDate.user_id == self.id)

    @staticmethod
    def verify_email_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)

    @property
    def organization(self):
        return Organization.query.filter_by(partner_id=self.id).first()


class TestDate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date)
    test = db.Column(db.String(24))
    status = db.Column(db.String(24), default='confirmed')
    reg_date = db.Column(db.Date)
    late_date = db.Column(db.Date)
    other_date = db.Column(db.Date)
    score_date = db.Column(db.Date)
    students = db.relationship('User', secondary='user_test_date', backref=db.backref('dates_interested'), lazy='dynamic')

    def __repr__(self):
        return '<TestDate {}>'.format(self.date)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    review = db.Column(db.String(1024))
    author = db.Column(db.String(64))
    photo_path = db.Column(db.String(128))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Review {}>'.format(self.date)


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    sat_spreadsheet_id = db.Column(db.String(255), nullable=True)
    act_spreadsheet_id = db.Column(db.String(255), nullable=True)
    color1 = db.Column(db.String(7), nullable=True)
    color2 = db.Column(db.String(7), nullable=True)
    color3 = db.Column(db.String(7), nullable=True)
    font_color = db.Column(db.String(7), nullable=True)
    logo_path = db.Column(db.String(128), nullable=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    partner = db.relationship(
        'User',
        backref=db.backref('partner_organization', uselist=False),
        foreign_keys=[partner_id]
    )


@login.user_loader
def load_user(id):
    return User.query.get(id)