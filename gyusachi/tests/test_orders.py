"""Gọi món: menu theo gói, giới hạn, giờ mở cửa, huỷ món trong thời hạn, luồng bếp."""
from datetime import datetime

import pytest

from app import db
from app import services as sv
from app.models import CancelRequest, Order, OrderItem
from app.services import BusinessError
from helpers import dish, open_table, place, user


# ---------------------------------------------------------------- menu theo gói
def test_menu_shows_only_dishes_of_the_package():
    low, high = open_table("B01", tier=1), open_table("B02", tier=6)
    names_low = {m.name for m in sv.menu_for_session(low)}
    names_high = {m.name for m in sv.menu_for_session(high)}
    assert "Bò Wagyu A5" not in names_low and "Bò Wagyu A5" in names_high
    assert names_low <= names_high                      # gói đắt gồm cả món của gói rẻ


def test_cannot_order_dish_above_package():
    sess = open_table(tier=1)
    with pytest.raises(BusinessError):
        place(sess, ("Bò Wagyu A5", 1))
    assert Order.query.count() == 0


@pytest.mark.parametrize("qty", [-1, 0, 6])             # Ba chỉ bò Mỹ tối đa 5 mỗi lần
def test_quantity_must_stay_within_limit(qty):
    sess = open_table()
    with pytest.raises(BusinessError):
        place(sess, ("Ba chỉ bò Mỹ", qty))


def test_quantity_at_limit_is_fine():
    sess = open_table()
    assert place(sess, ("Ba chỉ bò Mỹ", 5)).items[0].quantity == 5


def test_sold_out_and_hidden_dishes_cannot_be_ordered():
    sess = open_table()
    sv.set_sold_out(dish("Trà đá").id, True)
    with pytest.raises(BusinessError):
        place(sess, ("Trà đá", 1))
    sv.set_sold_out(dish("Trà đá").id, False)
    place(sess, ("Trà đá", 1))                          # hết rồi lại còn
    sv.set_dish_active(dish("Kim chi").id, False)
    with pytest.raises(BusinessError):
        place(sess, ("Kim chi", 1))                     # món bị ẩn khỏi menu


def test_one_bad_line_creates_nothing():
    sess = open_table(tier=1)
    with pytest.raises(BusinessError):
        place(sess, ("Ba chỉ bò Mỹ", 1), ("Bò Wagyu A5", 1))
    assert Order.query.count() == 0 and OrderItem.query.count() == 0


def test_empty_cart_is_rejected():
    with pytest.raises(BusinessError):
        sv.create_order(open_table(), [])


@pytest.mark.parametrize("when, allowed", [
    (datetime(2026, 11, 11, 12, 0), True),     # Thứ 4, ca trưa
    (datetime(2026, 11, 11, 14, 0), True),     # đúng giờ đóng cửa vẫn tính
    (datetime(2026, 11, 11, 15, 0), False),    # giữa hai ca
    (datetime(2026, 11, 11, 17, 0), True),     # ca tối
    (datetime(2026, 11, 11, 22, 30), False),   # sau giờ đóng cửa
    (datetime(2026, 11, 14, 15, 0), True),     # Thứ 7 mở cả ngày
    (datetime(2026, 11, 14, 23, 0), False),
])
def test_opening_hours(clock, when, allowed):
    sess = open_table()
    clock.t = when
    assert sv.is_open_now() is allowed
    if allowed:
        assert place(sess, ("Trà đá", 1))
    else:
        with pytest.raises(BusinessError):
            place(sess, ("Trà đá", 1))


def test_no_new_orders_once_payment_is_requested():
    sess = open_table()
    sv.request_payment(sess)
    with pytest.raises(BusinessError):
        place(sess, ("Trà đá", 1))


# ---------------------------------------------------------------- huỷ món
def test_cancel_within_window(clock):
    order = place(open_table(), ("Ba chỉ bò Mỹ", 2))
    clock.advance(minutes=4)
    req = sv.request_cancel(order.items[0].id, "đổi ý")
    assert req.status == "PENDING"


def test_cancel_after_window_is_rejected(clock):
    order = place(open_table(), ("Ba chỉ bò Mỹ", 2))
    clock.advance(minutes=6)
    with pytest.raises(BusinessError):
        sv.request_cancel(order.items[0].id, "muộn rồi")


def test_cancel_window_follows_the_setting(clock):
    sv.set_setting("cancel_minutes", 1)
    order = place(open_table(), ("Ba chỉ bò Mỹ", 2))
    clock.advance(minutes=2)
    with pytest.raises(BusinessError):
        sv.request_cancel(order.items[0].id, "")


def test_duplicate_cancel_request_is_blocked(clock):
    order = place(open_table(), ("Ba chỉ bò Mỹ", 2))
    sv.request_cancel(order.items[0].id, "")
    with pytest.raises(BusinessError):
        sv.request_cancel(order.items[0].id, "")
    assert CancelRequest.query.count() == 1


def test_kitchen_approves_cancel_only_before_cooking():
    order = place(open_table(), ("Ba chỉ bò Mỹ", 2), ("Trà đá", 1))
    fresh, started = order.items
    sv.set_item_status(started.id, "COOKING")
    r1, r2 = sv.request_cancel(fresh.id, ""), sv.request_cancel(started.id, "")
    sv.decide_cancel(r1.id, True, user("bep"))
    assert fresh.status == "CANCELLED" and r1.status == "APPROVED"
    with pytest.raises(BusinessError):
        sv.decide_cancel(r2.id, True, user("bep"))         # món đã chế biến thì không huỷ được
    assert started.status == "COOKING"


def test_kitchen_can_reject_cancel():
    item = place(open_table(), ("Ba chỉ bò Mỹ", 2)).items[0]
    req = sv.request_cancel(item.id, "")
    sv.decide_cancel(req.id, False, user("bep"))
    assert item.status == "PENDING" and req.status == "REJECTED"


def test_cancelled_item_cannot_be_cancelled_again():
    item = place(open_table(), ("Ba chỉ bò Mỹ", 2)).items[0]
    sv.decide_cancel(sv.request_cancel(item.id, "").id, True, user("bep"))
    with pytest.raises(BusinessError):
        sv.request_cancel(item.id, "")


def test_decided_request_cannot_be_decided_twice():
    item = place(open_table(), ("Ba chỉ bò Mỹ", 2)).items[0]
    req = sv.request_cancel(item.id, "")
    sv.decide_cancel(req.id, False, user("bep"))
    with pytest.raises(BusinessError):
        sv.decide_cancel(req.id, True, user("bep"))


# ---------------------------------------------------------------- luồng bếp
def test_kitchen_status_flow():
    item = place(open_table(), ("Ba chỉ bò Mỹ", 1)).items[0]
    with pytest.raises(BusinessError):
        sv.set_item_status(item.id, "READY")            # không nhảy cóc: phải qua "đang làm"
    sv.set_item_status(item.id, "COOKING")
    sv.set_item_status(item.id, "READY")
    assert item.status == "READY"
    with pytest.raises(BusinessError):
        sv.set_item_status(item.id, "COOKING")          # không quay ngược
    with pytest.raises(BusinessError):
        sv.set_item_status(item.id, "DONE")             # trạng thái lạ
