"""Trang Admin: vai trò, tài khoản, tham số, máy in, sao lưu theo lịch, dọn dẹp, nhật ký."""
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

import seed
from app import admin_service as adm
from app import audit, db
from app.models import (
    AuditLog, CancelRequest, ErrorLog, Invoice, LoginLog, Order, Permission, Role, Shift, StaffCall,
    TableSession, User, shift_tables,
)
from app.services import BusinessError
from helpers import add_order, open_table, paid_session, role, table, user


# ---------------------------------------------------------------- vai trò
def test_role_rules():
    r = adm.create_role("Ketoan")
    with pytest.raises(BusinessError):
        adm.create_role("KETOAN")                           # trùng tên (không phân biệt hoa thường)
    with pytest.raises(BusinessError):
        adm.create_role("   ")
    adm.rename_role(r.id, "Ke toan")
    for system in ("BEP", "ADMIN", "CHU"):
        with pytest.raises(BusinessError):
            adm.rename_role(role(system).id, "Doi ten")
        with pytest.raises(BusinessError):
            adm.delete_role(role(system).id)


def test_cannot_delete_role_in_use():
    r = adm.create_role("Ketoan")
    u = adm.create_account("kt1", "123456", "Kế Toán", r.id)
    with pytest.raises(BusinessError):
        adm.delete_role(r.id)
    db.session.delete(u)
    db.session.commit()
    adm.delete_role(r.id)
    assert Role.query.filter_by(name="Ketoan").count() == 0


def test_permission_matrix_never_changes_admin():
    adm.set_permission_matrix({role("BEP").id: {"CAN_COOK", "CAN_OPEN_TABLE"}, role("ADMIN").id: set()})
    assert {p.code for p in role("BEP").permissions} == {"CAN_COOK", "CAN_OPEN_TABLE"}
    assert len(role("ADMIN").permissions) == len(seed.PERMS)
    with pytest.raises(BusinessError):
        adm.set_permission_matrix({role("BEP").id: {"CAN_FLY"}})


def test_seed_topup_only_adds_new_permissions():
    p = Permission.query.filter_by(code="CAN_CONFIG_SYSTEM").one()
    for r in Role.query.all():
        if p in r.permissions:
            r.permissions.remove(p)
    db.session.delete(p)
    role("BEP").permissions = list(Permission.query.filter(Permission.code.in_(["CAN_COOK", "CAN_OPEN_TABLE"])))
    db.session.commit()
    added = seed.top_up_permissions()
    assert any("CAN_CONFIG_SYSTEM" in a for a in added)
    assert "CAN_CONFIG_SYSTEM" in {x.code for x in role("ADMIN").permissions}
    assert {x.code for x in role("BEP").permissions} == {"CAN_COOK", "CAN_OPEN_TABLE"}      # chỉnh sửa của Admin được giữ
    assert seed.top_up_permissions() == []                                                  # chạy lại không thêm gì


# ---------------------------------------------------------------- tài khoản
def test_admin_can_create_any_role():
    for i, name in enumerate(("CHU", "QUAN_LY", "BEP")):
        u = adm.create_account(f"tk{i}", "123456", f"TK {i}", role(name).id)
        assert u.role.name == name


def test_last_active_admin_is_protected():
    a = user("admin")
    with pytest.raises(BusinessError):
        adm.lock_account(a.id, True, acting_user_id=999)               # chỉ còn một Admin
    with pytest.raises(BusinessError):
        adm.lock_account(a.id, True, acting_user_id=a.id)              # không tự khoá mình
    with pytest.raises(BusinessError):
        adm.edit_account(a.id, "Admin", role("CHU").id, acting_user_id=999)    # không hạ Admin cuối
    b = adm.create_account("admin2", "123456", "Admin 2", role("ADMIN").id)
    adm.lock_account(a.id, True, acting_user_id=b.id)                  # đã có Admin khác nên được
    with pytest.raises(BusinessError):
        adm.lock_account(b.id, True, acting_user_id=a.id)              # b lại là Admin cuối


def test_reset_password_rules():
    with pytest.raises(BusinessError):
        adm.reset_password(user("bep").id, "ngan")
    u = user("bep")
    u.failed_attempts, u.locked_until = 4, datetime(2030, 1, 1)
    db.session.commit()
    adm.reset_password(u.id, "matkhaumoi")
    assert u.check_password("matkhaumoi") and u.failed_attempts == 0 and u.locked_until is None


# ---------------------------------------------------------------- tham số và máy in
def test_system_parameters_are_validated():
    good = {"session_timeout_minutes": 60, "max_login_attempts": 3, "cancel_minutes": 10}
    for key, bad in (("session_timeout_minutes", 2), ("max_login_attempts", 99), ("cancel_minutes", 0), ("cancel_minutes", None)):
        with pytest.raises(BusinessError):
            adm.update_params({**good, key: bad})
    assert adm.get_params()["cancel_minutes"] == 5                     # lần lỗi không làm đổi gì
    adm.update_params(good)
    assert adm.get_params() == good


def test_printer_rules():
    with pytest.raises(BusinessError):
        adm.update_printer("NETWORK", "", 9100)
    for port in (None, 0, 70000):
        with pytest.raises(BusinessError):
            adm.update_printer("NETWORK", "192.168.1.50", port)
    with pytest.raises(BusinessError):
        adm.update_printer("FAX", "x", 1)
    adm.update_printer("NETWORK", "192.168.1.50", 9100)
    assert adm.get_printer() == {"type": "NETWORK", "address": "192.168.1.50", "port": "9100"}
    adm.update_printer("USB", "POS-80", None)
    assert adm.get_printer() == {"type": "USB", "address": "POS-80", "port": ""}
    with pytest.raises(BusinessError):
        adm.test_printer()                                             # chỉ thử được máy in mạng
    adm.update_printer("", "", None)
    assert adm.get_printer()["type"] == ""


# ---------------------------------------------------------------- sao lưu
def test_backup_schedule_validation():
    for mode, hhmm, keep in (("weekly", "02:00", 7), ("daily", "25:99", 7), ("daily", "02:00", 0), ("daily", "02:00", 61)):
        with pytest.raises(BusinessError):
            adm.update_backup_schedule(mode, hhmm, keep)
    adm.update_backup_schedule("daily", "03:15", 10)
    assert adm.backup_schedule() == {"mode": "daily", "time": "03:15", "keep": 10, "last_auto": ""}


def test_scheduled_backup_runs_once_per_day(clock, monkeypatch):
    calls = []
    monkeypatch.setattr(adm, "run_backup_now", lambda *a, **k: calls.append(1) or "b.sql")
    adm.update_backup_schedule("daily", "02:00", 7)
    clock.t = datetime(2026, 11, 11, 1, 0)
    assert adm.run_scheduled_backup_if_due() is None                   # chưa tới giờ
    clock.t = datetime(2026, 11, 11, 3, 0)
    assert adm.run_scheduled_backup_if_due() == "b.sql"
    assert adm.run_scheduled_backup_if_due() is None and len(calls) == 1   # cùng ngày không chạy lại
    assert ErrorLog.query.filter_by(level="INFO").count() == 1
    clock.t = datetime(2026, 11, 12, 3, 0)
    assert adm.run_scheduled_backup_if_due() == "b.sql" and len(calls) == 2


def test_manual_mode_never_backs_up_by_itself(clock, monkeypatch):
    monkeypatch.setattr(adm, "run_backup_now", lambda *a, **k: pytest.fail("không được tự chạy"))
    clock.t = datetime(2026, 11, 11, 23, 0)
    assert adm.run_scheduled_backup_if_due() is None


def test_failed_scheduled_backup_is_not_retried_all_day(clock, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise BusinessError("pg_dump lỗi")

    monkeypatch.setattr(adm, "run_backup_now", boom)
    adm.update_backup_schedule("daily", "02:00", 7)
    clock.t = datetime(2026, 11, 11, 3, 0)
    assert adm.run_scheduled_backup_if_due() is None
    assert adm.run_scheduled_backup_if_due() is None
    assert len(calls) == 1


def test_restore_needs_the_confirmation_word():
    with pytest.raises(BusinessError, match="PHUC HOI"):
        adm.restore_backup_file("gyusachi-x.sql", "co")


# ---------------------------------------------------------------- dọn dẹp dữ liệu cũ
OLD, RECENT = datetime(2025, 9, 1, 12, 0), datetime(2026, 11, 10, 12, 0)


def make_history():
    old = paid_session(OLD, OLD.replace(hour=13), code="B01")
    add_order(old, OLD.replace(minute=5), ("Trà đá", 1, "READY"))
    item = Order.query.one().items[0]
    db.session.add_all([CancelRequest(order_item_id=item.id, status="REJECTED"), StaffCall(session_id=old.id),
                        Shift(user_id=user("phucvu").id, work_date=OLD.date(), start_time=datetime(2000, 1, 1, 10).time(),
                              end_time=datetime(2000, 1, 1, 14).time(), tables=[table("B01")]),
                        AuditLog(user_id=user("quanly").id, action="SHIFT_ADD", created_at=OLD),
                        LoginLog(username="bep", event="LOGIN", created_at=OLD),
                        ErrorLog(level="ERROR", message="cũ", created_at=OLD)])
    recent = paid_session(RECENT, RECENT.replace(hour=13), code="B02")
    add_order(recent, RECENT.replace(minute=5), ("Kim chi", 1, "READY"))
    db.session.add_all([AuditLog(user_id=user("quanly").id, action="SHIFT_ADD", created_at=RECENT),
                        LoginLog(username="bep", event="LOGIN", created_at=RECENT)])
    stale_open = open_table("B03")                                     # phiên mở từ lâu nhưng CHƯA đóng: phải giữ
    stale_open.opened_at = OLD
    db.session.commit()


def test_cleanup_minimum_retention():
    for months in (None, 0, 2):
        with pytest.raises(BusinessError):
            adm.cleanup_preview(months)
    with pytest.raises(BusinessError):
        adm.cleanup_preview(121)


def test_cleanup_preview_does_not_delete():
    make_history()
    _, rows = adm.cleanup_preview(12)
    counts = dict(rows)
    assert counts["Phiên bàn"] == 1 and counts["Hoá đơn"] == 1 and counts["Đơn gọi món"] == 1
    assert counts["Món đã gọi"] == 1 and counts["Yêu cầu huỷ món"] == 1 and counts["Lượt gọi nhân viên"] == 1
    assert counts["Ca làm việc"] == 1 and counts["Nhật ký thao tác"] == 1
    assert counts["Nhật ký đăng nhập"] == 1 and counts["Nhật ký lỗi"] == 1
    assert TableSession.query.count() == 3


def test_cleanup_needs_confirmation_and_a_backup(monkeypatch):
    make_history()
    with pytest.raises(BusinessError):
        adm.run_cleanup(12, "xoá")
    monkeypatch.setattr(adm, "run_backup_now", lambda *a, **k: (_ for _ in ()).throw(BusinessError("không sao lưu được")))
    with pytest.raises(BusinessError, match="không sao lưu được"):
        adm.run_cleanup(12, "xoa du lieu")
    assert TableSession.query.count() == 3                             # không sao lưu được thì không xoá gì


def test_cleanup_removes_only_old_closed_data(monkeypatch):
    make_history()
    monkeypatch.setattr(adm, "run_backup_now", lambda *a, **k: "x.sql")
    adm.run_cleanup(12, "Xoa Du Lieu")
    assert TableSession.query.count() == 2                             # phiên gần đây + phiên còn mở
    assert Invoice.query.count() == 1 and Order.query.count() == 1
    assert CancelRequest.query.count() == 0 and StaffCall.query.count() == 0 and Shift.query.count() == 0
    assert db.session.scalar(select(func.count()).select_from(shift_tables)) == 0
    assert AuditLog.query.count() == 1 and LoginLog.query.count() == 1 and ErrorLog.query.count() == 0
    with pytest.raises(BusinessError):
        adm.run_cleanup(12, "xoa du lieu")                             # không còn gì quá hạn


# ---------------------------------------------------------------- nhật ký
def test_operation_log_filters():
    def log(who, action, when):
        db.session.add(AuditLog(user_id=user(who).id, action=action, detail="", created_at=when))

    day = datetime(2026, 11, 11, 9, 0)
    log("quanly", "MENU_DISH_ADD", day)
    log("phucvu", "PASSWORD_CHANGE", day)
    log("admin", "BACKUP_RUN", day)
    db.session.commit()
    d = date(2026, 11, 11)
    total, rows = audit.search_logs(d, d)                              # mặc định: chỉ Quản lý (màn của Chủ)
    assert total == 1 and rows[0]["action"] == "Thêm món"
    assert audit.search_logs(d, d, role_names=None)[0] == 3            # Admin xem tất cả
    assert audit.search_logs(d, d, role_names=None, action="BACKUP_RUN")[0] == 1
    assert audit.search_logs(d, d, user_id=user("admin").id)[0] == 1
    assert audit.search_logs(date(2026, 11, 12), date(2026, 11, 12), role_names=None)[0] == 0
    with pytest.raises(BusinessError):
        audit.search_logs(date(2026, 11, 12), date(2026, 11, 1))


def test_error_and_login_logs():
    day = datetime(2026, 11, 11, 9, 0)
    db.session.add_all([ErrorLog(level="ERROR", message="a", created_at=day), ErrorLog(level="WARNING", message="b", created_at=day),
                        LoginLog(username="x", success=False, event=None, created_at=day),     # dòng cũ chưa có cột event
                        LoginLog(username="y", success=True, event="TIMEOUT", created_at=day)])
    db.session.commit()
    d = date(2026, 11, 11)
    assert audit.search_errors(d, d)[0] == 2 and audit.search_errors(d, d, "ERROR")[0] == 1
    _, logins = audit.search_logins(d, d)
    events = {r["username"]: r for r in logins}
    assert events["x"]["event"] == "LOGIN_FAIL" and "Hết phiên" in events["y"]["event_vi"]
    assert audit.search_logins(d, d, "y")[0] == 1


def test_log_error_never_raises_and_normalizes_level():
    audit.log_error("LẠ", "x")
    assert ErrorLog.query.one().level == "ERROR"
