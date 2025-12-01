# Open Path Tutoring

A Flask web application for tutoring services.

## Project Structure

This application uses the Flask application factory pattern with Blueprints for modular route organization:

```
app/
├── __init__.py          # Application factory (create_app)
├── extensions.py        # Flask extension instances
├── helpers.py           # Shared utility functions
├── models.py            # SQLAlchemy models
├── forms.py             # WTForms form classes
├── email.py             # Email sending functions
├── tasks.py             # Celery background tasks
├── blueprints/
│   ├── main/            # Public routes (index, team, mission, etc.)
│   ├── auth/            # Authentication routes (login, signup, etc.)
│   ├── admin/           # Admin routes (users, students, tutors, etc.)
│   └── api/             # API endpoints
├── templates/           # Jinja2 templates
└── static/              # Static files (CSS, JS, images)
```

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (copy .env.example to .env and configure):
```bash
cp .env.example .env
```

4. Initialize the database:
```bash
flask db upgrade
```

## Running the Application

### Development Server

```bash
# Using Flask CLI
export FLASK_CONFIG=development  # or set FLASK_ENV=development
flask run

# Or using the run script
python run.py
```

### Production (with Gunicorn)

```bash
gunicorn wsgi:app
```

## Configuration

The application supports multiple configuration modes:

- `development` - Debug enabled, auto-reload
- `testing` - For running tests
- `production` - Optimized for production

Set the configuration using environment variables:
- `FLASK_CONFIG` - Configuration name (development, testing, production)
- `FLASK_ENV` - Alternative way to set configuration

## Running Tests

```bash
# Install pytest if not already installed
pip install pytest

# Run tests
pytest tests/ -v
```

## Celery Workers

For background task processing:

```bash
celery -A app.celery worker --loglevel=info
```

## URL Structure

The application uses Flask Blueprints with the following URL patterns:

- **Main Blueprint** (`/`): Public pages
  - `/` - Home page
  - `/team` - Team page
  - `/mission` - Mission page
  - `/reviews` - Reviews page
  - `/sat-report` - SAT score report
  - `/act-report` - ACT score report

- **Auth Blueprint** (`/`): Authentication
  - `/signin` - Sign in page
  - `/signup` - Sign up page
  - `/login` - Login handler
  - `/logout` - Logout handler
  - `/request-password-reset` - Password reset request

- **Admin Blueprint** (`/`): Administrative functions (requires login)
  - `/users` - User management
  - `/students` - Student management
  - `/tutors` - Tutor management
  - `/orgs` - Organization management

- **API Blueprint** (`/`): API endpoints
  - `/cal-check` - Calendar check endpoint
