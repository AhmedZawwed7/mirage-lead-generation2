import os, re, sqlite3, io, csv, ipaddress, socket, urllib.parse, hmac
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
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.endpoint != "login":
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify(error="طلب من مصدر غير مسموح"), 403
        if not origin and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="طلب من مصدر غير مسموح"), 403

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS leads(
        id INTEGER PRIMARY KEY, company TEXT, phone TEXT, email TEXT, website TEXT,
        country TEXT, keyword TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
        owner TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(phone, website))""")
    cols = {row[1] for row in c.execute("PRAGMA table_info(leads)")}
    if "notes" not in cols:
        c.execute("ALTER TABLE leads ADD COLUMN notes TEXT DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'sales', active INTEGER DEFAULT 1,
        created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs(
        id INTEGER PRIMARY KEY, actor TEXT, action TEXT, entity TEXT, entity_id INTEGER,
        details TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP)""")
    if PASSWORD:
        c.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)",
                  (ADMIN, generate_password_hash(PASSWORD), "admin"))
    c.execute("""CREATE TABLE IF NOT EXISTS batches(
        id INTEGER PRIMARY KEY, name TEXT, keyword TEXT, country TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP, scanned INTEGER DEFAULT 0, added INTEGER DEFAULT 0)""")
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

def safe_fetch(url):
    if not is_public_url(url):
        return ""
    try:
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
        if not url or not is_public_url(url):
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
                    if urllib.parse.urlparse(candidate).hostname == host and is_public_url(candidate):
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
            session["user"] = user["username"]
            session["role"] = user["role"]
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
        "new": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='new'", params).fetchone()[0],
        "contacted": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='contacted'", params).fetchone()[0],
        "qualified": c.execute("SELECT COUNT(*) FROM leads" + where + (" AND" if where else " WHERE") + " status='qualified'", params).fetchone()[0],
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
    c.commit()
    c.close()
    rows, error = discover(keyword, country, data.get("limit", 25))
    c = db()
    added = 0
    for row in rows:
        try:
            c.execute("""INSERT INTO leads(company,phone,email,website,country,keyword,score)
                         VALUES(?,?,?,?,?,?,?)""", row)
            added += 1
        except sqlite3.IntegrityError:
            pass
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
    if "status" in data and data["status"] not in ("new", "contacted", "qualified", "won", "lost", "optout"):
        return jsonify(error="حالة غير صالحة"), 400
    c = db()
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

@app.get("/api/leads.csv")
@auth
def export_csv():
    c = db()
    rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner FROM leads ORDER BY id DESC").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0].keys() if rows else ["company","phone","email","website","country","keyword","score","status","owner"])
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
    rows = c.execute("SELECT company,phone,email,website,country,keyword,score,status,owner,notes FROM leads ORDER BY id DESC").fetchall()
    c.close()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Mirage Leads"
    headers = ["Company", "Phone", "Email", "Website", "Country", "Keyword", "Score", "Status", "Owner", "Notes"]
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
    for column, width in zip("ABCDEFGHIJ", [28, 20, 28, 40, 16, 22, 10, 16, 20, 40]):
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return Response(output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mirage-leads.xlsx"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 5000)), debug=False)
