"""Nghiệp vụ lõi của GYUSACHI.

Mọi quy tắc nằm ở đây; các route chỉ gọi hàm trong file này rồi trả về trang/JSON.
Khách và Phục vụ cùng dùng `create_order` (đúng ý "Phục vụ gọi món giống khách").
"""
from datetime import timedelta

from . import db, socketio
from .models import (
    CancelRequest, DiningTable, Invoice, MenuItem, Order, OrderItem,
    OpeningHour, Setting, StaffCall, TableSession,
)
from .utils import now


class BusinessError(Exception):
    """Lỗi nghiệp vụ: hiện nguyên văn cho người dùng."""


# ---------------------------------------------------------------- tiện ích
def get_setting(key, default=None):
    s = db.session.get(Setting, key)
    return s.value if s else default


def is_open_now():                                         # KH1.1.3
    t = now()
    rows = OpeningHour.query.filter_by(weekday=t.weekday()).all()
    return any(r.open_time <= t.time() <= r.close_time for r in rows)


def current_session(table):
    return TableSession.query.filter_by(table_id=table.id, is_open=True).first()


def menu_for_session(sess, category_id=None, keyword=None):   # KH2: món thuộc gói của bàn
    q = MenuItem.query.filter(
        MenuItem.is_active.is_(True),
        MenuItem.min_tier <= sess.package.tier,
    )
    if category_id:
        q = q.filter(MenuItem.category_id == int(category_id))
    if keyword:
        q = q.filter(MenuItem.name.ilike(f"%{keyword}%"))
    return q.order_by(MenuItem.category_id, MenuItem.name).all()


# ------------------------------------------------- Phục vụ: bàn, số khách (PV1)
def open_table(table_id, package_id, adults, kids_mid, kids_free, user):
    table = db.session.get(DiningTable, table_id)
    if not table or table.is_locked or table.status != "EMPTY":
        raise BusinessError("Bàn không trống")
    if adults < 0 or kids_mid < 0 or kids_free < 0 or adults + kids_mid < 1:
        raise BusinessError("Cần ít nhất 1 khách tính tiền")
    sess = TableSession(
        table_id=table.id, package_id=package_id, adults=adults,
        kids_mid=kids_mid, kids_free=kids_free, opened_by=user.id,
    )
    table.status = "IN_USE"
    db.session.add(sess)
    db.session.commit()
    return sess


def update_guests(sess, adults, kids_mid, kids_free):         # PV1.3
    inv = Invoice.query.filter_by(session_id=sess.id).first()
    if inv and inv.status == "PAID":
        raise BusinessError("Hoá đơn đã thu, không sửa được số khách")
    if adults < 0 or kids_mid < 0 or kids_free < 0 or adults + kids_mid < 1:
        raise BusinessError("Cần ít nhất 1 khách tính tiền")
    sess.adults, sess.kids_mid, sess.kids_free = adults, kids_mid, kids_free
    db.session.commit()


def change_table(sess, new_table_id):                         # PV1.4: không duyệt, không gộp
    new = db.session.get(DiningTable, new_table_id)
    if not new or new.is_locked or new.status != "EMPTY":
        raise BusinessError("Chỉ chuyển sang bàn trống")
    old = sess.table
    new.status = old.status          # giữ nguyên trạng thái (đang dùng / chờ thanh toán)
    old.status = "EMPTY"
    sess.table_id = new.id
    db.session.commit()


# --------------------------------------------------------------- Gọi món (KH4)
def create_order(sess, lines, user=None):
    if not is_open_now():
        raise BusinessError("Nhà hàng chưa mở cửa")
    if not sess.is_open:
        raise BusinessError("Bàn đã kết thúc")
    if sess.table.status == "WAITING_PAYMENT":
        raise BusinessError("Bàn đã yêu cầu thanh toán, không gọi thêm món")
    if not lines:
        raise BusinessError("Giỏ trống")

    order = Order(session_id=sess.id, created_by=user.id if user else None)
    for line in lines:
        item = db.session.get(MenuItem, int(line["id"]))
        qty = int(line["qty"])
        if not item or not item.is_active or item.is_sold_out:
            raise BusinessError("Có món đã hết hoặc ngừng bán, vui lòng chọn lại")
        if item.min_tier > sess.package.tier:
            raise BusinessError(f"Món {item.name} không thuộc gói của bàn")
        if not 1 <= qty <= item.max_qty:
            raise BusinessError(f"{item.name}: số lượng từ 1 đến {item.max_qty}")
        order.items.append(OrderItem(
            menu_item_id=item.id, quantity=qty, note=(line.get("note") or "")[:200] or None,
        ))
    db.session.add(order)
    db.session.commit()
    # đơn đi thẳng sang Bếp, không qua bước xác nhận
    socketio.emit("new_order", {"order_id": order.id, "table": sess.table.code}, to="kitchen")
    return order


# ------------------------------------------------------------------------ Bếp
def set_item_status(item_id, new_status):                     # BEP1.3, BEP1.4
    allowed = {"COOKING": "PENDING", "READY": "COOKING"}
    if new_status not in allowed:
        raise BusinessError("Trạng thái không hợp lệ")
    item = db.session.get(OrderItem, item_id)
    if not item or item.status != allowed[new_status]:
        raise BusinessError("Không đổi được trạng thái này")
    item.status = new_status
    db.session.commit()

    payload = {"item_id": item.id, "status": new_status,
               "table": item.order.session.table.code, "name": item.menu_item.name}
    socketio.emit("item_status", payload, to=f"session-{item.order.session_id}")
    if new_status == "READY":
        socketio.emit("item_ready", payload, to="waiter")     # "Mang ra bàn"


def set_sold_out(menu_item_id, sold_out):                     # BEP1.5
    item = db.session.get(MenuItem, menu_item_id)
    item.is_sold_out = sold_out
    db.session.commit()


def request_cancel(item_id, reason, user=None):               # KH4.3 / PV2.2
    item = db.session.get(OrderItem, item_id)
    if not item or item.status == "CANCELLED":
        raise BusinessError("Món không còn để huỷ")
    minutes = int(get_setting("cancel_minutes", 5))
    if now() - item.order.created_at > timedelta(minutes=minutes):
        raise BusinessError(f"Đã quá {minutes} phút, không huỷ được")
    if CancelRequest.query.filter_by(order_item_id=item.id, status="PENDING").first():
        raise BusinessError("Yêu cầu huỷ món này đang chờ bếp")
    req = CancelRequest(order_item_id=item.id, reason=(reason or "")[:200],
                        requested_by=user.id if user else None)
    db.session.add(req)
    db.session.commit()
    socketio.emit("cancel_request", {"id": req.id, "name": item.menu_item.name}, to="kitchen")
    return req


def decide_cancel(req_id, approve, user):                     # BEP1.2.2: Bếp quyết định
    req = db.session.get(CancelRequest, req_id)
    if not req or req.status != "PENDING":
        raise BusinessError("Yêu cầu đã được xử lý")
    if approve:
        if req.order_item.status != "PENDING":
            raise BusinessError("Món đã chế biến, không huỷ được")
        req.order_item.status = "CANCELLED"
    req.status = "APPROVED" if approve else "REJECTED"
    req.decided_by, req.decided_at = user.id, now()
    db.session.commit()
    socketio.emit(
        "item_status",
        {"item_id": req.order_item_id, "status": req.order_item.status,
         "table": req.order_item.order.session.table.code, "name": req.order_item.menu_item.name},
        to=f"session-{req.order_item.order.session_id}",
    )


# ------------------------------------------------- Gọi nhân viên, thanh toán
def call_staff(sess):                                         # KH4.6
    db.session.add(StaffCall(session_id=sess.id))
    db.session.commit()
    socketio.emit("staff_call", {"table": sess.table.code}, to="waiter")


def handle_staff_call(call_id):
    call = db.session.get(StaffCall, call_id)
    if call:
        call.handled = True
        db.session.commit()


def request_payment(sess):                                    # PV3.2
    if not sess.is_open:
        raise BusinessError("Bàn đã kết thúc")
    sess.table.status = "WAITING_PAYMENT"
    db.session.commit()
    socketio.emit("payment_request", {"table": sess.table.code}, to="cashier")


def calc_total(price, adults, kids_mid):
    """Giá gói × (người lớn + trẻ 1m–1m3 / 2), tính nguyên số để khỏi lệch lẻ."""
    return price * (2 * adults + kids_mid) // 2


def create_invoice(sess, cashier):                            # TN1.2
    if sess.table.status != "WAITING_PAYMENT":
        raise BusinessError("Bàn chưa được báo thanh toán")
    inv = Invoice.query.filter_by(session_id=sess.id).first()
    if inv and inv.status == "PAID":
        raise BusinessError("Hoá đơn đã thu, không sửa được")
    price = sess.package.price
    total = calc_total(price, sess.adults, sess.kids_mid)
    if inv:                                  # chưa thu: cập nhật theo số khách mới nhất
        inv.package_price, inv.adults, inv.kids_mid, inv.total = price, sess.adults, sess.kids_mid, total
    else:
        inv = Invoice(session_id=sess.id, package_price=price, adults=sess.adults,
                      kids_mid=sess.kids_mid, total=total, cashier_id=cashier.id)
        db.session.add(inv)
    db.session.commit()
    return inv


def confirm_paid(inv, method):                                # TN1.3, TN1.4
    if inv.status == "PAID":
        raise BusinessError("Hoá đơn đã thu")
    if method not in ("CASH", "TRANSFER"):
        raise BusinessError("Chọn hình thức thanh toán")
    inv.method, inv.status, inv.paid_at = method, "PAID", now()
    db.session.commit()


def checkout(sess):                                           # TN2.1
    inv = Invoice.query.filter_by(session_id=sess.id).first()
    if not inv or inv.status != "PAID":
        raise BusinessError("Chưa thu tiền, không checkout được")
    sess.is_open, sess.closed_at = False, now()
    sess.table.status = "EMPTY"
    db.session.commit()
