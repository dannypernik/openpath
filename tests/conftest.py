"""Test configuration and fixtures."""

import pytest
import os


@pytest.fixture
def app():
    """Create application for testing."""
    # Set TESTING environment variable before importing app
    os.environ['TESTING'] = '1'
    
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    
    from app import db
    
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.drop_all()
    
    # Clean up environment variable
    if 'TESTING' in os.environ:
        del os.environ['TESTING']


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create test CLI runner."""
    return app.test_cli_runner()
