#!/usr/bin/env python
"""
Development server entrypoint.

Usage:
    python run.py
    FLASK_CONFIG=development python run.py
"""

import os
from app import create_app

# Create the application using the factory
app = create_app()

if __name__ == '__main__':
    # Run the development server
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=debug)
