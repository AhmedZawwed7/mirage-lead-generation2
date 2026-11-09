import os, re, sqlite3, io, csv, ipaddress, socket, urllib.parse, hmac, time, urllib.robotparser, secrets, datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
try:
    import psycopg
    DB_INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.errors.UniqueViolation)
except ImportError:
    DB_INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template, jsonify, Response, flash
import requests
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.getenv("MIRAGE_DB", os.path.join(ROOT, "instance", "mirage.db"))
if not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")) and not os.getenv("VERCEL"):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1")
ADMIN = os.getenv("MIRAGE_ADMIN_USER", "admin")
PASSWORD = os.getenv("MIRAGE_ADMIN_PASSWORD", "")
PHONE = re.compile(r"(?<![\w/])(\+?\d[\d\s().-]{7,17}\d)(?![\w/])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

@app.before_request
def protect_mutations():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint not in ("login", "campaign_webhook"):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify(error="طلب من مصدر غير مسموح"), 403
        if not origin and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="طلب من مصدر غير مسموح"), 403
        if session.get("user"):
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return jsonify(error="انتهت صلاحية النموذج، حدّث الصفحة وحاول مجددًا"), 400

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

@app.context_processor
def inject_csrf_token():
    if session.get("user") and not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session.get("csrf_token", "")}

def db():
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if dsn:
        from database import connect, initialize
        c = connect(dsn)
        initialize(c)
        if PASSWORD:
            admin_row = c.execute("SELECT password_hash FROM users WHERE username=?", (ADMIN,)).fetchone()
            if not admin_row:
                c.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)",
                          (ADMIN, generate_password_hash(PASSWORD), "admin"))
            elif not check_password_hash(admin_row["password_hash"], PASSWORD):
                c.execute("UPDATE users SET password_hash=?, role='admin', active=1 WHERE username=?",
                          (generate_password_hash(PASSWORD), ADMIN))
        c.commit()
        return c

    # Vercel must never silently fall back to ephemeral SQLite storage.
    if os.getenv("VERCEL"):
        raise RuntimeError("PostgreSQL is not configured: set DATABASE_URL from the Neon integration.")
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS leads(
        id INTEGER PRIMARY KEY, company TEXT, phone TEXT, email TEXT, website TEXT,
        country TEXT, keyword TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
        owner TEXT DEFAULT '', source TEXT DEFAULT 'website', campaign TEXT DEFAULT '',
        external_id TEXT DEFAULT '', consent TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(phone, website))""")
    cols = {row[1] for row in c.execute("PRAGMA table_info(leads)")}
    migrations = {"notes": "TEXT DEFAULT ''", "source": "TEXT DEFAULT 'website'",
                  "campaign": "TEXT DEFAULT ''", "external_id": "TEXT DEFAULT ''",
                  "consent": "TEXT DEFAULT ''", "city": "TEXT DEFAULT ''"}
    for column, definition in migrations.items():
        if column not in cols:
            c.execute("ALTER TABLE leads ADD COLUMN " + column + " " + definition)
    c.execute("CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads(phone)")
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'sales', active INTEGER DEFAULT 1,
        created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs(
        id INTEGER PRIMARY KEY, actor TEXT, action TEXT, entity TEXT, entity_id INTEGER,
        details TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    if PASSWORD:
        admin_row = c.execute("SELECT password_hash FROM users WHERE username=?", (ADMIN,)).fetchone()
        if not admin_row:
            c.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)",
                      (ADMIN, generate_password_hash(PASSWORD), "admin"))
        elif not check_password_hash(admin_row["password_hash"], PASSWORD):
            c.execute("UPDATE users SET password_hash=?, role='admin', active=1 WHERE username=?",
                      (generate_password_hash(PASSWORD), ADMIN))
    c.execute("""CREATE TABLE IF NOT EXISTS batches(
        id INTEGER PRIMARY KEY, name TEXT, keyword TEXT, country TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP, scanned INTEGER DEFAULT 0, added INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS activities(
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, actor TEXT NOT NULL,
        activity_type TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, assigned_to TEXT NOT NULL,
        title TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        created_by TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cols = {row[1] for row in c.execute("PRAGMA table_info(leads)")}
    if "batch_id" not in cols:
        c.execute("ALTER TABLE leads ADD COLUMN batch_id INTEGER")
    c.execute("CREATE INDEX IF NOT EXISTS ix_leads_batch_id ON leads(batch_id)")
    c.commit()
    return c

def auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                return jsonify(error="ليست لديك صلاحية لتنفيذ هذا الإجراء"), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def audit(c, action, entity, entity_id=None, details=""):
    c.execute("INSERT INTO audit_logs(actor,action,entity,entity_id,details) VALUES(?,?,?,?,?)",
              (session.get("user", "system"), action, entity, entity_id, details))

def is_public_url(url):
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            return False
        if p.port and p.port not in (80, 443):
            return False
        addresses = socket.getaddrinfo(p.hostname, None)
        return bool(addresses) and all(ipaddress.ip_address(x[4][0]).is_global for x in addresses)
    except (ValueError, OSError):
        return False

_robots_cache = {}
_domain_last_fetch = {}

def robots_allowed(url):
    parsed = urllib.parse.urlparse(url)
    origin = parsed.scheme + "://" + parsed.netloc
    if origin not in _robots_cache:
        robots_url = origin + "/robots.txt"
        content = safe_fetch(robots_url)
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(content.splitlines() if content else [])
        _robots_cache[origin] = parser
    return _robots_cache[origin].can_fetch("MirageLeadResearch", url)

def safe_fetch(url):
    if not is_public_url(url):
        return ""
    try:
        host = urllib.parse.urlparse(url).netloc
        elapsed = time.monotonic() - _domain_last_fetch.get(host, 0)
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _domain_last_fetch[host] = time.monotonic()
        response = requests.get(url, timeout=10, headers={"User-Agent": "MirageLeadResearch/1.0"},
                                allow_redirects=False, stream=True)
        if 300 <= response.status_code < 400:
            target = urllib.parse.urljoin(url, response.headers.get("Location", ""))
            if not is_public_url(target):
                return ""
            response = requests.get(target, timeout=10, headers={"User-Agent": "MirageLeadResearch/1.0"},
                                    allow_redirects=False, stream=True)
        if response.status_code != 200:
            return ""
        chunks, size = [], 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > 1500000:
                return ""
            chunks.append(chunk)
        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return ""

def search_results(keyword, country, limit):
    query = keyword + " " + country + " اتصل بنا"
    serp_key = os.getenv("SERPAPI_KEY")
    google_key, google_cx = os.getenv("GOOGLE_API_KEY"), os.getenv("GOOGLE_CX")
    try:
        if serp_key:
            response = requests.get("https://serpapi.com/search.json",
                params={"engine": "google", "q": query, "api_key": serp_key, "num": min(int(limit), 50)},
                timeout=15)
            response.raise_for_status()
            return response.json().get("organic_results", []), ""
        if google_key and google_cx:
            response = requests.get("https://www.googleapis.com/customsearch/v1",
                params={"key": google_key, "cx": google_cx, "q": query, "num": min(int(limit), 10)},
                timeout=15)
            response.raise_for_status()
            return response.json().get("items", []), ""
        if DDGS is None:
            return [], "اضبط SERPAPI_KEY أو Google API أو ثبّت ddgs لتفعيل البحث."
        return list(DDGS().text(query, max_results=min(max(int(limit), 1), 50))), ""
    except Exception as exc:
        return [], "فشل مزود البحث: " + type(exc).__name__

def discover(keyword, country, limit):
    results, error = search_results(keyword, country, limit)
    if error:
        return [], error
    found = []
    for item in results:
        url = item.get("link") or item.get("href") or item.get("url")
        if not url or not is_public_url(url) or not robots_allowed(url):
            continue
        html = safe_fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        phones = []
        for phone in PHONE.findall(text):
            digits = re.sub(r"\D", "", phone)
            if 8 <= len(digits) <= 15 and phone not in phones:
                phones.append(phone)
        emails = [e.lower() for e in EMAIL.findall(html)
                  if "example." not in e.lower() and "sentry" not in e.lower()]
        if not phones and not emails:
            host = urllib.parse.urlparse(url).hostname
            links = []
            for anchor in soup.find_all("a", href=True):
                label = (anchor.get_text(" ", strip=True) + " " + anchor["href"]).lower()
                if any(word in label for word in ("contact", "اتصل", "تواصل", "about", "من نحن")):
                    candidate = urllib.parse.urljoin(url, anchor["href"])
                    if urllib.parse.urlparse(candidate).hostname == host and is_public_url(candidate) and robots_allowed(candidate):
                        links.append(candidate)
                if len(links) >= 2:
                    break
            for contact_url in links:
                contact_html = safe_fetch(contact_url)
                phones += [p for p in PHONE.findall(BeautifulSoup(contact_html, "html.parser").get_text(" "))
                           if 8 <= len(re.sub(r"\D", "", p)) <= 15 and p not in phones]
                emails += [e.lower() for e in EMAIL.findall(contact_html)
                           if "example." not in e.lower() and e.lower() not in emails]
                if phones or emails:
                    break
        if not phones and not emails:
            continue
        company = soup.title.string.strip()[:180] if soup.title and soup.title.string else item.get("title", "Company")
        score = min(100, 35 + 30 * bool(phones) + 25 * bool(emails))
        found.append((company, phones[0] if phones else "", emails[0] if emails else "",
                      url, country, keyword, score))
    return found, ""

@app.get("/health")
def health():
    return jsonify(status="ok", app="Mirage Leads Hunter")

@app.route("/login", methods=["GET", "POST"])
def login():
    c = db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user"] = user["username"]
            session["role"] = user["role"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            c.close()
            return redirect("/")
        flash("بيانات الدخول غير صحيحة أو الحساب موقوف.")
    c.close()
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.get("/")
@auth
def home():
    c = db()
    is_sales = session.get("role") == "sales"
    where = " WHERE owner=?" if is_sales else ""
    params = (session["user"],) if is_sales else ()
    stats = {
        "total": c.execute("SELECT COUNT(*) FROM leads" + where, params).fetchone()[0],
        "phones": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " phone IS NOT NULL AND phone<>''", params).fetchone()[0],
        "new": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='new'", params).fetchone()[0],
        "contacted": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='contacted'", params).fetchone()[0],
        "qualified": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='qualified'", params).fetchone()[0],
        "open_tasks": c.execute("SELECT COUNT(*) FROM tasks WHERE status='open' AND " + ("assigned_to=?" if is_sales else "1=1"), (session["user"],) if is_sales else ()).fetchone()[0],
        "overdue_tasks": c.execute("SELECT COUNT(*) FROM tasks WHERE status='open' AND due_at < datetime('now','localtime') AND " + ("assigned_to=?" if is_sales else "1=1"), (session["user"],) if is_sales else ()).fetchone()[0],
    }
    leads = c.execute("SELECT * FROM leads" + where + " ORDER BY id DESC LIMIT 500", params).fetchall()
    batches = c.execute("SELECT * FROM batches ORDER BY id DESC LIMIT 15").fetchall()
    c.close()
    return render_template("index.html", stats=stats, leads=leads, batches=batches,
                           user=session["user"], role=session["role"])

@app.post("/api/search")
@auth
@role_required("admin", "manager", "researcher")
def search():
    data = request.get_json(silent=True) or request.form
    keyword = (data.get("keyword") or "").strip()
    country = (data.get("country") or "السعودية").strip()
    if not keyword:
        return jsonify(error="اكتب كلمة البحث"), 400
    c = db()
    batch_id = c.execute("INSERT INTO batches(name,keyword,country) VALUES(?,?,?)",
                         (keyword + " - " + country, keyword, country)).lastrowid
    audit(c, "search.started", "batch", batch_id, keyword + " | " + country)
    c.commit()
    c.close()
    rows, error = discover(keyword, country, data.get("limit", 25))
    c = db()
    added = 0
    for row in rows:
        duplicate = c.execute(
            "SELECT id FROM leads WHERE (phone=? AND phone<>'') OR (website=? AND website<>'') LIMIT 1",
            (row[1], row[3])).fetchone()
        if duplicate:
            continue
        c.execute("""INSERT INTO leads(company,phone,email,website,country,keyword,score)
                     VALUES(?,?,?,?,?,?,?)""", row)
        added += 1
    c.execute("UPDATE batches SET scanned=?,added=? WHERE id=?", (len(rows), added, batch_id))
    c.commit()
    c.close()
    return jsonify(batch_id=batch_id, scanned=len(rows), added=added, error=error)

@app.patch("/api/leads/<int:lead_id>")
@auth
def update_lead(lead_id):
    data = request.get_json(silent=True) or {}
    role = session.get("role")
    allowed = ("status", "notes") if role == "sales" else ("status", "owner", "notes")
    data = {k: v for k, v in data.items() if k in allowed}
    if not data:
        return jsonify(error="لا توجد تغييرات صالحة"), 400
    if "status" in data and data["status"] not in ("new", "assigned", "contacted", "qualified", "demo", "won", "lost", "optout"):
        return jsonify(error="حالة غير صالحة"), 400
    c = db()
    if "owner" in data and data["owner"]:
        assignee = c.execute("SELECT role FROM users WHERE username=? AND active=1", (data["owner"],)).fetchone()
        if not assignee or assignee["role"] != "sales":
            c.close()
            return jsonify(error="اختر موظف مبيعات نشطًا من الفريق"), 400
    lead = c.execute("SELECT owner FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        c.close()
        return jsonify(error="العميل غير موجود"), 404
    if role == "sales" and lead["owner"] != session["user"]:
        c.close()
        return jsonify(error="هذا العميل غير مسند إليك"), 403
    c.execute("UPDATE leads SET " + ",".join(k + "=?" for k in data) + " WHERE id=?",
              (*data.values(), lead_id))
    audit(c, "lead.updated", "lead", lead_id, ",".join(data.keys()))
    c.commit()
    c.close()
    return jsonify(ok=True)



def _visible_lead(c, lead_id):
    lead = c.execute("SELECT id,owner FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        return None, (jsonify(error="العميل غير موجود"), 404)
    if session.get("role") == "sales" and lead["owner"] != session.get("user"):
        return None, (jsonify(error="هذا العميل غير مسند إليك"), 403)
    return lead, None

@app.route("/api/leads/<int:lead_id>/activities", methods=["GET", "POST"])
@auth
def lead_activities(lead_id):
    c = db()
    lead, error = _visible_lead(c, lead_id)
    if error:
        c.close()
        return error
    if request.method == "GET":
        rows = c.execute("SELECT id,actor,activity_type,note,created FROM activities WHERE lead_id=? ORDER BY id DESC LIMIT 100", (lead_id,)).fetchall()
        c.close()
        return jsonify(activities=[dict(x) for x in rows])
    data = request.get_json(silent=True) or {}
    kind, note = str(data.get("activity_type", "note")), str(data.get("note", "")).strip()
    if kind not in ("note", "call", "whatsapp", "email", "meeting", "status") or not note:
        c.close()
        return jsonify(error="نوع النشاط والملاحظة مطلوبان"), 400
    cur = c.execute("INSERT INTO activities(lead_id,actor,activity_type,note) VALUES(?,?,?,?)",
                    (lead_id, session["user"], kind, note[:2000]))
    audit(c, "activity.created", "lead", lead_id, kind)
    c.commit()
    row = c.execute("SELECT id,actor,activity_type,note,created FROM activities WHERE id=?", (cur.lastrowid,)).fetchone()
    c.close()
    return jsonify(ok=True, activity=dict(row)), 201


@app.get("/api/sales-users")
@auth
@role_required("admin", "manager")
def sales_users():
    c = db()
    rows = c.execute("SELECT username FROM users WHERE active=1 AND role='sales' ORDER BY username").fetchall()
    c.close()
    return jsonify(users=[row["username"] for row in rows])

@app.route("/api/tasks", methods=["GET", "POST"])
@auth
def tasks():
    c = db()
    if request.method == "GET":
        if session.get("role") == "sales":
            rows = c.execute("SELECT t.*,l.company FROM tasks t JOIN leads l ON l.id=t.lead_id WHERE t.assigned_to=? AND l.owner=? ORDER BY t.due_at LIMIT 200", (session["user"], session["user"])).fetchall()
        else:
            rows = c.execute("SELECT t.*,l.company FROM tasks t JOIN leads l ON l.id=t.lead_id ORDER BY t.due_at LIMIT 300").fetchall()
        c.close()
        return jsonify(tasks=[dict(x) for x in rows])
    data = request.get_json(silent=True) or {}
    try:
        lead_id = int(data.get("lead_id"))
    except (TypeError, ValueError):
        c.close()
        return jsonify(error="اختر عميلاً صالحاً"), 400
    lead, error = _visible_lead(c, lead_id)
    if error:
        c.close()
        return error
    title, due = str(data.get("title", "")).strip(), str(data.get("due_at", "")).strip()
    assignee = session["user"] if session.get("role") == "sales" else str(data.get("assigned_to") or "").strip()
    if not title or len(title) > 180 or not due:
        c.close()
        return jsonify(error="عنوان المهمة والموعد مطلوبان"), 400
    try:
        datetime.datetime.fromisoformat(due)
    except ValueError:
        c.close()
        return jsonify(error="صيغة الموعد غير صحيحة؛ استخدم YYYY-MM-DDTHH:MM"), 400
    if session.get("role") != "sales":
        user = c.execute("SELECT role FROM users WHERE username=? AND active=1", (assignee,)).fetchone()
        if not user or user["role"] != "sales":
            c.close()
            return jsonify(error="اختر موظف مبيعات نشطاً"), 400
        if lead["owner"] != assignee:
            c.close()
            return jsonify(error="يجب إسناد العميل إلى موظف المبيعات قبل إنشاء المتابعة"), 400
    cur = c.execute("INSERT INTO tasks(lead_id,assigned_to,title,due_at,created_by) VALUES(?,?,?,?,?)",
                    (lead_id, assignee, title, due[:40], session["user"]))
    audit(c, "task.created", "lead", lead_id, title)
    c.commit()
    row = c.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone()
    c.close()
    return jsonify(ok=True, task=dict(row)), 201

@app.patch("/api/tasks/<int:task_id>")
@auth
def update_task(task_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("open", "done", "cancelled"):
        return jsonify(error="حالة المهمة غير صالحة"), 400
    c = db()
    task = c.execute("SELECT t.*,l.owner AS lead_owner FROM tasks t JOIN leads l ON l.id=t.lead_id WHERE t.id=?", (task_id,)).fetchone()
    if not task:
        c.close()
        return jsonify(error="المهمة غير موجودة"), 404
    if session.get("role") == "sales" and (task["assigned_to"] != session["user"] or task["lead_owner"] != session["user"]):
        c.close()
        return jsonify(error="هذه المهمة ليست مسندة إليك"), 403
    c.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    audit(c, "task.updated", "task", task_id, status)
    c.commit()
    c.close()
    return jsonify(ok=True)

@app.post("/api/webhooks/leads/<source>")
def campaign_webhook(source):
    if source not in ("google_ads", "meta_ads", "tiktok_ads"):
        return jsonify(error="مصدر الحملة غير مدعوم"), 404
    secret = os.getenv("CAMPAIGN_WEBHOOK_TOKEN", "")
    supplied = request.headers.get("X-Mirage-Webhook-Token", "")
    if not secret:
        return jsonify(error="تكامل استقبال الحملات غير مهيأ"), 503
    if not hmac.compare_digest(supplied, secret):
        return jsonify(error="غير مصرح"), 401
    data = request.get_json(silent=True) or {}
    consent = data.get("consent") is True or str(data.get("consent", "")).lower() == "true"
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    if not consent:
        return jsonify(error="يجب تأكيد موافقة صاحب البيانات على التواصل"), 400
    if not phone and not email:
        return jsonify(error="رقم الهاتف أو البريد مطلوب"), 400
    c = db()
    external_id = str(data.get("external_id", "")).strip()
    if external_id:
        prior = c.execute("SELECT id FROM leads WHERE source=? AND external_id=?",
                          (source, external_id)).fetchone()
        if prior:
            c.close()
            return jsonify(ok=True, duplicate=True, lead_id=prior["id"]), 200
    prior_contact = c.execute(
        "SELECT id FROM leads WHERE (phone=? AND phone<>'') OR (email=? AND email<>'') LIMIT 1",
        (phone, email)).fetchone()
    if prior_contact:
        c.close()
        return jsonify(ok=True, duplicate=True, lead_id=prior_contact["id"]), 200
    try:
        cur = c.execute("""INSERT INTO leads(company,phone,email,website,country,keyword,score,source,campaign,external_id,consent)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (str(data.get("company") or data.get("name") or "عميل حملة")[:180],
             phone, email, str(data.get("website", ""))[:500],
             str(data.get("country", ""))[:80], str(data.get("campaign", source))[:180],
             60, source, str(data.get("campaign", ""))[:180], external_id, "granted"))
        audit(c, "campaign.lead.created", "lead", cur.lastrowid, source)
        c.commit()
        lead_id = cur.lastrowid
    except DB_INTEGRITY_ERRORS:
        c.close()
        return jsonify(ok=True, duplicate=True), 200
    c.close()
    return jsonify(ok=True, duplicate=False, lead_id=lead_id), 201

@app.get("/api/leads.csv")
@auth
def export_csv():
    c = db()
    if session.get("role") == "sales":
        rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner,source,campaign FROM leads WHERE owner=? ORDER BY id DESC", (session["user"],)).fetchall()
    else:
        rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner,source,campaign FROM leads ORDER BY id DESC").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0].keys() if rows else ["company","phone","email","website","country","keyword","score","status","owner","source","campaign"])
    for row in rows:
        writer.writerow([("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value)
                         for value in row])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=mirage-leads.csv"})



@app.route("/team", methods=["GET", "POST"])
@auth
def team():
    if session.get("role") not in ("admin", "manager"):
        return "Forbidden", 403
    c = db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "sales")
        allowed = ("sales", "researcher") if session["role"] == "manager" else ("manager", "sales", "researcher")
        if len(username) < 3 or len(password) < 12 or role not in allowed:
            flash("اسم المستخدم 3 أحرف على الأقل وكلمة المرور 12 حرفًا على الأقل.")
        else:
            try:
                cur = c.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                                (username, generate_password_hash(password), role))
                audit(c, "user.created", "user", cur.lastrowid, role)
                c.commit()
                flash("تم إنشاء المستخدم.")
            except sqlite3.IntegrityError:
                flash("اسم المستخدم موجود بالفعل.")
    users = c.execute("SELECT id,username,role,active,created FROM users ORDER BY id").fetchall()
    c.close()
    return render_template("team.html", users=users, user=session["user"], role=session["role"])

@app.get("/api/leads.xlsx")
@auth
def export_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    c = db()
    if session.get("role") == "sales":
        rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner,notes,source,campaign FROM leads WHERE owner=? ORDER BY id DESC", (session["user"],)).fetchall()
    else:
        rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner,notes,source,campaign FROM leads ORDER BY id DESC").fetchall()
    c.close()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Mirage Leads"
    headers = ["Company", "Phone", "Email", "Website", "Country", "Keyword", "Score", "Status", "Owner", "Notes", "Source", "Campaign"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="263B68")
    for row in rows:
        values = []
        for value in row:
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        sheet.append(values)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in zip("ABCDEFGHIJKL", [28, 20, 28, 40, 16, 22, 10, 16, 20, 40, 18, 24]):
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return Response(output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mirage-leads.xlsx"})



# Register the additional capabilities from the original Mirage Hunter package.
from features import register_features
register_features(app, db, auth, role_required, audit, safe_fetch, is_public_url, robots_allowed)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 5000)), debug=False)
