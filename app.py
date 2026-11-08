import os, re, sqlite3, io, csv, ipaddress, socket, urllib.parse
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template, jsonify, Response, flash
import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.getenv("MIRAGE_DB", os.path.join(ROOT, "instance", "mirage.db"))
os.makedirs(os.path.dirname(DB), exist_ok=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32)
ADMIN = os.getenv("MIRAGE_ADMIN_USER", "admin")
PASSWORD = os.getenv("MIRAGE_ADMIN_PASSWORD", "")
PHONE = re.compile(r"(?<![\w/])(\+?\d[\d\s().-]{7,17}\d)(?![\w/])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def db():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS leads(
        id INTEGER PRIMARY KEY, company TEXT, phone TEXT, email TEXT, website TEXT,
        country TEXT, keyword TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
        owner TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(phone, website))""")
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
    if request.method == "POST":
        if PASSWORD and request.form.get("username") == ADMIN and request.form.get("password") == PASSWORD:
            session["user"] = ADMIN
            return redirect("/")
        flash("بيانات الدخول غير صحيحة أو لم يتم إعداد كلمة المرور.")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.get("/")
@auth
def home():
    c = db()
    stats = {
        "total": c.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "new": c.execute("SELECT COUNT(*) FROM leads WHERE status='new'").fetchone()[0],
        "contacted": c.execute("SELECT COUNT(*) FROM leads WHERE status='contacted'").fetchone()[0],
        "qualified": c.execute("SELECT COUNT(*) FROM leads WHERE status='qualified'").fetchone()[0],
    }
    leads = c.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
    c.close()
    return render_template("index.html", stats=stats, leads=leads, user=session["user"])

@app.post("/api/search")
@auth
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
    data = {k: v for k, v in data.items() if k in ("status", "owner")}
    if not data:
        return jsonify(error="لا توجد تغييرات صالحة"), 400
    if "status" in data and data["status"] not in ("new", "contacted", "qualified", "won", "lost", "optout"):
        return jsonify(error="حالة غير صالحة"), 400
    c = db()
    c.execute("UPDATE leads SET " + ",".join(k + "=?" for k in data) + " WHERE id=?",
              (*data.values(), lead_id))
    changed = c.total_changes
    c.commit()
    c.close()
    return jsonify(ok=bool(changed))

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 5000)), debug=False)
