"""Phân quyền theo vai trò, khoá tài khoản, hết phiên, đổi mật khẩu (qua giao diện HTTP)."""
import time

import pytest

from app import admin_service as adm
from app import db
from app import services as sv
from app.models import ErrorLog, LoginLog, User
from app.services import BusinessError
from helpers import role, user

# (người dùng, địa chỉ, mã trả về mong đợi)
ACCESS = [
    ("phucvu", "/waiter/tables", 200), ("phucvu", "/kitchen/", 403), ("phucvu", "/cashier/", 403),
    ("phucvu", "/manager/overview", 403), ("phucvu", "/manager/staff", 403),
    ("phucvu", "/owner/reports", 403), ("phucvu", "/admin/users", 403),
    ("bep", "/kitchen/", 200), ("bep", "/kitchen/menu", 200), ("bep", "/waiter/tables", 403), ("bep", "/cashier/", 403),
    ("thungan", "/cashier/", 200), ("thungan", "/kitchen/", 403), ("thungan", "/waiter/tables", 403),
    ("quanly", "/manager/overview", 200), ("quanly", "/manager/reports", 200), ("quanly", "/manager/menu", 200),
    ("quanly", "/manager/staff", 200), ("quanly", "/manager/schedule", 200), ("quanly", "/manager/tables", 200),
    ("quanly", "/owner/reports", 403), ("quanly", "/owner/managers", 403), ("quanly", "/owner/config", 403),
    ("quanly", "/owner/logs", 403), ("quanly", "/admin/users", 403), ("quanly", "/admin/logs", 403),
    ("quanly", "/kitchen/", 403),
    ("chu", "/owner/reports", 200), ("chu", "/owner/compare", 200), ("chu", "/owner/export", 200),
    ("chu", "/owner/data", 200), ("chu", "/owner/logs", 200), ("chu", "/owner/managers", 200),
    ("chu", "/owner/config", 200), ("chu", "/manager/menu", 403), ("chu", "/admin/users", 403),
    ("chu", "/admin/logs", 403), ("chu", "/admin/settings", 403), ("chu", "/admin/backups", 403),
    ("admin", "/admin/users", 200), ("admin", "/admin/roles", 200), ("admin", "/admin/logs", 200),
    ("admin", "/admin/errors", 200), ("admin", "/admin/logins", 200), ("admin", "/admin/settings", 200),
    ("admin", "/owner/managers", 200), ("admin", "/manager/menu", 200),
]


@pytest.mark.parametrize("who, path, status", ACCESS)
def test_access_matrix(client, login, who, path, status):
    login(who)
    assert client.get(path).status_code == status


@pytest.mark.parametrize("path", ["/waiter/tables", "/kitchen/", "/cashier/", "/manager/overview",
                                  "/owner/reports", "/admin/users", "/password"])
def test_anonymous_users_are_sent_to_login(client, path):
    r = client.get(path)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


@pytest.mark.parametrize("who, landing", [
    ("phucvu", "/waiter/tables"), ("bep", "/kitchen/"), ("thungan", "/cashier/"),
    ("quanly", "/manager/overview"), ("chu", "/owner/reports"), ("admin", "/admin/users"),
])
def test_each_role_lands_on_its_own_screen(login, who, landing):
    assert login(who).headers["Location"].endswith(landing)


# ---------------------------------------------------------------- không leo thang đặc quyền
def test_manager_cannot_create_other_managers(client, login):
    login("quanly")
    r = client.post("/owner/managers/add", data={"username": "hack", "password": "123456", "full_name": "H"})
    assert r.status_code == 403 and User.query.filter_by(username="hack").count() == 0


def test_manager_cannot_create_a_manager_through_staff_screen(client, login):
    login("quanly")
    client.post("/manager/staff/add", data={"username": "ql99", "password": "123456", "full_name": "X", "role": "QUAN_LY"})
    assert User.query.filter_by(username="ql99").count() == 0


def test_manager_cannot_edit_admin_account(client, login):
    login("quanly")
    assert client.get(f"/manager/staff/{user('admin').id}/edit").status_code == 403
    assert client.post(f"/manager/staff/{user('admin').id}/lock").status_code == 302    # bị từ chối bằng thông báo
    assert user("admin").is_locked is False


def test_waiter_cannot_drive_the_kitchen(client, login):
    login("phucvu")
    assert client.post("/kitchen/items/1/cooking").status_code == 403


# ---------------------------------------------------------------- vai trò tự tạo và chỉnh quyền
def test_custom_role_lands_on_first_allowed_screen(client, login):
    r = adm.create_role("Ketoan")
    adm.set_permission_matrix({r.id: {"CAN_VIEW_SHIFT_REPORT"}})
    adm.create_account("ketoan", "123456", "Kế Toán", r.id)
    resp = client.post("/login", data={"username": "ketoan", "password": "123456"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/manager/overview")
    assert client.get("/manager/overview").status_code == 200
    assert client.get("/kitchen/").status_code == 403


def test_permission_change_takes_effect_immediately(client, login):
    login("bep")
    assert client.get("/waiter/tables").status_code == 403
    adm.set_permission_matrix({role("BEP").id: {"CAN_COOK", "CAN_OPEN_TABLE"}})
    assert client.get("/waiter/tables").status_code == 200
    adm.set_permission_matrix({role("BEP").id: {"CAN_COOK"}})
    assert client.get("/waiter/tables").status_code == 403


# ---------------------------------------------------------------- khoá tài khoản
def test_lockout_after_too_many_wrong_passwords(client):
    for _ in range(5):                                           # mặc định 5 lần
        assert client.post("/login", data={"username": "phucvu", "password": "sai"}).status_code == 200
    r = client.post("/login", data={"username": "phucvu", "password": "123456"})
    assert r.status_code == 200                                  # đúng mật khẩu nhưng đang bị khoá tạm
    assert user("phucvu").locked_until is not None
    assert ErrorLog.query.filter_by(level="WARNING").count() == 1
    assert LoginLog.query.filter_by(event="LOGIN_FAIL").count() >= 6


def test_lockout_threshold_follows_the_setting(client):
    adm.update_params({"session_timeout_minutes": 30, "max_login_attempts": 3, "cancel_minutes": 5})
    for _ in range(3):
        client.post("/login", data={"username": "bep", "password": "sai"})
    assert client.post("/login", data={"username": "bep", "password": "123456"}).status_code == 200


def test_reset_password_unlocks_a_temporarily_locked_account(client):
    for _ in range(5):
        client.post("/login", data={"username": "bep", "password": "sai"})
    adm.reset_password(user("bep").id, "matkhaumoi")
    assert client.post("/login", data={"username": "bep", "password": "matkhaumoi"}).status_code == 302


def test_locked_account_cannot_log_in(client):
    sv.set_staff_locked(user("bep").id, True)
    assert client.post("/login", data={"username": "bep", "password": "123456"}).status_code == 200


def test_locking_kicks_out_a_logged_in_user(client, login):
    login("bep")
    assert client.get("/kitchen/").status_code == 200
    sv.set_staff_locked(user("bep").id, True)
    r = client.get("/kitchen/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# ---------------------------------------------------------------- nhật ký đăng nhập, hết phiên
def test_login_and_logout_are_logged(client, login):
    login("bep")
    client.get("/logout")
    events = [e.event for e in LoginLog.query.filter_by(username="bep").order_by(LoginLog.id)]
    assert events == ["LOGIN", "LOGOUT"]


def test_idle_session_expires(client, login):
    login("bep")
    with client.session_transaction() as s:
        s["last_seen"] = time.time() - 31 * 60                  # im lặng 31 phút (hạn mặc định 30)
    r = client.get("/kitchen/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert LoginLog.query.filter_by(username="bep", event="TIMEOUT").count() == 1
    assert client.get("/kitchen/").status_code == 302           # đã bị đăng xuất thật


def test_active_session_survives(client, login):
    login("bep")
    with client.session_transaction() as s:
        s["last_seen"] = time.time() - 10 * 60
    assert client.get("/kitchen/").status_code == 200


def test_timeout_follows_the_setting(client, login):
    adm.update_params({"session_timeout_minutes": 5, "max_login_attempts": 5, "cancel_minutes": 5})
    login("bep")
    with client.session_transaction() as s:
        s["last_seen"] = time.time() - 6 * 60
    assert client.get("/kitchen/").status_code == 302


# ---------------------------------------------------------------- đổi mật khẩu
@pytest.mark.parametrize("old, new, repeat", [
    ("sai", "matkhau1", "matkhau1"),          # mật khẩu cũ sai
    ("123456", "ngan", "ngan"),               # quá ngắn
    ("123456", "matkhau1", "matkhau2"),       # nhập lại không khớp
    ("123456", "123456", "123456"),           # trùng mật khẩu cũ
])
def test_change_password_rejections(old, new, repeat):
    with pytest.raises(BusinessError):
        sv.change_password(user("bep"), old, new, repeat)
    assert user("bep").check_password("123456")


def test_change_password_works_end_to_end(client, login):
    login("bep")
    r = client.post("/password", data={"old": "123456", "new": "matkhaumoi", "repeat": "matkhaumoi"})
    assert r.status_code == 302
    client.get("/logout")
    assert client.post("/login", data={"username": "bep", "password": "123456"}).status_code == 200
    assert client.post("/login", data={"username": "bep", "password": "matkhaumoi"}).status_code == 302
