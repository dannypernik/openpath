"""Test configuration and fixtures."""

from __future__ import annotations
import pytest
import os


class DummyCreds:
    def __init__(self, *args, **kwargs):
        self.token = "test-token"
        self.project_id = "test-project"

    def refresh(self, request=None):
        # No-op for tests; if refreshed by callers, leave token as-is.
        return None

    def with_scopes(self, scopes):
        return self


@pytest.fixture(autouse=True)
def mock_service_account_file(monkeypatch):
    """Autouse fixture to prevent tests from trying to read a real service account file.

    Replaces Credentials.from_service_account_file with a no-file-required factory that
    returns DummyCreds. Also stubs google.auth._service_account_info.from_filename.
    """
    try:
        from google.oauth2 import service_account
        import google.auth._service_account_info as _sai

        monkeypatch.setattr(
            service_account.Credentials,
            "from_service_account_file",
            classmethod(lambda cls, filename, *a, **kw: DummyCreds()),
            raising=False,
        )

        # Some call paths go through google.auth._service_account_info
        monkeypatch.setattr(
            _sai,
            "from_filename",
            lambda filename: {},
            raising=False,
        )
    except (ImportError, ModuleNotFoundError):
        # If google auth libs are not present, nothing to mock.
        pass


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
