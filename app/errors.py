from flask import render_template
from app import app, db

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

@app.errorhandler(502)
def server_error(e):
    # Log the error for debugging purposes
    app.logger.error(f"502 Error: {e}")

    # Render a custom error page
    return render_template('502.html'), 502
