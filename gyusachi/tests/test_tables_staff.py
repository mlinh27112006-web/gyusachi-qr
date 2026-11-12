"""Bàn, nhân sự, phân ca (trùng giờ, trùng bàn)."""
from datetime import date, time

import pytest

from app import db
from app import services as sv
from app.models import DiningTable, Shift, User
from app.services import BusinessError
from helpers import open_table, role, table, user

TODAY = date(2026, 11, 11)             # ngày của đồng hồ giả
MORNING = (time(10, 30), time(14, 0))


# ---------------------------------------------------------------- bàn
def test_open_table_marks_it_in_use():
    sess = open_table("B01")
    assert table("B01").status == "IN_USE" and sess.is_open


def test_cannot_open_busy_or_locked_table():
    open_table("B01")
    with pytest.raises(BusinessError):
        open_table("B01")
    table("B02").is_locked = True
    db.session.commit()
    with pytest.raises(BusinessError):
        open_table("B02")


@pytest.mark.parametrize("adults, kids_mid, kids_free", [(0, 0, 0), (0, 0, 3), (-1, 2, 0)])
def test_need_at_least_one_paying_guest(adults, kids_mid, kids_free):
    with pytest.raises(BusinessError):
        open_table(adults=adults, kids_mid=kids_mid, kids_free=kids_free)


def test_change_table_keeps_payment_state():
    sess = open_table("B01")
    sv.request_payment(sess)
    sv.change_table(sess, table("B02").id)
    assert table("B01").status == "EMPTY"
    assert table("B02").status == "WAITING_PAYMENT" and sess.table.code == "B02"


def test_change_table_only_to_empty_unlocked_tables():
    sess = open_table("B01")
    open_table("B02")
    with pytest.raises(BusinessError):
        sv.change_table(sess, table("B02").id)           # bàn đang có khách, không gộp bàn
    table("B03").is_locked = True
    db.session.commit()
    with pytest.raises(BusinessError):
        sv.change_table(sess, table("B03").id)


# ---------------------------------------------------------------- tài khoản nhân viên
def test_manager_can_only_create_the_three_staff_roles():
    sv.create_staff("nv01", "123456", "Nhân viên 1", "BEP")
    for bad_role in ("QUAN_LY", "CHU", "ADMIN"):
        with pytest.raises(BusinessError):
            sv.create_staff(f"x{bad_role.lower()}", "123456", "X", bad_role)


def test_owner_can_only_create_managers():
    u = sv.create_staff("ql02", "123456", "Quản lý 2", "QUAN_LY", sv.MANAGER_ROLES)
    assert u.role.name == "QUAN_LY"
    with pytest.raises(BusinessError):
        sv.create_staff("bep9", "123456", "Bếp 9", "BEP", sv.MANAGER_ROLES)


@pytest.mark.parametrize("username, password, name", [
    ("ab", "123456", "Tên"),                   # tên đăng nhập quá ngắn
    ("Có Dấu", "123456", "Tên"),               # ký tự không hợp lệ
    ("hopLe", "12345", "Tên"),                 # mật khẩu dưới 6 ký tự
    ("hople", "123456", "   "),                # họ tên trống
])
def test_staff_input_validation(username, password, name):
    with pytest.raises(BusinessError):
        sv.create_staff(username, password, name, "BEP")


def test_username_must_be_unique_ignoring_case():
    with pytest.raises(BusinessError):
        sv.create_staff("PHUCVU", "123456", "Trùng tên", "BEP")


def test_password_is_stored_hashed():
    u = sv.create_staff("nv02", "matkhau1", "NV 2", "BEP")
    assert u.password_hash != "matkhau1" and u.check_password("matkhau1")


def test_manager_cannot_touch_manager_or_admin_accounts():
    for name in ("quanly", "chu", "admin"):
        with pytest.raises(BusinessError):
            sv.update_staff(user(name).id, "Đổi tên", "BEP")
        with pytest.raises(BusinessError):
            sv.set_staff_locked(user(name).id, True)


def test_unlock_clears_failed_attempts():
    u = user("phucvu")
    u.failed_attempts = 4
    db.session.commit()
    sv.set_staff_locked(u.id, True)
    sv.set_staff_locked(u.id, False)
    assert u.is_locked is False and u.failed_attempts == 0


# ---------------------------------------------------------------- phân ca
def shift(who="phucvu", day=TODAY, window=MORNING, tables=()):
    return sv.create_shift(user(who).id, day, window[0], window[1], [table(c).id for c in tables])


def test_waiter_shift_with_tables():
    s = shift(tables=("B01", "B02"))
    assert [t.code for t in s.tables] == ["B01", "B02"]


def test_same_person_cannot_have_overlapping_shifts():
    shift(window=(time(10, 30), time(14, 0)))
    with pytest.raises(BusinessError):
        shift(window=(time(13, 0), time(17, 0)))
    shift(window=(time(14, 0), time(18, 0)))              # nối tiếp sát giờ thì được
    shift(day=date(2026, 11, 12), window=(time(13, 0), time(17, 0)))   # ngày khác thì được


def test_same_table_cannot_go_to_two_waiters_at_the_same_time():
    other = sv.create_staff("phucvu2", "123456", "Phục vụ 2", "PHUC_VU")
    shift(tables=("B01",))
    with pytest.raises(BusinessError):
        sv.create_shift(other.id, TODAY, time(11, 0), time(13, 0), [table("B01").id])
    s = sv.create_shift(other.id, TODAY, time(11, 0), time(13, 0), [table("B02").id])   # bàn khác thì được
    assert s.tables[0].code == "B02"
    sv.create_shift(other.id, TODAY, time(14, 0), time(18, 0), [table("B01").id])        # giờ khác thì được


def test_only_waiters_get_tables():
    with pytest.raises(BusinessError):
        shift("bep", tables=("B01",))
    assert shift("bep").tables == []


def test_shift_time_and_date_rules():
    with pytest.raises(BusinessError):
        shift(window=(time(14, 0), time(10, 30)))          # giờ kết thúc phải sau giờ bắt đầu
    with pytest.raises(BusinessError):
        shift(window=(time(10, 0), time(10, 0)))
    with pytest.raises(BusinessError):
        shift(day=date(2026, 11, 10))                      # ngày đã qua


def test_cannot_schedule_locked_or_manager_accounts():
    sv.set_staff_locked(user("bep").id, True)
    with pytest.raises(BusinessError):
        shift("bep")
    with pytest.raises(BusinessError):
        sv.create_shift(user("quanly").id, TODAY, time(10, 30), time(14, 0), [])


def test_delete_shift_rules():
    future = shift(day=date(2026, 11, 12))
    sv.delete_shift(future.id)
    assert Shift.query.count() == 0
    past = Shift(user_id=user("bep").id, work_date=date(2026, 11, 1), start_time=time(10, 0), end_time=time(12, 0))
    db.session.add(past)
    db.session.commit()
    with pytest.raises(BusinessError):
        sv.delete_shift(past.id)


def test_leaving_the_waiter_role_drops_future_tables():
    s = shift(tables=("B01",))
    sv.update_staff(user("phucvu").id, "Phục vụ mẫu", "BEP")
    assert s.tables == []
    assert user("phucvu").role.name == "BEP"
