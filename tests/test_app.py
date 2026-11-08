import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MIRAGE_DB"] = "/tmp/mirage-test-" + str(os.getpid()) + ".db"
os.environ["MIRAGE_ADMIN_PASSWORD"] = "test-password"
import app

def test_health():
    assert app.app.test_client().get("/health").json["status"] == "ok"

def test_login_required():
    assert app.app.test_client().get("/").status_code == 302

def test_login_dashboard():
    client = app.app.test_client()
    response = client.post("/login", data={"username": "admin", "password": "test-password"})
    assert response.status_code == 302
    assert client.get("/").status_code == 200

def test_update_requires_login():
    assert app.app.test_client().patch("/api/leads/1", json={"status": "won"}).status_code == 302
