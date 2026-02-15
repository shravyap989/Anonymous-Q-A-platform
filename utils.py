import random
import string
from datetime import datetime, timedelta
from flask_mail import Message
from flask import current_app
from better_profanity import profanity
from models import db, OTP, User, BlockedUser, Notification
from flask_socketio import emit

# Initialize profanity filter
profanity.load_censor_words()

def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def create_otp(email, purpose):
    """Create and store OTP in database"""
    # Delete any existing OTPs for this email and purpose
    OTP.query.filter_by(email=email, purpose=purpose, is_used=False).delete()
    
    otp_code = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=current_app.config['OTP_EXPIRY_MINUTES'])
    
    new_otp = OTP(
        email=email,
        otp_code=otp_code,
        purpose=purpose,
        expires_at=expires_at
    )
    
    db.session.add(new_otp)
    db.session.commit()
    
    return otp_code

def verify_otp(email, otp_code, purpose):
    """Verify OTP"""
    otp_record = OTP.query.filter_by(
        email=email,
        otp_code=otp_code,
        purpose=purpose,
        is_used=False
    ).first()
    
    if not otp_record:
        return False, "Invalid OTP"
    
    if datetime.utcnow() > otp_record.expires_at:
        return False, "OTP has expired"
    
    # Mark OTP as used
    otp_record.is_used = True
    db.session.commit()
    
    return True, "OTP verified successfully"

def send_email(to, subject, body):
    """Send email using Flask-Mail"""
    from app import mail
    
    try:
        msg = Message(
            subject=subject,
            recipients=[to],
            body=body,
            sender=current_app.config['MAIL_DEFAULT_SENDER']
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

def send_otp_email(email, otp_code, purpose):
    """Send OTP via email"""
    if purpose == 'registration':
        subject = "Verify Your Email - QA Platform"
        body = f"""
Welcome to QA Platform!

Your OTP for email verification is: {otp_code}

This OTP will expire in 10 minutes.

If you didn't request this, please ignore this email.

Best regards,
QA Platform Team
        """
    else:  # password_reset
        subject = "Password Reset OTP - QA Platform"
        body = f"""
You requested to reset your password.

Your OTP is: {otp_code}

This OTP will expire in 10 minutes.

If you didn't request this, please ignore this email and your password will remain unchanged.

Best regards,
QA Platform Team
        """
    
    return send_email(email, subject, body)

def check_profanity(text):
    """Check if text contains profanity"""
    return profanity.contains_profanity(text)

def censor_profanity(text):
    """Censor profanity in text"""
    return profanity.censor(text)

def is_student_blocked(student_id):
    """Check if a student is blocked by any staff member"""
    blocked = BlockedUser.query.filter_by(student_id=student_id).first()
    return blocked is not None

def block_student(student_id, staff_id, reason="Inappropriate behavior"):
    """Block a student (blocks for all staff)"""
    # Check if already blocked
    if is_student_blocked(student_id):
        return False, "Student is already blocked"
    
    # Create block record
    block = BlockedUser(
        student_id=student_id,
        blocked_by_staff_id=staff_id,
        reason=reason
    )
    db.session.add(block)
    
    # Update user's blocked status
    student = User.query.get(student_id)
    if student:
        student.is_blocked = True
    
    db.session.commit()
    
    # Create notification for student
    create_notification(
        student_id,
        "Your account has been blocked due to policy violations. Please contact support.",
        "block"
    )
    
    return True, "Student blocked successfully"

def unblock_student(student_id):
    """Unblock a student"""
    BlockedUser.query.filter_by(student_id=student_id).delete()
    
    # Update user's blocked status
    student = User.query.get(student_id)
    if student:
        student.is_blocked = False
    
    db.session.commit()
    
    # Create notification for student
    create_notification(
        student_id,
        "Your account has been unblocked. You can now send messages again.",
        "unblock"
    )
    
    return True, "Student unblocked successfully"

def create_notification(user_id, message, notification_type, related_id=None):
    """Create a notification for a user"""
    notification = Notification(
        user_id=user_id,
        message=message,
        notification_type=notification_type,
        related_id=related_id
    )
    db.session.add(notification)
    db.session.commit()
    
    return notification

def send_notification_email(user_email, subject, message):
    """Send notification via email"""
    body = f"""
{message}

Visit the platform to view and respond: http://localhost:5000

Best regards,
QA Platform Team
    """
    return send_email(user_email, subject, body)

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(char.isdigit() for char in password):
        return False, "Password must contain at least one digit"
    
    if not any(char.isupper() for char in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(char.islower() for char in password):
        return False, "Password must contain at least one lowercase letter"
    
    special_characters = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(char in special_characters for char in password):
        return False, "Password must contain at least one special character"
    
    return True, "Password is valid"
