"""
Lucid School — Desktop Launcher
Opens the app in a native desktop window (no browser needed).
Requires pywebview:  pip install pywebview

Falls back to the system browser automatically if pywebview is not installed.
"""
import sys
import os
import threading
import time
import socket
import subprocess

# ── Working directory ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# ── Auto-install dependencies ─────────────────────────────────────────────────
REQUIRED = {
    'flask':      'flask',
    'reportlab':  'reportlab',
    'PIL':        'pillow',
    'werkzeug':   'werkzeug',
}

def silent_install(pkg_name, import_name):
    try:
        __import__(import_name)
    except ImportError:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', pkg_name, '-q'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

for import_name, pkg_name in REQUIRED.items():
    silent_install(pkg_name, import_name)

# ── Check pywebview ───────────────────────────────────────────────────────────
HAS_WEBVIEW = False
try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    pass

# ── Find a free port ──────────────────────────────────────────────────────────
def find_free_port(start=5000):
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start

PORT = find_free_port(5000)
URL  = f'http://127.0.0.1:{PORT}'

# ── Wait for server to be ready ───────────────────────────────────────────────
def wait_for_server(port, timeout=15):
    for _ in range(timeout * 10):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.1)
    return False

# ── Start Flask in background thread ─────────────────────────────────────────
def run_flask():
    from database import init_db
    init_db()
    from app import app
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

print("Starting Lucid School...")

if not wait_for_server(PORT, timeout=20):
    print("ERROR: Server did not start in time.")
    sys.exit(1)

# ── Open window ───────────────────────────────────────────────────────────────
if HAS_WEBVIEW:
    # Native desktop window — no browser, looks like a real app
    window = webview.create_window(
        title       = 'Lucid School Management System',
        url         = URL,
        width       = 1280,
        height      = 800,
        min_size    = (900, 600),
        text_select = True,
    )
    webview.start(debug=False)
else:
    # Fallback: open in system browser
    import webbrowser
    webbrowser.open(URL)
    print(f"\n{'='*55}")
    print("  🏫  LUCID SCHOOL — running at:")
    print(f"      {URL}")
    print()
    print("  💡  To get a proper desktop window (no browser),")
    print("      run:  pip install pywebview")
    print("      Then restart the app.")
    print(f"{'='*55}")
    print("  Press Ctrl+C to stop.")
    try:
        flask_thread.join()
    except KeyboardInterrupt:
        print("\nStopped.")
