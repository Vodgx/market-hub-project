from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, time, timedelta
import os

# --- สร้าง Database อัตโนมัติ ---
if not os.path.exists('market.db'):
    from setup_db import create_db
    create_db()
    print(">>> Database Created!")

app = Flask(__name__)
app.secret_key = 'market_project_key'

def get_db():
    conn = sqlite3.connect('market.db')
    conn.row_factory = sqlite3.Row
    return conn

# --- Helper Functions ---
def get_now_thai():
    # แปลงเวลา Server (UTC) เป็นเวลาไทย (UTC+7)
    return datetime.utcnow() + timedelta(hours=7)

def get_market_info():
    now_thai = get_now_thai()
    current_time = now_thai.time()
    
    # เวลาเปิด-ปิด (11:00 - 00:00)
    market_open = time(11, 0)
    is_open = current_time >= market_open
    
    # เส้นตายยกเลิก (10:30)
    cancel_deadline = time(10, 30)
    
    return {
        'status': 'OPEN' if is_open else 'CLOSED',
        'datetime': now_thai.strftime('%d/%m/%Y'), # ส่งแค่วันที่ เวลาไปใช้ Realtime JS เอา
        'cancel_deadline_str': '10:30 น.',
        'can_cancel': current_time < cancel_deadline
    }

def check_and_reset_daily():
    conn = get_db()
    now_thai = get_now_thai()
    today_str = now_thai.strftime('%Y-%m-%d')
    
    # Reset ล็อคของวันเก่า (ไม่คืนเงินเครดิต)
    conn.execute("""
        UPDATE stalls 
        SET status='available', shop_name='', phone='', product_category='', 
            booked_by=NULL, booking_date='', payment_ref='', payment_status='pending'
        WHERE status='booked' AND booking_date != ?
    """, (today_str,))
    conn.commit()
    conn.close()

# --- Routes ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    check_and_reset_daily()
    info = get_market_info()
    search = request.args.get('q', '')
    active_zone = request.args.get('zone', 'Food Court')
    
    conn = get_db()
    current_user = conn.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    # อัปเดตเครดิตใน session ให้ตรงกับ DB เสมอ
    if current_user:
        session['credit'] = current_user['credit']
    
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

# --- ระบบเติมเงิน ---
@app.route('/topup', methods=['GET', 'POST'])
def topup():
    if 'user_id' not in session: return redirect('/login')
    
    if request.method == 'POST':
        amount = int(request.form['amount'])
        conn = get_db()
        conn.execute("UPDATE users SET credit = credit + ? WHERE id=?", (amount, session['user_id']))
        conn.commit()
        conn.close()
        flash(f'เติมเงินสำเร็จ {amount} บาท!', 'success')
        return redirect(url_for('index'))
        
    return render_template('topup.html')

# --- ระบบจอง ---
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
        conn.close()
        return redirect(url_for('index', zone=current_zone))

    payment_ref = ''
    if payment_method == 'transfer':
        payment_ref = request.form['payment_ref']
        if not payment_ref:
            flash('กรุณากรอกข้อมูลการโอนเงิน', 'warning')
            conn.close()
            return redirect(url_for('index', zone=current_zone))
    elif payment_method == 'credit':
        if user['credit'] >= stall['price']:
            new_credit = user['credit'] - stall['price']
            conn.execute("UPDATE users SET credit=? WHERE id=?", (new_credit, session['user_id']))
            payment_ref = 'CREDIT'
        else:
            flash('เครดิตไม่พอ กรุณาเติมเงิน', 'danger')
            conn.close()
            return redirect(url_for('index', zone=current_zone))

    today_str = get_now_thai().strftime('%Y-%m-%d')
    conn.execute("""
        UPDATE stalls 
        SET status='booked', shop_name=?, phone=?, product_category=?, booked_by=?, booking_date=?, payment_ref=?, payment_status='paid'
        WHERE id=?
    """, (shop_name, phone, category, session['user_id'], today_str, payment_ref, stall_id))
    conn.commit()
    conn.close()
    
    flash('จองล็อคสำเร็จ!', 'success')
    return redirect(url_for('index', zone=current_zone))

# --- ระบบยกเลิกจอง ---
@app.route('/cancel_booking/<int:stall_id>')
def cancel_booking(stall_id):
    if 'user_id' not in session: return redirect('/login')
    
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

# --- Admin Dashboard ---
@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': 
        flash('สำหรับผู้ดูแลระบบเท่านั้น', 'danger')
        return redirect('/')
        
    conn = get_db()
    # ข้อมูลสรุป
    total_sales = conn.execute("SELECT SUM(price) FROM stalls WHERE status='booked'").fetchone()[0] or 0
    total_booked = conn.execute("SELECT COUNT(*) FROM stalls WHERE status='booked'").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    
    # ดึงข้อมูลการจอง + ชื่อคนจอง
    bookings = conn.execute("""
        SELECT stalls.*, users.username 
        FROM stalls 
        LEFT JOIN users ON stalls.booked_by = users.id 
        WHERE stalls.status='booked' 
        ORDER BY zone, name
    """).fetchall()

    # ดึงรายชื่อ User ทั้งหมดมาแสดง
    all_users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    
    conn.close()
    return render_template('admin.html', total_sales=total_sales, total_booked=total_booked, 
                           total_users=total_users, bookings=bookings, all_users=all_users)

# --- Admin Edit Credit ---
@app.route('/admin/update_credit', methods=['POST'])
def admin_update_credit():
    if session.get('role') != 'admin': return redirect('/')
    
    user_id = request.form['user_id']
    new_credit = request.form['credit']
    
    conn = get_db()
    conn.execute("UPDATE users SET credit = ? WHERE id = ?", (new_credit, user_id))
    conn.commit()
    conn.close()
    
    flash('อัปเดตเครดิตเรียบร้อย', 'success')
    return redirect('/admin')

# --- Auth: Login & Register ---
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
            flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        try:
            # สมัครใหม่แจกเครดิต 0 บาท (หรือจะแจกฟรีแก้เลขตรงนี้)
            conn.execute("INSERT INTO users (username, password, role, credit) VALUES (?, ?, 'user', 0)", (username, password))
            conn.commit()
            flash('สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('ชื่อผู้ใช้นี้มีคนใช้แล้ว', 'danger')
        finally:
            conn.close()
            
    return render_template('register.html')

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
