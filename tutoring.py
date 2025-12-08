from app import get_app, db
from app.models import User, TestDate

# Use the application factory to get or create the default app instance
app = get_app()


@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'TestDate': TestDate, 'users': User.query.all()}
