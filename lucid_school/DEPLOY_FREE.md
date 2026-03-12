# 🚀 FREE HOSTING GUIDE — Lucid School SaaS
# Get a live URL in 30 minutes. No credit card needed.
# Database is PostgreSQL on Supabase — your data NEVER gets wiped.
#
# Platform: Render.com (web server) + Supabase (database)
# Both are 100% free forever on the tiers used here.
# ================================================================


# ================================================================
# PART 1 — GET YOUR FREE POSTGRESQL DATABASE (Supabase)
# Your data lives here. Safe, free, permanent.
# ================================================================

STEP 1 — Create a Supabase account
  → Go to: https://supabase.com
  → Click "Start your project" → Sign up with GitHub (easiest)

STEP 2 — Create a new project
  → Click "New project"
  → Organisation: your default org (auto-created)
  → Project name: lucid-school
  → Database password: pick a STRONG password (save it — you'll need it once)
  → Region: pick one close to Ghana → "Europe West (EU)" is good
  → Click "Create new project"  (takes ~2 minutes to set up)

STEP 3 — Get your database connection string
  → In the Supabase dashboard, click your project
  → Left sidebar → Settings (gear icon) → Database
  → Scroll down to "Connection string" section
  → Click the "URI" tab
  → Copy the string — it looks like:
      postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:5432/postgres
  → Replace [YOUR-PASSWORD] with your actual database password
  → SAVE THIS STRING — you'll paste it into Render in Part 2

  ⚠️  KEEP THIS STRING PRIVATE — never put it in your code or GitHub


# ================================================================
# PART 2 — PUSH YOUR CODE TO GITHUB
# ================================================================

STEP 4 — Create a GitHub account (if you don't have one)
  → Go to: https://github.com → Sign up free

STEP 5 — Install Git (if not installed)
  → Download: https://git-scm.com/download/win
  → Install with all default settings

STEP 6 — Open your project folder in VSCode
  → VSCode → File → Open Folder → select your lucid_deploy folder

STEP 7 — Open terminal in VSCode (Ctrl + `)

STEP 8 — Check the .gitignore is correct
  → Open the file called ".gitignore" in your project
  → Make sure it contains at minimum:
      instance/
      __pycache__/
      *.pyc
      *.db
      .env
      venv/

STEP 9 — Run these commands in the terminal:
  git init
  git add .
  git commit -m "Initial deploy — Lucid School SaaS"

STEP 10 — Install GitHub CLI
  → Download: https://cli.github.com
  → Install it → restart VSCode

STEP 11 — Login and push to GitHub:
  gh auth login
  (choose GitHub.com → HTTPS → Login with web browser → follow steps)

  gh repo create lucid-school --public --source=. --remote=origin --push

  → Your code is now at: https://github.com/YOUR_USERNAME/lucid-school


# ================================================================
# PART 3 — DEPLOY TO RENDER.COM (Free Web Server)
# ================================================================

STEP 12 — Create a Render account
  → Go to: https://render.com
  → Click "Get started for free" → Sign up with GitHub (use same GitHub account)

STEP 13 — Create a new Web Service
  → Render dashboard → click "New +" → "Web Service"
  → Connect your GitHub repo: search for "lucid-school" → click Connect

STEP 14 — Configure the service (fill in these fields):
  Name:              lucid-school
  Region:            Oregon (US West) — or Frankfurt for better Ghana latency
  Branch:            main
  Runtime:           Python 3
  Build Command:     pip install -r requirements.txt && python database.py
  Start Command:     gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120 --preload
  Instance Type:     Free ✓

STEP 15 — Add Environment Variables
  → Scroll down to "Environment Variables" section
  → Click "Add Environment Variable" for EACH of these:

  Key: DATABASE_URL
  Value: postgresql://postgres:YOURPASSWORD@db.xxxx.supabase.co:5432/postgres
  (paste the full Supabase connection string from Step 3)

  Key: SECRET_KEY
  Value: (generate one at https://randomkeygen.com — pick a 256-bit key)

  Key: PYTHON_VERSION
  Value: 3.11.0

STEP 16 — Click "Create Web Service"
  → Render will now:
    1. Download your code from GitHub
    2. Install requirements (flask, psycopg2, gunicorn, etc.)
    3. Run python database.py (creates all tables in Supabase)
    4. Start your app with gunicorn
  → This takes about 3-5 minutes
  → Watch the logs — look for "✅ Lucid School database initialised"
  → When you see "Your service is live 🎉" — you're done!

STEP 17 — Get your URL
  → At the top of the Render dashboard you'll see:
      https://lucid-school.onrender.com
  → That's your live app! 🎉
  → Open it → you should see the login page


# ================================================================
# PART 4 — TEST YOUR LIVE APP
# ================================================================

STEP 18 — Login and verify everything works

  Platform Admin login:
    URL:      https://lucid-school.onrender.com/login
    Username: superadmin
    Password: admin123

  School Admin login:
    URL:      https://lucid-school.onrender.com/login
    Username: schooladmin
    Password: school123

  ⚠️  CHANGE BOTH PASSWORDS IMMEDIATELY after first login!
  → Platform admin: click your name → Change Password
  → School admin: Settings → Change Password


# ================================================================
# PART 5 — KEEP YOUR APP AWAKE (Free tier sleeps after 15 min)
# ================================================================

STEP 19 — Set up UptimeRobot (free pinger)
  → Go to: https://uptimerobot.com → Sign up free
  → Click "Add New Monitor"
  → Monitor Type: HTTP(s)
  → Friendly Name: Lucid School
  → URL: https://lucid-school.onrender.com/login
  → Monitoring Interval: Every 5 minutes
  → Click "Create Monitor"
  → Done! Your app will now stay awake 24/7 for free.


# ================================================================
# PART 6 — GENERATE YOUR ANDROID APK
# ================================================================

Now that you have a live URL, you can build the Android APK.

STEP 20 — Install Node.js
  → Download: https://nodejs.org → LTS version → Install

STEP 21 — Install Android Studio
  → Download: https://developer.android.com/studio → Install
  → First launch: let it download SDK components (~2GB, takes a while)

STEP 22 — In your project folder, run these commands:
  npm install
  npx cap sync android

STEP 23 — Update your live URL in the app
  → Open: capacitor.config.json
  → Find the "server" section
  → Replace the URL with your Render URL:
      "url": "https://lucid-school.onrender.com"
  → Save the file

STEP 24 — Open in Android Studio:
  npx cap open android

STEP 25 — Build the APK in Android Studio:
  → Menu: Build → Build Bundle(s)/APK(s) → Build APK(s)
  → Wait ~2 minutes
  → Click "locate" when done
  → Your APK is at:
      android/app/build/outputs/apk/debug/app-debug.apk

STEP 26 — Install on your Android phone:
  → Transfer the APK to your phone (via USB, WhatsApp, Google Drive)
  → On your phone: Settings → Security → Allow Unknown Sources (or "Install unknown apps")
  → Open the APK file → Install
  → Open "Lucid School" app → it loads your live web app! ✅


# ================================================================
# PART 7 — YOUR PORTAL URLS (share with clients)
# ================================================================

Staff/Admin Login:
  https://lucid-school.onrender.com/login

Parent Portal:
  https://lucid-school.onrender.com/parent/login
  (parents enter their school code + username + password)

Android APK Download:
  Share the .apk file directly via WhatsApp or Google Drive


# ================================================================
# PART 8 — ADDING REAL SCHOOL CLIENTS
# ================================================================

When a school pays and you want to add them:

1. Login as superadmin → Platform → Add School
   → Fill in school name, short code (e.g. "GPS" for Govt Primary School)
   → This creates their admin account automatically

2. Send the school admin:
   → Login URL: https://lucid-school.onrender.com/login
   → Username: (what you set)
   → Password: (what you set)
   → Parent portal URL: https://lucid-school.onrender.com/parent/login
   → Their school code (the short_name you set)
   → APK download link (your Render URL or a Google Drive link to the APK)

3. Their data is completely isolated from other schools
   → Multi-tenant: each school only sees their own data


# ================================================================
# PART 9 — DEPLOYING UPDATES
# ================================================================

When you update your code and want to push changes:

  git add .
  git commit -m "describe what you changed"
  git push

→ Render auto-deploys every time you push to GitHub
→ Takes ~3 minutes → your live app updates automatically
→ Database is untouched — no data is lost


# ================================================================
# PART 10 — CUSTOM DOMAIN (optional, GH₵ 140/year)
# ================================================================

Instead of lucid-school.onrender.com you can have app.lucidschool.com.gh

1. Buy domain from NIC Ghana: https://nic.gh (~GH₵ 140/year for .com.gh)

2. In your domain registrar's DNS settings, add:
   Type: CNAME
   Name: app  (or @)
   Value: lucid-school.onrender.com

3. In Render → your service → Settings → Custom Domains
   → Add: app.lucidschool.com.gh
   → Render auto-provisions a free SSL certificate

4. Done! Your app is now at: https://app.lucidschool.com.gh


# ================================================================
# SUMMARY — WHAT YOU NOW HAVE
# ================================================================

✅ Web app live at:    https://lucid-school.onrender.com
✅ Database at:        Supabase PostgreSQL (data never wiped on restart)
✅ SSL/HTTPS:          Free, auto-managed by Render
✅ Auto-deploy:        Push to GitHub → live in 3 minutes
✅ Always-on:          UptimeRobot pings every 5 min (free)
✅ Android APK:        Built from your live URL via Capacitor
✅ Multi-tenant:       Each school's data is fully isolated

Monthly cost: GH₵ 0.00 🎉

When you outgrow free tier (>5 schools, heavy traffic):
→ Render paid: $7/month (GH₵ 110)
→ Or move to Contabo VPS: €4.50/month (GH₵ 70)
→ Keep Supabase free (500MB, enough for 20+ schools)


# ================================================================
# DEFAULT CREDENTIALS (CHANGE IMMEDIATELY!)
# ================================================================

Platform Admin:
  URL:      /login
  Username: superadmin
  Password: admin123  ← CHANGE THIS NOW

Demo School Admin:
  URL:      /login
  Username: schooladmin
  Password: school123  ← CHANGE THIS NOW

# ================================================================
# SUPPORT
# ================================================================
WhatsApp: 0542361753
Email:    support@lucidithub.com
