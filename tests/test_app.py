import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MIRAGE_DB"] = "/tmp/mirage-test-" + str(os.getpid()) + ".db"
os.environ["MIRAGE_ADMIN_PASSWORD"] = "test-password"
import app

def logged_in():
    client = app.app.test_client()
    response = client.post("/login", data={"username": "admin", "password": "test-password"})
    assert response.status_code == 302
    return client

def csrf(client):
    with client.session_transaction() as session_data:
        return session_data["csrf_token"]

def test_health():
    response = app.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"

def test_login_required():
    assert app.app.test_client().get("/").status_code == 302

def test_login_dashboard():
    client = logged_in()
    assert client.get("/").status_code == 200

def test_update_requires_login():
    assert app.app.test_client().patch("/api/leads/1", json={"status": "won"}).status_code == 302

def test_private_ip_is_blocked(monkeypatch):
    monkeypatch.setattr(app.socket, "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 0))])
    assert app.is_public_url("http://localhost/") is False

def test_non_http_url_is_blocked():
    assert app.is_public_url("file:///etc/passwd") is False

def test_cross_origin_mutation_is_blocked():
    client = logged_in()
    response = client.post("/api/search", json={"keyword": "cleaning"},
                           headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf(client)})
    assert response.status_code == 403

def test_search_saves_and_deduplicates(monkeypatch):
    client = logged_in()
    row = ("Test Company", "+966501234567", "hello@test.example",
           "https://company.example", "السعودية", "cleaning", 90)
    monkeypatch.setattr(app, "discover", lambda *a: ([row], ""))
    first = client.post("/api/search", json={"keyword": "cleaning"}, headers={"X-CSRF-Token": csrf(client)})
    second = client.post("/api/search", json={"keyword": "cleaning"}, headers={"X-CSRF-Token": csrf(client)})
    assert first.json["added"] == 1
    assert second.json["added"] == 0

def test_csv_requires_login():
    assert app.app.test_client().get("/api/leads.csv").status_code == 302

def test_excel_export():
    client = logged_in()
    response = client.get("/api/leads.xlsx")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def test_security_headers():
    response = app.app.test_client().get("/health")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"

def test_team_requires_admin_or_manager():
    assert app.app.test_client().get("/team").status_code == 302

def test_sales_user_cannot_create_search():
    c = logged_in()
    assert c.get("/team").status_code == 200

def test_sales_user_only_edits_assigned_leads(monkeypatch):
    cdb = app.db()
    username = "sales-" + str(os.getpid())
    cdb.execute("INSERT OR REPLACE INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
                (username, app.generate_password_hash("long-test-password"), "sales"))
    own_id = cdb.execute(
        "INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
        ("Own Lead", "+966501119991", "", "https://own.example", "SA", "test", 60, username)).lastrowid
    other_id = cdb.execute(
        "INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
        ("Other Lead", "+966501119992", "", "https://other.example", "SA", "test", 60, "someone-else")).lastrowid
    cdb.commit()
    cdb.close()
    client = app.app.test_client()
    login_response = client.post("/login", data={"username": username, "password": "long-test-password"})
    assert login_response.status_code == 302
    assert client.patch("/api/leads/" + str(own_id), json={"status": "contacted"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 200
    assert client.patch("/api/leads/" + str(other_id), json={"status": "contacted"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 403
    assert client.post("/api/search", json={"keyword": "test"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 403

def test_campaign_webhook_requires_secret_and_consent(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_WEBHOOK_TOKEN", "webhook-test-secret")
    client = app.app.test_client()
    denied = client.post("/api/webhooks/leads/meta_ads", json={
        "company": "Demo Co", "phone": "+971500001234", "consent": True
    })
    assert denied.status_code == 401
    no_consent = client.post("/api/webhooks/leads/meta_ads",
        headers={"X-Mirage-Webhook-Token": "webhook-test-secret"},
        json={"company": "Demo Co", "phone": "+971500001234"})
    assert no_consent.status_code == 400

def test_campaign_webhook_saves_and_deduplicates(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_WEBHOOK_TOKEN", "webhook-test-secret")
    client = app.app.test_client()
    headers = {"X-Mirage-Webhook-Token": "webhook-test-secret"}
    payload = {"company": "Campaign Co", "phone": "+971500009876",
               "email": "lead@campaign.example", "campaign": "Q4 Leads",
               "external_id": "meta-unique-" + str(os.getpid()), "consent": True}
    first = client.post("/api/webhooks/leads/meta_ads", headers=headers, json=payload)
    second = client.post("/api/webhooks/leads/meta_ads", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json["duplicate"] is True

def test_sales_user_cannot_access_unassigned_leads_or_search():
    cdb = app.db()
    username = "sales-scope-" + str(os.getpid())
    cdb.execute("INSERT OR REPLACE INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
                (username, app.generate_password_hash("long-test-password"), "sales"))
    own_id = cdb.execute(
        "INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
        ("Own Lead", "+966501119991", "", "https://own-scope.example", "SA", "test", 60, username)).lastrowid
    other_id = cdb.execute(
        "INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
        ("Other Lead", "+966501119992", "", "https://other-scope.example", "SA", "test", 60, "another-user")).lastrowid
    cdb.commit()
    cdb.close()
    client = app.app.test_client()
    login_response = client.post("/login", data={"username": username, "password": "long-test-password"})
    assert login_response.status_code == 302
    assert client.patch("/api/leads/" + str(own_id), json={"status": "contacted"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 200
    assert client.patch("/api/leads/" + str(other_id), json={"status": "contacted"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 403
    assert client.post("/api/search", json={"keyword": "test"}, headers={"X-CSRF-Token": csrf(client)}).status_code == 403

def test_robots_txt_can_block_page(monkeypatch):
    monkeypatch.setattr(app, "safe_fetch", lambda url: "User-agent: MirageLeadResearch\nDisallow: /private")
    app._robots_cache.clear()
    assert app.robots_allowed("https://public.example/private/data") is False
    assert app.robots_allowed("https://public.example/open") is True

def test_authenticated_mutation_requires_csrf():
    client = logged_in()
    response = client.post("/api/search", json={"keyword": "csrf"})
    assert response.status_code == 400

def test_sales_csv_export_is_scoped_to_assigned_leads():
    cdb = app.db()
    suffix = str(os.getpid())[-7:]
    username = "export-sales-" + suffix
    own_phone = "+2010" + suffix
    other_phone = "+2011" + suffix
    cdb.execute("INSERT OR REPLACE INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
                (username, app.generate_password_hash("long-test-password"), "sales"))
    cdb.execute("INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
                ("Visible Company", own_phone, "", "https://visible-" + suffix + ".example", "EG", "test", 60, username))
    cdb.execute("INSERT INTO leads(company,phone,email,website,country,keyword,score,owner) VALUES(?,?,?,?,?,?,?,?)",
                ("Private Company", other_phone, "", "https://private-" + suffix + ".example", "EG", "test", 60, "other-sales"))
    cdb.commit()
    cdb.close()
    client = app.app.test_client()
    client.post("/login", data={"username": username, "password": "long-test-password"})
    response = client.get("/api/leads.csv")
    body = response.get_data(as_text=True)
    assert "Visible Company" in body
    assert "Private Company" not in body


def test_crm_activities_tasks_and_sales_scope():
    cdb = app.db()
    suffix = str(os.getpid())
    username = "crm-user-" + suffix
    cdb.execute("INSERT OR REPLACE INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
                (username, app.generate_password_hash("long-test-password"), "sales"))
    own = cdb.execute("INSERT INTO leads(company,phone,website,owner) VALUES(?,?,?,?)",
                      ("CRM Own", "+20100000" + suffix[-5:], "https://crm-own-" + suffix + ".example", username)).lastrowid
    other = cdb.execute("INSERT INTO leads(company,phone,website,owner) VALUES(?,?,?,?)",
                        ("CRM Other", "+20111111" + suffix[-5:], "https://crm-other-" + suffix + ".example", "other-user")).lastrowid
    cdb.commit()
    cdb.close()
    client = app.app.test_client()
    client.post("/login", data={"username": username, "password": "long-test-password"})
    headers = {"X-CSRF-Token": csrf(client)}
    created = client.post(f"/api/leads/{own}/activities",
                          json={"activity_type": "call", "note": "تم التواصل"}, headers=headers)
    assert created.status_code == 201
    assert client.get(f"/api/leads/{own}/activities").json["activities"][0]["note"] == "تم التواصل"
    assert client.post(f"/api/leads/{other}/activities",
                       json={"activity_type": "note", "note": "ممنوع"}, headers=headers).status_code == 403
    task = client.post("/api/tasks", json={"lead_id": own, "title": "متابعة العميل",
                        "due_at": "2026-11-10T10:00", "assigned_to": "other-user"}, headers=headers)
    assert task.status_code == 201
    assert task.json["task"]["assigned_to"] == username
    task_id = task.json["task"]["id"]
    assert client.patch(f"/api/tasks/{task_id}", json={"status": "done"}, headers=headers).status_code == 200
    assert client.get("/api/tasks").json["tasks"][0]["status"] == "done"
    assert client.post("/api/tasks", json={"lead_id": other, "title": "اختراق نطاق",
                        "due_at": "2026-11-10T10:00"}, headers=headers).status_code == 403
