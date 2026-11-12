"""Hàm dựng dữ liệu cho kiểm thử."""
from app import db
from app import services as sv
from app.models import (
    BuffetPackage, DiningTable, Invoice, MenuItem, Order, OrderItem, Role, TableSession, User,
)


def user(name):
    return User.query.filter_by(username=name).one()


def role(name):
    return Role.query.filter_by(name=name).one()


def pkg(tier):
    return BuffetPackage.query.filter_by(tier=tier).one()


def table(code="B01"):
    return DiningTable.query.filter_by(code=code).one()


def dish(name):
    return MenuItem.query.filter_by(name=name).one()


def open_table(code="B01", tier=1, adults=2, kids_mid=0, kids_free=0, by="phucvu"):
    return sv.open_table(table(code).id, pkg(tier).id, adults, kids_mid, kids_free, user(by))


def place(sess, *items):
    """items: (tên món, số lượng). Đơn tạo xong được gán giờ tạo = giờ của đồng hồ giả."""
    order = sv.create_order(sess, [{"id": dish(n).id, "qty": q} for n, q in items])
    order.created_at = sv.now()
    db.session.commit()
    return order


def pay(sess, method="CASH"):
    sv.request_payment(sess)
    inv = sv.create_invoice(sess, user("thungan"))
    sv.confirm_paid(inv, method)
    return inv


def paid_session(opened, paid, tier=1, adults=2, kids_mid=0, kids_free=0, code="B01", status="PAID"):
    """Dựng sẵn một phiên bàn ĐÃ ĐÓNG kèm hoá đơn, với giờ cụ thể (dùng cho báo cáo, dọn dẹp)."""
    p = pkg(tier)
    s = TableSession(table_id=table(code).id, package_id=p.id, package_price=p.price, adults=adults,
                     kids_mid=kids_mid, kids_free=kids_free, opened_at=opened, closed_at=paid,
                     is_open=False, opened_by=user("phucvu").id)
    db.session.add(s)
    db.session.flush()
    is_paid = status == "PAID"
    db.session.add(Invoice(session_id=s.id, package_price=p.price, adults=adults, kids_mid=kids_mid,
                           total=sv.calc_total(p.price, adults, kids_mid), status=status,
                           method="CASH" if is_paid else None, paid_at=paid if is_paid else None,
                           cashier_id=user("thungan").id))
    db.session.commit()
    return s


def add_order(sess, created_at, *items):
    """items: (tên món, số lượng, trạng thái)."""
    o = Order(session_id=sess.id, created_at=created_at)
    for name, qty, status in items:
        o.items.append(OrderItem(menu_item_id=dish(name).id, quantity=qty, status=status))
    db.session.add(o)
    db.session.commit()
    return o
