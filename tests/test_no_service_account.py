"""Test that the application can start without service account file."""

import pytest
import os


def test_app_starts_without_service_account(monkeypatch):
    """Test that the application initializes without service_account_key2.json file."""
    # Ensure service account file environment variable is not set
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    # Set TESTING environment variable
    monkeypatch.setenv('TESTING', '1')
    
    # Import app after setting environment variables
    from app import app
    
    # Verify app was created successfully
    assert app is not None
    assert app.config.get('TESTING') or os.getenv('TESTING') == '1'
    
    # Import the modules that load credentials and verify they handled the missing file gracefully
    from app import new_student_folders
    
    # Verify that services are None when credentials are not loaded
    assert new_student_folders.drive_service is None, "drive_service should be None in test mode"
    assert new_student_folders.sheets_service is None, "sheets_service should be None in test mode"


def test_app_creates_with_ci_env_var(monkeypatch):
    """Test that the application initializes with CI environment variable set."""
    # Ensure service account file environment variable is not set
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    # Set CI environment variable
    monkeypatch.setenv('CI', '1')
    
    # Clear any cached imports
    import sys
    if 'app.new_student_folders' in sys.modules:
        del sys.modules['app.new_student_folders']
    
    # Import app after setting environment variables
    from app import app
    
    # Verify app was created successfully
    assert app is not None
    
    # Import the modules that load credentials and verify they handled the missing file gracefully
    from app import new_student_folders
    
    # Verify that services are None when CI is set
    assert new_student_folders.drive_service is None, "drive_service should be None with CI=1"
    assert new_student_folders.sheets_service is None, "sheets_service should be None with CI=1"
