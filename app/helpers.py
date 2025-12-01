"""Helper functions shared across the application."""

import os
from functools import wraps

from flask import flash, redirect, request, url_for, current_app
from flask_login import current_user, login_required, logout_user


def full_name(user):
    """Return full name of user, handling None last_name."""
    if user.last_name == '' or user.last_name is None:
        name = user.first_name
    else:
        name = user.first_name + ' ' + user.last_name
    return name


def admin_required(f):
    """Decorator for views that require admin privileges."""
    @login_required
    @wraps(f)
    def wrap(*args, **kwargs):
        if current_user.is_admin:
            return f(*args, **kwargs)
        else:
            flash('You must have administrator privileges to access this page.', 'error')
            logout_user()
            return redirect(url_for('auth.signin', next=request.endpoint, org=request.view_args.get('org')))
    return wrap


def get_next_page():
    """Get the next page to redirect to after login."""
    next_page = request.args.get('next')
    if next_page not in current_app.view_functions:
        next_page = 'auth.start_page'
    return next_page


def proper(name):
    """Convert name to proper title case."""
    try:
        name = name.title()
        return name
    except:
        return name


def dir_last_updated(folder):
    """Return timestamp of most recently modified file in folder."""
    return str(max(os.path.getmtime(os.path.join(root_path, f))
                   for root_path, dirs, files in os.walk(folder)
                   for f in files))
