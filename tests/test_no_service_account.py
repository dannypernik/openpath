"""Test that modules handle missing service account file gracefully."""

import pytest
import os
import sys
import importlib.util


def _get_app_module_path(module_name):
    """Helper to get the path to an app module relative to this test file."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(test_dir)
    return os.path.join(repo_root, 'app', f'{module_name}.py')


def _setup_mock_app(testing=True):
    """Helper to set up a minimal mock Flask app for testing."""
    from flask import Flask
    from config import Config
    import types
    
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)
    if testing:
        flask_app.config['TESTING'] = True
    
    # Create a minimal app module
    test_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(test_dir)
    app_dir = os.path.join(repo_root, 'app')
    
    app_module = types.ModuleType('app')
    app_module.app = flask_app
    app_module.__file__ = os.path.join(app_dir, '__init__.py')
    app_module.__path__ = [app_dir]
    app_module.__package__ = 'app'
    
    return app_module


def test_new_student_folders_module_without_service_account(monkeypatch):
    """Test that new_student_folders module handles missing service_account_key2.json file."""
    # Set environment variables before any imports
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    monkeypatch.setenv('TESTING', '1')
    
    # Clear any cached app modules
    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('app')]
    for mod in modules_to_remove:
        del sys.modules[mod]
    
    try:
        # Set up mock app
        app_module = _setup_mock_app(testing=True)
        sys.modules['app'] = app_module
        
        # Load the new_student_folders module file directly to avoid full app initialization
        module_path = _get_app_module_path('new_student_folders')
        spec = importlib.util.spec_from_file_location(
            "new_student_folders",
            module_path
        )
        
        # Now load new_student_folders module
        new_student_folders = importlib.util.module_from_spec(spec)
        sys.modules['new_student_folders'] = new_student_folders
        
        # This should not raise FileNotFoundError
        spec.loader.exec_module(new_student_folders)
        
        # Verify that services are None when credentials are not loaded
        assert new_student_folders.drive_service is None, "drive_service should be None in test mode"
        assert new_student_folders.sheets_service is None, "sheets_service should be None in test mode"
        assert new_student_folders.should_init_google is False, "should_init_google should be False"
    finally:
        # Cleanup - remove test modules
        if 'new_student_folders' in sys.modules:
            del sys.modules['new_student_folders']


def test_new_student_folders_with_ci_variable(monkeypatch):
    """Test that new_student_folders handles CI environment variable."""
    # Set environment variables
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    monkeypatch.setenv('CI', 'true')
    
    # Clear cached modules
    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('app') or k == 'new_student_folders']
    for mod in modules_to_remove:
        del sys.modules[mod]
    
    try:
        # Create minimal app setup
        app_module = _setup_mock_app(testing=False)
        sys.modules['app'] = app_module
        
        # Load the module
        module_path = _get_app_module_path('new_student_folders')
        spec = importlib.util.spec_from_file_location(
            "new_student_folders",
            module_path
        )
        new_student_folders = importlib.util.module_from_spec(spec)
        sys.modules['new_student_folders'] = new_student_folders
        
        # This should not raise FileNotFoundError
        spec.loader.exec_module(new_student_folders)
        
        # Verify services are None with CI=true
        assert new_student_folders.drive_service is None, "drive_service should be None with CI=true"
        assert new_student_folders.sheets_service is None, "sheets_service should be None with CI=true"
    finally:
        # Cleanup - remove test modules
        if 'new_student_folders' in sys.modules:
            del sys.modules['new_student_folders']
