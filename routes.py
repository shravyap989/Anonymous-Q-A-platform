from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, User, Question, Answer, Notification
from utils import (
    check_profanity, is_student_blocked, block_student, 
    unblock_student, create_notification, send_notification_email
)
from datetime import datetime

main = Blueprint('main', __name__)

@main.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@main.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_type == 'student':
        return redirect(url_for('main.student_dashboard'))
    else:
        return redirect(url_for('main.staff_dashboard'))

@main.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.user_type != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check if blocked
    if current_user.is_blocked:
        flash('Your account is blocked. You cannot send messages.', 'error')
    
    # Get student's questions
    my_questions = Question.query.filter_by(student_id=current_user.id)\
        .order_by(Question.created_at.desc()).all()
    
    # Get all staff members for private messaging
    staff_members = User.query.filter_by(user_type='staff').all()
    
    # Get unread notifications
    unread_notifications = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).order_by(Notification.created_at.desc()).all()
    
    return render_template('student_dashboard.html',
                         my_questions=my_questions,
                         staff_members=staff_members,
                         unread_notifications=unread_notifications)

@main.route('/staff/dashboard')
@login_required
def staff_dashboard():
    if current_user.user_type != 'staff':
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Get public questions
    public_questions = Question.query.filter_by(is_public=True)\
        .order_by(Question.created_at.desc()).all()
    
    # Get private questions directed to this staff member
    private_questions = Question.query.filter_by(
        is_public=False,
        staff_id=current_user.id
    ).order_by(Question.created_at.desc()).all()
    
    # Get unread notifications
    unread_notifications = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).order_by(Notification.created_at.desc()).all()
    
    return render_template('staff_dashboard.html',
                         public_questions=public_questions,
                         private_questions=private_questions,
                         unread_notifications=unread_notifications)

@main.route('/public-questions')
@login_required
def public_questions():
    questions = Question.query.filter_by(is_public=True)\
        .order_by(Question.created_at.desc()).all()
    return render_template('public_questions.html', questions=questions)

@main.route('/ask-question', methods=['POST'])
@login_required
def ask_question():
    try:
        if current_user.user_type != 'student':
            return jsonify({'success': False, 'message': 'Only students can ask questions'}), 403
        
        # Check if student is blocked
        if current_user.is_blocked or is_student_blocked(current_user.id):
            return jsonify({'success': False, 'message': 'You are blocked and cannot send messages'}), 403
        
        content = request.form.get('content', '').strip()
        is_public = request.form.get('is_public') == 'true'
        staff_id = request.form.get('staff_id')
        
        if not content:
            return jsonify({'success': False, 'message': 'Question cannot be empty'}), 400
        
        # Check for profanity
        if check_profanity(content):
            return jsonify({
                'success': False,
                'message': 'Your message contains inappropriate language. Please remove it before sending.'
            }), 400
        
        # Create question
        question = Question(
            content=content,
            student_id=current_user.id,
            is_public=is_public
        )
        
        if not is_public and staff_id:
            question.staff_id = int(staff_id)
            recipient_id = int(staff_id)
        else:
            recipient_id = None
        
        db.session.add(question)
        db.session.commit()
        
        # Create notification
        if is_public:
            # Notify all staff members
            staff_members = User.query.filter_by(user_type='staff').all()
            for staff in staff_members:
                notification = create_notification(
                    staff.id,
                    f'New public question: "{content[:50]}..."',
                    'question',
                    question.id
                )
                # Send email notification
                send_notification_email(
                    staff.email,
                    'New Question on QA Platform',
                    f'A new public question has been posted: "{content[:100]}..."'
                )
        
        else:
            # Notify specific staff member
            if recipient_id:
                staff = User.query.get(recipient_id)
                if staff:
                    notification = create_notification(
                        staff.id,
                        f'New private question from anonymous student',
                        'question',
                        question.id
                    )
                    # Send email notification
                    send_notification_email(
                        staff.email,
                        'New Private Question on QA Platform',
                        f'You have received a new private question (anonymous)'
                    )
        
        return jsonify({
            'success': True,
            'message': 'Question submitted successfully',
            'question_id': question.id
        })
    
    except Exception as e:
        db.session.rollback()
        print(f"Error in ask_question: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Server error occurred'}), 500

@main.route('/answer-question', methods=['POST'])
@login_required
def answer_question():
    try:
        if current_user.user_type != 'staff':
            return jsonify({'success': False, 'message': 'Only staff can answer questions'}), 403
        
        question_id = request.form.get('question_id')
        content = request.form.get('content', '').strip()
        
        if not content:
            return jsonify({'success': False, 'message': 'Answer cannot be empty'}), 400
        
        # Check for profanity
        if check_profanity(content):
            return jsonify({
                'success': False,
                'message': 'Your message contains inappropriate language. Please remove it before sending.'
            }), 400
        
        question = Question.query.get(question_id)
        if not question:
            return jsonify({'success': False, 'message': 'Question not found'}), 404
        
        # Check if staff has permission to answer this question
        if not question.is_public and question.staff_id != current_user.id:
            return jsonify({'success': False, 'message': 'You cannot answer this private question'}), 403
        
        # Create answer
        answer = Answer(
            content=content,
            question_id=question.id,
            staff_id=current_user.id
        )
        
        db.session.add(answer)
        question.is_answered = True
        db.session.commit()
        
        # Notify the student who asked
        student = User.query.get(question.student_id)
        if student:
            notification = create_notification(
                student.id,
                f'Your question has been answered',
                'answer',
                answer.id
            )
            
            # Send email notification
            send_notification_email(
                student.email,
                'Your Question Has Been Answered',
                f'Your question has received an answer: "{content[:100]}..."'
            )
        
        return jsonify({
            'success': True,
            'message': 'Answer submitted successfully',
            'answer_id': answer.id
        })
    
    except Exception as e:
        db.session.rollback()
        print(f"Error in answer_question: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Server error occurred'}), 500

@main.route('/block-student', methods=['POST'])
@login_required
def block_student_route():
    if current_user.user_type != 'staff':
        return jsonify({'success': False, 'message': 'Only staff can block students'}), 403
    
    student_id = request.form.get('student_id')
    reason = request.form.get('reason', 'Inappropriate behavior')
    
    if not student_id:
        return jsonify({'success': False, 'message': 'Student ID required'}), 400
    
    success, message = block_student(int(student_id), current_user.id, reason)
    
    return jsonify({'success': success, 'message': message})

@main.route('/unblock-student', methods=['POST'])
@login_required
def unblock_student_route():
    if current_user.user_type != 'staff':
        return jsonify({'success': False, 'message': 'Only staff can unblock students'}), 403
    
    student_id = request.form.get('student_id')
    
    if not student_id:
        return jsonify({'success': False, 'message': 'Student ID required'}), 400
    
    success, message = unblock_student(int(student_id))
    
    return jsonify({'success': success, 'message': message})

@main.route('/check-profanity', methods=['POST'])
@login_required
def check_profanity_route():
    text = request.json.get('text', '')
    contains_profanity = check_profanity(text)
    
    return jsonify({
        'contains_profanity': contains_profanity,
        'message': 'Inappropriate language detected' if contains_profanity else 'Text is clean'
    })

@main.route('/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(20).all()
    
    return jsonify({
        'notifications': [{
            'id': n.id,
            'message': n.message,
            'type': n.notification_type,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat()
        } for n in notifications]
    })

@main.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get(notification_id)
    
    if not notification or notification.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404
    
    notification.is_read = True
    db.session.commit()
    
    return jsonify({'success': True})

@main.route('/question/<int:question_id>')
@login_required
def view_question(question_id):
    question = Question.query.get_or_404(question_id)
    
    # Check permissions
    if not question.is_public:
        if current_user.user_type == 'student' and question.student_id != current_user.id:
            flash('Access denied', 'error')
            return redirect(url_for('main.dashboard'))
        elif current_user.user_type == 'staff' and question.staff_id != current_user.id:
            flash('Access denied', 'error')
            return redirect(url_for('main.dashboard'))
    
    return render_template('view_question.html', question=question)


# ============================================
# ADMIN ROUTES
# ============================================

@main.route('/admin')
@login_required
def admin_panel():
    # For now, allow any staff member to access admin panel
    # You can add specific admin role check here
    if current_user.user_type != 'staff':
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('main.dashboard'))
    
    from datetime import datetime, timedelta
    from sqlalchemy import func
    
    # Get statistics
    total_users = User.query.count()
    students_count = User.query.filter_by(user_type='student').count()
    staff_count = User.query.filter_by(user_type='staff').count()
    
    total_questions = Question.query.count()
    public_questions = Question.query.filter_by(is_public=True).count()
    private_questions = Question.query.filter_by(is_public=False).count()
    
    total_answers = Answer.query.count()
    answered_questions = Question.query.filter_by(is_answered=True).count()
    
    blocked_users = User.query.filter_by(is_blocked=True).count()
    
    # Get all users
    all_users = User.query.order_by(User.created_at.desc()).all()
    
    # Get all questions
    all_questions = Question.query.order_by(Question.created_at.desc()).all()
    
    # Get blocked users list with details
    from models import BlockedUser
    blocked_users_list = db.session.query(BlockedUser)\
        .join(User, BlockedUser.student_id == User.id)\
        .add_columns(User.email)\
        .all()
    
    # Format blocked users list
    formatted_blocked = []
    for block, email in blocked_users_list:
        student = User.query.get(block.student_id)
        blocker = User.query.get(block.blocked_by_staff_id)
        formatted_blocked.append({
            'student': student,
            'blocker': blocker,
            'reason': block.reason,
            'blocked_at': block.blocked_at,
            'student_id': block.student_id
        })
    
    # Today's stats
    today = datetime.utcnow().date()
    questions_today = Question.query.filter(
        func.date(Question.created_at) == today
    ).count()
    
    answers_today = Answer.query.filter(
        func.date(Answer.created_at) == today
    ).count()
    
    new_users_today = User.query.filter(
        func.date(User.created_at) == today
    ).count()
    
    active_users_today = User.query.filter(
        func.date(User.last_login) == today
    ).count()
    
    # Top students (most questions)
    top_students = db.session.query(
        User,
        func.count(Question.id).label('question_count')
    ).join(Question, User.id == Question.student_id)\
     .filter(User.user_type == 'student')\
     .group_by(User.id)\
     .order_by(func.count(Question.id).desc())\
     .limit(5).all()
    
    # Format top students
    formatted_top_students = []
    for user, count in top_students:
        formatted_top_students.append({
            'email': user.email,
            'question_count': count
        })
    
    # Top staff (most answers)
    top_staff = db.session.query(
        User,
        func.count(Answer.id).label('answer_count')
    ).join(Answer, User.id == Answer.staff_id)\
     .filter(User.user_type == 'staff')\
     .group_by(User.id)\
     .order_by(func.count(Answer.id).desc())\
     .limit(5).all()
    
    # Format top staff
    formatted_top_staff = []
    for user, count in top_staff:
        formatted_top_staff.append({
            'email': user.email,
            'answer_count': count
        })
    
    # Response rate
    answered_percentage = round((answered_questions / total_questions * 100) if total_questions > 0 else 0, 1)
    
    # Average response time (simplified)
    avg_response_time = "< 24 hours"  # You can calculate actual average
    
    return render_template('admin_panel.html',
                         total_users=total_users,
                         students_count=students_count,
                         staff_count=staff_count,
                         total_questions=total_questions,
                         public_questions=public_questions,
                         private_questions=private_questions,
                         total_answers=total_answers,
                         answered_questions=answered_questions,
                         blocked_users=blocked_users,
                         all_users=all_users,
                         all_questions=all_questions,
                         blocked_users_list=formatted_blocked,
                         questions_today=questions_today,
                         answers_today=answers_today,
                         new_users_today=new_users_today,
                         active_users_today=active_users_today,
                         top_students=formatted_top_students,
                         top_staff=formatted_top_staff,
                         answered_percentage=answered_percentage,
                         avg_response_time=avg_response_time)

@main.route('/admin/user/<int:user_id>')
@login_required
def admin_user_details(user_id):
    if current_user.user_type != 'staff':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    user = User.query.get_or_404(user_id)
    
    questions_count = Question.query.filter_by(student_id=user_id).count()
    answers_count = Answer.query.filter_by(staff_id=user_id).count()
    
    return jsonify({
        'email': user.email,
        'user_type': user.user_type,
        'is_blocked': user.is_blocked,
        'is_verified': user.is_verified,
        'created_at': user.created_at.strftime('%b %d, %Y %I:%M %p'),
        'last_login': user.last_login.strftime('%b %d, %Y %I:%M %p') if user.last_login else None,
        'questions_count': questions_count,
        'answers_count': answers_count
    })

@main.route('/admin/delete-user/<int:user_id>', methods=['DELETE'])
@login_required
def admin_delete_user(user_id):
    if current_user.user_type != 'staff':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    user = User.query.get_or_404(user_id)
    
    # Don't allow deleting yourself
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot delete your own account'}), 400
    
    try:
        # Delete related records
        Question.query.filter_by(student_id=user_id).delete()
        Answer.query.filter_by(staff_id=user_id).delete()
        Notification.query.filter_by(user_id=user_id).delete()
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@main.route('/admin/delete-question/<int:question_id>', methods=['DELETE'])
@login_required
def admin_delete_question(question_id):
    if current_user.user_type != 'staff':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    question = Question.query.get_or_404(question_id)
    
    try:
        db.session.delete(question)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Question deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
