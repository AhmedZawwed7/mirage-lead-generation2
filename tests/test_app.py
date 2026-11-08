import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MIRAGE_DB"] = "/tmp/mirage-test-" + str(os.getpid()) + ".db"
os.environ["MIRAGE_ADMIN_PASSWORD"] = "test-password"
import app

def logged_in():
    client = app.app.test_client()
    client.post("/login", data={"username": "admin", "password": "test-password"})
    return client

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
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403

def test_search_saves_and_deduplicates(monkeypatch):
    client = logged_in()
    row = ("Test Company", "+966501234567", "hello@test.example",
           "https://company.example", "السعودية", "cleaning", 90)
    monkeypatch.setattr(app, "discover", lambda *a: ([row], ""))
    first = client.post("/api/search", json={"keyword": "cleaning"})
    second = client.post("/api/search", json={"keyword": "cleaning"})
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
    c = app.app.test_client()
    c.post("/login", data={"username": "admin", "password": "test-password"})
    assert c.get("/team").status_code == 200
