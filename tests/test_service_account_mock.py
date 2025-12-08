"""Test that the service account mock fixture works correctly."""

import pytest


def test_mock_service_account_file_prevents_file_access():
    """Test that from_service_account_file doesn't try to read actual files."""
    from google.oauth2.service_account import Credentials
    
    # This should not raise FileNotFoundError even though file doesn't exist
    creds = Credentials.from_service_account_file('nonexistent_file.json')
    
    # Verify we got a DummyCreds object with expected attributes
    assert hasattr(creds, 'token')
    assert hasattr(creds, 'project_id')
    assert hasattr(creds, 'refresh')
    assert hasattr(creds, 'with_scopes')
    
    assert creds.token == "test-token"
    assert creds.project_id == "test-project"


def test_dummy_creds_with_scopes():
    """Test that DummyCreds.with_scopes returns self."""
    from google.oauth2.service_account import Credentials
    
    creds = Credentials.from_service_account_file('nonexistent_file.json')
    scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/drive'])
    
    # Should return the same object
    assert scoped_creds is creds


def test_dummy_creds_refresh():
    """Test that DummyCreds.refresh is a no-op."""
    from google.oauth2.service_account import Credentials
    
    creds = Credentials.from_service_account_file('nonexistent_file.json')
    
    # refresh should not raise an error
    result = creds.refresh()
    assert result is None
    
    # token should remain unchanged
    assert creds.token == "test-token"


def test_service_account_info_from_filename_mocked():
    """Test that google.auth._service_account_info.from_filename is also mocked."""
    import google.auth._service_account_info as _sai
    
    # This should not raise FileNotFoundError
    result = _sai.from_filename('nonexistent_file.json')
    
    # Should return empty dict
    assert result == {}
