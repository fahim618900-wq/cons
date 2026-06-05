from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import json
from datetime import datetime, timedelta
import calendar
import os

app = Flask(__name__, static_folder='.')
DB_PATH = 'sss.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'admin'
    )''')
    
    # Students table
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        father TEXT,
        mobile TEXT,
        address TEXT,
        class TEXT,
        residential INTEGER DEFAULT 0,
        photo TEXT,
        father_nid TEXT,
        birth_reg TEXT,
        start_month TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT
    )''')
    
    # Class fees
    c.execute('''CREATE TABLE IF NOT EXISTS class_fees (
        class_name TEXT PRIMARY KEY,
        tuition_fee INTEGER DEFAULT 0,
        food_fee INTEGER DEFAULT 0
    )''')
    
    # Default fees
    default_fees = [
        ('প্লে', 700, 0), ('নার্সারি', 700, 0),
        ('১ম', 800, 0), ('২য়', 1000, 0), ('৩য়', 1000, 0),
        ('৪র্থ', 1200, 0), ('৫ম', 1200, 0), ('৬ষ্ঠ', 800, 0),
        ('হিফয', 1000, 3500)
    ]
    for class_name, tuition, food in default_fees:
        c.execute("INSERT OR IGNORE INTO class_fees (class_name, tuition_fee, food_fee) VALUES (?,?,?)", (class_name, tuition, food))
    
    # Payments table (with audit trail)
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_no TEXT UNIQUE,
        student_id TEXT,
        payment_month TEXT,
        tuition_paid INTEGER DEFAULT 0,
        food_paid INTEGER DEFAULT 0,
        other_paid INTEGER DEFAULT 0,
        discount_tuition INTEGER DEFAULT 0,
        discount_food INTEGER DEFAULT 0,
        discount_other INTEGER DEFAULT 0,
        total_paid INTEGER DEFAULT 0,
        total_discount INTEGER DEFAULT 0,
        net_due_after_payment INTEGER DEFAULT 0,
        received_by TEXT,
        created_at TEXT,
        voided INTEGER DEFAULT 0,
        void_reason TEXT,
        voided_at TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )''')
    
    # Expenses table
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        amount INTEGER,
        description TEXT,
        date TEXT
    )''')
    
    # Discount logs table (optional, for audit)
    c.execute('''CREATE TABLE IF NOT EXISTS discount_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER,
        student_id TEXT,
        amount INTEGER,
        reason TEXT,
        given_by TEXT,
        created_at TEXT
    )''')
    
    # Insert default admin
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)", ('admin', '123', 'admin'))
    
    conn.commit()
    conn.close()

def get_next_student_id():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM students WHERE status='active' ORDER BY id DESC LIMIT 1")
    last = c.fetchone()
    conn.close()
    if not last:
        return "2026001"
    last_num = int(last[0])
    return str(last_num + 1)

def get_next_receipt_no():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now()
    yymm = now.strftime('%Y%m')
    c.execute("SELECT receipt_no FROM payments WHERE receipt_no LIKE ? ORDER BY receipt_no DESC LIMIT 1", (f'RCP-{yymm}%',))
    last = c.fetchone()
    if not last:
        num = 1
    else:
        try:
            num = int(last[0].split('-')[-1]) + 1
        except:
            num = 1
    conn.close()
    return f"RCP-{yymm}-{num:04d}"

def calculate_monthly_fee(student_id, month_str):
    """মাসিক ফি (টিউশন + খাবার যদি আবাসিক হয়)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT class, residential FROM students WHERE id=?", (student_id,))
    row = c.fetchone()
    if not row:
        return 0
    cls, res = row
    c.execute("SELECT tuition_fee, food_fee FROM class_fees WHERE class_name=?", (cls,))
    fee_row = c.fetchone()
    tuition = fee_row[0] if fee_row else 0
    food = fee_row[1] if res else 0
    conn.close()
    return tuition + food

def get_student_due(student_id, target_month=None):
    """মোট বকেয়া (শুরু মাস থেকে target_month পর্যন্ত)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT start_month FROM students WHERE id=?", (student_id,))
    start = c.fetchone()
    if not start:
        return 0
    start_month = start[0]
    if not target_month:
        target_month = datetime.now().strftime('%Y-%m')
    
    total_due = 0
    current = datetime.strptime(start_month, '%Y-%m')
    end = datetime.strptime(target_month, '%Y-%m')
    
    while current <= end:
        ym = current.strftime('%Y-%m')
        monthly_fee = calculate_monthly_fee(student_id, ym)
        c.execute("SELECT SUM(total_paid) as paid, SUM(total_discount) as disc FROM payments WHERE student_id=? AND payment_month=? AND voided=0", (student_id, ym))
        row = c.fetchone()
        paid = row[0] if row[0] else 0
        disc = row[1] if row[1] else 0
        due = monthly_fee - disc - paid
        if due > 0:
            total_due += due
        # next month
        if current.month == 12:
            current = current.replace(year=current.year+1, month=1)
        else:
            current = current.replace(month=current.month+1)
    conn.close()
    return total_due

def get_last_payment_date(student_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT created_at FROM payments WHERE student_id=? AND voided=0 ORDER BY created_at DESC LIMIT 1", (student_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0]).strftime('%d %b %Y')
    return 'কখনও নয়'

# ---------- রুট ----------
@app.route('/')
def index():
    return send_from_directory('.', 'login.html')

@app.route('/<path:filename>')
def serve_file(filename):
    return send_from_directory('.', filename)

# ---------- AUTH ----------
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (data['username'], data['password']))
    user = c.fetchone()
    conn.close()
    if user:
        return jsonify({'status': 'ok', 'role': user[3]})
    return jsonify({'status': 'error'})

# ---------- STUDENTS ----------
@app.route('/api/students')
def get_students():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE status='active' ORDER BY id")
    students = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(students)

@app.route('/api/student/<id>')
def get_student(id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE id=?", (id,))
    student = dict(c.fetchone() or {})
    conn.close()
    return jsonify(student)

@app.route('/api/add_student', methods=['POST'])
def add_student():
    data = request.json
    new_id = get_next_student_id()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO students 
        (id, name, father, mobile, address, class, residential, father_nid, birth_reg, start_month, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (new_id, data['name'], data.get('father'), data.get('mobile'), data.get('address'),
         data['class'], 1 if data.get('residential') else 0, data.get('father_nid'), data.get('birth_reg'),
         data.get('start_month', datetime.now().strftime('%Y-%m')), 'active', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'id': new_id})

@app.route('/api/update_student/<id>', methods=['POST'])
def update_student(id):
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''UPDATE students SET name=?, father=?, mobile=?, address=?, class=?, residential=?, father_nid=?, birth_reg=?, start_month=? WHERE id=?''',
        (data['name'], data.get('father'), data.get('mobile'), data.get('address'),
         data['class'], 1 if data.get('residential') else 0, data.get('father_nid'), data.get('birth_reg'),
         data.get('start_month'), id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/delete_student/<id>', methods=['DELETE'])
def delete_student(id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE students SET status='inactive' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/class_shift', methods=['POST'])
def class_shift():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE students SET class=? WHERE id=?", (data['new_class'], data['student_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/inactive_students')
def inactive_students():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE status='inactive' ORDER BY id")
    students = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(students)

# ---------- CLASS FEES ----------
@app.route('/api/class_fees')
def get_class_fees():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM class_fees")
    fees = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(fees)

@app.route('/api/update_class_fees', methods=['POST'])
def update_class_fees():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for item in data:
        c.execute("UPDATE class_fees SET tuition_fee=?, food_fee=? WHERE class_name=?", (item['tuition_fee'], item['food_fee'], item['class_name']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# ---------- PAYMENTS ----------
@app.route('/api/add_payment', methods=['POST'])
def add_payment():
    data = request.json
    student_id = data['student_id']
    month = data['payment_month']
    tuition_paid = int(data.get('tuition_paid',0))
    food_paid = int(data.get('food_paid',0))
    other_paid = int(data.get('other_paid',0))
    disc_t = int(data.get('discount_tuition',0))
    disc_f = int(data.get('discount_food',0))
    disc_o = int(data.get('discount_other',0))
    
    total_paid = tuition_paid + food_paid + other_paid
    total_discount = disc_t + disc_f + disc_o
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE id=?", (student_id,))
    student = c.fetchone()
    if not student:
        return jsonify({'status': 'error', 'error': 'Student not found'})
    
    monthly_fee = calculate_monthly_fee(student_id, month)
    c.execute("SELECT SUM(total_paid) as paid, SUM(total_discount) as disc FROM payments WHERE student_id=? AND payment_month=? AND voided=0", (student_id, month))
    prev = c.fetchone()
    prev_paid = prev[0] if prev[0] else 0
    prev_disc = prev[1] if prev[1] else 0
    net_due = monthly_fee - (prev_disc + total_discount) - (prev_paid + total_paid)
    if net_due < 0: net_due = 0
    
    receipt_no = get_next_receipt_no()
    c.execute('''INSERT INTO payments 
        (receipt_no, student_id, payment_month, tuition_paid, food_paid, other_paid,
         discount_tuition, discount_food, discount_other, total_paid, total_discount,
         net_due_after_payment, received_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (receipt_no, student_id, month, tuition_paid, food_paid, other_paid,
         disc_t, disc_f, disc_o, total_paid, total_discount, net_due,
         data.get('received_by','admin'), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'receipt_no': receipt_no})

@app.route('/api/payments')
def get_payments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT p.*, s.name as student_name FROM payments p LEFT JOIN students s ON p.student_id=s.id WHERE p.voided=0 ORDER BY p.id DESC")
    payments = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(payments)

@app.route('/api/payment/<int:id>')
def get_payment(id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE id=? AND voided=0", (id,))
    payment = dict(c.fetchone() or {})
    conn.close()
    return jsonify(payment)

@app.route('/api/void_payment/<int:id>', methods=['POST'])
def void_payment(id):
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE payments SET voided=1, void_reason=?, voided_at=? WHERE id=?", (data.get('reason',''), datetime.now().isoformat(), id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/student_payments/<student_id>')
def student_payments(student_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM payments WHERE student_id=? AND voided=0 ORDER BY payment_month", (student_id,))
    payments = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(payments)

# ---------- STUDENT MONTHLY STATEMENT ----------
@app.route('/api/student_statement/<student_id>')
def student_statement(student_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT class, residential, start_month FROM students WHERE id=?", (student_id,))
    student = c.fetchone()
    if not student:
        return jsonify({'months': []})
    class_name, residential, start_month = student
    c.execute("SELECT tuition_fee, food_fee FROM class_fees WHERE class_name=?", (class_name,))
    fees = c.fetchone()
    tuition_fee = fees[0] if fees else 0
    food_fee = fees[1] if residential else 0
    total_fee = tuition_fee + food_fee
    
    c.execute("SELECT payment_month, SUM(total_paid) as paid, SUM(total_discount) as disc FROM payments WHERE student_id=? AND voided=0 GROUP BY payment_month", (student_id,))
    payments = c.fetchall()
    payment_dict = {}
    for p in payments:
        payment_dict[p[0]] = {'paid': p[1], 'disc': p[2]}
    
    start = datetime.strptime(start_month, '%Y-%m')
    now = datetime.now()
    months_data = []
    current = start
    while current <= now:
        ym = current.strftime('%Y-%m')
        month_name = current.strftime('%B %Y')
        p = payment_dict.get(ym, {'paid': 0, 'disc': 0})
        due = total_fee - p['disc'] - p['paid']
        if due < 0: due = 0
        
        months_data.append({
            'month': month_name,
            'tuition_fee': tuition_fee,
            'food_fee': food_fee,
            'total_fee': total_fee,
            'paid': p['paid'],
            'discount': p['disc'],
            'due': due
        })
        if current.month == 12:
            current = current.replace(year=current.year+1, month=1)
        else:
            current = current.replace(month=current.month+1)
    conn.close()
    return jsonify({'months': months_data})

# ---------- DASHBOARD STATS (সঠিক চলতি মাসের বকেয়া) ----------
@app.route('/api/dashboard_stats')
def dashboard_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # মোট আদায়
    c.execute("SELECT SUM(total_paid) FROM payments WHERE voided=0")
    total_collected = c.fetchone()[0] or 0
    
    # আজকের আদায়
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT SUM(total_paid) FROM payments WHERE voided=0 AND DATE(created_at)=?", (today,))
    today_collected = c.fetchone()[0] or 0
    
    # মোট ছাত্র (active)
    c.execute("SELECT COUNT(*) FROM students WHERE status='active'")
    total_students = c.fetchone()[0] or 0
    
    # চলতি মাসের নাম
    current_month = datetime.now().strftime('%Y-%m')
    
    # চলতি মাসের বকেয়া (শুধু এই মাসের ফি - ছাড় - জমা)
    current_month_due = 0
    c.execute("SELECT id FROM students WHERE status='active'")
    active_students = c.fetchall()
    
    for (sid,) in active_students:
        monthly_fee = calculate_monthly_fee(sid, current_month)
        c.execute("SELECT SUM(total_paid), SUM(total_discount) FROM payments WHERE student_id=? AND payment_month=? AND voided=0", (sid, current_month))
        paid, disc = c.fetchone()
        paid = paid or 0
        disc = disc or 0
        due = monthly_fee - disc - paid
        if due > 0:
            current_month_due += due
    
    # মোট বকেয়া (সব মাস) এবং বকেয়া ছাত্র তালিকা (মোট বকেয়ার ভিত্তিতে)
    total_due = 0
    due_students = []
    for (sid,) in active_students:
        total_due_student = get_student_due(sid, current_month)
        if total_due_student > 0:
            total_due += total_due_student
            c.execute("SELECT name, class FROM students WHERE id=?", (sid,))
            name, cls = c.fetchone()
            due_students.append({'id': sid, 'name': name, 'class': cls, 'due_amount': total_due_student})
    
    conn.close()
    return jsonify({
        'total_collected': total_collected,
        'today_collected': today_collected,
        'total_students': total_students,
        'total_due': total_due,
        'current_month_due': current_month_due,
        'current_month': current_month,
        'due_students': due_students
    })

# ---------- বকেয়া ছাত্র তালিকা API ----------
@app.route('/api/due_list')
def due_list():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    class_filter = request.args.get('class', '')
    residential_filter = request.args.get('residential', '')
    month_filter = request.args.get('month', datetime.now().strftime('%Y-%m'))
    
    query = "SELECT id, name, class, residential, mobile FROM students WHERE status='active'"
    params = []
    if class_filter and class_filter != 'সব':
        query += " AND class=?"
        params.append(class_filter)
    if residential_filter and residential_filter != 'সব':
        res_val = 1 if residential_filter == 'আবাসিক' else 0
        query += " AND residential=?"
        params.append(res_val)
    
    c.execute(query, params)
    students = c.fetchall()
    
    due_list = []
    for stu in students:
        sid, name, cls, residential, mobile = stu
        monthly_fee = calculate_monthly_fee(sid, month_filter)
        c.execute("SELECT SUM(total_paid), SUM(total_discount) FROM payments WHERE student_id=? AND payment_month=? AND voided=0", (sid, month_filter))
        paid, disc = c.fetchone()
        paid = paid or 0
        disc = disc or 0
        current_month_due = monthly_fee - disc - paid
        if current_month_due < 0: current_month_due = 0
        
        total_due = get_student_due(sid, month_filter)
        last_payment = get_last_payment_date(sid)
        
        if current_month_due > 0 or total_due > 0:
            due_list.append({
                'id': sid,
                'name': name,
                'class': cls,
                'mobile': mobile,
                'current_month_due': current_month_due,
                'total_due': total_due,
                'last_payment': last_payment
            })
    
    due_list.sort(key=lambda x: x['total_due'], reverse=True)
    conn.close()
    return jsonify(due_list)

# ---------- EXPENSES ----------
@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM expenses ORDER BY date DESC")
    expenses = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(expenses)

@app.route('/api/add_expense', methods=['POST'])
def add_expense():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO expenses (category, amount, description, date) VALUES (?,?,?,?)",
              (data['category'], data['amount'], data.get('description',''), data.get('date', datetime.now().strftime('%Y-%m-%d'))))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/delete_expense/<int:id>', methods=['DELETE'])
def delete_expense(id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# ---------- INCOME REPORT ----------
@app.route('/api/income_report', methods=['POST'])
def income_report():
    data = request.json
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if start_date and end_date:
        c.execute("SELECT SUM(total_paid) FROM payments WHERE voided=0 AND DATE(created_at) BETWEEN ? AND ?", (start_date, end_date))
        total_income = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM expenses WHERE date BETWEEN ? AND ?", (start_date, end_date))
        total_expense = c.fetchone()[0] or 0
    else:
        c.execute("SELECT SUM(total_paid) FROM payments WHERE voided=0")
        total_income = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM expenses")
        total_expense = c.fetchone()[0] or 0
    conn.close()
    return jsonify({'income': total_income, 'expense': total_expense, 'profit': total_income - total_expense})

# ---------- RECEIPT HTML ----------
@app.route('/api/receipt/<int:payment_id>')
def receipt(payment_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT p.*, s.name as student_name, s.class, s.father 
                 FROM payments p JOIN students s ON p.student_id=s.id 
                 WHERE p.id=? AND p.voided=0''', (payment_id,))
    p = c.fetchone()
    if not p:
        return "<h3>রসিদ পাওয়া যায়নি বা ভয়েড করা হয়েছে</h3>"
    
    # Column indices (order matters, but safe to reference by index)
    receipt_no = p[1]
    student_name = p[19] if len(p) > 19 else ''
    student_class = p[20] if len(p) > 20 else ''
    father = p[21] if len(p) > 21 else ''
    month = p[3]
    tuition_paid = p[4]
    food_paid = p[5]
    other_paid = p[6]
    disc_t = p[7]
    disc_f = p[8]
    disc_o = p[9]
    total_paid = p[10]
    total_discount = p[11]
    net_due = p[12]
    received_by = p[13]
    created_at = datetime.fromisoformat(p[14]).strftime('%d %b %Y, %I:%M %p')
    
    monthly_fee = calculate_monthly_fee(p[2], month)
    
    html = f'''<!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>পেমেন্ট রসিদ</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f1f5f9; }}
        .receipt {{ max-width: 500px; margin: auto; background: white; border-radius: 16px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; border-bottom: 2px solid #0f172a; padding-bottom: 12px; margin-bottom: 20px; }}
        .header h2 {{ margin: 0; color: #1e293b; }}
        .row {{ display: flex; justify-content: space-between; margin: 8px 0; }}
        .total {{ font-weight: bold; font-size: 1.1em; border-top: 1px dashed #ccc; margin-top: 12px; padding-top: 8px; }}
        .due {{ color: #dc2626; font-weight: bold; }}
        .footer {{ text-align: center; margin-top: 24px; font-size: 12px; color: #64748b; }}
        @media print {{ body {{ background: white; padding: 0; }} .receipt {{ box-shadow: none; padding: 0; }} .no-print {{ display: none; }} }}
    </style>
    </head>
    <body>
    <div class="receipt">
        <div class="header"><h2>মাদরাসা অ্যাকাউন্টিং সিস্টেম</h2><p>পেমেন্ট রসিদ</p></div>
        <div class="row"><span>রসিদ নং:</span><span><strong>{receipt_no}</strong></span></div>
        <div class="row"><span>তারিখ ও সময়:</span><span>{created_at}</span></div>
        <div class="row"><span>ছাত্রের নাম:</span><span>{student_name}</span></div>
        <div class="row"><span>পিতার নাম:</span><span>{father}</span></div>
        <div class="row"><span>শ্রেণি:</span><span>{student_class}</span></div>
        <div class="row"><span>মাস:</span><span>{month}</span></div>
        <hr>
        <div class="row"><span>মাসিক ফি:</span><span>{monthly_fee} ৳</span></div>
        <div class="row"><span>ছাড় (টিউশন/খাবার/অন্যান্য):</span><span>{total_discount} ৳</span></div>
        <div class="row"><span>এখন জমা দিলেন:</span><span>{total_paid} ৳</span></div>
        <div class="total row"><span>এই মাস শেষে বকেয়া:</span><span class="due">{net_due} ৳</span></div>
        <hr>
        <div class="row"><span>প্রাপক:</span><span>{received_by}</span></div>
        <div class="footer">ধন্যবাদ। সঠিক হিসাব রাখতে এই রসিদ সংরক্ষণ করুন।</div>
    </div>
    <div style="text-align:center; margin-top:16px;" class="no-print">
        <button onclick="window.print()">প্রিন্ট করুন</button>
        <button onclick="window.close()">বন্ধ করুন</button>
    </div>
    </body>
    </html>'''
    return html

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)