from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, time, timedelta
import os
# ... import อื่นๆ ...

# --- ส่วนที่เพิ่ม: สร้าง Database อัตโนมัติถ้ายังไม่มี ---
if not os.path.exists('market.db'):
    from setup_db import create_db
    create_db()
    print(">>> สร้าง Database บน Server เรียบร้อย!")
# ------------------------------------------------
app = Flask(__name__)
app.secret_key = 'market_project_key'

def get_db():
    conn = sqlite3.connect('market.db')
    conn.row_factory = sqlite3.Row
    return conn

# --- Helper Functions ---

def get_market_info():
    now = datetime.now()
    current_time = now.time()
    
    # กำหนดเวลาเปิด-ปิดตลาด (11:00 - 00:00)
    market_open = time(11, 0)
    market_close = time(0, 0) # เที่ยงคืนคือขอบเขตวัน
    
    # Logic ตลาดเปิด: ถ้าเวลาปัจจุบันมากกว่า 11 โมง
    is_open = current_time >= market_open
    
    # กำหนดเส้นตายการยกเลิก (10:30 น.)
    cancel_deadline = time(10, 30)
    
    return {
        'status': 'OPEN' if is_open else 'CLOSED',
        'datetime': now.strftime('%d %B %Y | %H:%M น.'),
        'cancel_deadline_str': '10:30 น.',
        'can_cancel': current_time < cancel_deadline # จะเป็น True ถ้ายังไม่ถึง 10:30
    }

def check_and_reset_daily():
    conn = get_db()
    today_str = datetime.now().strftime('%Y-%m-%d')
    # ล้างข้อมูลเมื่อขึ้นวันใหม่
    conn.execute("""
        UPDATE stalls 
        SET status='available', shop_name='', phone='', product_category='', booked_by=NULL, booking_date='', payment_ref='', payment_status='pending'
        WHERE status='booked' AND booking_date != ?
    """, (today_str,))
    conn.commit()
    conn.close()

# --- Routes ---

@app.route('/')
def index():
    check_and_reset_daily()
    info = get_market_info()
    search = request.args.get('q', '')
    active_zone = request.args.get('zone', 'Food Court')
    
    conn = get_db()
    
    # Get User & Credit
    current_user = None
    if 'user_id' in session:
        current_user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
        session['credit'] = current_user['credit']

    # Search & Filter
    if search:
        stalls = conn.execute("SELECT * FROM stalls WHERE shop_name LIKE ?", ('%' + search + '%',)).fetchall()
        if stalls: active_zone = stalls[0]['zone']
    else:
        stalls = conn.execute("SELECT * FROM stalls").fetchall()
    
    zones = {}
    for stall in stalls:
        z = stall['zone']
        if z not in zones: zones[z] = []
        zones[z].append(stall)
        
    reviews = conn.execute("SELECT * FROM reviews ORDER BY id DESC").fetchall()
    avg_rating = conn.execute("SELECT AVG(rating) FROM reviews").fetchone()[0] or 0.0
    conn.close()
    
    return render_template('index.html', zones=zones, reviews=reviews, avg_rating=round(avg_rating, 1),
                           search=search, active_zone=active_zone, info=info, user_info=current_user)

@app.route('/book', methods=['POST'])
def book_stall():
    if 'user_id' not in session: return redirect('/login')

    stall_id = request.form['stall_id']
    shop_name = request.form['shop_name']
    phone = request.form['phone']
    category = request.form['category']
    current_zone = request.form['current_zone']
    payment_method = request.form.get('payment_method', 'transfer')
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    stall = conn.execute("SELECT * FROM stalls WHERE id=?", (stall_id,)).fetchone()

    if stall['status'] == 'booked':
        flash('ไม่ทัน! ล็อคนี้ถูกจองไปแล้ว', 'danger')
        return redirect(url_for('index', zone=current_zone))

    payment_ref = ''
    if payment_method == 'transfer':
        payment_ref = request.form['payment_ref']
        if not payment_ref:
            flash('กรุณากรอกข้อมูลการโอนเงิน', 'warning')
            return redirect(url_for('index', zone=current_zone))
    elif payment_method == 'credit':
        if user['credit'] >= stall['price']:
            new_credit = user['credit'] - stall['price']
            conn.execute("UPDATE users SET credit=? WHERE id=?", (new_credit, session['user_id']))
            payment_ref = 'CREDIT'
        else:
            flash('เครดิตไม่พอ', 'danger')
            return redirect(url_for('index', zone=current_zone))

    today_str = datetime.now().strftime('%Y-%m-%d')
    conn.execute("""
        UPDATE stalls 
        SET status='booked', shop_name=?, phone=?, product_category=?, booked_by=?, booking_date=?, payment_ref=?, payment_status='paid'
        WHERE id=?
    """, (shop_name, phone, category, session['user_id'], today_str, payment_ref, stall_id))
    conn.commit()
    conn.close()
    
    flash('จองล็อคสำเร็จ!', 'success')
    return redirect(url_for('index', zone=current_zone))

@app.route('/cancel_booking/<int:stall_id>')
def cancel_booking(stall_id):
    if 'user_id' not in session: return redirect('/login')
    
    # เช็คเวลาว่าเกิน 10:30 หรือยัง (Admin ยกเลิกได้ตลอดเวลา)
    info = get_market_info()
    if not info['can_cancel'] and session['role'] != 'admin':
        flash(f'ไม่สามารถยกเลิกได้! (ต้องยกเลิกก่อนเวลา {info["cancel_deadline_str"]})', 'danger')
        return redirect('/')

    conn = get_db()
    stall = conn.execute("SELECT * FROM stalls WHERE id=?", (stall_id,)).fetchone()
    
    if stall and (stall['booked_by'] == session['user_id'] or session['role'] == 'admin'):
        refund = stall['price']
        conn.execute("UPDATE users SET credit = credit + ? WHERE id=?", (refund, stall['booked_by']))
        conn.execute("""
            UPDATE stalls 
            SET status='available', shop_name='', phone='', product_category='', booking_date='', booked_by=NULL, payment_ref='', payment_status='pending' 
            WHERE id=?
        """, (stall_id,))
        conn.commit()
        flash(f'ยกเลิกสำเร็จ! คืนเครดิต {refund} บาท', 'warning')
    
    conn.close()
    return redirect('/')

# --- Admin Dashboard (ที่หายไป ผมใส่กลับมาให้แล้วครับ) ---
@app.route('/admin')
def admin_dashboard():
    # ป้องกันคนนอกเข้า
    if session.get('role') != 'admin': 
        flash('สำหรับผู้ดูแลระบบเท่านั้น', 'danger')
        return redirect('/')
        
    conn = get_db()
    # ดึงสถิติต่างๆ
    total_sales = conn.execute("SELECT SUM(price) FROM stalls WHERE status='booked'").fetchone()[0] or 0
    total_booked = conn.execute("SELECT COUNT(*) FROM stalls WHERE status='booked'").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    
    # ดึงรายการจองทั้งหมด
    bookings = conn.execute("SELECT * FROM stalls WHERE status='booked' ORDER BY zone, name").fetchall()
    
    conn.close()
    return render_template('admin.html', total_sales=total_sales, total_booked=total_booked, total_users=total_users, bookings=bookings)

# --- Auth & Review Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['credit'] = user['credit']
            return redirect('/')
        else:
            flash('Login Failed', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/review', methods=['POST'])
def add_review():
    conn = get_db()
    conn.execute("INSERT INTO reviews (shop_name, rating, comment, reviewer_name) VALUES (?, ?, ?, ?)",
                 (request.form['shop_name'], request.form['rating'], request.form['comment'], session.get('username', 'Guest')))
    conn.commit()
    conn.close()
    return redirect('/')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)