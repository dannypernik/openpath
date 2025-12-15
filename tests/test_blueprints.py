"""Smoke tests for Flask Blueprints."""

import pytest


def test_app_creation(app):
    """Test that application is created successfully."""
    assert app is not None
    assert app.config['TESTING'] is True


def test_blueprints_registered(app):
    """Test that all blueprints are registered."""
    blueprint_names = ['', 'auth', 'admin', 'api']
    for name in blueprint_names:
        assert name in app.blueprints, f"Blueprint '{name}' not registered"


def test_index_returns_200(client):
    """Test that index page returns 200."""
    response = client.get('/')
    assert response.status_code == 200


def test_team_page_returns_200(client):
    """Test that team page returns 200."""
    response = client.get('/team')
    assert response.status_code == 200


def test_mission_page_returns_200(client):
    """Test that mission page returns 200."""
    response = client.get('/mission')
    assert response.status_code == 200


def test_about_page_returns_200(client):
    """Test that about page returns 200."""
    response = client.get('/about')
    assert response.status_code == 200


def test_reviews_page_returns_200(client):
    """Test that reviews page returns 200."""
    response = client.get('/reviews')
    assert response.status_code == 200


def test_signin_page_returns_200(client):
    """Test that signin page returns 200."""
    response = client.get('/signin')
    assert response.status_code == 200


def test_login_page_returns_200(client):
    """Test that login page returns 200."""
    response = client.get('/login')
    assert response.status_code == 200


def test_signup_page_returns_200(client):
    """Test that signup page returns 200."""
    response = client.get('/signup')
    assert response.status_code == 200


def test_test_dates_page_returns_200(client):
    """Test that test-dates page returns 200."""
    response = client.get('/test-dates')
    assert response.status_code == 200


def test_test_reminders_page_returns_200(client):
    """Test that test-reminders page returns 200."""
    response = client.get('/test-reminders')
    assert response.status_code == 200


def test_sat_report_page_returns_200(client):
    """Test that sat-report page returns 200."""
    response = client.get('/sat-report')
    assert response.status_code == 200


def test_act_report_page_returns_200(client):
    """Test that act-report page returns 200."""
    response = client.get('/act-report')
    assert response.status_code == 200


def test_api_cal_check_returns_200(client):
    """Test that API cal-check endpoint returns 200."""
    response = client.post('/cal-check', json={})
    assert response.status_code == 200


def test_request_password_reset_returns_200(client):
    """Test that request-password-reset page returns 200."""
    response = client.get('/request-password-reset')
    assert response.status_code == 200


def test_unsubscribe_returns_200(client):
    """Test that unsubscribe page returns 200."""
    response = client.get('/unsubscribe')
    assert response.status_code == 200


def test_admin_routes_require_auth(client):
    """Test that admin routes redirect when not authenticated."""
    admin_routes = ['/users', '/students', '/tutors', '/recap', '/orgs']
    for route in admin_routes:
        response = client.get(route)
        # Should redirect to login (302) or show flash message
        assert response.status_code in [302, 401, 403], f"Route {route} should require auth"


def test_404_error_handler(client):
    """Test 404 error handler."""
    response = client.get('/nonexistent-page-12345')
    assert response.status_code == 404
