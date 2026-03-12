#!/usr/bin/env python3
"""
Lucid IT Hub — SaaS School Management System
One-command startup. Installs dependencies automatically.
"""
import subprocess, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Auto-install dependencies
for dep in ['flask','reportlab','pillow','werkzeug']:
    try: __import__(dep.replace('pillow','PIL'))
    except ImportError:
        print(f"Installing {dep}...")
        subprocess.check_call([sys.executable,'-m','pip','install',dep])

from database import init_db
init_db()

from app import app

print("\n" + "="*60)
print("  🏫  LUCID IT HUB — SaaS SCHOOL MANAGEMENT SYSTEM v2.0")
print("="*60)
print("  ✅  Database ready")
print("  🌐  Open → http://127.0.0.1:5000")
print()
print("  👤  Platform Admin:  superadmin / admin123")
print("  🏫  School Admin:    schooladmin / school123")
print()
print("  📋  Features:")
print("       • Multi-school SaaS with separate logins")
print("       • WAEC grading + report cards with school logo")
print("       • Student photos on report cards")
print("       • Bulk email + SMS to parents")
print("       • Analytics dashboard with charts")
print("       • Class broadsheet (landscape PDF)")
print("       • Fee management & tracking")
print("       • Timetable management")
print("       • Teacher accounts & roles")
print()
print("  ⏹️   Press Ctrl+C to stop")
print("="*60 + "\n")
app.run(debug=True, host='0.0.0.0', port=5000)
