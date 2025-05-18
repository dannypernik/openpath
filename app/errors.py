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

@app.route('/generate-502')
def generate_502():
    # Load the environment variable
    hello = app.config['HELLO_EMAIL']

    # Render the 502.html template with the base.html layout
    rendered_html = render_template('502.html', hello=hello)

    # Save the rendered HTML to templates
    output_path = 'app/static/502.html'
    with open(output_path, 'w') as f:
        f.write(rendered_html)

    return f"502.html generated successfully at {output_path}"