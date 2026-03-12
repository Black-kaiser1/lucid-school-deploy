# 🏫 Lucid IT Hub — SaaS School Management System v2.0

**Multi-tenant school platform with WAEC reports, bulk email/SMS, analytics & more**
*Designed by Rabbi Akwasi, Founder — Lucid IT Hub | 0542 361 753 / 0207 923 981*

---

## ✅ All Features

| Feature | Details |
|---|---|
| 🔐 Multi-tenant Login | Platform admin + school admin + teacher roles |
| 🏫 School Registration | Each school has own login, branding, data |
| 🎨 Custom Branding | School logo + colors appear on every report card |
| 📷 Student Photos | Photo captured and printed on report card |
| 📝 WAEC Grading | A1–F9, best-6 aggregate, Distinction/Credit/Pass/Fail |
| 📄 PDF Report Cards | Professional A4 with logo, photo, grades, remarks |
| 📊 Class Broadsheet | Full class result summary — landscape A3 PDF |
| 📧 Bulk Email | Send all report cards to parents in one click |
| 📱 SMS Alerts | Send result summaries via Hubtel SMS (Ghana) |
| 📈 Analytics Dashboard | Subject averages, top students, class performance charts |
| 💰 Fee Management | Track fees, payments, balances per student per term |
| 📅 Timetable | Visual weekly timetable per class |
| 👩‍🏫 Teacher Accounts | Teachers login and enter scores for their class |
| 📋 Email/SMS Log | Full history of all communications |

---

## 🚀 Running Locally (Windows 10)

### Step 1 — Install Python
Download from https://www.python.org/downloads/
**⚠️ Check "Add Python to PATH" during installation!**

### Step 2 — Extract ZIP
Extract `saas_school.zip` to e.g. `C:\Users\YourName\Desktop\saas_school`

### Step 3 — Create required folders
Inside the `saas_school` folder, create these folders if missing:
- `instance`
- `reports`
- `uploads/logos`
- `uploads/photos`

### Step 4 — Open Command Prompt in the folder
Click the address bar → type `cmd` → press Enter

### Step 5 — Install dependencies (one time only)
```
pip install flask reportlab pillow werkzeug
```

### Step 6 — Run
```
python run.py
```

### Step 7 — Open browser
Go to: **http://127.0.0.1:5000**

---

## 🔑 Default Login Credentials

| Account | Username | Password | Access |
|---|---|---|---|
| Platform Admin (You) | `superadmin` | `admin123` | All schools |
| Demo School Admin | `schooladmin` | `school123` | Demo school only |

**Change these passwords immediately after first login!**

---

## 🌐 Hosting Online (Free — Render.com)

To make the system accessible from ANY browser or phone worldwide:

### Step 1 — Create free account
Go to https://render.com and sign up free

### Step 2 — Create a `requirements.txt` file
```
flask
reportlab
pillow
werkzeug
gunicorn
```

### Step 3 — Create a `Procfile` file (no extension)
```
web: gunicorn app:app
```

### Step 4 — Push to GitHub
- Create free GitHub account at github.com
- Create new repository
- Upload all files

### Step 5 — Deploy on Render
1. Click "New Web Service"
2. Connect your GitHub repository
3. Set Start Command: `gunicorn app:app`
4. Click Deploy

### Step 6 — Share the link
Render gives you a URL like: `https://yourschool.onrender.com`
Share this with all schools — they access from any device!

---

## 📧 Gmail Setup for Emails

1. Enable 2-Factor Auth on Gmail: https://myaccount.google.com/security
2. Create App Password: https://myaccount.google.com/apppasswords
3. Enter in the Reports page when sending

---

## 📱 SMS Setup (Ghana — Hubtel)

1. Register at https://unity.hubtel.com
2. Get API Key and Client Secret
3. Go to Settings → SMS Configuration
4. Enter credentials and enable

---

## 🏗️ Project Structure

```
saas_school/
├── run.py                    ← START HERE
├── app.py                    ← Flask routes
├── database.py               ← Multi-tenant DB schema
├── grading.py                ← WAEC logic
├── pdf_generator.py          ← Report card PDFs
├── broadsheet_generator.py   ← Class broadsheet PDF
├── email_sender.py           ← Email + SMS sender
├── templates/
│   ├── auth/login.html
│   ├── admin/               ← Platform admin pages
│   ├── school/              ← School pages (dashboard, students, etc.)
│   └── base.html
├── instance/
│   └── saas_school.db       ← SQLite database (auto-created)
├── reports/                 ← Generated PDFs
└── uploads/
    ├── logos/               ← School logos
    └── photos/              ← Student photos
```

---

## 💼 Adding a New School (As Platform Admin)

1. Login as `superadmin`
2. Go to **All Schools** → **➕ Add New School**
3. Fill in school name, contact, colors, admin credentials
4. Click **Create School**
5. Share the login credentials with the school

Each school is completely isolated — they can only see their own students and data.

---

## 📞 Support & Services

**Lucid IT Hub** — Professional Data & Presentation Services
- 📱 WhatsApp: **0542 361 753 / 0207 923 981**
- 💼 Services: School Systems, Excel Reports, PowerPoint Presentations
- 🌐 Custom development, training, deployment

*Turning Data into Decisions* 💡
