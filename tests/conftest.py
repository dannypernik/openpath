"""Test configuration and fixtures."""

from __future__ import annotations
import pytest
from app import create_app
from app.extensions import db


class DummyCreds:
    def __init__(self, *args, **kwargs):
        self.token = "test-token"
        self.project_id = "test-project"

    def refresh(self, request=None):
        # No-op for tests; if refreshed by callers, leave token as-is.
        return None

    def with_scopes(self, scopes):
        return self

    def authorize(self, request):
        return request


@pytest.fixture(autouse=True)
def mock_service_account_file(monkeypatch):
    """Autouse fixture to prevent tests from trying to read a real service account file.

    Replaces Credentials.from_service_account_file with a no-file-required factory that
    returns DummyCreds. Also stubs google.auth._service_account_info.from_filename.
    """
    try:
        from google.oauth2 import service_account
        import google.auth._service_account_info as _sai

        def from_service_account_file_mock(cls, filename, *args, **kwargs):
            """Mock factory for creating credentials without reading a file.

            Note: Intentionally returns DummyCreds instead of cls() to avoid
            instantiating real Credentials objects that might have other dependencies.
            """
            return DummyCreds()

        def from_filename_mock(filename):
            """Mock function to avoid reading service account info from file."""
            return {}

        monkeypatch.setattr(
            service_account.Credentials,
            "from_service_account_file",
            classmethod(from_service_account_file_mock),
            raising=False,
        )

        # Some call paths go through google.auth._service_account_info
        monkeypatch.setattr(
            _sai,
            "from_filename",
            from_filename_mock,
            raising=False,
        )
    except (ImportError, ModuleNotFoundError):
        # If google auth libs are not present, nothing to mock.
        pass


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create test CLI runner."""
    return app.test_cli_runner()
