from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_session import Session
from functools import wraps
import bcrypt
import os
import uuid
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import qrcode
from io import BytesIO
import base64
from dotenv import load_dotenv

from db_connect import get_db_connection

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

Session(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== DECORATORS ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== BASIC TEST ROUTES ====================
@app.route('/test')
def test():
    return "<h1>Flask is working!</h1><p>If you see this, Flask is running correctly.</p>"

@app.route('/raw')
def raw():
    return "<h1>Raw HTML works!</h1><p>Flask is functioning properly.</p>"

# ==================== MAIN ROUTES ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['full_name'] = user['full_name']
                session['role'] = user.get('role', 'user')
                
                if session['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('dashboard'))
            else:
                error = 'Invalid username or password'
        else:
            error = 'Database connection failed'
    
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    message = ''
    if request.method == 'POST':
        full_name = request.form['full_name']
        faculty = request.form['faculty']
        username = request.form['username']
        email = request.form['email']
        role = request.form.get('role', 'user')
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            message = 'Passwords do not match!'
        else:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                
                # Generate unique_id
                cursor.execute("SELECT unique_id FROM users WHERE unique_id LIKE 'A%' ORDER BY id DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    num = int(result[0][1:]) + 1
                    unique_id = f'A{num:04d}'
                else:
                    unique_id = 'A0001'
                
                # Check if username exists
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    message = 'Username already exists'
                else:
                    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cursor.fetchone():
                        message = 'Email already exists'
                    else:
                        cursor.execute("""
                            INSERT INTO users (unique_id, full_name, faculty, username, email, password, role)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (unique_id, full_name, faculty, username, email, hashed_password, role))
                        conn.commit()
                        message = 'Registration successful! Please login.'
                
                cursor.close()
                conn.close()
            else:
                message = 'Database connection failed'
    
    return render_template('register.html', message=message)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    unique_id = ''
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT unique_id FROM users WHERE id = %s", (session['user_id'],))
        result = cursor.fetchone()
        unique_id = result[0] if result else ''
        cursor.close()
        conn.close()
    
    return render_template('dashboard.html', 
                         full_name=session.get('full_name', 'User'),
                         unique_id=unique_id)

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    reports = []
    users = []
    
    if conn:
        cursor = conn.cursor(dictionary=True)
        
        # Create admin user if not exists
        admin_username = 'admin'
        admin_password = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("SELECT id FROM users WHERE username = %s", (admin_username,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO users (username, password, email, full_name, faculty, role)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (admin_username, admin_password, 'admin@campusfind.local', 'Administrator', 'Admin', 'admin'))
            conn.commit()
        
        cursor.execute("SELECT * FROM item_reports ORDER BY report_date DESC")
        reports = cursor.fetchall()
        
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        users = cursor.fetchall()
        
        cursor.close()
        conn.close()
    
    return render_template('admin_dashboard.html', reports=reports, users=users)

@app.route('/admin_delete', methods=['POST'])
@admin_required
def admin_delete():
    data = request.json
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        if 'delete_report_id' in data:
            cursor.execute("DELETE FROM item_reports WHERE id = %s", (data['delete_report_id'],))
        elif 'delete_user_id' in data:
            cursor.execute("DELETE FROM users WHERE id = %s", (data['delete_user_id'],))
        conn.commit()
        cursor.close()
        conn.close()
    
    return jsonify({'success': True})

@app.route('/report_lost', methods=['GET', 'POST'])
@login_required
def report_lost():
    if request.method == 'POST':
        item_name = request.form['item_name']
        description = request.form['description']
        location = request.form['location']
        report_date = request.form['date_lost']
        contact_option = request.form.get('contact_option', 'anonymous')
        contact = request.form.get('contact', '-') if contact_option == 'contact' else '-'
        user_id = session['user_id']
        
        image_path = ''
        if 'picture' in request.files:
            file = request.files['picture']
            if file.filename:
                filename = secure_filename(f"lost_{datetime.now().timestamp()}_{uuid.uuid4().hex[:4]}.{file.filename.split('.')[-1]}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = filepath
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO item_reports (user_id, report_type, item_name, description, location, report_date, contact, image_path)
                VALUES (%s, 'lost', %s, %s, %s, %s, %s, %s)
            """, (user_id, item_name, description, location, report_date, contact, image_path))
            conn.commit()
            cursor.close()
            conn.close()
        
        flash('Lost item reported successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('report_lost.html')

@app.route('/report_found', methods=['GET', 'POST'])
@login_required
def report_found():
    if request.method == 'POST':
        item_name = request.form['item_name']
        description = request.form['description']
        location = request.form['location']
        report_date = request.form['date_found']
        contact_option = request.form.get('contact_option', 'anonymous')
        contact = request.form.get('contact', '-') if contact_option == 'contact' else '-'
        user_id = session['user_id']
        
        image_path = ''
        if 'picture' in request.files:
            file = request.files['picture']
            if file.filename:
                filename = secure_filename(f"found_{datetime.now().timestamp()}_{uuid.uuid4().hex[:4]}.{file.filename.split('.')[-1]}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = filepath
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO item_reports (user_id, report_type, item_name, description, location, report_date, contact, image_path)
                VALUES (%s, 'found', %s, %s, %s, %s, %s, %s)
            """, (user_id, item_name, description, location, report_date, contact, image_path))
            conn.commit()
            cursor.close()
            conn.close()
        
        flash('Found item reported successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('report_found.html')

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    
    sql = "SELECT * FROM item_reports WHERE 1=1"
    params = []
    
    if query:
        sql += " AND (item_name LIKE %s OR description LIKE %s OR location LIKE %s)"
        like_query = f"%{query}%"
        params.extend([like_query, like_query, like_query])
    
    if category:
        sql += " AND item_name = %s"
        params.append(category)
    
    if status:
        sql += " AND report_type = %s"
        params.append(status.lower())
    
    sql += " ORDER BY report_date DESC LIMIT 20"
    
    conn = get_db_connection()
    results = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        results = cursor.fetchall()
        cursor.close()
        conn.close()
    
    return render_template('search.html', results=results, query=query)

@app.route('/chat_list')
@login_required
def chat_list():
    user_id = session['user_id']
    
    conn = get_db_connection()
    chats = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ir.*, 
                   (SELECT MAX(sent_at) FROM chat_messages WHERE item_report_id = ir.id) as last_time,
                   (SELECT message FROM chat_messages WHERE item_report_id = ir.id ORDER BY sent_at DESC LIMIT 1) as last_msg
            FROM item_reports ir
            WHERE ir.user_id = %s OR ir.id IN (SELECT item_report_id FROM chat_messages WHERE sender_id = %s)
            ORDER BY last_time DESC, ir.report_date DESC
        """, (user_id, user_id))
        chats = cursor.fetchall()
        cursor.close()
        conn.close()
    
    return render_template('chat_list.html', chats=chats)

@app.route('/chat')
@login_required
def chat():
    item_report_id = request.args.get('item', type=int)
    if not item_report_id:
        return redirect(url_for('search'))
    
    user_id = session['user_id']
    
    conn = get_db_connection()
    if not conn:
        return "Database error", 500
    
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT user_id, item_name FROM item_reports WHERE id = %s", (item_report_id,))
    item = cursor.fetchone()
    if not item:
        cursor.close()
        conn.close()
        return "Item not found", 404
    
    owner_id = item['user_id']
    item_name = item['item_name']
    
    other_user_id = owner_id if user_id != owner_id else None
    
    user1_id = owner_id
    user2_id = other_user_id if other_user_id else user_id
    
    cursor.execute("""
        SELECT id FROM chats 
        WHERE item_report_id = %s AND user1_id = %s AND user2_id = %s
    """, (item_report_id, user1_id, user2_id))
    chat = cursor.fetchone()
    
    if not chat:
        cursor.execute("""
            INSERT INTO chats (item_report_id, user1_id, user2_id)
            VALUES (%s, %s, %s)
        """, (item_report_id, user1_id, user2_id))
        conn.commit()
        chat_id = cursor.lastrowid
    else:
        chat_id = chat['id']
    
    cursor.execute("""
        SELECT * FROM chat_messages 
        WHERE chat_id = %s ORDER BY sent_at ASC
    """, (chat_id,))
    messages = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('chat.html', item_name=item_name, item_report_id=item_report_id, 
                         messages=messages, user_id=user_id, owner_id=owner_id)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    data = request.json
    chat_id = data.get('chat_id')
    item_report_id = data.get('item_report_id')
    message = data.get('message', '').strip()
    
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_messages (chat_id, item_report_id, sender_id, message, sent_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (chat_id, item_report_id, session['user_id'], message))
        conn.commit()
        cursor.close()
        conn.close()
    
    return jsonify({'success': True})

@app.route('/campus_tag_manage', methods=['GET', 'POST'])
@login_required
def campus_tag_manage():
    user_id = session['user_id']
    conn = get_db_connection()
    full_name = ''
    tag = None
    has_tag = False
    
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT full_name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        full_name = user['full_name'] if user else ''
        
        cursor.execute("SELECT contact_number, faculty, room_number FROM campus_tag WHERE user_id = %s", (user_id,))
        tag = cursor.fetchone()
        has_tag = tag is not None
        cursor.close()
        conn.close()
    
    faculties = [
        'Pusat Asasi Pertahanan', 'Fakulti Perubatan dan Kesihatan Pertahanan',
        'Fakulti Kejuruteraan', 'Fakulti Sains dan Teknologi Pertahanan',
        'Fakulti Pengajian dan Pengurusan Pertahanan', 'Pusat Bahasa',
        'Akademi Kecergasan Pertahanan', 'Akademi Pengajian Pertahanan Islam'
    ]
    
    return render_template('campus_tag_manage.html', full_name=full_name, has_tag=has_tag,
                         tag=tag, faculties=faculties)

@app.route('/campus_tag_qr')
@login_required
def campus_tag_qr():
    user_id = session['user_id']
    conn = get_db_connection()
    
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT full_name, unique_id FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    cursor.execute("SELECT contact_number, faculty, room_number FROM campus_tag WHERE user_id = %s", (user_id,))
    tag = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not user or not tag:
        return jsonify({'error': 'Not found'}), 404
    
    name_parts = user['full_name'].split(' ', 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ''
    
    vcard = f"BEGIN:VCARD\nVERSION:3.0\nN:{last_name};{first_name};;;\nFN:{user['full_name']}\nTEL;TYPE=CELL:{tag['contact_number']}\nORG:{tag['faculty']}\nTITLE:Room {tag['room_number']}\nNOTE:Campus Tag ID: {user['unique_id']}\nEND:VCARD"
    
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(vcard)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return jsonify({'qr_code': f'data:image/png;base64,{img_str}'})

@app.route('/campus_tag_status')
@login_required
def campus_tag_status():
    user_id = session['user_id']
    conn = get_db_connection()
    has_tag = False
    
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM campus_tag WHERE user_id = %s", (user_id,))
        has_tag = cursor.fetchone() is not None
        cursor.close()
        conn.close()
    
    return jsonify({'has_tag': has_tag})

@app.route('/ai_matching')
@login_required
def ai_matching():
    conn = get_db_connection()
    reports = []
    
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, item_name, report_type, report_date 
            FROM item_reports WHERE user_id = %s ORDER BY report_date DESC
        """, (session['user_id'],))
        reports = cursor.fetchall()
        cursor.close()
        conn.close()
    
    return render_template('ai_matching.html', reports=reports)

@app.route('/ai_matching_process', methods=['POST'])
@login_required
def ai_matching_process():
    image_path = ''
    item_report_id = request.form.get('item_report_id')
    
    if 'image' in request.files:
        file = request.files['image']
        if file.filename:
            filename = secure_filename(f"ai_match_{datetime.now().timestamp()}_{uuid.uuid4().hex[:4]}.{file.filename.split('.')[-1]}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            image_path = filepath
    
    if image_path:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            if item_report_id:
                cursor.execute("""
                    INSERT INTO ai_matching_images (user_id, image_path, uploaded_at, item_report_id)
                    VALUES (%s, %s, NOW(), %s)
                """, (session['user_id'], image_path, item_report_id))
            else:
                cursor.execute("""
                    INSERT INTO ai_matching_images (user_id, image_path, uploaded_at)
                    VALUES (%s, %s, NOW())
                """, (session['user_id'], image_path))
            conn.commit()
            cursor.close()
            conn.close()
        message = 'Image uploaded successfully!'
        similar_images = []
    else:
        similar_images = []
        message = 'No image uploaded.'
    
    return render_template('ai_matching_result.html', message=message, image_path=image_path, 
                         similar_images=similar_images)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    message = ''
    if request.method == 'POST':
        email = request.form['email']
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            
            if user:
                token = uuid.uuid4().hex
                expiry = datetime.now() + timedelta(hours=1)
                cursor.execute("UPDATE users SET reset_token = %s, reset_token_expiry = %s WHERE email = %s",
                             (token, expiry, email))
                conn.commit()
                message = f'Password reset link (demo): {url_for("reset_password", token=token, _external=True)}'
                flash(message, 'info')
            else:
                message = 'Email not found'
            
            cursor.close()
            conn.close()
    
    return render_template('forgot_password.html', message=message)

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('token', '')
    error = ''
    success = ''
    show_form = False
    
    if request.method == 'POST':
        token = request.form['token']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            error = 'Passwords do not match!'
        else:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cursor.execute("""
                    UPDATE users SET password = %s, reset_token = NULL, reset_token_expiry = NULL 
                    WHERE reset_token = %s
                """, (hashed_password, token))
                conn.commit()
                
                if cursor.rowcount > 0:
                    success = 'Password has been reset. You can now login.'
                else:
                    error = 'Failed to reset password.'
                
                cursor.close()
                conn.close()
    else:
        if token:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE reset_token = %s AND reset_token_expiry > NOW()", (token,))
                if cursor.fetchone():
                    show_form = True
                else:
                    error = 'Invalid or expired token.'
                cursor.close()
                conn.close()
        else:
            error = 'No token provided.'
    
    return render_template('reset_password.html', token=token, error=error, 
                         success=success, show_form=show_form)

# ==================== RUN APP ====================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)