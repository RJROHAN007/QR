from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import qrcode
import io
import base64
import database
import os
from functools import wraps
import requests
from PIL import Image
from itsdangerous import URLSafeSerializer


app = Flask(__name__)

SECRET_TOKEN_KEY = os.environ.get('TOKEN_SECRET', 'super-secret-key-change-this')
serializer = URLSafeSerializer(SECRET_TOKEN_KEY)

# Configuration
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
    SESSION_COOKIE_SECURE=os.environ.get('FLASK_ENV') == 'production',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

# Initialize database
db = database.db


def get_image_from_url(image_url):
    """Get image from Google Drive URL and convert to base64"""
    try:
        if not image_url or 'google.com' not in image_url:
            return None

        # Convert Google Drive URL to direct download link
        if 'drive.google.com' in image_url:
            file_id = image_url.split('/d/')[1].split('/')[0]
            direct_url = f"https://drive.google.com/uc?export=view&id={file_id}"
        else:
            direct_url = image_url

        response = requests.get(direct_url, timeout=10)
        if response.status_code == 200:
            # Convert to base64
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            return f"data:image/jpeg;base64,{image_base64}"
    except Exception as e:
        print(f"Error loading image from URL: {e}")
    return None


def generate_qr_code(member_id, base_url):
    """Generate QR code for a specific user"""
    try:
        print(f"🔄 Generating QR code for user: {member_id}")
        print(f"   Base URL: {base_url}")

        if not member_id:
            print("❌ No member_id provided for QR generation")
            return None, None

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )

        # signed token for this member
        token = serializer.dumps({'member_id': member_id})
        login_url = f"{base_url}secure-login/{token}"

        print(f"   Login URL: {login_url}")

        qr.add_data(login_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        # Convert to base64
        qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        print(f"✅ QR generated successfully for user {member_id}")
        return qr_base64, login_url

    except Exception as e:
        print(f"❌ Error generating QR code for {member_id}: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def admin_required(f):
    """Decorator to require admin authentication"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)

    return decorated_function


@app.before_request
def make_session_permanent():
    session.permanent = True


# Main Routes
@app.route('/')
def home():
    return redirect(url_for('admin_login'))


@app.route('/generate-qr-codes')
def generate_qr_codes():
    """Generate QR codes for all users from database"""
    """Generate QR codes for all users from database with search and filters"""
    search_term = request.args.get('search', '')
    blood_filter = request.args.get('blood_group', '')
    membership_filter = request.args.get('membership_type', '')

    # Get filtered users
    if search_term:
        users = db.search_users(search_term)
    else:
        users = db.get_all_users()

    # Apply additional filters
    filtered_users = []
    for user in users:
        if blood_filter and user.get('blood_group') != blood_filter:
            continue
        if membership_filter and user.get('membership_type') != membership_filter:
            continue
        filtered_users.append(user)

    if not filtered_users:
        return render_template('generate_qr.html', qr_codes=[], error="No users found matching your criteria!",
                               search_term=search_term, blood_filter=blood_filter, membership_filter=membership_filter)

    qr_codes = []
    base_url = request.host_url

    for user in filtered_users:
        qr_code_data, login_url = generate_qr_code(user['member_id'], base_url)

        if qr_code_data:
            qr_codes.append({
                'member_id': user['member_id'],
                'name': user['name'],
                'qr_code': qr_code_data,
                'login_url': login_url
            })

    return render_template('generate_qr.html', qr_codes=qr_codes,
                           search_term=search_term, blood_filter=blood_filter, membership_filter=membership_filter)


@app.route('/login/<member_id>', methods=['GET', 'POST'])
def login(member_id):
    """Login page - member_id is hardcoded from QR code"""
    print(f"🔐 LOGIN PAGE ACCESSED for user: {member_id}")

    user = db.get_user_by_id(member_id)

    if not user:
        print(f"❌ USER NOT FOUND: {member_id}")
        return render_template('error.html', error="User not found! Please check your QR code."), 404

    print(f"✅ USER FOUND: {user['name']} ({member_id})")
    session.clear()

    if request.method == 'POST':
        password = request.form.get('password', '')
        print(f"📝 LOGIN FORM SUBMITTED:")
        print(f"   Member ID: {member_id}")
        print(f"   Password entered: '{password}'")

        # Check if password is provided
        if not password:
            print("❌ NO PASSWORD PROVIDED")
            return render_template('login.html',
                                   user=user,
                                   error="❌ Password is required!")

        # Verify password
        print(f"🔐 VERIFYING PASSWORD...")
        password_valid = db.verify_password(member_id, password)
        print(f"✅ PASSWORD VERIFICATION RESULT: {password_valid}")

        if password_valid:
            session['member_id'] = member_id
            session['logged_in'] = True
            session.permanent = True
            print(f"🎉 LOGIN SUCCESSFUL!")
            return redirect(url_for('user_profile', member_id=member_id))
        else:
            print(f"❌ LOGIN FAILED - Invalid password")
            return render_template('login.html',
                                   user=user,
                                   error="❌ Invalid password! Please try again.")

    # GET request - show login form
    print(f"📄 SHOWING LOGIN FORM for {member_id}")
    return render_template('login.html', user=user)


@app.route('/profile/<member_id>')
def user_profile(member_id):
    """User profile page that requires login"""
    # Check if user is logged in and matches the profile
    if not session.get('logged_in') or session.get('member_id') != member_id:
        return redirect(url_for('login', member_id=member_id))

    user = db.get_user_by_id(member_id)
    if not user:
        return render_template('error.html', error="User not found!"), 404

    image_path = user.get('image_path')
    if image_path:
        image_path = db.convert_google_drive_url(image_path)
        print(f"🖼️ User profile - Converted image URL: {image_path}")
    else:
        image_path = None
    # Generate QR code
    base_url = request.host_url
    qr_code_data, login_url = generate_qr_code(member_id, base_url)

    return render_template('user_profile.html',
                           user=user,
                           qr_code=qr_code_data,
                           login_url=login_url or f"{base_url}login/{member_id}",
                           image_path=image_path,  # Pass image_path instead of image_data
                           is_admin_view=False)


@app.route('/logout')
def logout():
    """User logout"""
    member_id = session.get('member_id')
    session.clear()
    print("LOGGED OUT")
    return redirect(url_for('login',member_id=member_id))


# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if db.verify_admin(username, password):
            session['is_admin'] = True
            session['admin_username'] = username
            flash('✅ Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="❌ Invalid admin credentials!")

    return render_template('admin_login.html')


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    stats = db.get_user_stats()
    users = db.get_all_users()
    return render_template('admin_dashboard.html', stats=stats, users=users)


@app.route('/admin/users')
@admin_required
def admin_users():
    """User management page"""
    search_term = request.args.get('search', '')
    if search_term:
        users = db.search_users(search_term)
    else:
        users = db.get_all_users()
    return render_template('admin_users.html', users=users, search_term=search_term)
    users = db.get_all_users()
    return render_template('admin_users.html', users=users)


@app.route('/admin/add-user', methods=['GET', 'POST'])
@admin_required
def admin_add_user():
    """Add new user"""
    if request.method == 'POST':
        user_data = {
            'member_id': request.form.get('member_id'),
            'name': request.form.get('name'),
            'date_of_birth': request.form.get('date_of_birth'),
            'address': request.form.get('address'),
            'blood_group': request.form.get('blood_group'),
            'phone': request.form.get('phone'),
            'image_path': request.form.get('image_path'),
            'membership_type': request.form.get('membership_type'),
            'membership_joining_date': request.form.get('membership_joining_date'),
            'password': request.form.get('password', '123456')
        }

        success, message = db.add_user(user_data)
        if success:
            flash(f'✅ {message}', 'success')
            return redirect(url_for('admin_users'))
        else:
            flash(f'❌ {message}', 'error')

    return render_template('admin_add_user.html')


@app.route('/admin/edit-user/<member_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(member_id):
    """Edit user data"""
    user = db.get_user_by_id(member_id)
    if not user:
        flash('❌ User not found!', 'error')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        user_data = {
            'name': request.form.get('name'),
            'date_of_birth': request.form.get('date_of_birth'),
            'address': request.form.get('address'),
            'blood_group': request.form.get('blood_group'),
            'phone': request.form.get('phone'),
            'image_path': request.form.get('image_path'),
            'membership_type': request.form.get('membership_type'),
            'membership_joining_date': request.form.get('membership_joining_date')
        }

        success, message = db.update_user(member_id, user_data)
        if success:
            flash(f'✅ {message}', 'success')
            return redirect(url_for('admin_users'))
        else:
            flash(f'❌ {message}', 'error')

    return render_template('admin_edit_user.html', user=user)


@app.route('/admin/bulk-edit', methods=['GET', 'POST'])
@admin_required
def admin_bulk_edit():
    """Bulk edit users"""
    if request.method == 'POST':
        member_ids = request.form.getlist('member_ids')
        field = request.form.get('field')
        value = request.form.get('value')

        print(f"Bulk edit request: {len(member_ids)} users, field: {field}, value: {value}")

        if not member_ids or not field or not value:
            flash('❌ Please select users, field, and provide a value!', 'error')
            return redirect(url_for('admin_bulk_edit'))

        # Create updates data structure
        updates_data = {}
        for member_id in member_ids:
            updates_data[member_id] = {field: value}

        success_count, errors = db.bulk_update_users(updates_data)

        if success_count > 0:
            flash(f'✅ Successfully updated {success_count} users!', 'success')
        if errors:
            for error in errors[:5]:  # Show first 5 errors
                flash(f'❌ {error}', 'error')
            if len(errors) > 5:
                flash(f'❌ ... and {len(errors) - 5} more errors', 'error')

        return redirect(url_for('admin_bulk_edit'))

        # GET request - show the form
    search_term = request.args.get('search', '')
    if search_term:
        users = db.search_users(search_term)
    else:
        users = db.get_all_users()
    return render_template('admin_bulk_edit.html', users=users, search_term=search_term)


@app.route('/admin/delete-user/<member_id>')
@admin_required
def admin_delete_user(member_id):
    """Delete user"""
    success, message = db.delete_user(member_id)
    if success:
        flash(f'✅ {message}', 'success')
    else:
        flash(f'❌ {message}', 'error')

    return redirect(url_for('admin_users'))


@app.route('/admin/import-excel', methods=['POST'])
@admin_required
def admin_import_excel():
    """Import users from Excel file"""
    if 'excel_file' not in request.files:
        flash('❌ No file selected!', 'error')
        return redirect(url_for('admin_users'))

    file = request.files['excel_file']
    if file.filename == '':
        flash('❌ No file selected!', 'error')
        return redirect(url_for('admin_users'))

    if file and file.filename.endswith('.xlsx'):
        try:
            file_path = 'temp_upload.xlsx'
            file.save(file_path)
            success = db.import_from_excel(file_path)

            if os.path.exists(file_path):
                os.remove(file_path)

            if success:
                flash('✅ Users imported successfully from Excel!', 'success')
            else:
                flash('❌ Failed to import users from Excel!', 'error')
        except Exception as e:
            flash(f'❌ Error importing Excel file: {str(e)}', 'error')
    else:
        flash('❌ Please upload a valid Excel file (.xlsx)!', 'error')

    return redirect(url_for('admin_users'))


@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.pop('is_admin', None)
    session.pop('admin_username', None)
    flash('✅ Admin logged out successfully!', 'success')
    return redirect(url_for('admin_login'))


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error="Page not found!"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error="Internal server error!"), 500


# Security headers
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response


# Add these imports at the top
import secrets


# Add CSRF protection
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(16)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = generate_csrf_token


def verify_csrf_token(token):
    return token == session.get('_csrf_token')


# Add these routes to your app.py

@app.route('/admin/reset-passwords')
@admin_required
def admin_reset_passwords():
    """Admin password reset page"""
    users = db.get_all_users()
    return render_template('admin_reset_passwords.html', users=users)


@app.route('/admin/bulk-reset-passwords', methods=['POST'])
@admin_required
def admin_bulk_reset_passwords():
    """Bulk reset all passwords"""
    if not verify_csrf_token(request.form.get('csrf_token')):
        flash('❌ Security token invalid!', 'error')
        return redirect(url_for('admin_reset_passwords'))

    default_password = request.form.get('default_password', '123456')

    if not default_password or len(default_password) < 4:
        flash('❌ Password must be at least 4 characters long!', 'error')
        return redirect(url_for('admin_reset_passwords'))

    success = db.reset_all_passwords(default_password)
    if success:
        flash(f'✅ All passwords reset to: {default_password}', 'success')
    else:
        flash('❌ Failed to reset passwords', 'error')

    return redirect(url_for('admin_reset_passwords'))


@app.route('/admin/reset-single-password', methods=['POST'])
@admin_required
def admin_reset_single_password():
    """Reset single user password"""
    if not verify_csrf_token(request.form.get('csrf_token')):
        flash('❌ Security token invalid!', 'error')
        return redirect(url_for('admin_reset_passwords'))

    member_id = request.form.get('member_id')
    new_password = request.form.get('new_password')

    if not member_id or not new_password:
        flash('❌ Member ID and new password are required!', 'error')
        return redirect(url_for('admin_reset_passwords'))

    if len(new_password) < 4:
        flash('❌ Password must be at least 4 characters long!', 'error')
        return redirect(url_for('admin_reset_passwords'))

    success, message = db.change_user_password(member_id, new_password)

    if success:
        flash(f'✅ Password reset for user {member_id}', 'success')
    else:
        flash(f'❌ {message}', 'error')

    return redirect(url_for('admin_reset_passwords'))


@app.route('/change-own-password', methods=['POST'])
def change_own_password():
    """User changes their own password"""
    # Check if user is logged in
    if not session.get('logged_in'):
        flash('❌ Please login first!', 'error')
        return redirect(url_for('home'))

    member_id = session.get('member_id')
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    # Validate inputs
    if not all([current_password, new_password, confirm_password]):
        flash('❌ All fields are required!', 'error')
        return redirect(url_for('user_profile', member_id=member_id))

    if new_password != confirm_password:
        flash('❌ New password and confirmation do not match!', 'error')
        return redirect(url_for('user_profile', member_id=member_id))

    if len(new_password) < 6:
        flash('❌ Password must be at least 6 characters long!', 'error')
        return redirect(url_for('user_profile', member_id=member_id))

    # Change password
    success, message = db.change_own_password(member_id, current_password, new_password)

    if success:
        flash('✅ Password changed successfully!', 'success')
        # Logout user after password change for security
        session.clear()
        flash('🔒 Please login with your new password', 'info')
        return redirect(url_for('login', member_id=member_id))
    else:
        flash(f'❌ {message}', 'error')
        return redirect(url_for('user_profile', member_id=member_id))

@app.route('/admin/view-profile/<member_id>')
@admin_required
def admin_view_profile(member_id):
    """Admin can view any user profile without password"""
    user = db.get_user_by_id(member_id)
    if not user:
        flash('❌ User not found!', 'error')
        return redirect(url_for('admin_users'))

    # Convert Google Drive URL to direct image URL
    image_path = user.get('image_path')
    if image_path:
        image_path = db.convert_google_drive_url(image_path)
        print(f"🖼️ Converted image URL: {image_path}")
    else:
        image_path = None

    # Generate QR code for this user
    base_url = request.host_url
    qr_code_data, login_url = generate_qr_code(member_id, base_url)

    return render_template(
        'user_profile.html',
        user=user,
        qr_code=qr_code_data,
        login_url=login_url or f"{base_url}login/{member_id}",
        image_path=image_path,  # Safe to pass now
        is_admin_view=True
    )

@app.route('/admin/reload-images')
@admin_required
def admin_reload_images():
    """Reload all user images"""
    reloaded_count = db.reload_all_images()
    flash(f'✅ Reloaded {reloaded_count} user images', 'success')
    return redirect(url_for('admin_users'))

@app.route('/secure-login/<token>', methods=['GET', 'POST'])
def secure_login(token):
    """Secure login page using signed token (member ID hidden)"""
    try:
        data = serializer.loads(token)
        member_id = data.get('member_id')
    except Exception:
        return render_template('error.html', error="Invalid or expired QR code!"), 403

    # Reuse your normal login logic
    return login(member_id)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'

    print("🚀 Starting User QR System...")
    print(f"📊 Database: {db.db_path}")
    print(f"🔗 Port: {port}")
    print(f"🐛 Debug: {debug}")
    print("👨‍💼 Admin Panel: /admin/login")
    print("🔑 Default Admin: username='admin', password='admin123'")
    print("👤 Default User Password: 123456")


    app.run(host='0.0.0.0', port=port, debug=debug)
