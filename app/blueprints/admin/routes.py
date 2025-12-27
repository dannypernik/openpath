"""Admin blueprint routes for administrative functions."""

import os
import logging
from datetime import datetime

from markupsafe import Markup
from flask import render_template, flash, redirect, url_for, request, send_file, abort, current_app
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.blueprints.admin import admin_bp
from app.extensions import db
from app.helpers import full_name, admin_required, proper
from app.forms import (
    UserForm, StudentForm, TutorForm, TestDateForm, RecapForm, OrgSettingsForm
)
from app.models import User, TestDate, UserTestDate, Organization
from app.email import send_session_recap_email, send_verification_email
from app.utils import is_dark_color, color_svg_white_to_input, add_test_dates_from_ss
from app.create_sat_report import (
    create_custom_sat_spreadsheet, update_sat_org_logo, update_sat_partner_logo
)
from app.create_act_report import (
    create_custom_act_spreadsheet, update_act_org_logo, update_act_partner_logo
)
from app.tasks import style_custom_sat_spreadsheet_task, style_custom_act_spreadsheet_task
from reminders import get_student_events

logger = logging.getLogger(__name__)

@admin_bp.route('/users', methods=['GET', 'POST'])
@admin_required
def users():
    form = UserForm(None)
    roles = User.query.with_entities(User.role).distinct()
    users = User.query.order_by(User.first_name, User.last_name).all()
    parents = User.query.filter_by(role='parent')
    parent_list = [(0, '')] + [(u.id, full_name(u)) for u in parents]
    tutors = User.query.filter_by(role='tutor')
    tutor_list = [(0, '')] + [(u.id, full_name(u)) for u in tutors]
    form.parent_id.choices = parent_list
    form.tutor_id.choices = tutor_list
    if form.validate_on_submit():
        user = User(first_name=form.first_name.data, last_name=form.last_name.data,
                    email=form.email.data.lower(), secondary_email=form.secondary_email.data.lower(),
                    phone=form.phone.data, timezone=form.timezone.data, location=form.location.data,
                    role=form.role.data, status='active', is_admin=False,
                    session_reminders=True, test_reminders=True)
        user.tutor_id = form.tutor_id.data
        user.status = form.status.data
        user.parent_id = form.parent_id.data
        if form.tutor_id.data == 0:
            user.tutor_id = None
        if form.parent_id.data == 0:
            user.parent_id = None
        if form.status.data == 'none':
            user.status = None
        try:
            db.session.add(user)
            db.session.commit()
            flash(user.first_name + ' added')
        except:
            db.session.rollback()
            flash(user.first_name + ' could not be added', 'error')
            return redirect(url_for('admin.users'))
        return redirect(url_for('admin.users'))
    return render_template('users.html', title='Users', form=form, users=users, roles=roles,
                           full_name=full_name, proper=proper)


@admin_bp.route('/edit-user/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    form = UserForm(user.email, obj=user)
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.date > datetime.today().date())
    parents = User.query.order_by(User.first_name, User.last_name).filter_by(role='parent')
    parent_list = [(0, '')] + [(u.id, full_name(u)) for u in parents]
    tutors = User.query.order_by(User.first_name, User.last_name).filter_by(role='tutor')
    tutor_list = [(0, '')] + [(u.id, full_name(u)) for u in tutors]
    form.parent_id.choices = parent_list
    form.tutor_id.choices = tutor_list
    registered_tests = []
    interested_tests = []

    if form.validate_on_submit():
        if 'save' in request.form:
            user.first_name = form.first_name.data
            user.last_name = form.last_name.data
            user.email = form.email.data.lower()
            user.phone = form.phone.data
            user.secondary_email = form.secondary_email.data.lower()
            user.timezone = form.timezone.data
            user.location = form.location.data
            user.status = form.status.data
            user.role = form.role.data
            user.title = form.title.data
            user.grad_year = form.grad_year.data
            user.is_admin = form.is_admin.data
            user.session_reminders = form.session_reminders.data
            user.test_reminders = form.test_reminders.data
            if form.tutor_id.data == 0:
                user.tutor_id = None
            else:
                user.tutor_id = form.tutor_id.data
            if form.parent_id.data == 0:
                user.parent_id = None
            else:
                user.parent_id = form.parent_id.data
            if form.grad_year.data == 0:
                user.grad_year = None
            else:
                user.grad_year = form.grad_year.data

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
                return redirect(url_for('admin.users'))
        elif 'delete' in request.form:
            db.session.delete(user)
            db.session.commit()
            flash('Deleted ' + user.first_name)
        else:
            flash('Code error in POST request', 'error')
        if user.role == 'student' or user.role == 'tutor':
            return redirect(url_for('admin.' + user.role + 's'))
        else:
            return redirect(url_for('admin.users'))
    elif request.method == 'GET':
        form.first_name.data = user.first_name
        form.last_name.data = user.last_name
        form.email.data = user.email
        form.phone.data = user.phone
        form.secondary_email.data = user.secondary_email
        form.timezone.data = user.timezone
        form.location.data = user.location
        form.status.data = user.status
        form.role.data = user.role
        form.title.data = user.title
        form.grad_year.data = user.grad_year
        form.tutor_id.data = user.tutor_id
        form.parent_id.data = user.parent_id
        form.is_admin.data = user.is_admin
        form.test_reminders.data = user.test_reminders

        test_selections = user.get_dates().all()
        for d in upcoming_dates:
            if d in test_selections:
                if user.is_registered(d):
                    registered_tests.append(d.id)
                else:
                    interested_tests.append(d.id)

    return render_template('edit-user.html', title=full_name(user), form=form, user=user,
                           tests=tests, upcoming_dates=upcoming_dates, registered_tests=registered_tests,
                           interested_tests=interested_tests)


@admin_bp.route('/students', methods=['GET', 'POST'])
@admin_required
def students():
    form = StudentForm()
    students = User.query.order_by(User.first_name, User.last_name).filter_by(role='student')
    parents = User.query.order_by(User.first_name, User.last_name).filter_by(role='parent')
    parent_list = [(0, 'New parent')] + [(u.id, full_name(u)) for u in parents]
    form.parent_id.choices = parent_list
    tutors = User.query.filter_by(role='tutor')
    tutor_list = [(u.id, full_name(u)) for u in tutors]
    form.tutor_id.choices = tutor_list
    status_order = ['prospective', 'active', 'paused', 'inactive']
    statuses = []
    for s in status_order:
        if User.query.filter(User.status == s).first():
            statuses.append(s)
    other_students = User.query.filter((User.role == 'student') & (User.status.notin_(statuses)))
    upcoming_dates = TestDate.query.order_by(TestDate.date).filter(TestDate.status != 'past')
    tests = sorted(set(TestDate.test for TestDate in TestDate.query.all()), reverse=True)

    if form.validate_on_submit():
        student = User(first_name=form.student_name.data, last_name=form.student_last_name.data,
                       email=form.student_email.data.lower(), phone=form.student_phone.data, timezone=form.timezone.data,
                       location=form.location.data, status=form.status.data, tutor_id=form.tutor_id.data,
                       role='student', grad_year=form.grad_year.data, session_reminders=True, test_reminders=True)
        if form.parent_id.data == 0:
            parent = User(first_name=form.parent_name.data, last_name=form.parent_last_name.data,
                          email=form.parent_email.data.lower(), secondary_email=form.secondary_email.data.lower(),
                          phone=form.parent_phone.data, timezone=form.timezone.data, role='parent',
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
            return redirect(url_for('admin.students'))
        flash(student.first_name + ' added')
        return redirect(url_for('admin.students'))
    return render_template('students.html', title='Students', form=form, students=students,
                           statuses=statuses, upcoming_dates=upcoming_dates, tests=tests, other_students=other_students,
                           full_name=full_name, proper=proper)


@admin_bp.route('/tutors', methods=['GET', 'POST'])
@admin_required
def tutors():
    form = TutorForm()
    tutors = User.query.order_by(User.id.desc()).filter_by(role='tutor')
    statuses = User.query.filter_by(role='tutor').with_entities(User.status).distinct()

    if form.validate_on_submit():
        tutor = User(first_name=form.first_name.data, last_name=form.last_name.data,
                     email=form.email.data.lower(), phone=form.phone.data, timezone=form.timezone.data,
                     session_reminders=form.session_reminders.data, test_reminders=form.test_reminders.data,
                     status='active', role='tutor')
        try:
            db.session.add(tutor)
            db.session.commit()
            flash(tutor.first_name + ' added')
        except:
            db.session.rollback()
            flash(tutor.first_name + ' could not be added', 'error')
            return redirect(url_for('admin.tutors'))
        return redirect(url_for('admin.tutors'))
    return render_template('tutors.html', title='Tutors', form=form, tutors=tutors,
                           statuses=statuses, full_name=full_name, proper=proper)


@admin_bp.route('/edit-date/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_date(id):
    form = TestDateForm()
    date = TestDate.query.get_or_404(id)
    students = date.students
    if form.validate_on_submit():
        if 'save' in request.form:
            date.test = form.test.data
            date.date = form.date.data
            date.reg_date = form.reg_date.data
            date.late_date = form.late_date.data
            date.other_date = form.other_date.data
            date.score_date = form.score_date.data
            date.status = form.status.data

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
        form.test.data = date.test
        form.date.data = date.date
        form.reg_date.data = date.reg_date
        form.late_date.data = date.late_date
        form.other_date.data = date.other_date
        form.score_date.data = date.score_date
        form.status.data = date.status
    return render_template('edit-date.html', title='Edit date', form=form, date=date,
                           students=students)


@admin_bp.route('/add-test-dates', methods=['GET', 'POST'])
@admin_required
def add_test_dates():
    add_test_dates_from_ss()
    flash('Test dates added/updated from spreadsheet')
    return redirect(url_for('test_dates'))



@admin_bp.route('/recap', methods=['GET', 'POST'])
@admin_required
def recap():
    form = RecapForm()
    students = User.query.order_by(User.first_name, User.last_name).filter(
        (User.role == 'student') & (User.status == 'active') | (User.status == 'prospective'))
    student_list = [(0, 'Student name')] + [(s.id, full_name(s)) for s in students]
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
        return redirect(url_for('admin.recap'))
    return render_template('recap.html', form=form)


@admin_bp.route('/orgs')
@admin_required
def orgs():
    organizations = Organization.query.order_by(Organization.name.asc()).all()
    sat_template_id = current_app.config['ORG_SAT_REPORT_SS_ID']
    act_template_id = current_app.config['ACT_REPORT_SS_ID']
    return render_template('orgs.html', organizations=organizations, sat_template_id=sat_template_id, act_template_id=act_template_id)


@admin_bp.route('/new-org')
@admin_required
def new_org():
    return redirect(url_for('admin.org_settings', org='new'))


@admin_bp.route('/delete-org/<org_slug>', methods=['POST', 'GET'])
@admin_required
def delete_org(org_slug):
    org = Organization.query.filter_by(slug=org_slug).first_or_404()
    db.session.delete(org)
    db.session.commit()
    flash(f'{org.name} has been deleted.', 'success')
    return redirect(url_for('admin.orgs'))


@admin_bp.route('/org-settings/<org>', methods=['GET', 'POST'])
@admin_required
def org_settings(org):
    if org == 'new':
        organization = None
    else:
        organization = Organization.query.filter_by(slug=org).first()
        if not organization:
            flash('Organization not found.', 'error')
            return redirect(url_for('admin.org_settings', org='new'))

    form = OrgSettingsForm()

    partner_list = []
    partners = User.query.filter_by(role='partner').all()
    for partner in partners:
        if not Organization.query.filter_by(partner_id=partner.id).first() or (organization and partner.id == organization.partner_id):
            partner_list.append((partner.id, full_name(partner)))
    partner_list.insert(0, (0, 'New partner'))
    form.partner_id.choices = partner_list

    if organization and request.method == 'GET':
        form.org_name.data = organization.name
        form.slug.data = organization.slug
        form.color1.data = organization.color1
        form.color2.data = organization.color2
        form.color3.data = organization.color3
        form.font_color.data = organization.font_color
        form.logo.data = organization.logo_path
        form.ss_logo.data = organization.ss_logo_path
        form.partner_id.data = organization.partner_id
        form.sat_ss_id.data = organization.sat_spreadsheet_id
        form.act_ss_id.data = organization.act_spreadsheet_id

    if form.validate_on_submit():
        if 'save' in request.form:
            try:
                if not organization:
                    organization = Organization(name=form.org_name.data, slug=form.slug.data)
                    db.session.add(organization)
                else:
                    organization = Organization.query.filter_by(slug=org).first()

                if form.partner_id.data == 0:
                    partner = User(
                        first_name=form.first_name.data,
                        last_name=form.last_name.data,
                        email=form.email.data.lower(),
                        role='partner',
                        session_reminders=False,
                        test_reminders=False
                    )
                    db.session.add(partner)
                    db.session.flush()
                else:
                    partner = User.query.filter_by(id=form.partner_id.data).first()

                if (
                    organization.color1 != form.color1.data or
                    organization.color2 != form.color2.data or
                    organization.color3 != form.color3.data or
                    organization.font_color != form.font_color.data or
                    organization.sat_spreadsheet_id != form.sat_ss_id.data or
                    organization.act_spreadsheet_id != form.act_ss_id.data
                ):
                    is_style_updated = True
                else:
                    is_style_updated = False

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

                organization_data = {
                    'name': form.org_name.data,
                    'sat_ss_id': form.sat_ss_id.data,
                    'act_ss_id': form.act_ss_id.data,
                    'color1': form.color1.data,
                    'color2': form.color2.data,
                    'color3': form.color3.data,
                    'font_color': form.font_color.data,
                }

                if form.logo.data:
                    logo_file = form.logo.data
                    upload_dir = os.path.join(current_app.static_folder, 'img/orgs')
                    os.makedirs(upload_dir, exist_ok=True)

                    filename = secure_filename(f"{slug}.{logo_file.filename.split('.')[-1]}")
                    logo_path = os.path.join(upload_dir, filename)
                    logo_file.save(logo_path)

                    organization.logo_path = f"img/orgs/{filename}"
                    organization_data['logo_path'] = organization.logo_path

                if form.ss_logo.data:
                    ss_logo_file = form.ss_logo.data
                    upload_dir = os.path.join(current_app.static_folder, 'img/orgs')
                    os.makedirs(upload_dir, exist_ok=True)

                    filename = secure_filename(f"{slug}-ss.{ss_logo_file.filename.split('.')[-1]}")
                    ss_logo_path = os.path.join(upload_dir, filename)
                    ss_logo_file.save(ss_logo_path)

                    organization.ss_logo_path = f"img/orgs/{filename}"
                    organization_data['ss_logo_path'] = organization.ss_logo_path

                db.session.commit()

                if not form.sat_ss_id.data:
                    organization.sat_spreadsheet_id = create_custom_sat_spreadsheet(organization)
                    organization_data['sat_ss_id'] = organization.sat_spreadsheet_id

                if not form.act_ss_id.data:
                    organization.act_spreadsheet_id = create_custom_act_spreadsheet(organization)
                    organization_data['act_ss_id'] = organization.act_spreadsheet_id

                if form.ss_logo.data:
                    update_sat_org_logo(organization_data)
                    update_act_org_logo(organization_data)

                if is_style_updated:
                    partner_logos_dir = os.path.join(current_app.static_folder, 'img/orgs/partner-logos')
                    os.makedirs(partner_logos_dir, exist_ok=True)

                    if is_dark_color(organization.color1):
                        logo_color = '#ffffff'
                    else:
                        logo_color = organization.font_color

                    svg_path = os.path.join(current_app.static_folder, 'img/logo-header.svg')
                    safe_filename = secure_filename(f'opt-{logo_color}.png')
                    organization_data['partner_logo_path'] = f'img/orgs/partner-logos/{safe_filename}'
                    static_output_path = os.path.join(current_app.static_folder, organization_data['partner_logo_path'])

                    color_svg_white_to_input(svg_path, logo_color, static_output_path)
                    update_sat_partner_logo(organization_data)
                    update_act_partner_logo(organization_data)

                    style_custom_sat_spreadsheet_task.delay(organization_data)
                    style_custom_act_spreadsheet_task.delay(organization_data)

                db.session.commit()

                if is_style_updated or form.logo.data:
                    flash(Markup(f'{"Style" if is_style_updated else "Logo"} updated for \
                        <a href="https://docs.google.com/spreadsheets/d/{organization.sat_spreadsheet_id}" target="_blank">\
                            SAT spreadsheet</a> and \
                        <a href="https://docs.google.com/spreadsheets/d/{organization.act_spreadsheet_id}" target="_blank">\
                            ACT spreadsheet</a>'), 'success')
                else:
                    flash(f'{organization.name} saved', 'success')
                return redirect(url_for('admin.org_settings', org=slug))
            except Exception as e:
                flash(f"Error creating custom spreadsheet: {e}", 'error')
                logger.error(f"Error creating custom spreadsheet: {e}")
                db.session.rollback()
        elif 'delete' in request.form and organization:
            db.session.delete(organization)
            db.session.commit()
            flash(f'Organization {organization.name} deleted')
            return redirect(url_for('admin.orgs'))
    return render_template('org-settings.html', form=form, organization=organization)


@admin_bp.route('/admin-files/<path:filename>')
@admin_required
def admin_download(filename):
    private_folder = os.path.join(current_app.root_path, 'private')
    file_path = os.path.join(private_folder, filename)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True)
