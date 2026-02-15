from flask import Flask, render_template
from flask_login import LoginManager
from flask_mail import Mail
from flask_socketio import SocketIO, join_room, leave_room, emit
from models import db, User
from config import Config
import os

# Initialize extensions
mail = Mail()
socketio = SocketIO()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions with app
    db.init_app(app)
    mail.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Register blueprints
    from auth import auth
    from routes import main
    
    app.register_blueprint(auth)
    app.register_blueprint(main)
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    # Socket.IO events
    @socketio.on('connect')
    def handle_connect():
        from flask_login import current_user
        if current_user.is_authenticated:
            join_room(f'user_{current_user.id}')
            emit('connected', {'message': 'Connected to notification system'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        from flask_login import current_user
        if current_user.is_authenticated:
            leave_room(f'user_{current_user.id}')
    
    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500
    
    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
