"""Cấu hình kiểm thử: database SQLite trong bộ nhớ, đồng hồ giả lập, dữ liệu mẫu của seed.py.

Không cần PostgreSQL để chạy bộ kiểm thử này.
"""
import os
import tempfile
from datetime import datetime, timedelta

# PHẢI đặt trước khi import app (config.py đọc biến môi trường lúc import)
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test"
os.environ["BACKUP_DIR"] = tempfile.mkdtemp(prefix="gyusachi-test-backups-")

import pytest
from flask import g
from werkzeug.security import generate_password_hash

import seed
from app import admin_service, create_app, db, models, services

# băm mật khẩu nhẹ hơn để bộ kiểm thử chạy nhanh (chỉ trong kiểm thử)
models.generate_password_hash = lambda pw: generate_password_hash(pw, method="pbkdf2:sha256:1000")


class Clock:
    """Đồng hồ giả: mặc định Thứ 4 11/11/2026 12:00 (đang trong ca trưa 10:30–14:00)."""

    def __init__(self):
        self.t = datetime(2026, 11, 11, 12, 0)

    def __call__(self):
        return self.t

    def advance(self, **kwargs):
        self.t += timedelta(**kwargs)


@pytest.fixture(scope="session")
def _app():
    app = create_app()
    app.config.update(TESTING=True)

    # Bộ kiểm thử giữ MỘT app context mở suốt để dùng database, nên `flask.g` (nơi Flask-Login nhớ
    # người dùng hiện tại) sẽ sống qua nhiều request. Xoá nó trước mỗi request để mỗi request đọc lại
    # người dùng từ phiên đăng nhập, đúng như khi chạy thật.
    def forget_cached_user():
        g.pop("_login_user", None)

    app.before_request_funcs.setdefault(None, []).insert(0, forget_cached_user)
    return app


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(autouse=True)
def world(_app, clock, monkeypatch):
    """Mỗi test bắt đầu từ database sạch có dữ liệu mẫu và đồng hồ giả."""
    ctx = _app.app_context()
    ctx.push()
    db.drop_all()
    db.create_all()
    seed.populate()
    for module in (services, admin_service):          # các module dùng now() để so sánh thời gian
        monkeypatch.setattr(module, "now", clock)
    yield
    db.session.remove()
    ctx.pop()


@pytest.fixture
def client(_app):
    return _app.test_client()


PASSWORDS = {u: pw for u, _name, _role, pw in seed.USERS}


@pytest.fixture
def login(client):
    def _login(username):
        r = client.post("/login", data={"username": username, "password": PASSWORDS[username]})
        assert r.status_code == 302, f"đăng nhập {username} không thành công"
        return r
    return _login
