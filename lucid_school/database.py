"""
database.py — Schema initialisation for Lucid School SaaS.
Works with both SQLite (local dev) and PostgreSQL (production).
All SQL is ANSI-compatible — no SQLite-specific syntax.
"""
import os, hashlib, random
from db_adapter import get_db, is_postgres

# ─── SQLite Schema ────────────────────────────────────────────────────────────
SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS platform_admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    short_name TEXT NOT NULL UNIQUE, address TEXT DEFAULT '', phone TEXT DEFAULT '',
    email TEXT DEFAULT '', motto TEXT DEFAULT 'Excellence in Education',
    logo_path TEXT DEFAULT '', primary_color TEXT DEFAULT '#1B4332',
    secondary_color TEXT DEFAULT '#D4A017', subscription_plan TEXT DEFAULT 'basic',
    subscription_status TEXT DEFAULT 'active', subscription_expires TEXT DEFAULT '',
    max_students INTEGER DEFAULT 500, current_term INTEGER DEFAULT 1,
    current_year TEXT DEFAULT '2025/2026', created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS subscription_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'basic', period_type TEXT NOT NULL DEFAULT 'termly',
    amount_paid REAL NOT NULL DEFAULT 0, payment_method TEXT NOT NULL DEFAULT 'momo_mtn',
    reference TEXT NOT NULL DEFAULT '', academic_year TEXT NOT NULL DEFAULT '',
    term INTEGER DEFAULT NULL, notes TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TEXT DEFAULT (datetime('now')), reviewed_at TEXT DEFAULT '',
    reviewed_by TEXT DEFAULT '', rejection_reason TEXT DEFAULT '', extends_to TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS access_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
    school_id INTEGER REFERENCES schools(id) ON DELETE SET NULL,
    plan TEXT NOT NULL DEFAULT 'basic', period_type TEXT NOT NULL DEFAULT 'termly',
    months INTEGER NOT NULL DEFAULT 4, used INTEGER DEFAULT 0, used_at TEXT DEFAULT '',
    created_by TEXT DEFAULT 'admin', created_at TEXT DEFAULT (datetime('now')), notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    username TEXT NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'teacher', full_name TEXT DEFAULT '', phone TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1, last_login TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')), UNIQUE(school_id, username)
);
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    name TEXT NOT NULL, level TEXT DEFAULT 'JHS', capacity INTEGER DEFAULT 40,
    class_teacher_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(school_id, name)
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    name TEXT NOT NULL, code TEXT NOT NULL, is_core INTEGER DEFAULT 1, UNIQUE(school_id, code)
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
    date_of_birth TEXT DEFAULT '', gender TEXT DEFAULT '', class_id INTEGER REFERENCES classes(id),
    photo_path TEXT DEFAULT '', parent_name TEXT DEFAULT '', parent_phone TEXT DEFAULT '',
    parent_email TEXT DEFAULT '', parent_whatsapp TEXT DEFAULT '', address TEXT DEFAULT '',
    fee_amount REAL DEFAULT 0, fee_paid REAL DEFAULT 0, is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')), UNIQUE(school_id, student_id)
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    class_score REAL DEFAULT 0, exam_score REAL DEFAULT 0,
    entered_by INTEGER REFERENCES users(id),
    UNIQUE(school_id, student_id, subject_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    days_present INTEGER DEFAULT 0, days_absent INTEGER DEFAULT 0, total_days INTEGER DEFAULT 0,
    UNIQUE(school_id, student_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS daily_register (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    date TEXT NOT NULL, term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'present', note TEXT DEFAULT '',
    marked_by INTEGER REFERENCES users(id), marked_at TEXT DEFAULT (datetime('now')),
    UNIQUE(school_id, class_id, student_id, date)
);
CREATE TABLE IF NOT EXISTS remarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL, conduct TEXT DEFAULT 'Good',
    class_teacher_remark TEXT DEFAULT '', head_teacher_remark TEXT DEFAULT '',
    interest TEXT DEFAULT '', next_term_begins TEXT DEFAULT '',
    UNIQUE(school_id, student_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL, fee_type TEXT DEFAULT 'School Fees',
    amount_due REAL DEFAULT 0, amount_paid REAL DEFAULT 0, payment_date TEXT DEFAULT '',
    payment_method TEXT DEFAULT '', notes TEXT DEFAULT '',
    recorded_by INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(school_id, student_id, fee_type, term, academic_year)
);
CREATE TABLE IF NOT EXISTS fee_structure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE, level TEXT DEFAULT '',
    term INTEGER NOT NULL DEFAULT 1, academic_year TEXT NOT NULL DEFAULT '2025/2026',
    item_name TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, is_mandatory INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS school_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'General', description TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0, expense_date TEXT NOT NULL DEFAULT (date('now')),
    term INTEGER NOT NULL DEFAULT 1, academic_year TEXT NOT NULL DEFAULT '2025/2026',
    receipt_ref TEXT DEFAULT '', recorded_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS timetable (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id), teacher_id INTEGER REFERENCES users(id),
    day_of_week TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS grading_scales (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER NOT NULL UNIQUE,
    grades_json TEXT NOT NULL, aggregate_subjects TEXT DEFAULT 'best6',
    agg_distinction INTEGER DEFAULT 12, agg_credit INTEGER DEFAULT 18,
    agg_pass INTEGER DEFAULT 24, class_score_max INTEGER DEFAULT 40,
    exam_score_max INTEGER DEFAULT 60, FOREIGN KEY(school_id) REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '',
    username TEXT NOT NULL, password_hash TEXT NOT NULL, relation TEXT DEFAULT 'Parent',
    is_active INTEGER DEFAULT 1, last_login TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')), UNIQUE(school_id, username)
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT DEFAULT '',
    role TEXT DEFAULT '', action TEXT NOT NULL, detail TEXT DEFAULT '', ip TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id),
    student_id INTEGER REFERENCES students(id), parent_email TEXT DEFAULT '',
    term INTEGER, academic_year TEXT DEFAULT '', channel TEXT DEFAULT 'email',
    status TEXT DEFAULT 'pending', sent_at TEXT DEFAULT (datetime('now')), error_message TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sms_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT, school_id INTEGER REFERENCES schools(id) UNIQUE,
    provider TEXT DEFAULT 'hubtel', api_key TEXT DEFAULT '', api_secret TEXT DEFAULT '',
    sender_id TEXT DEFAULT 'SCHOOL', is_active INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_register_date ON daily_register(school_id, class_id, date);
CREATE INDEX IF NOT EXISTS idx_activity_school ON activity_log(school_id, created_at);
"""

# ─── PostgreSQL Schema ────────────────────────────────────────────────────────
SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS platform_admins (
    id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS schools (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, short_name TEXT NOT NULL UNIQUE,
    address TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '',
    motto TEXT DEFAULT 'Excellence in Education', logo_path TEXT DEFAULT '',
    primary_color TEXT DEFAULT '#1B4332', secondary_color TEXT DEFAULT '#D4A017',
    subscription_plan TEXT DEFAULT 'basic', subscription_status TEXT DEFAULT 'active',
    subscription_expires TEXT DEFAULT '', max_students INTEGER DEFAULT 500,
    current_term INTEGER DEFAULT 1, current_year TEXT DEFAULT '2025/2026',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS subscription_payments (
    id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'basic', period_type TEXT NOT NULL DEFAULT 'termly',
    amount_paid REAL NOT NULL DEFAULT 0, payment_method TEXT NOT NULL DEFAULT 'momo_mtn',
    reference TEXT NOT NULL DEFAULT '', academic_year TEXT NOT NULL DEFAULT '',
    term INTEGER DEFAULT NULL, notes TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMPTZ DEFAULT NOW(), reviewed_at TEXT DEFAULT '',
    reviewed_by TEXT DEFAULT '', rejection_reason TEXT DEFAULT '', extends_to TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS access_codes (
    id SERIAL PRIMARY KEY, code TEXT NOT NULL UNIQUE,
    school_id INTEGER REFERENCES schools(id) ON DELETE SET NULL,
    plan TEXT NOT NULL DEFAULT 'basic', period_type TEXT NOT NULL DEFAULT 'termly',
    months INTEGER NOT NULL DEFAULT 4, used INTEGER DEFAULT 0, used_at TEXT DEFAULT '',
    created_by TEXT DEFAULT 'admin', created_at TIMESTAMPTZ DEFAULT NOW(), notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    username TEXT NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'teacher', full_name TEXT DEFAULT '', phone TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1, last_login TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(school_id, username)
);
CREATE TABLE IF NOT EXISTS classes (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    name TEXT NOT NULL, level TEXT DEFAULT 'JHS', capacity INTEGER DEFAULT 40,
    class_teacher_id INTEGER REFERENCES users(id), created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(school_id, name)
);
CREATE TABLE IF NOT EXISTS subjects (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    name TEXT NOT NULL, code TEXT NOT NULL, is_core INTEGER DEFAULT 1, UNIQUE(school_id, code)
);
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
    date_of_birth TEXT DEFAULT '', gender TEXT DEFAULT '', class_id INTEGER REFERENCES classes(id),
    photo_path TEXT DEFAULT '', parent_name TEXT DEFAULT '', parent_phone TEXT DEFAULT '',
    parent_email TEXT DEFAULT '', parent_whatsapp TEXT DEFAULT '', address TEXT DEFAULT '',
    fee_amount REAL DEFAULT 0, fee_paid REAL DEFAULT 0, is_active INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(school_id, student_id)
);
CREATE TABLE IF NOT EXISTS scores (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    class_score REAL DEFAULT 0, exam_score REAL DEFAULT 0,
    entered_by INTEGER REFERENCES users(id),
    UNIQUE(school_id, student_id, subject_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    days_present INTEGER DEFAULT 0, days_absent INTEGER DEFAULT 0, total_days INTEGER DEFAULT 0,
    UNIQUE(school_id, student_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS daily_register (
    id SERIAL PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    date TEXT NOT NULL, term INTEGER NOT NULL, academic_year TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'present', note TEXT DEFAULT '',
    marked_by INTEGER REFERENCES users(id), marked_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(school_id, class_id, student_id, date)
);
CREATE TABLE IF NOT EXISTS remarks (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL, conduct TEXT DEFAULT 'Good',
    class_teacher_remark TEXT DEFAULT '', head_teacher_remark TEXT DEFAULT '',
    interest TEXT DEFAULT '', next_term_begins TEXT DEFAULT '',
    UNIQUE(school_id, student_id, term, academic_year)
);
CREATE TABLE IF NOT EXISTS fees (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
    term INTEGER NOT NULL, academic_year TEXT NOT NULL, fee_type TEXT DEFAULT 'School Fees',
    amount_due REAL DEFAULT 0, amount_paid REAL DEFAULT 0, payment_date TEXT DEFAULT '',
    payment_method TEXT DEFAULT '', notes TEXT DEFAULT '',
    recorded_by INTEGER REFERENCES users(id), created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(school_id, student_id, fee_type, term, academic_year)
);
CREATE TABLE IF NOT EXISTS fee_structure (
    id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE, level TEXT DEFAULT '',
    term INTEGER NOT NULL DEFAULT 1, academic_year TEXT NOT NULL DEFAULT '2025/2026',
    item_name TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, is_mandatory INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS school_expenses (
    id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'General', description TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL DEFAULT 0, expense_date TEXT NOT NULL DEFAULT CURRENT_DATE,
    term INTEGER NOT NULL DEFAULT 1, academic_year TEXT NOT NULL DEFAULT '2025/2026',
    receipt_ref TEXT DEFAULT '', recorded_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS timetable (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id), teacher_id INTEGER REFERENCES users(id),
    day_of_week TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS grading_scales (
    id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL UNIQUE, grades_json TEXT NOT NULL,
    aggregate_subjects TEXT DEFAULT 'best6', agg_distinction INTEGER DEFAULT 12,
    agg_credit INTEGER DEFAULT 18, agg_pass INTEGER DEFAULT 24,
    class_score_max INTEGER DEFAULT 40, exam_score_max INTEGER DEFAULT 60,
    FOREIGN KEY(school_id) REFERENCES schools(id)
);
CREATE TABLE IF NOT EXISTS parents (
    id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '',
    username TEXT NOT NULL, password_hash TEXT NOT NULL, relation TEXT DEFAULT 'Parent',
    is_active INTEGER DEFAULT 1, last_login TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(school_id, username)
);
CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, username TEXT DEFAULT '',
    role TEXT DEFAULT '', action TEXT NOT NULL, detail TEXT DEFAULT '', ip TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS email_log (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id),
    student_id INTEGER REFERENCES students(id), parent_email TEXT DEFAULT '',
    term INTEGER, academic_year TEXT DEFAULT '', channel TEXT DEFAULT 'email',
    status TEXT DEFAULT 'pending', sent_at TIMESTAMPTZ DEFAULT NOW(), error_message TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sms_config (
    id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id) UNIQUE,
    provider TEXT DEFAULT 'hubtel', api_key TEXT DEFAULT '', api_secret TEXT DEFAULT '',
    sender_id TEXT DEFAULT 'SCHOOL', is_active INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_register_date ON daily_register(school_id, class_id, date);
CREATE INDEX IF NOT EXISTS idx_activity_school ON activity_log(school_id, created_at DESC);
"""

DEFAULT_SETTINGS = {
    'price_per_student_termly':'3','price_per_student_annual':'8',
    'min_charge_termly':'150','min_charge_annual':'400',
    'price_basic_termly':'150','price_standard_termly':'250','price_premium_termly':'400',
    'price_basic_annual':'400','price_standard_annual':'650','price_premium_annual':'1050',
    'limit_basic_students':'200','limit_standard_students':'500','limit_premium_students':'2000',
    'momo_mtn_number':'0542361753','momo_mtn_name':'Lucid IT Hub',
    'momo_vodafone_number':'','momo_vodafone_name':'','momo_at_number':'','momo_at_name':'',
    'bank_name':'GCB Bank Ghana','bank_account_name':'Lucid IT Hub Ltd',
    'bank_account_number':'1234567890','bank_branch':'Accra Main Branch','bank_swift':'GHCBGHAC',
    'grace_period_days':'7','support_whatsapp':'0542361753','support_email':'support@lucidithub.com',
}


def _insert_get_id(db, sql, params):
    """Execute INSERT and return new row ID for both SQLite and PostgreSQL."""
    if is_postgres():
        cur = db.execute(sql + ' RETURNING id', params)
        row = cur.fetchone()
        return row[0] if row else None
    cur = db.execute(sql, params)
    return cur._c.lastrowid


def init_db():
    db = get_db()
    schema = SCHEMA_POSTGRES if is_postgres() else SCHEMA_SQLITE
    db.executescript(schema)
    db.commit()

    # Seed platform admin
    row = db.execute("SELECT COUNT(*) FROM platform_admins").fetchone()
    if row[0] == 0:
        db.execute("INSERT OR IGNORE INTO platform_admins (username,email,password_hash) VALUES (?,?,?)",
                   ('superadmin','admin@lucidithub.com', hash_password('admin123')))

    # Seed settings
    for k, v in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO platform_settings (key,value) VALUES (?,?)", (k, v))

    # Seed demo school
    row = db.execute("SELECT COUNT(*) FROM schools").fetchone()
    if row[0] == 0:
        _seed_demo(db)

    db.commit()
    db.close()
    print("✅ Lucid School database initialised.")


def _seed_demo(db):
    school_id = _insert_get_id(db,
        """INSERT INTO schools (name,short_name,address,phone,email,motto,primary_color,
           secondary_color,subscription_plan,subscription_status,subscription_expires,
           current_term,current_year) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ('Lucid International School','LIS','P.O. Box 123, Accra, Ghana',
         '0542361753','info@lucidschool.edu.gh','Excellence in Education',
         '#1B4332','#D4A017','premium','active','2027-12-31',1,'2025/2026'))

    admin_id = _insert_get_id(db,
        "INSERT INTO users (school_id,username,email,password_hash,role,full_name) VALUES (?,?,?,?,?,?)",
        (school_id,'schooladmin','admin@lucidschool.edu.gh',hash_password('school123'),'school_admin','School Administrator'))

    _insert_get_id(db,
        "INSERT INTO users (school_id,username,email,password_hash,role,full_name) VALUES (?,?,?,?,?,?)",
        (school_id,'teacher1','teacher1@lucidschool.edu.gh',hash_password('teacher123'),'teacher','Mr. Kofi Mensah'))

    class_ids = []
    for cn, lvl, cap in [('Basic 7A','JHS',35),('Basic 7B','JHS',35),('Basic 8A','JHS',35),
                          ('Basic 8B','JHS',35),('Basic 9A','JHS',35),('Basic 9B','JHS',35)]:
        class_ids.append(_insert_get_id(db,
            "INSERT INTO classes (school_id,name,level,capacity,class_teacher_id) VALUES (?,?,?,?,?)",
            (school_id,cn,lvl,cap,admin_id)))

    subj_ids = []
    for sn, sc, ic in [('Mathematics','MATH',1),('English Language','ENG',1),
                        ('Integrated Science','SCI',1),('Social Studies','SOC',1),
                        ('Religious & Moral Education','RME',1),('Ghanaian Language (TWI)','TWI',1),
                        ('Creative Arts','CA',0),('Information Technology','IT',0),('Career Technology','CT',0)]:
        subj_ids.append(_insert_get_id(db,
            "INSERT INTO subjects (school_id,name,code,is_core) VALUES (?,?,?,?)",
            (school_id,sn,sc,ic)))

    basic9a = class_ids[4]
    students_data = [
        ('STU001','Adjei','Damoah Sebastian','2010-03-15','Male','Mr. Daniel Adjei','0244123456','daniel.adjei@gmail.com'),
        ('STU002','Amisare','Sarkodie Jake','2010-07-22','Male','Mrs. Grace Sarkodie','0244234567','grace.sarkodie@yahoo.com'),
        ('STU003','Appiah','Kyere Noble','2009-11-08','Male','Mr. Joseph Appiah','0244345678','joseph.appiah@gmail.com'),
        ('STU004','Jones','Tommy Smart','2010-01-30','Male','Mrs. Cecilia Jones','0244456789','cecilia.jones@hotmail.com'),
        ('STU005','Gbarah','Ivan Dziedzorm','2010-05-14','Male','Mr. Victor Gbarah','0244567890','victor.gbarah@gmail.com'),
        ('STU006','Adomako','Leanne Pokuaa','2010-09-25','Female','Mrs. Esi Adomako','0244678901','esi.adomako@gmail.com'),
        ('STU007','Adomako','Lillian Pokuaa','2010-09-25','Female','Mrs. Esi Adomako','0244678901','esi.adomako@gmail.com'),
        ('STU008','Asiedu','Nhyira Mary','2010-02-18','Female','Mr. Frank Asiedu','0244789012','frank.asiedu@gmail.com'),
        ('STU009','Fomwaa','Christabel','2010-06-03','Female','Mrs. Patience Fomwaa','0244890123','patience.fomwaa@yahoo.com'),
        ('STU010','Owusuaa','Lordina Siwas','2009-12-20','Female','Mr. Bright Owusu','0244901234','bright.owusu@gmail.com'),
        ('STU011','Mahama','Inaaya','2010-04-11','Female','Mr. Abdul Mahama','0245012345','abdul.mahama@gmail.com'),
        ('STU012','Precious','Yawson Amenueve','2010-08-07','Female','Mrs. Dora Yawson','0245123456','dora.yawson@hotmail.com'),
    ]
    stu_ids = []
    for sd in students_data:
        stu_ids.append(_insert_get_id(db,
            """INSERT INTO students (school_id,student_id,last_name,first_name,date_of_birth,
               gender,class_id,parent_name,parent_phone,parent_email,parent_whatsapp,
               fee_amount,fee_paid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (school_id,sd[0],sd[1],sd[2],sd[3],sd[4],basic9a,sd[5],sd[6],sd[7],sd[6],500.00,500.00)))

    scores_raw = {
        0:[69,79,83,87,88,67,54,73,67],1:[56,65,71,83,96,43,66,52,73],
        2:[84,79,71,89,92,79,75,47,73],3:[54,57,56,77,88,37,78,37,53],
        4:[58,55,76,72,85,47,74,42,75],5:[49,52,58,74,76,47,53,38,54],
        6:[57,58,73,77,80,51,61,33,63],7:[53,77,69,85,90,59,64,36,72],
        8:[61,63,71,86,85,68,56,56,40],9:[70,62,81,83,83,69,64,42,67],
        10:[58,60,59,83,82,63,70,43,60],11:[69,62,72,89,82,37,70,31,68],
    }
    conducts=['Excellent','Very Good','Good','Good','Very Good','Good','Very Good','Excellent','Good','Very Good','Good','Excellent']
    teacher_remarks=['A dedicated student who consistently performs above average.','Shows great potential. Needs to focus more on TWI.',
        'Excellent student. Maintains top position in most subjects.','Good student. Extra attention to Maths will yield better results.',
        'Outstanding performance. Shows leadership qualities.','Average performance. More effort needed in Computing.',
        'Good progress this term. Keep it up.','Hardworking student with excellent manners.',
        'Shows resilience despite challenges. Keep pushing.','Brilliant student. Science performance is commendable.',
        'Consistent performer. Can do better with more practice.','Very good student. Works hard and is well-mannered.']
    head_remarks=['Keep up the excellent work.','Promoted to next class with distinction.',
        'Outstanding. Maintain this standard.','Good effort. More dedication needed.',
        'Excellent work. A model student.','Satisfactory. More effort required.',
        'Good performance. Stay focused.','Excellent. You are a pride to this school.',
        'Good. Consistency is key.','Very good. Maintain this standard.',
        'Good. Strive for excellence.','Very good. Keep it up.']

    random.seed(42)
    for i, (stu_id, sc_list) in enumerate(zip(stu_ids, scores_raw.values())):
        for subj_id, total in zip(subj_ids, sc_list):
            cs=round(total*0.4,1); es=round(total*0.6,1)
            db.execute("INSERT OR IGNORE INTO scores (school_id,student_id,subject_id,term,academic_year,class_score,exam_score,entered_by) VALUES (?,?,?,?,?,?,?,?)",
                       (school_id,stu_id,subj_id,1,'2025/2026',cs,es,admin_id))
        absent=random.randint(0,5); present=66-absent
        db.execute("INSERT OR IGNORE INTO attendance (school_id,student_id,term,academic_year,days_present,days_absent,total_days) VALUES (?,?,?,?,?,?,?)",
                   (school_id,stu_id,1,'2025/2026',present,absent,66))
        db.execute("INSERT OR IGNORE INTO remarks (school_id,student_id,term,academic_year,conduct,class_teacher_remark,head_teacher_remark,interest,next_term_begins) VALUES (?,?,?,?,?,?,?,?,?)",
                   (school_id,stu_id,1,'2025/2026',conducts[i],teacher_remarks[i],head_remarks[i],'Academic','Monday, 14th April 2026'))
        db.execute("INSERT OR IGNORE INTO fees (school_id,student_id,term,academic_year,fee_type,amount_due,amount_paid) VALUES (?,?,?,?,?,?,?)",
                   (school_id,stu_id,1,'2025/2026','School Fees',500.00,500.00))

    days=['Monday','Tuesday','Wednesday','Thursday','Friday']
    times=[('07:30','08:15'),('08:15','09:00'),('09:00','09:45'),('10:00','10:45'),('10:45','11:30'),('11:30','12:15')]
    for di,day in enumerate(days):
        for ti,(st,et) in enumerate(times[:len(subj_ids)]):
            sidx=(di*len(times)+ti)%len(subj_ids)
            db.execute("INSERT OR IGNORE INTO timetable (school_id,class_id,subject_id,teacher_id,day_of_week,start_time,end_time) VALUES (?,?,?,?,?,?,?)",
                       (school_id,basic9a,subj_ids[sidx],admin_id,day,st,et))


def hash_password(pw):  return hashlib.sha256(pw.encode()).hexdigest()
def check_password(pw,h): return hashlib.sha256(pw.encode()).hexdigest() == h

if __name__ == '__main__':
    init_db()
