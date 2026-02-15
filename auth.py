from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from utils import (
    create_otp, verify_otp, send_otp_email, 
    validate_password, send_email
)
from email_validator import validate_email, EmailNotValidError

auth = Blueprint('auth', __name__)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        user_type = request.form.get('user_type')  # 'student' or 'staff'
        
        # Validation
        try:
            valid = validate_email(email)
            email = valid.email
        except EmailNotValidError as e:
            flash('Invalid email address', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('register.html')
        
        is_valid, message = validate_password(password)
        if not is_valid:
            flash(message, 'error')
            return render_template('register.html')
        
        if user_type not in ['student', 'staff']:
            flash('Invalid user type', 'error')
            return render_template('register.html')
        
        # Check if user already exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Generate and send OTP
        otp_code = create_otp(email, 'registration')
        
        if send_otp_email(email, otp_code, 'registration'):
            # Store registration data in session temporarily
            from flask import session
            session['pending_registration'] = {
                'email': email,
                'password': password,
                'user_type': user_type
            }
            
            flash('OTP sent to your email. Please verify.', 'success')
            return redirect(url_for('auth.verify_otp_page', purpose='registration'))
        else:
            flash('Error sending OTP. Please try again.', 'error')
    
    return render_template('register.html')

@auth.route('/verify-otp/<purpose>', methods=['GET', 'POST'])
def verify_otp_page(purpose):
    if purpose not in ['registration', 'password_reset']:
        flash('Invalid verification purpose', 'error')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        otp_code = request.form.get('otp')
        from flask import session
        
        if purpose == 'registration':
            reg_data = session.get('pending_registration')
            if not reg_data:
                flash('Session expired. Please register again.', 'error')
                return redirect(url_for('auth.register'))
            
            is_valid, message = verify_otp(reg_data['email'], otp_code, 'registration')
            
            if is_valid:
                # Create user
                new_user = User(
                    email=reg_data['email'],
                    user_type=reg_data['user_type'],
                    is_verified=True
                )
                new_user.set_password(reg_data['password'])
                
                db.session.add(new_user)
                db.session.commit()
                
                session.pop('pending_registration', None)
                
                flash('Registration successful! Please login.', 'success')
                return redirect(url_for('auth.login'))
            else:
                flash(message, 'error')
        
        elif purpose == 'password_reset':
            reset_data = session.get('pending_reset')
            if not reset_data:
                flash('Session expired. Please try again.', 'error')
                return redirect(url_for('auth.forgot_password'))
            
            is_valid, message = verify_otp(reset_data['email'], otp_code, 'password_reset')
            
            if is_valid:
                session['reset_verified'] = True
                return redirect(url_for('auth.reset_password'))
            else:
                flash(message, 'error')
    
    return render_template('verify_otp.html', purpose=purpose)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash('Email not found', 'error')
            return render_template('login.html')
        
        if not user.is_verified:
            flash('Please verify your email first', 'error')
            return render_template('login.html')
        
        if user.is_blocked:
            flash('Your account has been blocked. Please contact support.', 'error')
            return render_template('login.html')
        
        if not user.check_password(password):
            flash('Incorrect password', 'error')
            return render_template('login.html')
        
        # Update last login
        from datetime import datetime
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        login_user(user, remember=remember)
        
        next_page = request.args.get('next')
        return redirect(next_page or url_for('main.dashboard'))
    
    return render_template('login.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('auth.login'))

@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Don't reveal if email exists
            flash('If the email exists, an OTP has been sent.', 'info')
            return render_template('forgot_password.html')
        
        # Generate and send OTP
        otp_code = create_otp(email, 'password_reset')
        
        if send_otp_email(email, otp_code, 'password_reset'):
            from flask import session
            session['pending_reset'] = {'email': email}
            flash('OTP sent to your email', 'success')
            return redirect(url_for('auth.verify_otp_page', purpose='password_reset'))
        else:
            flash('Error sending OTP. Please try again.', 'error')
    
    return render_template('forgot_password.html')

@auth.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    from flask import session
    
    if not session.get('reset_verified'):
        flash('Please verify OTP first', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    reset_data = session.get('pending_reset')
    if not reset_data:
        flash('Session expired', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('reset_password.html')
        
        is_valid, message = validate_password(password)
        if not is_valid:
            flash(message, 'error')
            return render_template('reset_password.html')
        
        user = User.query.filter_by(email=reset_data['email']).first()
        if user:
            user.set_password(password)
            db.session.commit()
            
            session.pop('reset_verified', None)
            session.pop('pending_reset', None)
            
            flash('Password reset successful! Please login.', 'success')
            return redirect(url_for('auth.login'))
    
    return render_template('reset_password.html')

@auth.route('/resend-otp/<purpose>')
def resend_otp(purpose):
    from flask import session
    
    if purpose == 'registration':
        reg_data = session.get('pending_registration')
        if reg_data:
            otp_code = create_otp(reg_data['email'], 'registration')
            send_otp_email(reg_data['email'], otp_code, 'registration')
            flash('OTP resent successfully', 'success')
    
    elif purpose == 'password_reset':
        reset_data = session.get('pending_reset')
        if reset_data:
            otp_code = create_otp(reset_data['email'], 'password_reset')
            send_otp_email(reset_data['email'], otp_code, 'password_reset')
            flash('OTP resent successfully', 'success')
    
    return redirect(url_for('auth.verify_otp_page', purpose=purpose))
