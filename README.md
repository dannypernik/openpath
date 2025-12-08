# Open Path Tutoring

A tutoring services web application.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables (create a .env file):
```bash
SECRET_KEY=your_secret_key
# ... other environment variables
```

3. Initialize the database:
```bash
flask db upgrade
```

4. (Production only) Set up Google Service Account credentials:
   - Obtain `service_account_key2.json` from your Google Cloud project
   - Place it in the root directory of the project
   - This file is gitignored and not required for testing/CI

## Google Service Account

The application uses Google Drive and Sheets APIs through a service account for various features:
- Creating student folders
- Generating score reports
- Accessing spreadsheet data

### Development and Testing

**The service account file (`service_account_key2.json`) is NOT required for tests or CI.**

The application automatically skips Google API initialization when:
- `app.config['TESTING']` is set to `True`
- The `CI` environment variable is set
- The service account file doesn't exist

To run tests locally without the service account file:
```bash
export TESTING=1  # or set CI=1
pytest tests/
```

### Production

In production, the service account file must be present for full functionality:
1. Obtain the service account JSON key from your Google Cloud Console
2. Save it as `service_account_key2.json` in the project root
3. Ensure the service account has appropriate permissions for Drive and Sheets APIs

You can override the default file path using the `GOOGLE_APPLICATION_CREDENTIALS` environment variable:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service_account.json
```

## Running the Application

```bash
# Development
python run.py

# Production
gunicorn wsgi:app
```

## Running Tests

```bash
pytest tests/ -v
```

Tests will run successfully without the service account file.
