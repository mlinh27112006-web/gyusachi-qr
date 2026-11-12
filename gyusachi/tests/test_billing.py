"""Tính tiền, hoá đơn, thanh toán, checkout."""
import pytest

from app import services as sv
from app.models import BuffetPackage, Invoice
from app.services import BusinessError, calc_total
from helpers import open_table, pay, pkg, table, user


@pytest.mark.parametrize("price, adults, kids_mid, expected", [
    (299000, 2, 1, 747500),     # ví dụ của tài liệu: 299.000 × 2,5
    (219000, 1, 0, 219000),
    (219000, 0, 2, 219000),     # hai trẻ nửa giá = một suất người lớn
    (249500, 1, 1, 374250),     # giá lẻ vẫn ra số nguyên
    (469000, 4, 0, 1876000),
    (219000, 0, 0, 0),
])
def test_calc_total(price, adults, kids_mid, expected):
    assert calc_total(price, adults, kids_mid) == expected


def test_invoice_uses_formula_and_free_kids_cost_nothing():
    sess = open_table(tier=3, adults=2, kids_mid=1, kids_free=2)
    sv.request_payment(sess)
    inv = sv.create_invoice(sess, user("thungan"))
    assert inv.total == 747500
    assert inv.status == "UNPAID"


def test_price_is_frozen_when_table_opens():
    sess = open_table(tier=1, adults=2)                                  # mở bàn lúc giá gói 1 là 219.000
    new_prices = {p.id: p.price + (20000 if p.tier == 1 else 0) for p in BuffetPackage.query.all()}
    sv.update_package_prices(new_prices)                                 # Chủ tăng giá gói 1 lên 239.000
    sv.request_payment(sess)
    assert sv.create_invoice(sess, user("thungan")).total == 438000      # bàn đang ăn giữ giá cũ
    later = open_table("B02", tier=1)
    assert later.package_price == 239000                                 # bàn mở sau dùng giá mới
    assert pkg(1).name == "Buffet 239K"                                  # tên gói tự đổi theo giá


def test_invoice_needs_payment_request_first():
    sess = open_table()
    with pytest.raises(BusinessError):
        sv.create_invoice(sess, user("thungan"))


def test_unpaid_invoice_follows_guest_changes():
    sess = open_table(tier=1, adults=2)
    sv.request_payment(sess)
    sv.create_invoice(sess, user("thungan"))
    sv.update_guests(sess, 3, 0, 0)
    assert sv.create_invoice(sess, user("thungan")).total == 219000 * 3
    assert Invoice.query.count() == 1


def test_paid_invoice_is_frozen():
    sess = open_table()
    inv = pay(sess)
    assert inv.status == "PAID" and inv.paid_at is not None
    with pytest.raises(BusinessError):
        sv.confirm_paid(inv, "CASH")                 # không thu hai lần
    with pytest.raises(BusinessError):
        sv.create_invoice(sess, user("thungan"))     # không lập lại hoá đơn đã thu
    with pytest.raises(BusinessError):
        sv.update_guests(sess, 5, 0, 0)              # không sửa số khách sau khi đã thu


def test_confirm_paid_needs_a_valid_method():
    sess = open_table()
    sv.request_payment(sess)
    inv = sv.create_invoice(sess, user("thungan"))
    with pytest.raises(BusinessError):
        sv.confirm_paid(inv, "BITCOIN")
    assert inv.status == "UNPAID"


def test_checkout_needs_payment_and_frees_the_table():
    sess = open_table("B05")
    sv.request_payment(sess)
    sv.create_invoice(sess, user("thungan"))
    with pytest.raises(BusinessError):
        sv.checkout(sess)                            # chưa thu tiền thì chưa checkout được
    sv.confirm_paid(Invoice.query.one(), "TRANSFER")
    sv.checkout(sess)
    assert sess.is_open is False and sess.closed_at is not None
    assert table("B05").status == "EMPTY"
