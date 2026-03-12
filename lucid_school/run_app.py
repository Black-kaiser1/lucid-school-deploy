"""
╔══════════════════════════════════════════════════════╗
║  LUCID SCHOOL SYSTEM — Desktop Launcher              ║
║  Double-click run_app.bat (Windows) to start         ║
╚══════════════════════════════════════════════════════╝

Opens the school management system as a native desktop
window — no browser required.

Dependencies (auto-installed on first run):
  pip install flask pywebview

If pywebview is not available, falls back to opening
the system's default web browser automatically.
"""

import sys
import os
import socket
import threading
import time
import webbrowser
import subprocess

# ── Ensure we're in the app directory ────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

# ── Auto-install missing packages ─────────────────────────────────────────────
def ensure_packages():
    required = ['flask', 'reportlab', 'pywebview']
    missing  = []
    for pkg in required:
        import_name = 'webview' if pkg == 'pywebview' else pkg
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"📦 Installing: {', '.join(missing)} ...")
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--quiet'] + missing,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("✅ Packages installed.")
        except Exception as e:
            print(f"⚠️  Could not auto-install: {e}")
            print("   Run:  pip install " + ' '.join(missing))

ensure_packages()

# ── Find a free port ───────────────────────────────────────────────────────────
def find_free_port(start=5050, end=5150):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 5050

PORT = find_free_port()
URL  = f'http://127.0.0.1:{PORT}'

# ── Start Flask in background thread ──────────────────────────────────────────
def start_flask():
    from database import init_db
    from app import app

    init_db()
    # Silence Flask's default request logging in desktop mode
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    app.run(
        host='127.0.0.1',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()

# ── Wait until Flask is ready ──────────────────────────────────────────────────
print("🚀 Starting Lucid School System …")
for _ in range(30):
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.5):
            break
    except (ConnectionRefusedError, OSError):
        time.sleep(0.3)

# ── Try pywebview (native desktop window) ─────────────────────────────────────
WEBVIEW_OK = False
try:
    import webview  # pywebview

    ICON = os.path.join(APP_DIR, 'static', 'icon.png')
    icon_arg = ICON if os.path.exists(ICON) else None

    window = webview.create_window(
        title     = '🏫 Lucid School Management System',
        url       = URL,
        width     = 1280,
        height    = 820,
        min_size  = (900, 600),
        resizable = True,
    )

    print(f"✅ Opening desktop window  →  {URL}")
    # start() blocks until window is closed
    webview.start(debug=False)
    WEBVIEW_OK = True

except ImportError:
    pass  # fall through to browser fallback

except Exception as e:
    print(f"⚠️  pywebview error: {e}")

# ── Browser fallback ───────────────────────────────────────────────────────────
if not WEBVIEW_OK:
    print(f"🌐 Opening in browser  →  {URL}")
    print("   (Install pywebview for a native window:  pip install pywebview)")
    webbrowser.open(URL)

    # Keep process alive so Flask stays running
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║  Lucid School System is running              ║")
    print(f"║  {URL:<44}║")
    print("║  Press Ctrl+C to shut down                   ║")
    print("╚══════════════════════════════════════════════╝")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Shutting down …")
        sys.exit(0)
