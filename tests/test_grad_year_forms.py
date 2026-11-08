from datetime import date
from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

BLANK_STUDENT = {'student_first_name': 'A', 'student_last_name': 'B', 'parent_first_name': 'P',
                 'parent_last_name': 'Q', 'parent_email': 'p@x.com', 'grad_year': ''}


def test_choices_are_built_per_form_instance_so_they_roll_over(app, monkeypatch):
    import app.grad_years as gy
    from app.forms import ScoreAnalysisForm

    class FakeDate(date):
        current = date(2026, 5, 31)

        @classmethod
        def today(cls):
            return cls.current
    monkeypatch.setattr(gy, 'date', FakeDate)
    with app.test_request_context():
        before = ScoreAnalysisForm().grad_year.choices
        FakeDate.current = date(2026, 6, 1)
        after = ScoreAnalysisForm().grad_year.choices
    assert before[1] == ('2026', '2026 (Senior)') and after[1] == ('2027', '2027 (Senior)')
    assert before[0] == after[0] == ('', 'Graduation year')


def test_public_form_accepts_blank_year_and_drops_old_options(app):
    from app.forms import ScoreAnalysisForm
    with app.test_request_context(method='POST', data=BLANK_STUDENT):
        form = ScoreAnalysisForm()
        assert form.validate_on_submit()
        assert form.grad_year.data == ''
        values = [v for v, _ in form.grad_year.choices]
        assert 'graduated' not in values and 'school' not in values


def test_new_student_form_accepts_blank_year(app):
    from app.forms import NewStudentForm
    with app.test_request_context(method='POST', data={'grad_year': ''}):
        form = NewStudentForm()
        assert form.grad_year.validate(form)


def test_user_form_keeps_stored_graduated_year_valid_on_post(app):
    from app.forms import UserForm
    stored = SimpleNamespace(grad_year='2020')
    with app.test_request_context(method='POST', data={'grad_year': '2020'}):
        form = UserForm('a@x.com', obj=stored)
        assert ('2020', '2020 (Graduated)') in form.grad_year.choices
        assert form.grad_year.validate(form)


def test_admin_edit_page_shows_graduated_year_and_saves(app, client):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(first_name='Ad', email='ad@x.com', is_admin=True, role='admin')
        student = User(first_name='Old', email='old@x.com', role='student', grad_year='2020', timezone='America/Chicago')
        db.session.add_all([admin, student])
        db.session.commit()
        admin_id, student_id = admin.id, student.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True

    page = client.get(f'/edit-user/{student_id}')
    assert page.status_code == 200
    assert b'2020 (Graduated)' in page.data

    resp = client.post(f'/edit-user/{student_id}', data={
        'save': '1', 'first_name': 'Old', 'last_name': '', 'secondary_email': '', 'email': 'old@x.com', 'timezone': 'America/Chicago',
        'grad_year': '2020', 'role': 'student', 'status': 'none', 'tutor_id': '0', 'parent_id': '0'})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, student_id).grad_year == '2020'

    client.post(f'/edit-user/{student_id}', data={
        'save': '1', 'first_name': 'Old', 'last_name': '', 'secondary_email': '', 'email': 'old@x.com', 'timezone': 'America/Chicago',
        'grad_year': '', 'role': 'student', 'status': 'none', 'tutor_id': '0', 'parent_id': '0'})
    with app.app_context():
        assert db.session.get(User, student_id).grad_year is None
