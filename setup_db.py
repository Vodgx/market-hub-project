import sqlite3
import random
from datetime import datetime

def create_db():
    conn = sqlite3.connect('market.db')
    c = conn.cursor()

    # Users
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        credit INTEGER DEFAULT 0 
    )''')

    # Stalls
    c.execute('''CREATE TABLE IF NOT EXISTS stalls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        zone TEXT NOT NULL,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'available', 
        shop_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        product_category TEXT DEFAULT '',
        booking_date TEXT DEFAULT '',
        booked_by INTEGER,
        payment_ref TEXT DEFAULT '',
        payment_status TEXT DEFAULT 'pending' 
    )''')

    # Reviews
    c.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_name TEXT NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT,
        reviewer_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Seed Data
    c.execute("INSERT OR IGNORE INTO users (username, password, role, credit) VALUES ('admin', '1234', 'admin', 0)")
    c.execute("INSERT OR IGNORE INTO users (username, password, role, credit) VALUES ('user', '1234', 'user', 5000)")

    fake_shops = ['ร้านป้าไก่', 'ข้าวมันไก่นาย ก.', 'เสื้อผ้าแฟชั่น', 'Gadget Store', 'เคสมือถือซิ่ง', 'หมูปิ้งนมสด', 'ยำแซ่บเวอร์', 'กางเกงยีนส์', 'น้ำปั่นผลไม้', 'ลูกชิ้นทอด']
    
    # แก้ชื่อโซนให้ถูกต้อง
    zones = [
        ('Food Court', 'A', 300),
        ('Fashion Street', 'B', 300),
        ('IT Zone', 'C', 500) 
    ]
    
    cat_map = {'Food Court': 'อาหาร', 'Fashion Street': 'เสื้อผ้า', 'IT Zone': 'ของใช้'}

    c.execute("DELETE FROM stalls")
    c.execute("DELETE FROM reviews")

    today_str = datetime.now().strftime('%Y-%m-%d')

    for zone_name, prefix, price in zones:
        for i in range(1, 13):
            stall_name = f"{prefix}{i:02d}"
            # สุ่มจอง 60%
            is_booked = random.choice([True, False, True, False, True]) 
            
            if is_booked:
                shop = random.choice(fake_shops)
                status = 'booked'
                booked_by = 2 # User ID 2
                payment_ref = f"SLIP-{random.randint(1000,9999)}"
                payment_status = 'paid'
                cat = cat_map[zone_name]
            else:
                shop = ''
                status = 'available'
                booked_by = None
                payment_ref = ''
                payment_status = 'pending'
                cat = ''

            c.execute(f"""INSERT INTO stalls 
                      (name, zone, price, status, shop_name, phone, product_category, booking_date, booked_by, payment_ref, payment_status) 
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                      (stall_name, zone_name, price, status, shop, '081-234-5678', cat, today_str, booked_by, payment_ref, payment_status))

    # Seed Reviews
    dummy_reviews = [
        ('ร้านป้าไก่', 5, 'อร่อยมากครับ', 'User01'),
        ('Gadget Store', 4, 'ของเยอะดี', 'User02'),
        ('เสื้อผ้าแฟชั่น', 5, 'แม่ค้าใจดี', 'User03')
    ]
    for r in dummy_reviews:
        c.execute("INSERT INTO reviews (shop_name, rating, comment, reviewer_name) VALUES (?, ?, ?, ?)", r)

    conn.commit()
    conn.close()
    print(">>> Setup Database Complete!")

if __name__ == '__main__':
    create_db()