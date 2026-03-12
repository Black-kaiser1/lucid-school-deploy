"""
Lucid IT Hub — SaaS School Management System
Multi-tenant Flask application.
Roles: platform_admin → school_admin → teacher
"""
import os, json, threading, functools, csv, io
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_file, session, abort, Response)
from werkzeug.utils import secure_filename
from db_adapter import get_db          # ← NEW: dual SQLite/PostgreSQL adapter
from database import init_db, hash_password, check_password
from grading import waec_grade, compute_aggregate, aggregate_remark, ordinal, scale_from_db_row, DEFAULT_SCALE
from pdf_generator import generate_report_card
from broadsheet_generator import generate_broadsheet
from email_sender import bulk_send, sms_message

app = Flask(__name__)

# ── Secret key: use environment variable in production ────────────────────────
app.secret_key = os.environ.get('SECRET_KEY', 'lucid-saas-school-dev-xK9mP-change-in-prod')

# ── Paths — use /tmp on platforms that don't allow writing to app dir ─────────
BASE     = os.path.dirname(os.path.abspath(__file__))

# On Render free tier, use /tmp for writable files
# On paid/VPS, files stay in the app directory
_writable = os.environ.get('RENDER') or os.environ.get('RAILWAY_ENVIRONMENT')
if _writable:
    REPORTS = '/tmp/lucid_reports'
    UPLOADS = '/tmp/lucid_uploads'
else:
    REPORTS = os.path.join(BASE, 'reports')
    UPLOADS = os.path.join(BASE, 'uploads')

LOGOS  = os.path.join(UPLOADS, 'logos')
PHOTOS = os.path.join(UPLOADS, 'photos')
for d in [REPORTS, UPLOADS, LOGOS, PHOTOS]:
    os.makedirs(d, exist_ok=True)

ALLOWED = {'png','jpg','jpeg','gif','webp'}
def allowed_file(fn): return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED

# ── In-memory email progress ──────────────────────────────────────────────────
email_jobs = {}  # keyed by school_id

# ── Auth helpers ──────────────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def decorated(*args,**kwargs):
        if not session.get('user_id') and not session.get('platform_admin'):
            return redirect(url_for('login'))
        # Subscription gate — expired schools see paywall (admins can still pay)
        if session.get('user_id') and not session.get('platform_admin'):
            # Only block non-subscription routes for school users
            exempt = {'subscription_page','submit_payment','logout','login',
                      'change_password','uploaded_file'}
            if request.endpoint not in exempt:
                school = get_school_by_id(session.get('school_id'))
                days_left, is_active = subscription_days_left(school)
                if not is_active and school.get('subscription_status') != 'active':
                    if school.get('subscription_expires',''):  # only gate if expiry was set
                        return redirect(url_for('subscription_page'))
        return f(*args,**kwargs)
    return decorated

def platform_admin_required(f):
    @functools.wraps(f)
    def decorated(*args,**kwargs):
        if not session.get('platform_admin'):
            flash('Platform admin access required.','error')
            return redirect(url_for('login'))
        return f(*args,**kwargs)
    return decorated

def school_admin_required(f):
    @functools.wraps(f)
    def decorated(*args,**kwargs):
        if not session.get('user_id') and not session.get('platform_admin'):
            return redirect(url_for('login'))
        if session.get('platform_admin'): return f(*args,**kwargs)
        if session.get('role') not in ('school_admin',):
            flash('School admin access required.','error')
            return redirect(url_for('school_dashboard'))
        return f(*args,**kwargs)
    return decorated

def teacher_required(f):
    """Allows teacher OR school_admin. Blocks everyone else."""
    @functools.wraps(f)
    def decorated(*args,**kwargs):
        if not session.get('user_id') and not session.get('platform_admin'):
            return redirect(url_for('login'))
        if session.get('platform_admin'): return f(*args,**kwargs)
        if session.get('role') not in ('school_admin','teacher'):
            flash('Access restricted.','error')
            return redirect(url_for('school_dashboard'))
        return f(*args,**kwargs)
    return decorated

def get_teacher_classes(user_id=None, school_id=None):
    """Return list of class IDs assigned to this teacher (as class_teacher_id).
    Returns None if user is school_admin/platform_admin (means: no restriction)."""
    if session.get('platform_admin'): return None
    if session.get('role') == 'school_admin': return None
    uid  = user_id  or session.get('user_id')
    sid  = school_id or session.get('school_id')
    if not uid or not sid: return []
    db = get_db()
    rows = db.execute(
        "SELECT id FROM classes WHERE school_id=? AND class_teacher_id=?", (sid, uid)
    ).fetchall()
    db.close()
    return [r['id'] for r in rows]

def is_teacher():
    return session.get('role') == 'teacher'

def log_activity(action, detail='', school_id=None):
    """Write to activity_log. Called from any route."""
    try:
        sid = school_id or session.get('school_id')
        db = get_db()
        db.execute("""
            INSERT INTO activity_log
                (school_id,user_id,username,role,action,detail,ip)
            VALUES (?,?,?,?,?,?,?)
        """, (sid, session.get('user_id'), session.get('username','?'),
              session.get('role','platform_admin') if not session.get('platform_admin') else 'platform_admin',
              action, detail[:500],
              request.remote_addr or ''))
        db.commit(); db.close()
    except Exception:
        pass  # never crash on logging

def parent_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('parent_id'):
            return redirect(url_for('parent_login'))
        return f(*args, **kwargs)
    return decorated


def get_school(): return get_school_by_id(session.get('school_id'))
def get_school_by_id(sid):
    db=get_db(); r=db.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    db.close(); return dict(r) if r else {}

def get_platform_settings():
    """Load all platform_settings into a plain dict."""
    db = get_db()
    rows = db.execute("SELECT key,value FROM platform_settings").fetchall()
    db.close()
    return {r['key']: r['value'] for r in rows}

def subscription_days_left(school):
    """Return (days_left, is_active). Negative = expired."""
    from datetime import datetime
    exp = school.get('subscription_expires','') or ''
    if not exp: return 9999, True   # no expiry = always active (legacy/manual)
    try:
        exp_dt = datetime.strptime(exp[:10], '%Y-%m-%d')
        delta  = (exp_dt - datetime.now()).days
        return delta, delta >= 0
    except Exception:
        return 9999, True

def get_grading_scale(school_id=None):
    """Load the grading scale for a school, falling back to WAEC defaults.
    Safe even when grading_scales table does not exist yet (old DB)."""
    sid = school_id or session.get('school_id')
    if not sid:
        return None
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM grading_scales WHERE school_id=?", (sid,)
        ).fetchone()
        db.close()
        return scale_from_db_row(dict(row)) if row else None
    except Exception:
        # Table doesn't exist yet on older DB — return None so WAEC defaults are used
        try: db.close()
        except: pass
        return None

def get_scores_for_student(school_id, student_id, term, year):
    db=get_db()
    rows=db.execute("""
        SELECT s.id as subject_id, s.name as subject_name, s.code,
               COALESCE(sc.class_score,0) as class_score,
               COALESCE(sc.exam_score,0) as exam_score,
               COALESCE(ROUND(sc.class_score+sc.exam_score,1),0) as total
        FROM subjects s
        LEFT JOIN scores sc ON sc.subject_id=s.id
            AND sc.student_id=? AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
        WHERE s.school_id=?
        ORDER BY s.is_core DESC, s.id
    """,(student_id,term,year,school_id,school_id)).fetchall()
    db.close(); return [dict(r) for r in rows]

def get_class_totals(school_id, class_id, term, year):
    db=get_db()
    rows=db.execute("""
        SELECT st.id, COALESCE(SUM(ROUND(sc.class_score+sc.exam_score,1)),0) as grand_total
        FROM students st
        LEFT JOIN scores sc ON sc.student_id=st.id
            AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
        WHERE st.class_id=? AND st.school_id=?
        GROUP BY st.id
    """,(term,year,school_id,class_id,school_id)).fetchall()
    db.close(); return {r['id']:r['grand_total'] for r in rows}

def generate_student_id(school_id):
    """Auto-generate next student ID: e.g. LIS-0013"""
    import re
    db = get_db()
    school = db.execute("SELECT short_name FROM schools WHERE id=?", (school_id,)).fetchone()
    prefix = (school['short_name'][:3] if school else 'STU').upper()
    last = db.execute(
        "SELECT student_id FROM students WHERE school_id=? ORDER BY id DESC LIMIT 1",
        (school_id,)
    ).fetchone()
    if last:
        nums = re.findall(r'\d+', last['student_id'])
        next_num = int(nums[-1]) + 1 if nums else 1
    else:
        next_num = 1
    db.close()
    return f"{prefix}-{next_num:04d}"

def build_report_pdf(school_id, student_id_int, term, year):
    """Generate PDF for one student, return path."""
    db=get_db()
    student=db.execute("""
        SELECT st.*,cl.name as class_name,cl.class_teacher_id,
               u.full_name as class_teacher_name
        FROM students st
        LEFT JOIN classes cl ON cl.id=st.class_id
        LEFT JOIN users u ON u.id=cl.class_teacher_id
        WHERE st.id=? AND st.school_id=?
    """,(student_id_int,school_id)).fetchone()
    if not student: db.close(); return None

    scores_data=get_scores_for_student(school_id,student_id_int,term,year)
    attendance=db.execute("SELECT * FROM attendance WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
                           (student_id_int,term,year,school_id)).fetchone()
    remarks=db.execute("SELECT * FROM remarks WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
                        (student_id_int,term,year,school_id)).fetchone()
    school=get_school_by_id(school_id)
    class_totals=get_class_totals(school_id,student['class_id'],term,year)
    all_totals=list(class_totals.values())
    my_total=sum(s['total'] for s in scores_data)
    sorted_t=sorted([t for t in all_totals if t],reverse=True)
    position=sorted_t.index(my_total)+1 if my_total in sorted_t else len(sorted_t)
    db.close()

    # Build photo path
    photo_path=''
    if student['photo_path']:
        photo_path=os.path.join(PHOTOS,student['photo_path'])

    pdf_name=f"RC_{school_id}_{student['student_id']}_T{term}_{year.replace('/','_')}.pdf"
    pdf_path=os.path.join(REPORTS,pdf_name)

    # Resolve logo to full path for PDF generator
    school_for_pdf = dict(school)
    if school_for_pdf.get('logo_path') and not os.path.isabs(school_for_pdf['logo_path']):
        school_for_pdf['logo_path'] = os.path.join(LOGOS, school_for_pdf['logo_path'])
    # Pass student dict with full photo path already set above
    student_for_pdf = dict(student)
    student_for_pdf['photo_path'] = photo_path

    scale = get_grading_scale(school_id)
    generate_report_card(
        student=student_for_pdf,
        scores_data=scores_data,
        attendance=dict(attendance) if attendance else {},
        remarks=dict(remarks) if remarks else {},
        school=school_for_pdf,
        class_position_data={'position':position,'total_students':len(all_totals)},
        output_path=pdf_path,
        scale=scale
    )
    return pdf_path, my_total, position, compute_aggregate([s['total'] for s in scores_data], scale=scale)

# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if session.get('platform_admin'): return redirect(url_for('platform_dashboard'))
    if session.get('user_id'):        return redirect(url_for('school_dashboard'))
    return redirect(url_for('login'))

@app.route('/health')
def health_check():
    """Health check endpoint — used by uptime monitors to keep app awake."""
    return jsonify({'status': 'ok', 'app': 'Lucid School', 'version': '5.0'}), 200

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        db=get_db()
        # Check platform admin
        pa=db.execute("SELECT * FROM platform_admins WHERE username=?",(username,)).fetchone()
        if pa and check_password(password,pa['password_hash']):
            session.clear()
            session['platform_admin']=True; session['username']=username
            db.close(); return redirect(url_for('platform_dashboard'))
        # Check school user
        u=db.execute("SELECT * FROM users WHERE username=? AND is_active=1",(username,)).fetchone()
        if u and check_password(password,u['password_hash']):
            db.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",(u['id'],))
            db.commit()
            session.clear()
            session['user_id']=u['id']; session['school_id']=u['school_id']
            session['role']=u['role']; session['username']=username
            session['full_name']=u['full_name']
            # Store teacher's assigned class IDs for portal filtering
            if u['role'] == 'teacher':
                tc = db.execute(
                    "SELECT id FROM classes WHERE school_id=? AND class_teacher_id=?",
                    (u['school_id'], u['id'])
                ).fetchall()
                session['assigned_class_ids'] = [r['id'] for r in tc]
            else:
                session['assigned_class_ids'] = None  # None = no restriction
            db.close(); return redirect(url_for('school_dashboard'))
        db.close()
        flash('Invalid username or password.','error')
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

# ── PLATFORM ADMIN ROUTES ─────────────────────────────────────────────────────
@app.route('/platform')
@platform_admin_required
def platform_dashboard():
    db=get_db()
    schools=[dict(r) for r in db.execute("SELECT * FROM schools ORDER BY created_at DESC").fetchall()]
    stats={
        'total_schools':db.execute("SELECT COUNT(*) FROM schools").fetchone()[0],
        'active_schools':db.execute("SELECT COUNT(*) FROM schools WHERE subscription_status='active'").fetchone()[0],
        'total_students':db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        'total_reports':db.execute("SELECT COUNT(*) FROM email_log WHERE status='sent'").fetchone()[0],
    }
    db.close()
    return render_template('admin/platform_dashboard.html', schools=schools, stats=stats)

@app.route('/platform/schools/add', methods=['GET','POST'])
@platform_admin_required
def add_school():
    if request.method=='POST':
        f=request.form
        db=get_db()
        try:
            db.execute("""INSERT INTO schools
                (name,short_name,address,phone,email,motto,
                 primary_color,secondary_color,subscription_plan,
                 subscription_status,max_students,current_term,current_year)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f['name'],f['short_name'],f.get('address',''),
                 f.get('phone',''),f.get('email',''),f.get('motto','Excellence'),
                 f.get('primary_color','#1B4332'),f.get('secondary_color','#D4A017'),
                 f.get('plan','basic'),f.get('status','active'),
                 int(f.get('max_students',200)),
                 int(f.get('current_term',1)),f.get('current_year','2025/2026')))
            school_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Create school admin
            ph=hash_password(f.get('admin_password','school123'))
            db.execute("""INSERT INTO users (school_id,username,email,password_hash,role,full_name)
                VALUES (?,?,?,?,?,?)""",
                (school_id,f['admin_username'],f.get('admin_email',''),
                 ph,'school_admin',f.get('admin_name','Administrator')))
            # Seed default subjects
            for sn,sc,ic in [('Mathematics','MATH',1),('English Language','ENG',1),
                              ('Integrated Science','SCI',1),('Social Studies','SOC',1),
                              ('RME','RME',1),('Ghanaian Language','TWI',1),
                              ('Creative Arts','CA',0),('IT','IT',0),('C.Tech','CT',0)]:
                db.execute("INSERT OR IGNORE INTO subjects (school_id,name,code,is_core) VALUES (?,?,?,?)",
                           (school_id,sn,sc,ic))
            db.commit()
            flash(f'✅ School "{f["name"]}" created successfully!','success')
            return redirect(url_for('platform_dashboard'))
        except Exception as e:
            flash(f'❌ Error: {str(e)}','error')
        db.close()
    return render_template('admin/add_school.html')

@app.route('/platform/schools/<int:sid>/toggle', methods=['POST'])
@platform_admin_required
def toggle_school(sid):
    db=get_db()
    s=db.execute("SELECT subscription_status FROM schools WHERE id=?",(sid,)).fetchone()
    new_status='suspended' if s['subscription_status']=='active' else 'active'
    db.execute("UPDATE schools SET subscription_status=? WHERE id=?",(new_status,sid))
    db.commit(); db.close()
    flash(f'School {"activated" if new_status=="active" else "suspended"}.','success')
    return redirect(url_for('platform_dashboard'))

@app.route('/platform/impersonate/<int:sid>')
@platform_admin_required
def impersonate(sid):
    db=get_db()
    school=db.execute("SELECT * FROM schools WHERE id=?",(sid,)).fetchone()
    admin=db.execute("SELECT * FROM users WHERE school_id=? AND role='school_admin' LIMIT 1",(sid,)).fetchone()
    db.close()
    if not school or not admin:
        flash('School or admin not found.','error')
        return redirect(url_for('platform_dashboard'))
    session['user_id']=admin['id']; session['school_id']=sid
    session['role']='school_admin'; session['username']=admin['username']
    session['full_name']=admin['full_name']; session['impersonating']=True
    return redirect(url_for('school_dashboard'))

# ── SCHOOL ROUTES ─────────────────────────────────────────────────────────────
@app.route('/school')
@login_required
def school_dashboard():
    school=get_school(); school_id=session['school_id']
    db=get_db()
    tc = get_teacher_classes()  # None=admin, [ids]=teacher

    # ── Teacher-scoped dashboard ──────────────────────────────────────────────
    if tc is not None:
        my_classes = tc or []
        cl_filter  = f"AND st.class_id IN ({','.join('?'*len(my_classes))})" if my_classes else "AND 1=0"
        student_count = db.execute(
            f"SELECT COUNT(*) FROM students WHERE school_id=? AND is_active=1 {cl_filter}",
            [school_id]+my_classes
        ).fetchone()[0] if my_classes else 0
        stats = {
            'students': student_count,
            'classes':  len(my_classes),
            'subjects': db.execute("SELECT COUNT(*) FROM subjects WHERE school_id=?",(school_id,)).fetchone()[0],
            'emails':   0,
            'fees_due': 0,
        }
        classes=db.execute(
            "SELECT cl.*,COUNT(st.id) as student_count FROM classes cl "
            "LEFT JOIN students st ON st.class_id=cl.id AND st.is_active=1 "
            "WHERE cl.school_id=? AND cl.class_teacher_id=? GROUP BY cl.id ORDER BY cl.name",
            (school_id, session['user_id'])
        ).fetchall()
        top_students = db.execute(f"""
            SELECT st.first_name||' '||st.last_name as name, cl.name as class_name,
                   SUM(ROUND(sc.class_score+sc.exam_score,1)) as grand_total
            FROM students st
            JOIN scores sc ON sc.student_id=st.id AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
            LEFT JOIN classes cl ON cl.id=st.class_id
            WHERE st.school_id=? AND st.is_active=1 {cl_filter}
            GROUP BY st.id ORDER BY grand_total DESC LIMIT 5
        """, [school['current_term'],school['current_year'],school_id,school_id]+my_classes).fetchall() if my_classes else []
        subj_avgs = db.execute(f"""
            SELECT s.name, s.code, AVG(ROUND(sc.class_score+sc.exam_score,1)) as avg_score
            FROM subjects s JOIN scores sc ON sc.subject_id=s.id
            JOIN students st ON st.id=sc.student_id
            WHERE s.school_id=? AND sc.term=? AND sc.academic_year=? {cl_filter}
            GROUP BY s.id ORDER BY avg_score DESC
        """, [school_id,school['current_term'],school['current_year']]+my_classes).fetchall() if my_classes else []
        db.close()
        return render_template('school/dashboard.html', school=school, stats=stats,
                               classes=classes, top_students=top_students,
                               subj_avgs=subj_avgs, recent_emails=[],
                               is_teacher=True, teacher_classes=my_classes)

    # ── Admin dashboard (unchanged) ───────────────────────────────────────────
    stats={
        'students':db.execute("SELECT COUNT(*) FROM students WHERE school_id=? AND is_active=1",(school_id,)).fetchone()[0],
        'classes':db.execute("SELECT COUNT(*) FROM classes WHERE school_id=?",(school_id,)).fetchone()[0],
        'subjects':db.execute("SELECT COUNT(*) FROM subjects WHERE school_id=?",(school_id,)).fetchone()[0],
        'emails':db.execute("SELECT COUNT(*) FROM email_log WHERE school_id=? AND status='sent'",(school_id,)).fetchone()[0],
        'fees_due':db.execute("SELECT COALESCE(SUM(amount_due-amount_paid),0) FROM fees WHERE school_id=? AND term=?",(school_id,school['current_term'])).fetchone()[0],
    }
    classes=db.execute("SELECT cl.*,COUNT(st.id) as student_count FROM classes cl LEFT JOIN students st ON st.class_id=cl.id AND st.is_active=1 WHERE cl.school_id=? GROUP BY cl.id ORDER BY cl.name",(school_id,)).fetchall()
    top_students=db.execute("""
        SELECT st.first_name||' '||st.last_name as name, cl.name as class_name,
               SUM(ROUND(sc.class_score+sc.exam_score,1)) as grand_total
        FROM students st
        JOIN scores sc ON sc.student_id=st.id AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
        LEFT JOIN classes cl ON cl.id=st.class_id
        WHERE st.school_id=? AND st.is_active=1
        GROUP BY st.id ORDER BY grand_total DESC LIMIT 5
    """,(school['current_term'],school['current_year'],school_id,school_id)).fetchall()
    subj_avgs=db.execute("""
        SELECT s.name, s.code, AVG(ROUND(sc.class_score+sc.exam_score,1)) as avg_score
        FROM subjects s JOIN scores sc ON sc.subject_id=s.id
        WHERE s.school_id=? AND sc.term=? AND sc.academic_year=?
        GROUP BY s.id ORDER BY avg_score DESC
    """,(school_id,school['current_term'],school['current_year'])).fetchall()
    recent_emails=db.execute("""SELECT el.*,st.first_name||' '||st.last_name as student_name
        FROM email_log el LEFT JOIN students st ON st.id=el.student_id
        WHERE el.school_id=? ORDER BY el.sent_at DESC LIMIT 8""",(school_id,)).fetchall()
    db.close()
    return render_template('school/dashboard.html', school=school, stats=stats,
                           classes=classes, top_students=top_students,
                           subj_avgs=subj_avgs, recent_emails=recent_emails,
                           is_teacher=False, teacher_classes=None)

# ── Students ──────────────────────────────────────────────────────────────────
@app.route('/school/students')
@login_required
def students():
    school_id=session['school_id']; school=get_school()
    db=get_db()
    cf=request.args.get('class_id',''); search=request.args.get('q','')
    show_inactive=request.args.get('show_inactive')=='1'
    tc = get_teacher_classes()
    # Teacher: restrict to their class, auto-select, read-only mode
    if tc is not None:
        if tc:
            classes=db.execute(
                f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc))}) ORDER BY name",
                [school_id]+tc
            ).fetchall()
        else:
            classes=[]
        if cf and int(cf) not in (tc or []):
            cf = str(tc[0]) if tc else ''
        if not cf and tc:
            cf = str(tc[0])
    else:
        classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    active_filter="" if show_inactive else " AND st.is_active=1"
    q="SELECT st.*,cl.name as class_name FROM students st LEFT JOIN classes cl ON cl.id=st.class_id WHERE st.school_id=?"+active_filter
    params=[school_id]
    if cf: q+=" AND st.class_id=?"; params.append(cf)
    elif tc is not None and tc:
        q+=f" AND st.class_id IN ({','.join('?'*len(tc))})"; params+=tc
    elif tc is not None and not tc:
        q+=" AND 1=0"  # no classes assigned — see nothing
    if search: q+=" AND (st.first_name LIKE ? OR st.last_name LIKE ? OR st.student_id LIKE ?)"; params+=[f'%{search}%']*3
    q+=" ORDER BY cl.name,st.last_name"
    students=[dict(r) for r in db.execute(q,params).fetchall()]
    db.close()
    return render_template('school/students.html', students=students,
                           classes=classes, school=school,
                           class_filter=cf, search=search, show_inactive=show_inactive,
                           is_teacher=(tc is not None))

@app.route('/school/students/<int:sid>/reactivate', methods=['POST'])
@school_admin_required
@login_required
def reactivate_student(sid):
    db=get_db()
    db.execute("UPDATE students SET is_active=1 WHERE id=? AND school_id=?",(sid,session['school_id']))
    db.commit(); db.close()
    flash('✅ Student reactivated.','success')
    return redirect(url_for('students',show_inactive=1))

# ── Student Profile ───────────────────────────────────────────────────────────
@app.route('/school/students/<int:sid>/profile')
@login_required
def student_profile(sid):
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()

    student = db.execute("""
        SELECT st.*, cl.name as class_name, cl.level as class_level
        FROM students st
        LEFT JOIN classes cl ON cl.id = st.class_id
        WHERE st.id=? AND st.school_id=?
    """, (sid, school_id)).fetchone()
    if not student:
        db.close(); abort(404)

    # All subjects for this school
    subjects = db.execute(
        "SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC, id",
        (school_id,)
    ).fetchall()
    subj_map = {s['id']: s for s in subjects}

    # All terms that have score data for this student
    terms_rows = db.execute("""
        SELECT DISTINCT term, academic_year FROM scores
        WHERE student_id=? AND school_id=?
        ORDER BY academic_year, term
    """, (sid, school_id)).fetchall()

    term_data = []
    best_agg  = None

    for tr in terms_rows:
        term = tr['term']; year = tr['academic_year']

        # Scores
        sc_rows = db.execute("""
            SELECT sc.*, sub.name as subject_name, sub.code, sub.is_core
            FROM scores sc JOIN subjects sub ON sub.id = sc.subject_id
            WHERE sc.student_id=? AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
            ORDER BY sub.is_core DESC, sc.subject_id
        """, (sid, term, year, school_id)).fetchall()

        # Class position
        class_totals = db.execute("""
            SELECT st.id, COALESCE(SUM(ROUND(sc2.class_score+sc2.exam_score,1)),0) as grand_total
            FROM students st
            LEFT JOIN scores sc2 ON sc2.student_id=st.id
                AND sc2.term=? AND sc2.academic_year=? AND sc2.school_id=?
            WHERE st.class_id=? AND st.school_id=? AND st.is_active=1
            GROUP BY st.id
        """, (term, year, school_id, student['class_id'], school_id)).fetchall()

        sorted_totals = sorted([r['grand_total'] for r in class_totals], reverse=True)
        my_total      = sum(r['total'] for r in sc_rows)
        position      = sorted_totals.index(my_total) + 1 if my_total in sorted_totals else None
        total_in_class = len(class_totals)

        # WAEC aggregate
        scale = get_grading_scale(school_id)
        agg          = compute_aggregate([r['total'] for r in sc_rows], scale=scale)
        agg_label, _ = aggregate_remark(agg, scale=scale)
        if best_agg is None or (agg and agg < best_agg['agg']):
            best_agg = {'agg': agg, 'label': agg_label, 'term': term, 'year': year}

        # Attendance & remarks
        att = db.execute(
            "SELECT * FROM attendance WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
            (sid, term, year, school_id)
        ).fetchone()
        rem = db.execute(
            "SELECT * FROM remarks WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
            (sid, term, year, school_id)
        ).fetchone()

        # Fees
        fee = db.execute(
            "SELECT * FROM fees WHERE student_id=? AND term=? AND academic_year=? AND school_id=? LIMIT 1",
            (sid, term, year, school_id)
        ).fetchone()

        term_data.append({
            'term': term,
            'year': year,
            'scores': [dict(r) for r in sc_rows],
            'total': my_total,
            'position': position,
            'total_in_class': total_in_class,
            'aggregate': agg,
            'agg_label': agg_label,
            'attendance': dict(att) if att else {},
            'remarks': dict(rem) if rem else {},
            'fee': dict(fee) if fee else {},
        })

    # Overall fee summary
    fee_summary = db.execute("""
        SELECT COALESCE(SUM(amount_due),0) as total_due,
               COALESCE(SUM(amount_paid),0) as total_paid
        FROM fees WHERE student_id=? AND school_id=?
    """, (sid, school_id)).fetchone()

    # Email/SMS log for this student
    comms = db.execute("""
        SELECT * FROM email_log WHERE student_id=? AND school_id=?
        ORDER BY sent_at DESC LIMIT 20
    """, (sid, school_id)).fetchall()

    db.close()
    return render_template('school/student_profile.html',
        student  = dict(student),
        school   = school,
        subjects = subjects,
        term_data = term_data,
        best_agg  = best_agg,
        fee_summary = dict(fee_summary) if fee_summary else {},
        comms    = comms,
    )



@app.route('/school/students/next-id')
@login_required
def student_next_id():
    """Return next auto-generated student ID as JSON (used by slide panel)."""
    return jsonify({'id': generate_student_id(session['school_id'])})

@app.route('/school/students/add', methods=['GET','POST'])
@login_required
def add_student():
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()
    classes   = db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
    auto_id   = generate_student_id(school_id)
    if request.method == 'GET':
        # Redirect to students list — add is done via slide panel
        db.close()
        return redirect(url_for('students'))
    if request.method == 'POST':
        f = request.form
        student_id = f.get('student_id', '').strip() or auto_id
        photo_filename = ''
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename and allowed_file(photo.filename):
                ext = photo.filename.rsplit('.', 1)[1].lower()
                photo_filename = secure_filename(f"stu_{school_id}_{student_id}.{ext}")
                photo.save(os.path.join(PHOTOS, photo_filename))
        try:
            db.execute("""INSERT INTO students
                (school_id,student_id,first_name,last_name,date_of_birth,gender,
                 class_id,photo_path,parent_name,parent_phone,parent_email,
                 parent_whatsapp,address,fee_amount)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (school_id, student_id, f['first_name'], f['last_name'],
                 f.get('date_of_birth',''), f.get('gender',''),
                 f.get('class_id') or None, photo_filename,
                 f.get('parent_name',''), f.get('parent_phone',''),
                 f.get('parent_email',''), f.get('parent_whatsapp',''),
                 f.get('address',''), float(f.get('fee_amount', 0) or 0)))
            db.commit()
            flash(f'✅ Student added! ID: {student_id}', 'success')
            return redirect(url_for('students'))
        except Exception as e:
            flash(f'❌ Error: {str(e)}', 'error')
    db.close()
    return render_template('school/student_form.html', student=None,
                           classes=classes, school=school, auto_id=auto_id)

@app.route('/school/students/<int:sid>/edit', methods=['GET','POST'])
@login_required
def edit_student(sid):
    school_id=session['school_id']; school=get_school(); db=get_db()
    student=db.execute("SELECT * FROM students WHERE id=? AND school_id=?",(sid,school_id)).fetchone()
    if not student: db.close(); abort(404)
    classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    if request.method=='GET':
        db.close()
        return redirect(url_for('students'))
    if request.method=='POST':
        f=request.form; photo_filename=student['photo_path']
        if 'photo' in request.files:
            photo=request.files['photo']
            if photo and photo.filename and allowed_file(photo.filename):
                ext2=photo.filename.rsplit('.',1)[1].lower()
                photo_filename=secure_filename(f"stu_{school_id}_{student['student_id']}.{ext2}")
                photo.save(os.path.join(PHOTOS,photo_filename))
        try:
            db.execute("""UPDATE students SET first_name=?,last_name=?,date_of_birth=?,
                gender=?,class_id=?,photo_path=?,parent_name=?,parent_phone=?,
                parent_email=?,parent_whatsapp=?,address=?,fee_amount=? WHERE id=? AND school_id=?""",
                (f['first_name'],f['last_name'],f.get('date_of_birth',''),
                 f.get('gender',''),f['class_id'],photo_filename,
                 f.get('parent_name',''),f.get('parent_phone',''),
                 f.get('parent_email',''),f.get('parent_whatsapp',''),
                 f.get('address',''),float(f.get('fee_amount',0) or 0),sid,school_id))
            db.commit(); flash('✅ Student updated.','success')
            return redirect(url_for('students'))
        except Exception as e: flash(f'❌ {str(e)}','error')
    db.close()
    return render_template('school/student_form.html', student=student,
                           classes=classes, school=school, auto_id='')

@app.route('/school/students/<int:sid>/delete', methods=['POST'])
@school_admin_required
@login_required
def delete_student(sid):
    """Soft-delete (deactivate) or hard-delete depending on form flag."""
    school_id = session['school_id']
    hard = request.form.get('hard_delete') == '1'
    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE id=? AND school_id=?", (sid, school_id)
    ).fetchone()
    if not student:
        db.close()
        flash('❌ Student not found.', 'error')
        return redirect(url_for('students'))

    if hard:
        # Permanent delete — also removes scores, attendance, remarks, fees
        db.execute("DELETE FROM scores     WHERE student_id=? AND school_id=?", (sid, school_id))
        db.execute("DELETE FROM attendance WHERE student_id=? AND school_id=?", (sid, school_id))
        db.execute("DELETE FROM remarks    WHERE student_id=? AND school_id=?", (sid, school_id))
        db.execute("DELETE FROM fees       WHERE student_id=? AND school_id=?", (sid, school_id))
        db.execute("DELETE FROM students   WHERE id=? AND school_id=?",         (sid, school_id))
        db.commit(); db.close()
        flash(f'🗑️ {student["first_name"]} {student["last_name"]} permanently deleted.', 'info')
    else:
        # Soft-delete: keeps all data, just hides from lists
        db.execute("UPDATE students SET is_active=0 WHERE id=? AND school_id=?", (sid, school_id))
        db.commit(); db.close()
        flash(f'📦 {student["first_name"]} {student["last_name"]} deactivated (data kept).', 'info')
    return redirect(url_for('students'))


# ── Subjects management page ──────────────────────────────────────────────────
@app.route('/school/subjects')
@login_required
def subjects_page():
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()
    subjects  = db.execute(
        "SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC, name",
        (school_id,)
    ).fetchall()
    db.close()
    return render_template('school/subjects.html', subjects=subjects, school=school,
                           is_teacher=is_teacher())

# ── Scores ────────────────────────────────────────────────────────────────────
@app.route('/school/scores')
@login_required
def scores():
    school_id=session['school_id']; school=get_school()
    db=get_db()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    cf=request.args.get('class_id','')
    tc = get_teacher_classes()  # None=admin (no restriction), list=teacher
    if tc is not None:
        # Teacher: only see their assigned classes
        if tc:
            classes=db.execute(
                f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc))}) ORDER BY name",
                [school_id]+tc
            ).fetchall()
        else:
            classes=[]
        # Enforce: if teacher picks a class not theirs, reset to first allowed
        if cf and int(cf) not in (tc or []):
            cf = str(tc[0]) if tc else ''
        # Auto-select if only one class
        if not cf and len(tc)==1:
            cf = str(tc[0])
    else:
        classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    subjects=db.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC,id",(school_id,)).fetchall()
    students=[]; existing_scores={}
    if cf:
        rows=db.execute("""SELECT st.*,cl.name as class_name FROM students st
            LEFT JOIN classes cl ON cl.id=st.class_id
            WHERE st.class_id=? AND st.school_id=? AND st.is_active=1
            ORDER BY st.last_name""",(cf,school_id)).fetchall()
        students=rows
        sc_rows=db.execute("""SELECT student_id,subject_id,class_score,exam_score,
            ROUND(class_score+exam_score,1) AS total
            FROM scores WHERE school_id=? AND term=? AND academic_year=?
            AND student_id IN (SELECT id FROM students WHERE class_id=? AND school_id=?)""",
            (school_id,term,year,cf,school_id)).fetchall()
        for sc in sc_rows:
            existing_scores[f"{sc['student_id']}_{sc['subject_id']}"]={'cs':sc['class_score'],'es':sc['exam_score'],'t':sc['total']}
    db.close()
    scale = get_grading_scale(school_id)
    from grading import DEFAULT_SCALE
    sc = scale or DEFAULT_SCALE
    return render_template('school/scores.html', students=students, subjects=subjects,
                           classes=classes, term=term, academic_year=year,
                           class_filter=cf, school=school,
                           existing_scores=json.dumps(existing_scores),
                           grade_scale=sc)

@app.route('/school/scores/save', methods=['POST'])
@login_required
def save_scores():
    db=get_db(); data=request.get_json()
    school_id=session['school_id']; user_id=session.get('user_id',1)
    tc = get_teacher_classes()
    try:
        for row in data['scores']:
            # Security: teacher can only save scores for their own class students
            if tc is not None:
                stu = db.execute("SELECT class_id FROM students WHERE id=? AND school_id=?",
                                 (row['student_id'], school_id)).fetchone()
                if not stu or stu['class_id'] not in tc:
                    db.close()
                    return jsonify({'status':'error','message':'Access denied — not your class.'}), 403
            db.execute("""INSERT INTO scores
                (school_id,student_id,subject_id,term,academic_year,class_score,exam_score,entered_by)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(school_id,student_id,subject_id,term,academic_year)
                DO UPDATE SET class_score=excluded.class_score,
                              exam_score=excluded.exam_score,
                              entered_by=excluded.entered_by""",
                (school_id,row['student_id'],row['subject_id'],row['term'],
                 row['academic_year'],row['class_score'],row['exam_score'],user_id))
        db.commit(); db.close()
        return jsonify({'status':'ok'})
    except Exception as e:
        db.close(); return jsonify({'status':'error','message':str(e)}),400

# ── Score CSV Download (template for bulk import) ─────────────────────────────
@app.route('/school/scores/csv-template')
@login_required
def scores_csv_template():
    school_id = session['school_id']
    db = get_db()
    class_id = request.args.get('class_id','')
    term     = request.args.get('term','1')
    year     = request.args.get('year','2025/2026')

    subjects = db.execute(
        "SELECT id,name,code FROM subjects WHERE school_id=? ORDER BY is_core DESC,id",
        (school_id,)
    ).fetchall()

    q = """SELECT st.id,st.student_id,st.first_name,st.last_name,
                  COALESCE(sc_map.scores,'') as existing
           FROM students st
           LEFT JOIN (
               SELECT student_id,
                      STRING_AGG(CAST(subject_id AS TEXT)||':'||CAST(ROUND(CAST(class_score AS NUMERIC),1) AS TEXT)||':'||CAST(ROUND(CAST(exam_score AS NUMERIC),1) AS TEXT), ',') as scores
               FROM scores
               WHERE school_id=? AND term=? AND academic_year=?
               GROUP BY student_id
           ) sc_map ON sc_map.student_id = st.id
           WHERE st.school_id=? AND st.is_active=1"""
    params = [school_id, term, year, school_id]
    if class_id:
        q += " AND st.class_id=?"
        params.append(class_id)
    q += " ORDER BY st.last_name, st.first_name"
    students = db.execute(q, params).fetchall()
    db.close()

    # Build existing score lookup {student_db_id: {subj_id: (cs,es)}}
    existing = {}
    for stu in students:
        existing[stu['id']] = {}
        if stu['existing']:
            for chunk in stu['existing'].split(','):
                parts = chunk.split(':')
                if len(parts) == 3:
                    existing[stu['id']][int(parts[0])] = (float(parts[1]), float(parts[2]))

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row 1: instructions
    writer.writerow(['# Lucid IT Hub — Score Import Template'])
    writer.writerow([f'# Term: {term}  |  Year: {year}  |  DO NOT change columns A-D'])
    writer.writerow([f'# Class Score max: 40   Exam Score max: 60'])
    writer.writerow([])

    # Header row: student info + subject columns
    headers = ['db_id','student_id','last_name','first_name']
    for subj in subjects:
        headers += [f'{subj["code"]}_CS(max40)', f'{subj["code"]}_ES(max60)', f'{subj["code"]}_Total']
    writer.writerow(headers)

    # Data rows
    for stu in students:
        row = [stu['id'], stu['student_id'], stu['last_name'], stu['first_name']]
        for subj in subjects:
            sc = existing.get(stu['id'],{}).get(subj['id'])
            cs = sc[0] if sc else ''
            es = sc[1] if sc else ''
            total = round(float(cs)+float(es),1) if cs != '' and es != '' else ''
            row += [cs, es, total]
        writer.writerow(row)

    output.seek(0)
    fname = f"scores_T{term}_{year.replace('/','_')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={fname}'}
    )

# ── Score CSV Upload (bulk import) ────────────────────────────────────────────
@app.route('/school/scores/csv-import', methods=['POST'])
@login_required
def scores_csv_import():
    school_id = session['school_id']
    user_id   = session.get('user_id', 1)
    term      = int(request.form.get('term', 1))
    year      = request.form.get('year', '2025/2026')

    if 'csv_file' not in request.files:
        return jsonify({'status':'error','message':'No file uploaded'}), 400

    f = request.files['csv_file']
    if not f.filename.endswith('.csv'):
        return jsonify({'status':'error','message':'File must be a .csv'}), 400

    db = get_db()
    subjects = db.execute(
        "SELECT id,code FROM subjects WHERE school_id=? ORDER BY is_core DESC,id",
        (school_id,)
    ).fetchall()
    subj_list = list(subjects)

    # Validate all student IDs belong to this school
    valid_student_ids = {
        str(r['id']) for r in
        db.execute("SELECT id FROM students WHERE school_id=? AND is_active=1",(school_id,)).fetchall()
    }

    errors = []; saved = 0; skipped = 0
    content = f.read().decode('utf-8-sig')  # handle BOM from Excel
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    # Find the actual data header row (skip comment rows starting with #)
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0].strip() == 'db_id':
            header_idx = i
            break
    if header_idx is None:
        db.close()
        return jsonify({'status':'error','message':'Could not find header row. Make sure you used the downloaded template.'}), 400

    headers = rows[header_idx]
    data_rows = rows[header_idx+1:]

    for line_num, row in enumerate(data_rows, start=header_idx+2):
        if not row or not row[0].strip():
            continue
        db_id = str(row[0]).strip()
        if db_id not in valid_student_ids:
            errors.append(f'Row {line_num}: Student ID "{db_id}" not found in this school')
            skipped += 1
            continue

        # Each subject occupies 3 columns (CS, ES, Total) starting at index 4
        for si, subj in enumerate(subj_list):
            col_cs  = 4 + si * 3
            col_es  = 5 + si * 3
            try:
                cs_raw = row[col_cs].strip() if col_cs < len(row) else ''
                es_raw = row[col_es].strip() if col_es < len(row) else ''
                if cs_raw == '' and es_raw == '':
                    continue  # blank = skip this subject
                cs = float(cs_raw) if cs_raw else 0.0
                es = float(es_raw) if es_raw else 0.0
                # Validation
                if cs < 0 or cs > 40:
                    errors.append(f'Row {line_num}, {subj["code"]} CS: {cs} out of range (0–40)')
                    skipped += 1; continue
                if es < 0 or es > 60:
                    errors.append(f'Row {line_num}, {subj["code"]} ES: {es} out of range (0–60)')
                    skipped += 1; continue
                db.execute("""
                    INSERT INTO scores
                    (school_id,student_id,subject_id,term,academic_year,class_score,exam_score,entered_by)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(school_id,student_id,subject_id,term,academic_year)
                    DO UPDATE SET class_score=excluded.class_score,
                                  exam_score=excluded.exam_score,
                                  entered_by=excluded.entered_by
                """, (school_id, int(db_id), subj['id'], term, year, cs, es, user_id))
                saved += 1
            except (ValueError, IndexError) as e:
                errors.append(f'Row {line_num}, {subj["code"]}: {str(e)}')
                skipped += 1

    db.commit(); db.close()
    return jsonify({
        'status': 'ok',
        'saved': saved,
        'skipped': skipped,
        'errors': errors[:20]  # cap at 20 error messages
    })

# ── Remarks ───────────────────────────────────────────────────────────────────
@app.route('/school/remarks')
@login_required
def remarks_page():
    school_id=session['school_id']; school=get_school(); db=get_db()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    cf=request.args.get('class_id','')
    tc = get_teacher_classes()
    if tc is not None:
        # Teacher: restrict to their classes, auto-select if only one
        if tc:
            classes=db.execute(
                f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc))}) ORDER BY name",
                [school_id]+tc
            ).fetchall()
        else:
            classes=[]
        if cf and int(cf) not in (tc or []):
            cf = str(tc[0]) if tc else ''
        if not cf and tc:
            cf = str(tc[0])
    else:
        classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    q="""SELECT st.*,cl.name as class_name,
                r.conduct,r.class_teacher_remark,r.head_teacher_remark,r.interest,r.next_term_begins,
                a.days_present,a.days_absent,a.total_days
         FROM students st
         LEFT JOIN classes cl ON cl.id=st.class_id
         LEFT JOIN remarks r ON r.student_id=st.id AND r.term=? AND r.academic_year=? AND r.school_id=?
         LEFT JOIN attendance a ON a.student_id=st.id AND a.term=? AND a.academic_year=? AND a.school_id=?
         WHERE st.school_id=? AND st.is_active=1"""
    params=[term,year,school_id,term,year,school_id,school_id]
    if cf: q+=" AND st.class_id=?"; params.append(cf)
    q+=" ORDER BY cl.name,st.last_name"
    students=db.execute(q,params).fetchall(); db.close()
    return render_template('school/remarks.html', students=students, classes=classes,
                           term=term, academic_year=year, class_filter=cf, school=school,
                           is_teacher=(tc is not None))

@app.route('/school/remarks/save', methods=['POST'])
@login_required
def save_remarks():
    db=get_db(); f=request.form; school_id=session['school_id']
    sid=int(f['student_id']); term=int(f['term']); yr=f['academic_year']
    # Security: teacher can only save remarks for students in their class
    tc = get_teacher_classes()
    if tc is not None:
        stu = db.execute("SELECT class_id FROM students WHERE id=? AND school_id=?",
                         (sid, school_id)).fetchone()
        if not stu or stu['class_id'] not in tc:
            db.close()
            flash('❌ Access denied — not your class.', 'error')
            return redirect(url_for('remarks_page'))
    try:
        db.execute("""INSERT INTO remarks
            (school_id,student_id,term,academic_year,conduct,class_teacher_remark,head_teacher_remark,interest,next_term_begins)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(school_id,student_id,term,academic_year)
            DO UPDATE SET conduct=excluded.conduct,class_teacher_remark=excluded.class_teacher_remark,
            head_teacher_remark=excluded.head_teacher_remark,interest=excluded.interest,next_term_begins=excluded.next_term_begins""",
            (school_id,sid,term,yr,f['conduct'],f.get('class_teacher_remark',''),
             f.get('head_teacher_remark',''),f.get('interest',''),f.get('next_term_begins','')))
        db.execute("""INSERT INTO attendance
            (school_id,student_id,term,academic_year,days_present,days_absent,total_days)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(school_id,student_id,term,academic_year)
            DO UPDATE SET days_present=excluded.days_present,days_absent=excluded.days_absent,total_days=excluded.total_days""",
            (school_id,sid,term,yr,int(f.get('days_present',0)),
             int(f.get('days_absent',0)),int(f.get('total_days',0))))
        db.commit(); flash('✅ Saved.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close()
    return redirect(url_for('remarks_page',term=term,year=yr,class_id=f.get('class_filter','')))

# ── Fees ──────────────────────────────────────────────────────────────────────
@app.route('/school/fees')
@school_admin_required
@login_required
def fees():
    school_id=session['school_id']; school=get_school(); db=get_db()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    cf=request.args.get('class_id','')
    classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    q="""SELECT st.*,cl.name as class_name,
                COALESCE(f.amount_due,st.fee_amount,0) as amount_due,
                COALESCE(f.amount_paid,st.fee_paid,0) as amount_paid,
                COALESCE(f.payment_date,'') as payment_date,
                COALESCE(f.payment_method,'') as payment_method,
                f.id as fee_id
         FROM students st LEFT JOIN classes cl ON cl.id=st.class_id
         LEFT JOIN fees f ON f.student_id=st.id AND f.term=? AND f.academic_year=? AND f.school_id=?
         WHERE st.school_id=? AND st.is_active=1"""
    params=[term,year,school_id,school_id]
    if cf: q+=" AND st.class_id=?"; params.append(cf)
    q+=" ORDER BY cl.name,st.last_name"
    students=db.execute(q,params).fetchall()
    totals=db.execute("""SELECT COALESCE(SUM(amount_due),0) as total_due,
        COALESCE(SUM(amount_paid),0) as total_paid FROM fees
        WHERE school_id=? AND term=? AND academic_year=?""",(school_id,term,year)).fetchone()
    # Per-class fee breakdown
    class_breakdown=db.execute("""
        SELECT cl.name, COUNT(st.id) as total_students,
               COUNT(f.id) as fee_records,
               COALESCE(SUM(f.amount_due),0) as due,
               COALESCE(SUM(f.amount_paid),0) as paid,
               SUM(CASE WHEN f.amount_paid>=f.amount_due AND f.amount_due>0 THEN 1 ELSE 0 END) as cleared
        FROM classes cl
        LEFT JOIN students st ON st.class_id=cl.id AND st.is_active=1
        LEFT JOIN fees f ON f.student_id=st.id AND f.term=? AND f.academic_year=? AND f.school_id=?
        WHERE cl.school_id=?
        GROUP BY cl.id ORDER BY cl.name
    """,(term,year,school_id,school_id)).fetchall()
    # Top debtors
    debtors=db.execute("""
        SELECT * FROM (
            SELECT st.first_name||' '||st.last_name as name, cl.name as class_name,
                   COALESCE(f.amount_due,st.fee_amount,0)-COALESCE(f.amount_paid,st.fee_paid,0) as balance
            FROM students st LEFT JOIN classes cl ON cl.id=st.class_id
            LEFT JOIN fees f ON f.student_id=st.id AND f.term=? AND f.academic_year=? AND f.school_id=?
            WHERE st.school_id=? AND st.is_active=1
        ) WHERE balance>0 ORDER BY balance DESC LIMIT 8
    """,(term,year,school_id,school_id)).fetchall()
    db.close()
    return render_template('school/fees.html', students=students, classes=classes,
                           term=term, academic_year=year, class_filter=cf,
                           school=school, totals=totals,
                           class_breakdown=class_breakdown, debtors=debtors)

@app.route('/school/fees/save', methods=['POST'])
@school_admin_required
@login_required
def save_fee():
    db=get_db(); f=request.form; school_id=session['school_id']
    try:
        db.execute("""INSERT INTO fees
            (school_id,student_id,term,academic_year,fee_type,amount_due,amount_paid,payment_date,payment_method,notes,recorded_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(school_id,student_id,fee_type,term,academic_year)
            DO UPDATE SET amount_due=excluded.amount_due,amount_paid=excluded.amount_paid,
            payment_date=excluded.payment_date,payment_method=excluded.payment_method,notes=excluded.notes""",
            (school_id,int(f['student_id']),int(f['term']),f['academic_year'],
             f.get('fee_type','School Fees'),float(f.get('amount_due',0) or 0),
             float(f.get('amount_paid',0) or 0),f.get('payment_date',''),
             f.get('payment_method',''),f.get('notes',''),session.get('user_id',1)))
        db.commit(); flash('✅ Fee record saved.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close()
    return redirect(url_for('fees',term=f['term'],year=f['academic_year'],class_id=f.get('class_filter','')))

# ── Fee Receipt (single fee record) ──────────────────────────────────────────
@app.route('/school/fees/receipt/<int:fee_id>')
@school_admin_required
@login_required
def fee_receipt(fee_id):
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()

    fee = db.execute("""
        SELECT f.*, st.first_name, st.last_name, st.student_id as stu_code,
               st.parent_name, st.parent_phone, st.parent_email,
               cl.name as class_name, u.full_name as recorded_by_name
        FROM fees f
        JOIN students st ON st.id = f.student_id
        LEFT JOIN classes cl ON cl.id = st.class_id
        LEFT JOIN users u ON u.id = f.recorded_by
        WHERE f.id=? AND f.school_id=?
    """, (fee_id, school_id)).fetchone()
    if not fee:
        db.close(); abort(404)

    # All fee records for this student (full history for bottom section)
    all_fees = db.execute("""
        SELECT * FROM fees WHERE student_id=? AND school_id=?
        ORDER BY academic_year, term
    """, (fee['student_id'], school_id)).fetchall()

    # Generate receipt number: RCPT-{school_id}-{fee_id:05d}
    receipt_no = f"RCPT-{school_id:02d}-{fee_id:05d}"

    db.close()
    return render_template('school/fee_receipt.html',
        fee        = dict(fee),
        all_fees   = [dict(r) for r in all_fees],
        school     = school,
        receipt_no = receipt_no,
    )

# ── Bulk receipts — all cleared students for a term ──────────────────────────
@app.route('/school/fees/bulk-receipts')
@school_admin_required
@login_required
def bulk_fee_receipts():
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()
    term  = int(request.args.get('term', school.get('current_term', 1)))
    year  = request.args.get('year', school.get('current_year','2025/2026'))
    cf    = request.args.get('class_id','')

    q = """
        SELECT f.*, st.first_name, st.last_name, st.student_id as stu_code,
               st.parent_name, cl.name as class_name, u.full_name as recorded_by_name
        FROM fees f
        JOIN students st ON st.id = f.student_id
        LEFT JOIN classes cl ON cl.id = st.class_id
        LEFT JOIN users u ON u.id = f.recorded_by
        WHERE f.school_id=? AND f.term=? AND f.academic_year=?
          AND f.amount_paid >= f.amount_due AND f.amount_due > 0
    """
    params = [school_id, term, year]
    if cf:
        q += " AND st.class_id=?"
        params.append(cf)
    q += " ORDER BY cl.name, st.last_name"

    fees = db.execute(q, params).fetchall()
    db.close()

    return render_template('school/fee_receipt_bulk.html',
        fees   = [dict(r) for r in fees],
        school = school,
        term   = term,
        year   = year,
    )


# ── Timetable ─────────────────────────────────────────────────────────────────
@app.route('/school/timetable')
@login_required
def timetable():
    school_id=session['school_id']; school=get_school(); db=get_db()
    cf=request.args.get('class_id','')
    tc = get_teacher_classes()
    if tc is not None:
        # Teacher: only show their assigned classes
        if tc:
            classes=db.execute(
                f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc))}) ORDER BY name",
                [school_id]+tc
            ).fetchall()
            if cf and int(cf) not in tc:
                cf = str(tc[0])
            if not cf:
                cf = str(tc[0])
        else:
            classes=[]
    else:
        classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    tt=[]; subjects=[]; teachers=[]
    if cf:
        tt=db.execute("""SELECT t.*,s.name as subject_name,s.code,
                                u.full_name as teacher_name,cl.name as class_name
            FROM timetable t
            LEFT JOIN subjects s ON s.id=t.subject_id
            LEFT JOIN users u ON u.id=t.teacher_id
            LEFT JOIN classes cl ON cl.id=t.class_id
            WHERE t.school_id=? AND t.class_id=?
            ORDER BY CASE t.day_of_week WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2
            WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 ELSE 5 END, t.start_time""",
            (school_id,cf)).fetchall()
        subjects=db.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
        teachers=db.execute("SELECT * FROM users WHERE school_id=? AND is_active=1 ORDER BY full_name",(school_id,)).fetchall()
    db.close()
    return render_template('school/timetable.html', timetable=tt, classes=classes,
                           subjects=subjects, teachers=teachers,
                           class_filter=cf, school=school,
                           days=['Monday','Tuesday','Wednesday','Thursday','Friday'])

@app.route('/school/timetable/save', methods=['POST'])
@login_required
def save_timetable():
    db=get_db(); f=request.form; school_id=session['school_id']
    tc = get_teacher_classes()
    if tc is not None:
        if not f.get('class_id') or int(f['class_id']) not in tc:
            db.close()
            flash('❌ Access denied — not your class.','error')
            return redirect(url_for('timetable',class_id=f.get('class_id','')))
    try:
        db.execute("""INSERT INTO timetable
            (school_id,class_id,subject_id,teacher_id,day_of_week,start_time,end_time,room)
            VALUES (?,?,?,?,?,?,?,?)""",
            (school_id,int(f['class_id']),int(f['subject_id']),
             int(f['teacher_id']),f['day_of_week'],f['start_time'],
             f['end_time'],f.get('room','')))
        db.commit(); flash('✅ Timetable entry added.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close()
    return redirect(url_for('timetable',class_id=f.get('class_id','')))

@app.route('/school/timetable/<int:tid>/delete', methods=['POST'])
@login_required
def delete_timetable(tid):
    db=get_db(); school_id=session['school_id']
    tc = get_teacher_classes()
    if tc is not None:
        entry = db.execute("SELECT class_id FROM timetable WHERE id=? AND school_id=?",(tid,school_id)).fetchone()
        if not entry or entry['class_id'] not in tc:
            db.close()
            flash('❌ Access denied.','error')
            return redirect(url_for('timetable'))
    db.execute("DELETE FROM timetable WHERE id=? AND school_id=?",(tid,school_id))
    db.commit(); db.close()
    return redirect(request.referrer or url_for('timetable'))

# ── Reports & Email ───────────────────────────────────────────────────────────
@app.route('/school/reports')
@login_required
def reports():
    school_id=session['school_id']; school=get_school(); db=get_db()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    cf=request.args.get('class_id','')
    tc = get_teacher_classes()
    if tc is not None:
        if tc:
            classes=db.execute(
                f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc))}) ORDER BY name",
                [school_id]+tc
            ).fetchall()
        else:
            classes=[]
        if cf and int(cf) not in (tc or []):
            cf = str(tc[0]) if tc else ''
        if not cf and tc:
            cf = str(tc[0])
    else:
        classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    students=[]
    if cf:
        students=db.execute("""SELECT st.*,cl.name as class_name FROM students st
            LEFT JOIN classes cl ON cl.id=st.class_id
            WHERE st.class_id=? AND st.school_id=? AND st.is_active=1
            ORDER BY st.last_name""",(cf,school_id)).fetchall()
    log=[] if tc is not None else db.execute("""SELECT el.*,st.first_name||' '||st.last_name as student_name
        FROM email_log el LEFT JOIN students st ON st.id=el.student_id
        WHERE el.school_id=? ORDER BY el.sent_at DESC LIMIT 30""",(school_id,)).fetchall()
    sms_cfg=db.execute("SELECT * FROM sms_config WHERE school_id=?",(school_id,)).fetchone()
    db.close()
    return render_template('school/reports.html', students=students, classes=classes,
                           term=term, academic_year=year, class_filter=cf,
                           school=school, email_log=log, sms_cfg=sms_cfg,
                           is_teacher=(tc is not None))

@app.route('/school/reports/preview/<int:sid>')
@login_required
def preview_report(sid):
    school_id=session['school_id']; school=get_school()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    # Security: teacher can only download cards for students in their class
    tc = get_teacher_classes()
    if tc is not None:
        db=get_db()
        stu=db.execute("SELECT class_id FROM students WHERE id=? AND school_id=?",(sid,school_id)).fetchone()
        db.close()
        if not stu or stu['class_id'] not in tc:
            abort(403)
    result=build_report_pdf(school_id,sid,term,year)
    if not result: abort(404)
    pdf_path=result[0]
    return send_file(pdf_path,as_attachment=False,mimetype='application/pdf')

@app.route('/school/reports/broadsheet/<int:class_id>')
@login_required
def broadsheet(class_id):
    school_id=session['school_id']; school=get_school(); db=get_db()
    term=int(request.args.get('term',school.get('current_term',1)))
    year=request.args.get('year',school.get('current_year','2025/2026'))
    cls=db.execute("SELECT * FROM classes WHERE id=? AND school_id=?",(class_id,school_id)).fetchone()
    if not cls: db.close(); abort(404)
    tc = get_teacher_classes()
    if tc is not None and class_id not in tc:
        db.close(); abort(403)
    students=db.execute("""SELECT st.* FROM students st
        WHERE st.class_id=? AND st.school_id=? AND st.is_active=1
        ORDER BY st.last_name""",(class_id,school_id)).fetchall()
    subjects=db.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC,id",(school_id,)).fetchall()
    class_totals=get_class_totals(school_id,class_id,term,year)
    all_totals=sorted(list(class_totals.values()),reverse=True)
    students_data=[]
    for s in students:
        scores_rows=db.execute("""SELECT subject_id, ROUND(class_score+exam_score,1) AS total
            FROM scores WHERE student_id=? AND term=? AND academic_year=? AND school_id=?""",
            (s['id'],term,year,school_id)).fetchall()
        scores_dict={r['subject_id']:r['total'] for r in scores_rows}
        total_score=sum(scores_dict.values())
        agg=compute_aggregate(list(scores_dict.values()), scale=get_grading_scale(school_id))
        att=db.execute("SELECT * FROM attendance WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
                       (s['id'],term,year,school_id)).fetchone()
        rem=db.execute("SELECT * FROM remarks WHERE student_id=? AND term=? AND academic_year=? AND school_id=?",
                       (s['id'],term,year,school_id)).fetchone()
        pos=all_totals.index(total_score)+1 if total_score in all_totals else None
        students_data.append({
            'name':f"{s['first_name']} {s['last_name']}",
            'student_id':s['student_id'],
            'scores':scores_dict,'total_score':total_score,
            'aggregate':agg,'position':pos,
            'attendance':dict(att) if att else {},
            'conduct':rem['conduct'] if rem else 'Good',
        })
    students_data.sort(key=lambda x:x['total_score'],reverse=True)
    db.close()
    bs_name=f"Broadsheet_{school_id}_{class_id}_T{term}_{year.replace('/','_')}.pdf"
    bs_path=os.path.join(REPORTS,bs_name)
    school_for_bs = dict(school)
    if school_for_bs.get('logo_path') and not os.path.isabs(school_for_bs['logo_path']):
        school_for_bs['logo_path'] = os.path.join(LOGOS, school_for_bs['logo_path'])
    generate_broadsheet(school_for_bs,cls['name'],students_data,[dict(s) for s in subjects],term,year,bs_path,scale=get_grading_scale(school_id))
    return send_file(bs_path,as_attachment=False,mimetype='application/pdf')

@app.route('/school/reports/send', methods=['POST'])
@login_required
def send_reports():
    global email_jobs
    school_id=session['school_id']; school=get_school()
    data=request.get_json()
    if email_jobs.get(school_id,{}).get('running'):
        return jsonify({'status':'error','message':'Job already running.'}),400
    smtp_cfg=data['smtp']; student_ids=data['student_ids']
    term=int(data['term']); year=data['academic_year']
    send_email_flag=data.get('send_email',True)
    send_sms_flag=data.get('send_sms',False)
    term_map={1:'First Term',2:'Second Term',3:'Third Term'}
    term_label=term_map.get(term,'First Term')
    db=get_db()
    sms_row=db.execute("SELECT * FROM sms_config WHERE school_id=?",(school_id,)).fetchone()
    sms_cfg=dict(sms_row) if sms_row else None
    jobs=[]
    for sid in student_ids:
        s=db.execute("""SELECT st.*,cl.name as class_name,cl.class_teacher_id,u.full_name as class_teacher_name
            FROM students st LEFT JOIN classes cl ON cl.id=st.class_id
            LEFT JOIN users u ON u.id=cl.class_teacher_id
            WHERE st.id=? AND st.school_id=?""",(sid,school_id)).fetchone()
        if not s: continue
        result=build_report_pdf(school_id,sid,term,year)
        if not result: continue
        pdf_path,my_total,position,agg=result
        agg_label,_=aggregate_remark(agg)
        jobs.append({
            'db_student_id':sid,'student_name':f"{s['first_name']} {s['last_name']}",
            'parent_name':s['parent_name'],'parent_email':s['parent_email'],
            'parent_phone':s['parent_phone'],'pdf_path':pdf_path,
            'agg_label':agg_label,'position':ordinal(position),
            'fee_balance':s['fee_amount']-s['fee_paid'],
        })
    db.close()
    email_jobs[school_id]={'running':True,'total':len(jobs),'done':0,'current':'','results':[]}

    def run():
        def cb(done,total,name):
            email_jobs[school_id].update({'done':done,'current':name})
        results=bulk_send(smtp_cfg,sms_cfg,jobs,school['name'],term_label,year,
                          send_email_flag,send_sms_flag,progress_cb=cb)
        db2=get_db()
        for r in results:
            db2.execute("""INSERT INTO email_log
                (school_id,student_id,parent_email,term,academic_year,channel,status,error_message)
                VALUES (?,?,?,?,?,?,?,?)""",
                (school_id,r['db_student_id'],r['parent_email'],term,year,
                 'email','sent' if r['email_success'] else 'failed',r['email_error']))
        db2.commit(); db2.close()
        email_jobs[school_id]['running']=False
        email_jobs[school_id]['results']=results
    threading.Thread(target=run,daemon=True).start()
    return jsonify({'status':'ok','total':len(jobs)})

@app.route('/school/reports/progress')
@login_required
def report_progress():
    return jsonify(email_jobs.get(session['school_id'],{'running':False,'total':0,'done':0,'results':[]}))

# ── Teachers / Users ──────────────────────────────────────────────────────────
@app.route('/school/teachers')
@school_admin_required
@login_required
def teachers():
    school_id=session['school_id']; school=get_school(); db=get_db()
    users=[dict(r) for r in db.execute("""
        SELECT u.*,
               cl2.id   as assigned_class_id,
               cl2.name as assigned_class
        FROM users u
        LEFT JOIN classes cl2 ON cl2.class_teacher_id=u.id AND cl2.school_id=u.school_id
        WHERE u.school_id=?
        GROUP BY u.id ORDER BY u.role,u.full_name""",(school_id,)).fetchall()]
    classes=db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name",(school_id,)).fetchall()
    db.close()
    return render_template('school/teachers.html', users=users, classes=classes, school=school)

@app.route('/school/teachers/add', methods=['POST'])
@school_admin_required
@login_required
def add_teacher():
    db=get_db(); f=request.form; school_id=session['school_id']
    try:
        ph=hash_password(f.get('password','teacher123'))
        db.execute("""INSERT INTO users (school_id,username,email,password_hash,role,full_name,phone)
            VALUES (?,?,?,?,?,?,?)""",
            (school_id,f['username'],f.get('email',''),ph,
             f.get('role','teacher'),f['full_name'],f.get('phone','')))
        if f.get('class_id'):
            db.execute("UPDATE classes SET class_teacher_id=(SELECT id FROM users WHERE username=? AND school_id=?) WHERE id=? AND school_id=?",
                       (f['username'],school_id,int(f['class_id']),school_id))
        db.commit(); flash('✅ Teacher added.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close()
    return redirect(url_for('teachers'))

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route('/school/teachers/<int:uid>/edit', methods=['POST'])
@school_admin_required
@login_required
def edit_teacher(uid):
    db=get_db(); f=request.form; school_id=session['school_id']
    u=db.execute("SELECT * FROM users WHERE id=? AND school_id=?",(uid,school_id)).fetchone()
    if not u: db.close(); return jsonify({'status':'error','message':'Not found'}),404
    db.execute("""UPDATE users SET full_name=?,email=?,phone=?,role=? WHERE id=? AND school_id=?""",
               (f['full_name'],f.get('email',''),f.get('phone',''),f.get('role','teacher'),uid,school_id))
    # Update class assignment
    new_cid=f.get('class_id') or None
    db.execute("UPDATE classes SET class_teacher_id=NULL WHERE class_teacher_id=? AND school_id=?",(uid,school_id))
    if new_cid:
        db.execute("UPDATE classes SET class_teacher_id=? WHERE id=? AND school_id=?",(uid,int(new_cid),school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok'})

@app.route('/school/teachers/<int:uid>/toggle', methods=['POST'])
@school_admin_required
@login_required
def toggle_teacher(uid):
    db=get_db(); school_id=session['school_id']
    u=db.execute("SELECT * FROM users WHERE id=? AND school_id=?",(uid,school_id)).fetchone()
    if not u: db.close(); return jsonify({'status':'error','message':'Not found'}),404
    new_status=0 if u['is_active'] else 1
    db.execute("UPDATE users SET is_active=? WHERE id=? AND school_id=?",(new_status,uid,school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok','is_active':new_status})

@app.route('/school/teachers/<int:uid>/reset-password', methods=['POST'])
@school_admin_required
@login_required
def reset_teacher_password(uid):
    db=get_db(); f=request.form; school_id=session['school_id']
    u=db.execute("SELECT * FROM users WHERE id=? AND school_id=?",(uid,school_id)).fetchone()
    if not u: db.close(); return jsonify({'status':'error','message':'Not found'}),404
    new_pw=f.get('password','').strip()
    if len(new_pw)<6: db.close(); return jsonify({'status':'error','message':'Password must be at least 6 characters.'}),400
    db.execute("UPDATE users SET password_hash=? WHERE id=? AND school_id=?",(hash_password(new_pw),uid,school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok'})


@app.route('/school/settings', methods=['GET','POST'])
@school_admin_required
@login_required
def school_settings():
    school_id=session['school_id']; db=get_db()
    school=get_school()
    if request.method=='POST':
        f=request.form; logo_path=school.get('logo_path','')
        if 'logo' in request.files:
            logo=request.files['logo']
            if logo and logo.filename and allowed_file(logo.filename):
                fn=secure_filename(f"logo_{school_id}.{logo.filename.rsplit('.',1)[1]}")
                logo.save(os.path.join(LOGOS,fn)); logo_path=fn
        db.execute("""UPDATE schools SET name=?,address=?,phone=?,email=?,motto=?,
            primary_color=?,secondary_color=?,current_term=?,current_year=?,logo_path=?
            WHERE id=?""",
            (f['name'],f.get('address',''),f.get('phone',''),f.get('email',''),
             f.get('motto',''),f.get('primary_color','#1B4332'),
             f.get('secondary_color','#D4A017'),int(f.get('current_term',1)),
             f.get('current_year','2025/2026'),logo_path,school_id))
        db.commit(); flash('✅ Settings updated.','success')
        school=get_school()
    classes=db.execute("""
        SELECT cl.*,u.full_name as teacher_name,
               (SELECT COUNT(*) FROM students st WHERE st.class_id=cl.id AND st.is_active=1) as student_count
        FROM classes cl LEFT JOIN users u ON u.id=cl.class_teacher_id
        WHERE cl.school_id=? ORDER BY cl.name""",(school_id,)).fetchall()
    subjects=db.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC,id",(school_id,)).fetchall()
    sms_cfg=db.execute("SELECT * FROM sms_config WHERE school_id=?",(school_id,)).fetchone()
    teachers=db.execute("SELECT id,full_name FROM users WHERE school_id=? AND is_active=1 ORDER BY full_name",(school_id,)).fetchall()
    try:
        scale_row=db.execute("SELECT * FROM grading_scales WHERE school_id=?",(school_id,)).fetchone()
    except Exception:
        scale_row=None
    db.close()
    from grading import DEFAULT_SCALE
    grade_scale = scale_from_db_row(dict(scale_row)) if scale_row else DEFAULT_SCALE
    return render_template('school/settings.html', school=school,
                           classes=classes, subjects=subjects, sms_cfg=sms_cfg,
                           teachers=teachers, grade_scale=grade_scale)

@app.route('/school/settings/sms', methods=['POST'])
@school_admin_required
@login_required
def save_sms_settings():
    db=get_db(); f=request.form; school_id=session['school_id']
    db.execute("""INSERT INTO sms_config (school_id,provider,api_key,api_secret,sender_id,is_active)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(school_id) DO UPDATE SET provider=excluded.provider,
        api_key=excluded.api_key,api_secret=excluded.api_secret,
        sender_id=excluded.sender_id,is_active=excluded.is_active""",
        (school_id,f.get('provider','hubtel'),f.get('api_key',''),
         f.get('api_secret',''),f.get('sender_id','SCHOOL'),
         1 if f.get('is_active') else 0))
    db.commit(); db.close()
    flash('✅ SMS settings saved.','success')
    return redirect(url_for('school_settings'))

@app.route('/school/settings/class/add', methods=['POST'])
@school_admin_required
@login_required
def add_class():
    db=get_db(); f=request.form; school_id=session['school_id']
    try:
        db.execute("INSERT INTO classes (school_id,name,level,capacity) VALUES (?,?,?,?)",
                   (school_id,f['name'],f.get('level','JHS'),int(f.get('capacity',40) or 40)))
        db.commit(); flash('✅ Class added.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close(); return redirect(url_for('school_settings'))

@app.route('/school/settings/subject/add', methods=['POST'])
@school_admin_required
@login_required
def add_subject():
    db=get_db(); f=request.form; school_id=session['school_id']
    try:
        db.execute("INSERT INTO subjects (school_id,name,code,is_core) VALUES (?,?,?,?)",
                   (school_id,f['name'],f['code'].upper(),int(f.get('is_core',1))))
        db.commit(); flash('✅ Subject added.','success')
    except Exception as e: flash(f'❌ {str(e)}','error')
    db.close(); return redirect(url_for('school_settings'))

# ── Change Password (for any logged-in user) ──────────────────────────────────
@app.route('/school/change-password', methods=['GET','POST'])
@login_required
def change_password():
    school = get_school()
    if request.method == 'POST':
        f = request.form
        current  = f.get('current_password','')
        new_pw   = f.get('new_password','')
        confirm  = f.get('confirm_password','')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=? AND school_id=?",
                          (session['user_id'], session['school_id'])).fetchone()
        if not user or not check_password(current, user['password_hash']):
            db.close()
            flash('❌ Current password is incorrect.','error')
            return redirect(url_for('change_password'))
        if len(new_pw) < 6:
            db.close()
            flash('❌ New password must be at least 6 characters.','error')
            return redirect(url_for('change_password'))
        if new_pw != confirm:
            db.close()
            flash('❌ Passwords do not match.','error')
            return redirect(url_for('change_password'))
        db.execute("UPDATE users SET password_hash=? WHERE id=? AND school_id=?",
                   (hash_password(new_pw), session['user_id'], session['school_id']))
        db.commit(); db.close()
        flash('✅ Password changed successfully!','success')
        return redirect(url_for('school_dashboard'))
    return render_template('school/change_password.html', school=school)


# ── Save grading scale ────────────────────────────────────────────────────────
@app.route('/school/settings/grading', methods=['POST'])
@school_admin_required
@login_required
def save_grading():
    import json as _json
    school_id = session['school_id']
    db = get_db()
    f  = request.get_json(force=True)

    grades_json      = _json.dumps(f.get('grades', []))
    agg_subjects     = f.get('aggregate_subjects', 'best6')
    agg_distinction  = int(f.get('agg_distinction', 12))
    agg_credit       = int(f.get('agg_credit',      18))
    agg_pass         = int(f.get('agg_pass',         24))
    cs_max           = int(f.get('class_score_max',  40))
    es_max           = int(f.get('exam_score_max',   60))

    # Validate totals add up to 100
    if cs_max + es_max != 100:
        db.close()
        return jsonify({'status':'error',
                        'message':f'Class score max ({cs_max}) + Exam score max ({es_max}) must equal 100.'}), 400

    # Validate grades: at least 2 bands, points must be unique positive integers
    grades = f.get('grades', [])
    if len(grades) < 2:
        db.close()
        return jsonify({'status':'error','message':'You need at least 2 grade bands.'}), 400
    for g in grades:
        if not g.get('letter','').strip():
            db.close()
            return jsonify({'status':'error','message':'Every grade band needs a letter (e.g. A1, B, Pass).'}), 400

    # Auto-create table if it doesn't exist (upgrade from older install)
    db.execute("""CREATE TABLE IF NOT EXISTS grading_scales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL UNIQUE,
        grades_json TEXT NOT NULL,
        aggregate_subjects TEXT DEFAULT 'best6',
        agg_distinction INTEGER DEFAULT 12,
        agg_credit       INTEGER DEFAULT 18,
        agg_pass         INTEGER DEFAULT 24,
        class_score_max  INTEGER DEFAULT 40,
        exam_score_max   INTEGER DEFAULT 60,
        FOREIGN KEY(school_id) REFERENCES schools(id)
    )""")
    db.execute("""INSERT INTO grading_scales
        (school_id, grades_json, aggregate_subjects,
         agg_distinction, agg_credit, agg_pass, class_score_max, exam_score_max)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(school_id) DO UPDATE SET
            grades_json=excluded.grades_json,
            aggregate_subjects=excluded.aggregate_subjects,
            agg_distinction=excluded.agg_distinction,
            agg_credit=excluded.agg_credit,
            agg_pass=excluded.agg_pass,
            class_score_max=excluded.class_score_max,
            exam_score_max=excluded.exam_score_max""",
        (school_id, grades_json, agg_subjects,
         agg_distinction, agg_credit, agg_pass, cs_max, es_max))
    db.commit(); db.close()
    return jsonify({'status':'ok'})

@app.route('/school/settings/grading/reset', methods=['POST'])
@school_admin_required
@login_required
def reset_grading():
    school_id = session['school_id']
    db = get_db()
    db.execute("DELETE FROM grading_scales WHERE school_id=?", (school_id,))
    db.commit(); db.close()
    return jsonify({'status':'ok'})


# ── Class & Subject inline edit/delete ───────────────────────────────────────

@app.route('/school/settings/class/<int:cid>/edit', methods=['POST'])
@school_admin_required
@login_required
def edit_class(cid):
    db = get_db(); f = request.form; school_id = session['school_id']
    try:
        db.execute("""UPDATE classes SET name=?,level=?,capacity=?,class_teacher_id=?
                      WHERE id=? AND school_id=?""",
            (f['name'], f.get('level','JHS'),
             int(f.get('capacity', 40) or 40),
             int(f['teacher_id']) if f.get('teacher_id') else None,
             cid, school_id))
        db.commit()
        db.close()
        return jsonify({'status':'ok'})
    except Exception as e:
        db.close()
        return jsonify({'status':'error','message':str(e)}), 400

@app.route('/school/settings/class/<int:cid>/delete', methods=['POST'])
@school_admin_required
@login_required
def delete_class(cid):
    school_id = session['school_id']
    db = get_db()
    # Safety: block if students are enrolled
    count = db.execute(
        "SELECT COUNT(*) as n FROM students WHERE class_id=? AND school_id=? AND is_active=1",
        (cid, school_id)
    ).fetchone()['n']
    if count > 0:
        db.close()
        return jsonify({'status':'error',
                        'message': f'Cannot delete — {count} student(s) are enrolled in this class. Move them first.'}), 400
    db.execute("DELETE FROM classes WHERE id=? AND school_id=?", (cid, school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok'})

@app.route('/school/settings/subject/<int:sid>/edit', methods=['POST'])
@school_admin_required
@login_required
def edit_subject(sid):
    db = get_db(); f = request.form; school_id = session['school_id']
    try:
        db.execute("""UPDATE subjects SET name=?,code=?,is_core=?
                      WHERE id=? AND school_id=?""",
            (f['name'], f['code'].upper(), int(f.get('is_core', 1)),
             sid, school_id))
        db.commit(); db.close()
        return jsonify({'status':'ok'})
    except Exception as e:
        db.close()
        return jsonify({'status':'error','message':str(e)}), 400

@app.route('/school/settings/subject/<int:sid>/delete', methods=['POST'])
@school_admin_required
@login_required
def delete_subject(sid):
    school_id = session['school_id']
    db = get_db()
    # Safety: block if scores exist for this subject
    count = db.execute(
        "SELECT COUNT(*) as n FROM scores WHERE subject_id=? AND school_id=?",
        (sid, school_id)
    ).fetchone()['n']
    if count > 0:
        db.close()
        return jsonify({'status':'error',
                        'message': f'Cannot delete — {count} score record(s) exist for this subject.'}), 400
    db.execute("DELETE FROM subjects WHERE id=? AND school_id=?", (sid, school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok'})



# ══════════════════════════════════════════════════════════════════════════════
# ── ANALYTICS ─────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/school/analytics')
@login_required
def analytics():
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()
    tc        = get_teacher_classes()

    # class filter (teacher restriction)
    if tc is not None:
        classes = db.execute(
            f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc)) if tc else '0'}) ORDER BY name",
            [school_id] + (tc or [])
        ).fetchall()
    else:
        classes = db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school_id,)).fetchall()

    cf   = request.args.get('class_id', '')
    year = request.args.get('year', school.get('current_year', '2025/2026'))

    if tc is not None and cf and int(cf) not in (tc or []):
        cf = str(tc[0]) if tc else ''
    if tc is not None and not cf and tc:
        cf = str(tc[0])

    subjects = db.execute("SELECT * FROM subjects WHERE school_id=? ORDER BY is_core DESC, name", (school_id,)).fetchall()

    # ── Term comparison — avg per subject per term ────────────────────────────
    term_avgs = []  # [{name, t1, t2, t3}]
    if cf:
        for subj in subjects:
            row = {'id': subj['id'], 'name': subj['name'], 'code': subj['code']}
            for t in [1, 2, 3]:
                r = db.execute("""
                    SELECT AVG(ROUND(sc.class_score+sc.exam_score,1)) as avg FROM scores sc
                    JOIN students st ON st.id=sc.student_id
                    WHERE sc.school_id=? AND sc.subject_id=? AND sc.term=?
                      AND sc.academic_year=? AND st.class_id=? AND st.is_active=1
                """, (school_id, subj['id'], t, year, cf)).fetchone()
                row[f't{t}'] = round(r['avg'], 1) if r['avg'] else None
            if any(row.get(f't{t}') is not None for t in [1,2,3]):
                term_avgs.append(row)

    # ── Overall class averages across all terms ───────────────────────────────
    class_avgs = []
    for cls in classes:
        r = db.execute("""
            SELECT AVG(ROUND(sc.class_score+sc.exam_score,1)) as avg, COUNT(DISTINCT sc.student_id) as stu_count
            FROM scores sc JOIN students st ON st.id=sc.student_id
            WHERE sc.school_id=? AND st.class_id=? AND sc.academic_year=? AND st.is_active=1
        """, (school_id, cls['id'], year)).fetchone()
        class_avgs.append({
            'name': cls['name'],
            'avg': round(r['avg'], 1) if r['avg'] else 0,
            'count': r['stu_count'] or 0,
        })

    # ── Pass / Fail summary (per class, current selected term or term 1) ─────
    sel_term = int(request.args.get('term', school.get('current_term', 1)))
    pass_fail = []
    q_classes = [db.execute("SELECT * FROM classes WHERE id=?", (cf,)).fetchone()] if cf else classes
    for cls in q_classes:
        if not cls: continue
        students_in_class = db.execute("""
            SELECT st.id,
                   COUNT(sc.id) as subj_count,
                   SUM(CASE WHEN ROUND(sc.class_score+sc.exam_score,1) >= 50 THEN 1 ELSE 0 END) as passed_subjs
            FROM students st
            LEFT JOIN scores sc ON sc.student_id=st.id AND sc.school_id=? AND sc.term=? AND sc.academic_year=?
            WHERE st.class_id=? AND st.school_id=? AND st.is_active=1
            GROUP BY st.id
        """, (school_id, sel_term, year, cls['id'], school_id)).fetchall()

        total = len(students_in_class)
        full_pass = sum(1 for s in students_in_class if s['subj_count'] > 0 and s['passed_subjs'] == s['subj_count'])
        partial   = sum(1 for s in students_in_class if s['subj_count'] > 0 and 0 < s['passed_subjs'] < s['subj_count'])
        failed    = sum(1 for s in students_in_class if s['subj_count'] > 0 and s['passed_subjs'] == 0)
        no_scores = sum(1 for s in students_in_class if s['subj_count'] == 0)

        pass_fail.append({
            'class': cls['name'],
            'total': total,
            'full_pass': full_pass,
            'partial': partial,
            'failed': failed,
            'no_scores': no_scores,
            'pass_rate': round((full_pass / total * 100) if total > 0 else 0, 1),
        })

    # ── Top performers ────────────────────────────────────────────────────────
    top_q = """
        SELECT st.first_name||' '||st.last_name as name, cl.name as class_name,
               SUM(ROUND(sc.class_score+sc.exam_score,1)) as grand_total, COUNT(sc.id) as subj_count
        FROM students st
        JOIN scores sc ON sc.student_id=st.id AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
        LEFT JOIN classes cl ON cl.id=st.class_id
        WHERE st.school_id=? AND st.is_active=1
    """
    top_params = [sel_term, year, school_id, school_id]
    if cf:
        top_q += " AND st.class_id=?"
        top_params.append(cf)
    top_q += " GROUP BY st.id ORDER BY grand_total DESC LIMIT 10"
    top_students = db.execute(top_q, top_params).fetchall()

    db.close()
    return render_template('school/analytics.html',
        school=school, classes=classes, subjects=subjects,
        class_filter=cf, year=year, sel_term=sel_term,
        term_avgs=term_avgs, class_avgs=class_avgs,
        pass_fail=pass_fail, top_students=top_students,
        is_teacher=(tc is not None),
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── BULK OPERATIONS ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/school/bulk')
@school_admin_required
@login_required
def bulk_ops():
    school_id = session['school_id']
    school    = get_school()
    db        = get_db()
    classes   = db.execute("""
        SELECT cl.*, COUNT(st.id) as student_count
        FROM classes cl LEFT JOIN students st ON st.class_id=cl.id AND st.is_active=1
        WHERE cl.school_id=? GROUP BY cl.id ORDER BY cl.name
    """, (school_id,)).fetchall()
    db.close()
    return render_template('school/bulk_ops.html', school=school, classes=classes)


@app.route('/school/bulk/promote', methods=['POST'])
@school_admin_required
@login_required
def bulk_promote():
    """Promote students from one class to another in bulk."""
    school_id = session['school_id']
    f         = request.form
    from_id   = int(f.get('from_class_id', 0))
    to_id     = int(f.get('to_class_id', 0))
    if not from_id or not to_id or from_id == to_id:
        return jsonify({'status': 'error', 'message': 'Select two different classes.'}), 400
    db = get_db()
    # Verify both classes belong to this school
    fc = db.execute("SELECT name FROM classes WHERE id=? AND school_id=?", (from_id, school_id)).fetchone()
    tc2 = db.execute("SELECT name FROM classes WHERE id=? AND school_id=?", (to_id, school_id)).fetchone()
    if not fc or not tc2:
        db.close()
        return jsonify({'status': 'error', 'message': 'Invalid class selection.'}), 400
    result = db.execute(
        "UPDATE students SET class_id=? WHERE class_id=? AND school_id=? AND is_active=1",
        (to_id, from_id, school_id)
    )
    moved = result.rowcount
    db.commit(); db.close()
    return jsonify({'status': 'ok', 'moved': moved,
                    'message': f'{moved} student(s) promoted from {fc["name"]} → {tc2["name"]}'})


@app.route('/school/bulk/promote-all', methods=['POST'])
@school_admin_required
@login_required
def bulk_promote_all():
    """Promote every class to the next according to a JSON mapping."""
    school_id = session['school_id']
    mapping   = request.get_json()  # [{from_id, to_id}, ...]
    if not mapping:
        return jsonify({'status': 'error', 'message': 'No mapping provided.'}), 400
    db = get_db()
    results = []
    for m in mapping:
        from_id = int(m.get('from_id', 0))
        to_id   = int(m.get('to_id', 0))
        if not from_id or not to_id or from_id == to_id:
            continue
        fc  = db.execute("SELECT name FROM classes WHERE id=? AND school_id=?", (from_id, school_id)).fetchone()
        tc3 = db.execute("SELECT name FROM classes WHERE id=? AND school_id=?", (to_id,   school_id)).fetchone()
        if not fc or not tc3: continue
        r = db.execute(
            "UPDATE students SET class_id=? WHERE class_id=? AND school_id=? AND is_active=1",
            (to_id, from_id, school_id)
        )
        results.append({'from': fc['name'], 'to': tc3['name'], 'moved': r.rowcount})
    db.commit(); db.close()
    total = sum(r['moved'] for r in results)
    return jsonify({'status': 'ok', 'results': results, 'total': total})


@app.route('/school/bulk/set-term', methods=['POST'])
@school_admin_required
@login_required
def bulk_set_term():
    """Advance the school's current term (end-of-term rollover)."""
    school_id = session['school_id']
    f = request.form
    new_term = int(f.get('new_term', 1))
    new_year = f.get('new_year', '')
    db = get_db()
    if new_year:
        db.execute("UPDATE schools SET current_term=?, current_year=? WHERE id=?",
                   (new_term, new_year, school_id))
    else:
        db.execute("UPDATE schools SET current_term=? WHERE id=?", (new_term, school_id))
    db.commit(); db.close()
    return jsonify({'status': 'ok', 'term': new_term, 'year': new_year})


# ══════════════════════════════════════════════════════════════════════════════
# ── PLATFORM ADMIN — enhanced ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/platform/schools/<int:sid>/edit', methods=['GET', 'POST'])
@platform_admin_required
def edit_school(sid):
    db = get_db()
    school = db.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not school:
        db.close(); flash('School not found.', 'error')
        return redirect(url_for('platform_dashboard'))
    if request.method == 'POST':
        f = request.form
        try:
            db.execute("""UPDATE schools SET name=?,short_name=?,address=?,phone=?,email=?,
                motto=?,subscription_plan=?,subscription_status=?,
                subscription_expires=?,max_students=?,current_term=?,current_year=?
                WHERE id=?""",
                (f['name'], f['short_name'], f.get('address',''), f.get('phone',''),
                 f.get('email',''), f.get('motto',''),
                 f.get('plan','basic'), f.get('status','active'),
                 f.get('expires','') or None, int(f.get('max_students',200)),
                 int(f.get('current_term',1)), f.get('current_year','2025/2026'), sid))
            db.commit()
            flash('✅ School updated.', 'success')
            return redirect(url_for('platform_dashboard'))
        except Exception as e:
            flash(f'❌ {e}', 'error')
    db.close()
    return render_template('admin/edit_school.html', school=school)


@app.route('/platform/schools/<int:sid>/stats')
@platform_admin_required
def school_stats_api(sid):
    """JSON stats for a single school — used in platform dashboard."""
    db = get_db()
    s = {
        'students':  db.execute("SELECT COUNT(*) FROM students WHERE school_id=? AND is_active=1", (sid,)).fetchone()[0],
        'teachers':  db.execute("SELECT COUNT(*) FROM users WHERE school_id=? AND role='teacher'", (sid,)).fetchone()[0],
        'reports':   db.execute("SELECT COUNT(*) FROM email_log WHERE school_id=? AND status='sent'", (sid,)).fetchone()[0],
        'fees_paid': db.execute("SELECT COALESCE(SUM(amount_paid),0) FROM fees WHERE school_id=?", (sid,)).fetchone()[0],
    }
    db.close()
    return jsonify(s)



# ══════════════════════════════════════════════════════════════════════════════
# ── SUBSCRIPTION / PAYMENT SYSTEM ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/school/subscription')
@login_required
def subscription_page():
    """School admin views their subscription status and can submit a payment."""
    school_id = session['school_id']
    school    = get_school()
    cfg       = get_platform_settings()
    db        = get_db()

    days_left, is_active = subscription_days_left(school)

    # Recent payments for this school
    payments = db.execute("""
        SELECT * FROM subscription_payments
        WHERE school_id=? ORDER BY submitted_at DESC LIMIT 10
    """, (school_id,)).fetchall()

    # Any pending payment?
    pending = db.execute("""
        SELECT id FROM subscription_payments
        WHERE school_id=? AND status='pending' LIMIT 1
    """, (school_id,)).fetchone()

    db.close()

    # Pricing grid for the school's plan
    plan = school.get('subscription_plan','basic')
    pricing = {
        'termly': float(cfg.get(f'price_{plan}_termly', 150)),
        'annual': float(cfg.get(f'price_{plan}_annual', 400)),
    }

    years = ['2025/2026','2026/2027','2027/2028']

    return render_template('school/subscription.html',
        school=school, cfg=cfg, days_left=days_left,
        is_active=is_active, payments=[dict(p) for p in payments],
        has_pending=bool(pending), pricing=pricing, years=years,
    )


@app.route('/school/subscription/pay', methods=['POST'])
@login_required
def submit_payment():
    """School submits proof of payment for review."""
    school_id = session['school_id']
    f = request.form
    db = get_db()

    # Prevent duplicate pending submissions
    existing = db.execute("""
        SELECT id FROM subscription_payments
        WHERE school_id=? AND status='pending'
    """, (school_id,)).fetchone()
    if existing:
        db.close()
        flash('❌ You already have a pending payment under review. Please wait for approval.', 'error')
        return redirect(url_for('subscription_page'))

    period_type   = f.get('period_type', 'termly')
    payment_method = f.get('payment_method', 'momo_mtn')
    reference     = f.get('reference', '').strip()
    amount        = float(f.get('amount', 0) or 0)
    year          = f.get('academic_year', '')
    term          = f.get('term', None)
    notes         = f.get('notes', '').strip()

    if not reference:
        db.close()
        flash('❌ Transaction reference / receipt number is required.', 'error')
        return redirect(url_for('subscription_page'))
    if amount <= 0:
        db.close()
        flash('❌ Amount must be greater than 0.', 'error')
        return redirect(url_for('subscription_page'))

    school = db.execute("SELECT subscription_plan FROM schools WHERE id=?", (school_id,)).fetchone()
    plan = school['subscription_plan'] if school else 'basic'

    db.execute("""
        INSERT INTO subscription_payments
        (school_id, plan, period_type, amount_paid, payment_method,
         reference, academic_year, term, notes, status)
        VALUES (?,?,?,?,?,?,?,?,?,'pending')
    """, (school_id, plan, period_type, amount, payment_method,
          reference, year, int(term) if term else None, notes))
    db.commit(); db.close()

    flash('✅ Payment submitted! Our team will review and activate your subscription within 24 hours.', 'success')
    return redirect(url_for('subscription_page'))


# ── Platform admin: payments queue ───────────────────────────────────────────
@app.route('/platform/payments')
@platform_admin_required
def platform_payments():
    db  = get_db()
    cfg = get_platform_settings()

    payments = db.execute("""
        SELECT sp.*, sc.name as school_name, sc.short_name,
               sc.subscription_plan, sc.subscription_status,
               sc.subscription_expires
        FROM subscription_payments sp
        JOIN schools sc ON sc.id = sp.school_id
        ORDER BY CASE sp.status WHEN 'pending' THEN 0 ELSE 1 END,
                 sp.submitted_at DESC
    """).fetchall()

    pending_count = db.execute(
        "SELECT COUNT(*) FROM subscription_payments WHERE status='pending'"
    ).fetchone()[0]

    db.close()
    return render_template('admin/payments.html',
        payments=[dict(p) for p in payments],
        pending_count=pending_count, cfg=cfg,
    )


@app.route('/platform/payments/<int:pid>/approve', methods=['POST'])
@platform_admin_required
def approve_payment(pid):
    """Approve a payment — extends the school's subscription."""
    from datetime import datetime, timedelta
    db  = get_db()
    pay = db.execute("SELECT * FROM subscription_payments WHERE id=?", (pid,)).fetchone()
    if not pay or pay['status'] != 'pending':
        db.close()
        return jsonify({'status':'error','message':'Payment not found or already reviewed.'}), 400

    school = db.execute("SELECT * FROM schools WHERE id=?", (pay['school_id'],)).fetchone()
    if not school:
        db.close()
        return jsonify({'status':'error','message':'School not found.'}), 400

    # Calculate new expiry
    # Start from current expiry if still in future, else from today
    existing_exp = school['subscription_expires'] or ''
    try:
        base_date = datetime.strptime(existing_exp[:10], '%Y-%m-%d')
        if base_date < datetime.now():
            base_date = datetime.now()
    except Exception:
        base_date = datetime.now()

    if pay['period_type'] == 'annual':
        new_expiry = base_date + timedelta(days=365)
    else:
        # Termly = ~4 months (one school term)
        new_expiry = base_date + timedelta(days=122)

    exp_str = new_expiry.strftime('%Y-%m-%d')

    # Update school
    db.execute("""
        UPDATE schools
        SET subscription_status='active',
            subscription_expires=?,
            subscription_plan=?
        WHERE id=?
    """, (exp_str, pay['plan'], pay['school_id']))

    # Mark payment approved
    db.execute("""
        UPDATE subscription_payments
        SET status='approved', reviewed_at=datetime('now'),
            reviewed_by=?, extends_to=?
        WHERE id=?
    """, (session.get('username','admin'), exp_str, pid))

    db.commit(); db.close()
    return jsonify({'status':'ok', 'expires': exp_str,
                    'message': f'✅ Payment approved. Subscription extended to {exp_str}.'})


@app.route('/platform/payments/<int:pid>/reject', methods=['POST'])
@platform_admin_required
def reject_payment(pid):
    db  = get_db()
    pay = db.execute("SELECT * FROM subscription_payments WHERE id=?", (pid,)).fetchone()
    if not pay or pay['status'] != 'pending':
        db.close()
        return jsonify({'status':'error','message':'Payment not found or already reviewed.'}), 400

    reason = request.get_json(silent=True) or {}
    reason_text = reason.get('reason','').strip() or 'No reason given.'

    db.execute("""
        UPDATE subscription_payments
        SET status='rejected', reviewed_at=datetime('now'),
            reviewed_by=?, rejection_reason=?
        WHERE id=?
    """, (session.get('username','admin'), reason_text, pid))
    db.commit(); db.close()
    return jsonify({'status':'ok','message':'Payment rejected.'})


@app.route('/platform/settings/payment', methods=['GET','POST'])
@platform_admin_required
def payment_settings():
    """Platform admin edits pricing and payment account details."""
    cfg = get_platform_settings()
    if request.method == 'POST':
        f  = request.form
        db = get_db()
        keys = [
            'price_basic_termly','price_standard_termly','price_premium_termly',
            'price_basic_annual','price_standard_annual','price_premium_annual',
            'momo_mtn_number','momo_mtn_name',
            'momo_vodafone_number','momo_vodafone_name',
            'momo_at_number','momo_at_name',
            'bank_name','bank_account_name','bank_account_number',
            'bank_branch','bank_swift',
            'grace_period_days','support_whatsapp','support_email',
        ]
        for key in keys:
            val = f.get(key,'').strip()
            if val:
                db.execute("INSERT OR REPLACE INTO platform_settings (key,value) VALUES (?,?)",
                           (key, val))
        db.commit(); db.close()
        flash('✅ Payment settings saved.','success')
        return redirect(url_for('payment_settings'))
    return render_template('admin/payment_settings.html', cfg=cfg)



# ══════════════════════════════════════════════════════════════════════════════
# ── CLASS REGISTER ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

@app.route('/school/register')
@login_required
def register_home():
    """Landing page — pick a class and date, then take the register."""
    school_id = session['school_id']
    school    = get_school()
    tc        = get_teacher_classes()
    db        = get_db()

    if tc is not None:
        classes = db.execute(
            f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc)) if tc else '0'}) ORDER BY name",
            [school_id] + (tc or [])
        ).fetchall() if tc else []
    else:
        classes = db.execute(
            "SELECT * FROM classes WHERE school_id=? ORDER BY name", (school_id,)
        ).fetchall()

    # Recent register dates (last 14 days with any entry)
    recent = db.execute("""
        SELECT DISTINCT date, class_id,
               COUNT(*) as total,
               SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN status='absent'  THEN 1 ELSE 0 END) as absent
        FROM daily_register
        WHERE school_id=? AND date >= date('now','-14 days')
        GROUP BY date, class_id ORDER BY date DESC, class_id
        LIMIT 30
    """, (school_id,)).fetchall()

    # Get class name map
    class_map = {c['id']: c['name'] for c in classes}
    if not tc:
        all_cls = db.execute("SELECT id,name FROM classes WHERE school_id=?", (school_id,)).fetchall()
        for c in all_cls: class_map[c['id']] = c['name']

    today = _date.today().isoformat()
    db.close()
    return render_template('school/register_home.html',
        school=school, classes=[dict(c) for c in classes],
        recent=[dict(r) for r in recent], class_map=class_map,
        today=today, is_teacher=(tc is not None),
    )


@app.route('/school/register/take')
@login_required
def take_register():
    """Mobile-friendly register-taking page for a class on a date."""
    school_id = session['school_id']
    school    = get_school()
    tc        = get_teacher_classes()
    db        = get_db()

    class_id = request.args.get('class_id', '', type=int)
    reg_date = request.args.get('date', _date.today().isoformat())

    # Teacher restriction
    if tc is not None and class_id not in (tc or []):
        flash('❌ You can only take the register for your assigned class.', 'error')
        return redirect(url_for('register_home'))

    cls = db.execute("SELECT * FROM classes WHERE id=? AND school_id=?",
                     (class_id, school_id)).fetchone()
    if not cls:
        flash('Class not found.', 'error')
        return redirect(url_for('register_home'))

    # Get students in class
    students = db.execute("""
        SELECT st.*, COALESCE(dr.status,'present') as reg_status, dr.note as reg_note
        FROM students st
        LEFT JOIN daily_register dr
            ON dr.student_id=st.id AND dr.class_id=? AND dr.date=? AND dr.school_id=?
        WHERE st.class_id=? AND st.is_active=1
        ORDER BY st.last_name, st.first_name
    """, (class_id, reg_date, school_id, class_id)).fetchall()

    # Already submitted today?
    is_submitted = db.execute("""
        SELECT COUNT(*) FROM daily_register
        WHERE school_id=? AND class_id=? AND date=?
    """, (school_id, class_id, reg_date)).fetchone()[0] > 0

    # Summary for the date (if already taken)
    summary = None
    if is_submitted:
        summary = db.execute("""
            SELECT
              SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) as present,
              SUM(CASE WHEN status='absent'  THEN 1 ELSE 0 END) as absent,
              SUM(CASE WHEN status='late'    THEN 1 ELSE 0 END) as late,
              SUM(CASE WHEN status='excused' THEN 1 ELSE 0 END) as excused,
              COUNT(*) as total
            FROM daily_register
            WHERE school_id=? AND class_id=? AND date=?
        """, (school_id, class_id, reg_date)).fetchone()

    term  = school.get('current_term', 1)
    year  = school.get('current_year', '2025/2026')

    db.close()
    return render_template('school/take_register.html',
        school=school, cls=dict(cls),
        students=[dict(s) for s in students],
        reg_date=reg_date,
        is_submitted=is_submitted,
        summary=dict(summary) if summary else None,
        term=term, academic_year=year,
        is_teacher=(tc is not None),
    )


@app.route('/school/register/save', methods=['POST'])
@login_required
def save_register():
    """Save a full day's register for a class."""
    school_id  = session['school_id']
    tc         = get_teacher_classes()
    user_id    = session.get('user_id')

    # All params come as JSON from the mobile page
    body = request.get_json(silent=True) or {}
    class_id = int(body.get('class_id', 0))
    reg_date = body.get('date', _date.today().isoformat())
    term     = int(body.get('term', 1))
    year     = body.get('academic_year', '')
    entries  = body.get('entries', [])

    if not class_id:
        return jsonify({'status':'error','message':'class_id required.'}), 400

    if tc is not None and class_id not in (tc or []):
        return jsonify({'status':'error','message':'Not authorised for this class.'}), 403

    db = get_db()
    try:
        for entry in entries:
            sid    = int(entry.get('student_id', 0))
            status = entry.get('status', 'present')
            note   = (entry.get('note','') or '')[:200]
            if status not in ('present','absent','late','excused'): status = 'present'

            db.execute("""
                INSERT INTO daily_register
                    (school_id, class_id, student_id, date, term, academic_year,
                     status, note, marked_by)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(school_id,class_id,student_id,date)
                DO UPDATE SET status=excluded.status, note=excluded.note,
                              marked_by=excluded.marked_by,
                              marked_at=datetime('now')
            """, (school_id, class_id, sid, reg_date, term, year, status, note, user_id))

        # Auto-sync term summary
        _sync_attendance_summary(db, school_id, class_id, term, year)

        db.commit()
        db.close()
        return jsonify({'status':'ok','saved':len(entries)})
    except Exception as e:
        db.close()
        return jsonify({'status':'error','message':str(e)}), 500


@app.route('/school/register/sync', methods=['POST'])
@login_required
def sync_attendance():
    """Manually re-sync daily register → attendance term summary for a class/term."""
    school_id = session['school_id']
    f = request.get_json(silent=True) or request.form
    class_id  = int(f.get('class_id', 0) or 0)
    term      = int(f.get('term', 1) or 1)
    year      = f.get('academic_year', '') or get_school().get('current_year','')
    db = get_db()
    try:
        synced = _sync_attendance_summary(db, school_id, class_id, term, year)
        db.commit(); db.close()
        return jsonify({'status':'ok','synced_students':synced})
    except Exception as e:
        db.close()
        return jsonify({'status':'error','message':str(e)}), 500


def _sync_attendance_summary(db, school_id, class_id, term, year):
    """Recompute days_present/absent/total from daily_register → attendance table."""
    students = db.execute("""
        SELECT DISTINCT student_id FROM daily_register
        WHERE school_id=? AND class_id=? AND term=? AND academic_year=?
    """, (school_id, class_id, term, year)).fetchall()

    synced = 0
    for row in students:
        sid = row['student_id']
        counts = db.execute("""
            SELECT
              SUM(CASE WHEN status IN ('present','late') THEN 1 ELSE 0 END) as days_present,
              SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) as days_absent,
              COUNT(*) as total_days
            FROM daily_register
            WHERE school_id=? AND student_id=? AND class_id=?
              AND term=? AND academic_year=?
        """, (school_id, sid, class_id, term, year)).fetchone()

        db.execute("""
            INSERT INTO attendance
                (school_id,student_id,term,academic_year,days_present,days_absent,total_days)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(school_id,student_id,term,academic_year)
            DO UPDATE SET days_present=excluded.days_present,
                          days_absent=excluded.days_absent,
                          total_days=excluded.total_days
        """, (school_id, sid, term, year,
              counts['days_present'] or 0,
              counts['days_absent']  or 0,
              counts['total_days']   or 0))
        synced += 1
    return synced


@app.route('/school/register/history')
@login_required
def register_history():
    """View all register dates for a class, with drill-down."""
    school_id = session['school_id']
    school    = get_school()
    tc        = get_teacher_classes()
    db        = get_db()

    class_id  = request.args.get('class_id', '', type=int)
    term      = int(request.args.get('term', school.get('current_term', 1)))
    year      = request.args.get('year', school.get('current_year','2025/2026'))

    if tc is not None:
        classes = db.execute(
            f"SELECT * FROM classes WHERE school_id=? AND id IN ({','.join('?'*len(tc)) if tc else '0'}) ORDER BY name",
            [school_id] + (tc or [])
        ).fetchall() if tc else []
        if not class_id and classes:
            class_id = classes[0]['id']
        elif class_id and class_id not in (tc or []):
            class_id = classes[0]['id'] if classes else 0
    else:
        classes = db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school_id,)).fetchall()

    # All dates taken for this class/term
    dates = db.execute("""
        SELECT date,
               COUNT(*) as total,
               SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN status='absent'  THEN 1 ELSE 0 END) as absent,
               SUM(CASE WHEN status='late'    THEN 1 ELSE 0 END) as late
        FROM daily_register
        WHERE school_id=? AND class_id=? AND term=? AND academic_year=?
        GROUP BY date ORDER BY date DESC
    """, (school_id, class_id, term, year)).fetchall() if class_id else []

    # Student summary table
    student_summary = db.execute("""
        SELECT st.first_name||' '||st.last_name as name, st.student_id as sid,
               COUNT(*) as total_days,
               SUM(CASE WHEN dr.status='present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN dr.status='absent'  THEN 1 ELSE 0 END) as absent,
               SUM(CASE WHEN dr.status='late'    THEN 1 ELSE 0 END) as late,
               SUM(CASE WHEN dr.status='excused' THEN 1 ELSE 0 END) as excused
        FROM students st
        JOIN daily_register dr ON dr.student_id=st.id
            AND dr.class_id=? AND dr.term=? AND dr.academic_year=? AND dr.school_id=?
        WHERE st.school_id=? AND st.is_active=1
        GROUP BY st.id ORDER BY absent DESC, st.last_name
    """, (class_id, term, year, school_id, school_id)).fetchall() if class_id else []

    cls = db.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone() if class_id else None
    db.close()

    return render_template('school/register_history.html',
        school=school, classes=[dict(c) for c in classes],
        dates=[dict(d) for d in dates],
        student_summary=[dict(s) for s in student_summary],
        cls=dict(cls) if cls else None,
        class_id=class_id, term=term, year=year,
        is_teacher=(tc is not None),
    )


@app.route('/school/register/day')
@login_required
def register_day_detail():
    """JSON: all student statuses for a class on one day."""
    school_id = session['school_id']
    class_id  = request.args.get('class_id', type=int)
    reg_date  = request.args.get('date', '')
    db = get_db()
    rows = db.execute("""
        SELECT st.first_name||' '||st.last_name as name,
               st.student_id as sid, dr.status, dr.note
        FROM daily_register dr
        JOIN students st ON st.id=dr.student_id
        WHERE dr.school_id=? AND dr.class_id=? AND dr.date=?
        ORDER BY st.last_name
    """, (school_id, class_id, reg_date)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/platform/codes')
@platform_admin_required
def access_codes():
    db  = get_db()
    codes = db.execute("""
        SELECT ac.*, sc.name as school_name
        FROM access_codes ac
        LEFT JOIN schools sc ON sc.id=ac.school_id
        ORDER BY ac.created_at DESC
    """).fetchall()
    db.close()
    return render_template('admin/access_codes.html', codes=[dict(c) for c in codes])

@app.route('/platform/codes/generate', methods=['POST'])
@platform_admin_required
def generate_code():
    f = request.form
    db = get_db()
    qty         = min(int(f.get('qty', 1)), 50)
    plan        = f.get('plan', 'basic')
    period_type = f.get('period_type', 'termly')
    months      = int(f.get('months', 4))
    notes       = f.get('notes', '')
    generated   = []
    for _ in range(qty):
        code = _gen_code()
        db.execute("""INSERT INTO access_codes (code,plan,period_type,months,notes,created_by)
                      VALUES (?,?,?,?,?,?)""",
                   (code, plan, period_type, months, notes,
                    session.get('username','admin')))
        generated.append(code)
    db.commit(); db.close()
    log_activity('generate_codes', f'{qty} code(s) for {plan}/{period_type}')
    return jsonify({'status':'ok', 'codes': generated})

@app.route('/school/activate', methods=['GET','POST'])
@login_required
def activate_code():
    """School admin enters an access code to activate subscription."""
    school_id = session['school_id']
    if request.method == 'POST':
        code = request.form.get('code','').strip().upper()
        db   = get_db()
        ac   = db.execute(
            "SELECT * FROM access_codes WHERE code=? AND used=0", (code,)
        ).fetchone()
        if not ac:
            db.close()
            flash('❌ Invalid or already-used code.', 'error')
            return redirect(url_for('activate_code'))
        from datetime import datetime as _dt, timedelta as _td
        months = ac['months'] or 4
        school = db.execute("SELECT subscription_expires FROM schools WHERE id=?",
                            (school_id,)).fetchone()
        exp = school['subscription_expires'] or ''
        try:
            base = _dt.strptime(exp[:10], '%Y-%m-%d')
            if base < _dt.now(): base = _dt.now()
        except Exception: base = _dt.now()
        new_exp = (base + _td(days=int(months*30.5))).strftime('%Y-%m-%d')
        db.execute("""UPDATE schools SET subscription_status='active',
                      subscription_expires=?, subscription_plan=? WHERE id=?""",
                   (new_exp, ac['plan'], school_id))
        db.execute("""UPDATE access_codes SET used=1, used_at=datetime('now'),
                      school_id=? WHERE id=?""", (school_id, ac['id']))
        db.commit(); db.close()
        log_activity('activate_code', f'code={code}, expires={new_exp}')
        flash(f'✅ Subscription activated! Valid until {new_exp}.', 'success')
        return redirect(url_for('school_dashboard'))
    return render_template('school/activate_code.html', school=get_school())


# ══════════════════════════════════════════════════════════════════════════════
# ── PLATFORM: ACTIVITY LOG ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/platform/activity')
@platform_admin_required
def platform_activity():
    db = get_db()
    school_filter = request.args.get('school_id', '', type=int)
    q = """SELECT al.*, sc.name as school_name
           FROM activity_log al
           LEFT JOIN schools sc ON sc.id=al.school_id
           WHERE 1=1 """
    params = []
    if school_filter:
        q += " AND al.school_id=?"; params.append(school_filter)
    q += " ORDER BY al.created_at DESC LIMIT 500"
    logs  = db.execute(q, params).fetchall()
    schools = db.execute("SELECT id,name FROM schools ORDER BY name").fetchall()
    db.close()
    return render_template('admin/activity_log.html',
        logs=[dict(l) for l in logs],
        schools=[dict(s) for s in schools],
        school_filter=school_filter,
    )

@app.route('/platform/schools/<int:sid>/credentials')
@platform_admin_required
def school_credentials(sid):
    """Platform admin views all usernames + plain passwords for a school."""
    db = get_db()
    school = db.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not school:
        db.close(); return jsonify({'error':'not found'}), 404
    # We store sha256 hashes — we return them + allow admin to reset
    users = db.execute(
        "SELECT id,username,email,role,full_name,is_active,password_hash FROM users WHERE school_id=? ORDER BY role,username",
        (sid,)
    ).fetchall()
    parents = db.execute(
        "SELECT p.username,p.email,p.full_name,p.relation,p.password_hash,st.first_name||' '||st.last_name as student_name FROM parents p JOIN students st ON st.id=p.student_id WHERE p.school_id=? ORDER BY p.full_name",
        (sid,)
    ).fetchall()
    db.close()
    log_activity('view_credentials', f'Viewed credentials for school_id={sid}')
    return render_template('admin/school_credentials.html',
        school=dict(school),
        users=[dict(u) for u in users],
        parents=[dict(p) for p in parents],
    )

@app.route('/platform/schools/<int:sid>/reset-user/<int:uid>', methods=['POST'])
@platform_admin_required
def platform_reset_user(sid, uid):
    new_pw = request.form.get('password','school123')
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=? AND school_id=?",
               (hash_password(new_pw), uid, sid))
    db.commit(); db.close()
    log_activity('reset_user_pw', f'uid={uid} school={sid}')
    return jsonify({'status':'ok','new_password': new_pw})


# ══════════════════════════════════════════════════════════════════════════════
# ── PARENTS PORTAL ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/parent/login', methods=['GET','POST'])
def parent_login():
    if session.get('parent_id'):
        return redirect(url_for('parent_dashboard'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        school_code = request.form.get('school_code','').strip().upper()
        db = get_db()
        school = db.execute(
            "SELECT * FROM schools WHERE short_name=? AND subscription_status='active'",
            (school_code,)
        ).fetchone()
        if not school:
            error = 'School code not found or subscription inactive.'
            db.close()
        else:
            parent = db.execute(
                "SELECT * FROM parents WHERE username=? AND school_id=? AND is_active=1",
                (username, school['id'])
            ).fetchone()
            if parent and check_password(password, parent['password_hash']):
                session['parent_id']     = parent['id']
                session['parent_name']   = parent['full_name']
                session['parent_school'] = school['id']
                session['parent_student']= parent['student_id']
                db.execute("UPDATE parents SET last_login=datetime('now') WHERE id=?",
                           (parent['id'],))
                db.commit(); db.close()
                return redirect(url_for('parent_dashboard'))
            else:
                error = 'Invalid username or password.'
                db.close()
    return render_template('parent/login.html', error=error)

@app.route('/parent/logout')
def parent_logout():
    for k in ('parent_id','parent_name','parent_school','parent_student'):
        session.pop(k, None)
    return redirect(url_for('parent_login'))

@app.route('/parent')
@parent_required
def parent_dashboard():
    school_id  = session['parent_school']
    student_id = session['parent_student']
    db = get_db()
    school  = db.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
    student = db.execute("""
        SELECT st.*, cl.name as class_name FROM students st
        LEFT JOIN classes cl ON cl.id=st.class_id
        WHERE st.id=? AND st.school_id=?
    """, (student_id, school_id)).fetchone()
    if not student:
        db.close(); return redirect(url_for('parent_logout'))
    term = school['current_term']; year = school['current_year']
    scores = db.execute("""
        SELECT sc.total, su.name as subject_name, su.code
        FROM scores sc JOIN subjects su ON su.id=sc.subject_id
        WHERE sc.student_id=? AND sc.term=? AND sc.academic_year=? AND sc.school_id=?
        ORDER BY su.name
    """, (student_id, term, year, school_id)).fetchall()
    fees = db.execute("""
        SELECT * FROM fees WHERE student_id=? AND school_id=?
        ORDER BY term DESC, created_at DESC LIMIT 6
    """, (student_id, school_id)).fetchall()
    attendance = db.execute("""
        SELECT * FROM attendance WHERE student_id=? AND term=? AND academic_year=? AND school_id=?
    """, (student_id, term, year, school_id)).fetchone()
    remarks = db.execute("""
        SELECT * FROM remarks WHERE student_id=? AND term=? AND academic_year=? AND school_id=?
    """, (student_id, term, year, school_id)).fetchone()
    # Fee structure for student's class
    fee_structure = db.execute("""
        SELECT * FROM fee_structure
        WHERE school_id=? AND (class_id=? OR class_id IS NULL)
          AND term=? AND academic_year=?
        ORDER BY is_mandatory DESC, item_name
    """, (school_id, student['class_id'], term, year)).fetchall()
    db.close()
    return render_template('parent/dashboard.html',
        school=dict(school), student=dict(student),
        scores=[dict(s) for s in scores],
        fees=[dict(f) for f in fees],
        attendance=dict(attendance) if attendance else {},
        remarks=dict(remarks) if remarks else {},
        fee_structure=[dict(f) for f in fee_structure],
        term=term, year=year,
    )

@app.route('/parent/timetable')
@parent_required
def parent_timetable():
    school_id  = session['parent_school']
    student_id = session['parent_student']
    db = get_db()
    student = db.execute("SELECT class_id FROM students WHERE id=?", (student_id,)).fetchone()
    days = ['Monday','Tuesday','Wednesday','Thursday','Friday']
    timetable = {}
    if student:
        rows = db.execute("""
            SELECT tt.*,su.name as subject_name,
                   u.full_name as teacher_name
            FROM timetable tt
            JOIN subjects su ON su.id=tt.subject_id
            LEFT JOIN users u ON u.id=tt.teacher_id
            WHERE tt.class_id=? AND tt.school_id=?
            ORDER BY tt.start_time
        """, (student['class_id'], school_id)).fetchall()
        for r in rows:
            timetable.setdefault(r['day_of_week'], []).append(dict(r))
    school = db.execute("SELECT name,primary_color FROM schools WHERE id=?", (school_id,)).fetchone()
    db.close()
    return render_template('parent/timetable.html',
        timetable=timetable, days=days, school=dict(school))


# ── School admin: manage parents ──────────────────────────────────────────────
@app.route('/school/parents')
@school_admin_required
@login_required
def manage_parents():
    school_id = session['school_id']
    db = get_db()
    parents = db.execute("""
        SELECT p.*, st.first_name||' '||st.last_name as student_name,
               st.student_id as student_code, cl.name as class_name
        FROM parents p
        JOIN students st ON st.id=p.student_id
        LEFT JOIN classes cl ON cl.id=st.class_id
        WHERE p.school_id=? ORDER BY st.last_name
    """, (school_id,)).fetchall()
    students = db.execute("""
        SELECT st.id, st.first_name||' '||st.last_name as name,
               st.student_id as sid, cl.name as class_name
        FROM students st LEFT JOIN classes cl ON cl.id=st.class_id
        WHERE st.school_id=? AND st.is_active=1 ORDER BY st.last_name
    """, (school_id,)).fetchall()
    school = get_school()
    db.close()
    return render_template('school/parents.html',
        parents=[dict(p) for p in parents],
        students=[dict(s) for s in students],
        school=school,
    )

@app.route('/school/parents/add', methods=['POST'])
@school_admin_required
@login_required
def add_parent():
    school_id = session['school_id']
    f = request.form; db = get_db()
    try:
        username  = f['username'].strip()
        password  = f.get('password','parent123')
        student_id = int(f['student_id'])
        db.execute("""
            INSERT INTO parents (school_id,student_id,full_name,phone,email,username,
                                 password_hash,relation)
            VALUES (?,?,?,?,?,?,?,?)
        """, (school_id, student_id, f.get('full_name',''),
              f.get('phone',''), f.get('email',''),
              username, hash_password(password), f.get('relation','Parent')))
        db.commit()
        log_activity('add_parent', f'username={username}')
        flash(f'✅ Parent account created. Username: {username}  Password: {password}', 'success')
    except Exception as e:
        flash(f'❌ {e}', 'error')
    db.close()
    return redirect(url_for('manage_parents'))

@app.route('/school/parents/<int:pid>/reset', methods=['POST'])
@school_admin_required
@login_required
def reset_parent_password(pid):
    school_id = session['school_id']
    new_pw = request.form.get('password', 'parent123')
    db = get_db()
    db.execute("UPDATE parents SET password_hash=? WHERE id=? AND school_id=?",
               (hash_password(new_pw), pid, school_id))
    db.commit(); db.close()
    return jsonify({'status':'ok', 'new_password': new_pw})

@app.route('/school/parents/<int:pid>/toggle', methods=['POST'])
@school_admin_required
@login_required
def toggle_parent(pid):
    school_id = session['school_id']
    db = get_db()
    cur = db.execute("SELECT is_active FROM parents WHERE id=? AND school_id=?",
                     (pid, school_id)).fetchone()
    if cur:
        db.execute("UPDATE parents SET is_active=? WHERE id=?",
                   (0 if cur['is_active'] else 1, pid))
        db.commit()
    db.close()
    return jsonify({'status':'ok'})


# ══════════════════════════════════════════════════════════════════════════════
# ── FEE STRUCTURE (customisable per class/level) ──────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/school/fee-structure')
@school_admin_required
@login_required
def fee_structure_page():
    school_id = session['school_id']
    school    = get_school()
    db = get_db()
    term = int(request.args.get('term', school.get('current_term',1)))
    year = request.args.get('year', school.get('current_year','2025/2026'))
    classes = db.execute("SELECT * FROM classes WHERE school_id=? ORDER BY name", (school_id,)).fetchall()
    structure = db.execute("""
        SELECT fs.*, cl.name as class_name
        FROM fee_structure fs
        LEFT JOIN classes cl ON cl.id=fs.class_id
        WHERE fs.school_id=? AND fs.term=? AND fs.academic_year=?
        ORDER BY cl.name, fs.is_mandatory DESC, fs.item_name
    """, (school_id, term, year)).fetchall()
    # Summary per class
    summary = db.execute("""
        SELECT COALESCE(cl.name,'School-Wide') as class_name,
               SUM(fs.amount) as total, COUNT(*) as items,
               fs.class_id
        FROM fee_structure fs
        LEFT JOIN classes cl ON cl.id=fs.class_id
        WHERE fs.school_id=? AND fs.term=? AND fs.academic_year=?
        GROUP BY fs.class_id ORDER BY cl.name
    """, (school_id, term, year)).fetchall()
    db.close()
    return render_template('school/fee_structure.html',
        school=school, classes=[dict(c) for c in classes],
        structure=[dict(s) for s in structure],
        summary=[dict(s) for s in summary],
        term=term, year=year,
    )

@app.route('/school/fee-structure/save', methods=['POST'])
@school_admin_required
@login_required
def save_fee_structure():
    school_id = session['school_id']
    data = request.get_json(silent=True) or {}
    items = data.get('items', [])
    term  = int(data.get('term', 1))
    year  = data.get('year', '')
    db = get_db()
    try:
        for item in items:
            class_id = item.get('class_id') or None
            if class_id: class_id = int(class_id)
            amount = float(item.get('amount', 0) or 0)
            name   = str(item.get('item_name','')).strip()
            mandatory = int(item.get('is_mandatory', 1))
            if not name: continue
            db.execute("""
                INSERT INTO fee_structure
                    (school_id,class_id,term,academic_year,item_name,amount,is_mandatory)
                VALUES (?,?,?,?,?,?,?)
            """, (school_id, class_id, term, year, name, amount, mandatory))
        db.commit(); db.close()
        log_activity('save_fee_structure', f'term={term} year={year} {len(items)} items')
        return jsonify({'status':'ok'})
    except Exception as e:
        db.close()
        return jsonify({'status':'error','message':str(e)}), 500

@app.route('/school/fee-structure/<int:fid>/delete', methods=['POST'])
@school_admin_required
@login_required
def delete_fee_item(fid):
    db = get_db()
    db.execute("DELETE FROM fee_structure WHERE id=? AND school_id=?",
               (fid, session['school_id']))
    db.commit(); db.close()
    return jsonify({'status':'ok'})

@app.route('/school/fee-structure/copy', methods=['POST'])
@school_admin_required
@login_required
def copy_fee_structure():
    """Copy fee structure from one term to another."""
    school_id = session['school_id']
    f = request.form
    from_term = int(f.get('from_term',1))
    from_year = f.get('from_year','')
    to_term   = int(f.get('to_term',1))
    to_year   = f.get('to_year','')
    db = get_db()
    rows = db.execute("""
        SELECT class_id,item_name,amount,is_mandatory
        FROM fee_structure WHERE school_id=? AND term=? AND academic_year=?
    """, (school_id, from_term, from_year)).fetchall()
    for r in rows:
        db.execute("""
            INSERT OR IGNORE INTO fee_structure
                (school_id,class_id,term,academic_year,item_name,amount,is_mandatory)
            VALUES (?,?,?,?,?,?,?)
        """, (school_id, r['class_id'], to_term, to_year,
              r['item_name'], r['amount'], r['is_mandatory']))
    db.commit(); db.close()
    flash(f'✅ Copied {len(rows)} fee items to Term {to_term}, {to_year}.', 'success')
    return redirect(url_for('fee_structure_page', term=to_term, year=to_year))


# ══════════════════════════════════════════════════════════════════════════════
# ── SCHOOL EXPENSES ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
EXPENSE_CATEGORIES = [
    'Staff Salaries', 'Utilities', 'Maintenance & Repairs', 'Supplies & Stationery',
    'Transport', 'Food & Catering', 'IT & Technology', 'Events & Activities',
    'Books & Materials', 'Insurance', 'Bank Charges', 'Other',
]

@app.route('/school/expenses')
@school_admin_required
@login_required
def expenses_page():
    school_id = session['school_id']
    school    = get_school()
    db = get_db()
    term = int(request.args.get('term', school.get('current_term',1)))
    year = request.args.get('year', school.get('current_year','2025/2026'))
    cat  = request.args.get('category','')
    q = """SELECT e.*, u.full_name as recorded_by_name FROM school_expenses e
           LEFT JOIN users u ON u.id=e.recorded_by
           WHERE e.school_id=? AND e.term=? AND e.academic_year=?"""
    params = [school_id, term, year]
    if cat: q += " AND e.category=?"; params.append(cat)
    q += " ORDER BY e.expense_date DESC"
    expenses = db.execute(q, params).fetchall()
    # Category totals
    totals = db.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM school_expenses WHERE school_id=? AND term=? AND academic_year=?
        GROUP BY category ORDER BY total DESC
    """, (school_id, term, year)).fetchall()
    grand_total = sum(r['total'] for r in totals)
    # Income (total fees collected this term)
    fees_collected = db.execute("""
        SELECT COALESCE(SUM(amount_paid),0) as total
        FROM fees WHERE school_id=? AND term=? AND academic_year=?
    """, (school_id, term, year)).fetchone()['total']
    db.close()
    return render_template('school/expenses.html',
        school=school, expenses=[dict(e) for e in expenses],
        totals=[dict(t) for t in totals],
        grand_total=grand_total,
        fees_collected=fees_collected,
        categories=EXPENSE_CATEGORIES,
        term=term, year=year, cat_filter=cat,
    )

@app.route('/school/expenses/add', methods=['POST'])
@school_admin_required
@login_required
def add_expense():
    school_id = session['school_id']
    f = request.form; db = get_db()
    try:
        db.execute("""
            INSERT INTO school_expenses
                (school_id,category,description,amount,expense_date,term,academic_year,
                 receipt_ref,recorded_by)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (school_id, f['category'], f['description'],
              float(f['amount']), f['expense_date'],
              int(f['term']), f['academic_year'],
              f.get('receipt_ref',''), session.get('user_id')))
        db.commit()
        log_activity('add_expense', f"{f['category']}: GH₵{f['amount']}")
        flash('✅ Expense recorded.', 'success')
    except Exception as e:
        flash(f'❌ {e}', 'error')
    db.close()
    return redirect(url_for('expenses_page', term=f['term'], year=f['academic_year']))

@app.route('/school/expenses/<int:eid>/delete', methods=['POST'])
@school_admin_required
@login_required
def delete_expense(eid):
    db = get_db()
    db.execute("DELETE FROM school_expenses WHERE id=? AND school_id=?",
               (eid, session['school_id']))
    db.commit(); db.close()
    return jsonify({'status':'ok'})


# ══════════════════════════════════════════════════════════════════════════════
# ── SUBSCRIPTION: per-student pricing ────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/school/subscription/quote')
@login_required
def subscription_quote():
    """Return JSON quote for this school based on student count × price/student."""
    school_id = session['school_id']
    cfg = get_platform_settings()
    db  = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM students WHERE school_id=? AND is_active=1", (school_id,)
    ).fetchone()[0]
    db.close()
    pps_t = float(cfg.get('price_per_student_termly', 3))
    pps_a = float(cfg.get('price_per_student_annual', 8))
    min_t = float(cfg.get('min_charge_termly', 150))
    min_a = float(cfg.get('min_charge_annual', 400))
    termly = max(count * pps_t, min_t)
    annual = max(count * pps_a, min_a)
    return jsonify({
        'students': count,
        'price_per_student_termly': pps_t,
        'price_per_student_annual': pps_a,
        'termly': round(termly, 2),
        'annual': round(annual, 2),
        'min_termly': min_t, 'min_annual': min_a,
    })



if __name__=='__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print("\n"+"="*55)
    print("  🏫  LUCID IT HUB — SaaS SCHOOL SYSTEM")
    print("="*55)
    print(f"  Platform Admin → http://127.0.0.1:{port}/login")
    print("  Username: superadmin  |  Password: admin123")
    print("  School Login: schooladmin / school123")
    print("="*55+"\n")
    app.run(debug=False, host='0.0.0.0', port=port)

# ── Serve uploaded files (logos, photos) ─────────────────────────────────────
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded logos and photos — works on Windows and Linux."""
    full_path = os.path.join(UPLOADS, filename)
    if not os.path.exists(full_path):
        abort(404)
    return send_file(full_path)

