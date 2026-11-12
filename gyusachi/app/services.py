"""Nghiệp vụ lõi của GYUSACHI.

Mọi quy tắc nằm ở đây; các route chỉ gọi hàm trong file này rồi trả về trang/JSON.
Khách và Phục vụ cùng dùng `create_order` (đúng ý "Phục vụ gọi món giống khách").
"""
import re
from datetime import timedelta

from sqlalchemy import func

from . import db, socketio
from .models import (
    BuffetPackage, CancelRequest, Category, DiningTable, Invoice, MenuItem, Order,
    OrderItem, OpeningHour, RestaurantInfo, Role, Setting, Shift, StaffCall, TableSession, User,
)
from .utils import now, package_label


class BusinessError(Exception):
    """Lỗi nghiệp vụ: hiện nguyên văn cho người dùng."""


# ---------------------------------------------------------------- tiện ích
def get_setting(key, default=None):
    s = db.session.get(Setting, key)
    return s.value if s else default


def set_setting(key, value):
    s = db.session.get(Setting, key)
    if s:
        s.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))
    db.session.commit()


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
    package = db.session.get(BuffetPackage, package_id)
    if not package:
        raise BusinessError("Chọn gói buffet")
    if adults < 0 or kids_mid < 0 or kids_free < 0 or adults + kids_mid < 1:
        raise BusinessError("Cần ít nhất 1 khách tính tiền")
    sess = TableSession(
        table_id=table.id, package_id=package.id, package_price=package.price, adults=adults,
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


def session_price(sess):
    """Giá/người của phiên: giá lúc mở bàn (phiên cũ chưa lưu thì lấy giá gói hiện tại)."""
    return sess.package_price or sess.package.price


def calc_total(price, adults, kids_mid):
    """Giá gói × (người lớn + trẻ 1m–1m3 / 2), tính nguyên số để khỏi lệch lẻ."""
    return price * (2 * adults + kids_mid) // 2


def create_invoice(sess, cashier):                            # TN1.2
    if sess.table.status != "WAITING_PAYMENT":
        raise BusinessError("Bàn chưa được báo thanh toán")
    inv = Invoice.query.filter_by(session_id=sess.id).first()
    if inv and inv.status == "PAID":
        raise BusinessError("Hoá đơn đã thu, không sửa được")
    price = session_price(sess)
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


# ------------------------------------------------------ Quản trị menu (QLTT2)
KEEP = object()          # "giữ nguyên" khi sửa món


def _clean(text, limit):
    return (text or "").strip()[:limit]


def add_category(name):                                       # QLTT2.1.1
    name = _clean(name, 80)
    if not name:
        raise BusinessError("Nhập tên nhóm món")
    if Category.query.filter(func.lower(Category.name) == name.lower()).first():
        raise BusinessError("Nhóm món đã tồn tại")
    cat = Category(name=name)
    db.session.add(cat)
    db.session.commit()
    return cat


def rename_category(cat_id, name):                            # QLTT2.1.2
    cat = db.session.get(Category, cat_id)
    name = _clean(name, 80)
    if not cat:
        raise BusinessError("Không tìm thấy nhóm món")
    if not name:
        raise BusinessError("Nhập tên mới cho nhóm món")
    dup = Category.query.filter(func.lower(Category.name) == name.lower(), Category.id != cat.id).first()
    if dup:
        raise BusinessError("Đã có nhóm món trùng tên")
    cat.name = name
    db.session.commit()


def delete_category(cat_id):                                  # QLTT2.1.3: chặn nếu còn món
    cat = db.session.get(Category, cat_id)
    if not cat:
        raise BusinessError("Không tìm thấy nhóm món")
    if MenuItem.query.filter_by(category_id=cat.id).count():
        raise BusinessError("Nhóm còn món, không xoá được. Hãy chuyển món sang nhóm khác trước.")
    db.session.delete(cat)
    db.session.commit()


def _check_rules(min_tier, max_qty):
    if not BuffetPackage.query.filter_by(tier=min_tier).first():
        raise BusinessError("Gói buffet không hợp lệ")
    if not 1 <= max_qty <= 99:
        raise BusinessError("Số lượng tối đa mỗi lần gọi phải từ 1 đến 99")


def _check_dish_name(name, category_id, exclude_id=None):
    if not name:
        raise BusinessError("Nhập tên món")
    if not db.session.get(Category, category_id):
        raise BusinessError("Chọn nhóm món")
    q = MenuItem.query.filter(MenuItem.category_id == category_id,
                              func.lower(MenuItem.name) == name.lower())
    if exclude_id:
        q = q.filter(MenuItem.id != exclude_id)
    if q.first():
        raise BusinessError("Nhóm này đã có món trùng tên")


def create_dish(name, category_id, description, image_url, min_tier=1, max_qty=5):   # QLTT2.2
    name = _clean(name, 120)
    _check_dish_name(name, category_id)
    _check_rules(min_tier, max_qty)
    item = MenuItem(name=name, category_id=category_id, description=_clean(description, 1000) or None,
                    image_url=image_url, min_tier=min_tier, max_qty=max_qty, is_active=True)
    db.session.add(item)
    db.session.commit()
    return item


def update_dish(item_id, name, category_id, description, image_url=KEEP):            # QLTT2.3
    item = db.session.get(MenuItem, item_id)
    if not item:
        raise BusinessError("Không tìm thấy món")
    name = _clean(name, 120)
    _check_dish_name(name, category_id, exclude_id=item.id)
    item.name, item.category_id = name, category_id
    item.description = _clean(description, 1000) or None
    if image_url is not KEEP:
        item.image_url = image_url
    db.session.commit()
    return item


def set_dish_rules(item_id, min_tier, max_qty):               # QLTT2.4 + QLTT2.5
    item = db.session.get(MenuItem, item_id)
    if not item:
        raise BusinessError("Không tìm thấy món")
    _check_rules(min_tier, max_qty)
    item.min_tier, item.max_qty = min_tier, max_qty
    db.session.commit()


def set_all_max_qty(max_qty):                                 # QLTT2.5.1: "hoặc tất cả món"
    _check_rules(1, max_qty)
    MenuItem.query.update({MenuItem.max_qty: max_qty})
    db.session.commit()


def set_dish_active(item_id, active):                         # QLTT2.6
    item = db.session.get(MenuItem, item_id)
    if not item:
        raise BusinessError("Không tìm thấy món")
    item.is_active = active
    db.session.commit()


# ------------------------------------------------------ Nhân sự và phân ca (QLTT4)
STAFF_ROLES = ("PHUC_VU", "BEP", "THU_NGAN")        # Quản lý chỉ quản được ba vai trò này
MANAGER_ROLES = ("QUAN_LY",)                        # Chủ chỉ quản được tài khoản Quản lý (CHU3)
ROLE_VI = {"PHUC_VU": "Phục vụ", "BEP": "Bếp", "THU_NGAN": "Thu ngân",
           "QUAN_LY": "Quản lý", "CHU": "Chủ", "ADMIN": "Admin"}


def accounts_by_roles(roles, only_active=False):
    q = (User.query.join(Role, User.role_id == Role.id)
         .filter(Role.name.in_(roles)))
    if only_active:
        q = q.filter(User.is_locked.is_(False))
    return q.order_by(Role.name, User.full_name).all()


def staff_users(only_active=False):
    return accounts_by_roles(STAFF_ROLES, only_active)


def manager_users(only_active=False):
    return accounts_by_roles(MANAGER_ROLES, only_active)


def _names(allowed):
    return ", ".join(ROLE_VI.get(r, r) for r in allowed)


def _staff_user(user_id, allowed=STAFF_ROLES):
    user = db.session.get(User, user_id)
    if not user or user.role.name not in allowed:
        raise BusinessError(f"Chỉ quản lý được tài khoản {_names(allowed)}")
    return user


def _staff_role(role_name, allowed=STAFF_ROLES):
    if role_name not in allowed:
        raise BusinessError(f"Vai trò phải là {_names(allowed)}")
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        raise BusinessError("Chưa có vai trò này trong hệ thống")
    return role


def create_staff(username, password, full_name, role_name, allowed=STAFF_ROLES):   # QLTT4.1, CHU3.1
    username = _clean(username, 50).lower()
    full_name = _clean(full_name, 100)
    role = _staff_role(role_name, allowed)
    if not re.fullmatch(r"[a-z0-9_.]{3,50}", username):
        raise BusinessError("Tên đăng nhập 3–50 ký tự: chữ thường không dấu, số, dấu chấm hoặc gạch dưới")
    if User.query.filter(func.lower(User.username) == username).first():
        raise BusinessError("Tên đăng nhập đã tồn tại")
    if not full_name:
        raise BusinessError("Nhập họ tên")
    if len(password or "") < 6:
        raise BusinessError("Mật khẩu tối thiểu 6 ký tự")
    user = User(username=username, full_name=full_name, role_id=role.id)
    user.set_password(password)                       # mã hoá trước khi lưu (QLTT4.1.2)
    db.session.add(user)
    db.session.commit()
    return user


def update_staff(user_id, full_name, role_name, allowed=STAFF_ROLES):  # QLTT4.2, CHU3.2
    user = _staff_user(user_id, allowed)
    full_name = _clean(full_name, 100)
    role = _staff_role(role_name, allowed)
    if not full_name:
        raise BusinessError("Nhập họ tên")
    if role.id != user.role_id:
        if user.role.name == "PHUC_VU":               # không còn là Phục vụ: bỏ giao bàn các ca sắp tới
            for sh in Shift.query.filter(Shift.user_id == user.id, Shift.work_date >= now().date()):
                sh.tables = []
        user.role_id = role.id
    user.full_name = full_name
    db.session.commit()
    return user


def set_staff_locked(user_id, locked, allowed=STAFF_ROLES):          # QLTT4.3, CHU3.2
    user = _staff_user(user_id, allowed)
    user.is_locked = locked
    if not locked:
        user.failed_attempts, user.locked_until = 0, None
    db.session.commit()
    return user


def _overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def create_shift(user_id, work_date, start, end, table_ids):         # QLTT4.4
    user = _staff_user(user_id)
    if user.is_locked:
        raise BusinessError("Tài khoản đang bị khoá, không xếp ca được")
    if work_date < now().date():
        raise BusinessError("Không xếp ca cho ngày đã qua")
    if end <= start:
        raise BusinessError("Giờ kết thúc phải sau giờ bắt đầu (ca không qua nửa đêm)")

    tables = DiningTable.query.filter(DiningTable.id.in_(table_ids)).all() if table_ids else []
    if tables and user.role.name != "PHUC_VU":
        raise BusinessError("Chỉ giao bàn phụ trách cho Phục vụ")

    same_day = Shift.query.filter_by(work_date=work_date).all()
    for sh in same_day:
        if not _overlap(start, end, sh.start_time, sh.end_time):
            continue
        if sh.user_id == user.id:
            raise BusinessError(f"{user.full_name} đã có ca {sh.start_time:%H:%M}–{sh.end_time:%H:%M} trùng giờ")
        clash = [t.code for t in tables if t in sh.tables]
        if clash:
            raise BusinessError(f"Bàn {', '.join(clash)} đã giao cho {sh.user.full_name} "
                                f"({sh.start_time:%H:%M}–{sh.end_time:%H:%M}) trùng giờ")

    shift = Shift(user_id=user.id, work_date=work_date, start_time=start, end_time=end, tables=tables)
    db.session.add(shift)
    db.session.commit()
    return shift


def delete_shift(shift_id):
    shift = db.session.get(Shift, shift_id)
    if not shift:
        raise BusinessError("Không tìm thấy ca")
    if shift.work_date < now().date():
        raise BusinessError("Không xoá được ca đã qua")
    db.session.delete(shift)
    db.session.commit()


# ------------------------------------------------------ Cấu hình kinh doanh (CHU2)
WEEKDAYS_VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
MIN_PRICE, MAX_PRICE = 1000, 10_000_000


def get_restaurant():
    info = RestaurantInfo.query.first()
    if not info:
        info = RestaurantInfo(name="GYUSACHI", address="")
        db.session.add(info)
        db.session.commit()
    return info


def update_restaurant(name, address):                                # CHU2.1
    name, address = _clean(name, 120), _clean(address, 255)
    if not name:
        raise BusinessError("Nhập tên nhà hàng")
    info = get_restaurant()
    info.name, info.address = name, address
    db.session.commit()


def add_opening_hours(weekdays, open_time, close_time):              # CHU2.2
    if not weekdays:
        raise BusinessError("Chọn ít nhất một ngày áp dụng")
    if any(wd not in range(7) for wd in weekdays):
        raise BusinessError("Ngày áp dụng không hợp lệ")
    if close_time <= open_time:
        raise BusinessError("Giờ đóng phải sau giờ mở (khung giờ không qua nửa đêm)")
    weekdays = sorted(set(weekdays))
    for wd in weekdays:                       # kiểm tra hết rồi mới lưu: hoặc cả nhóm ngày, hoặc không ngày nào
        for row in OpeningHour.query.filter_by(weekday=wd).all():
            if open_time < row.close_time and row.open_time < close_time:
                raise BusinessError(f"{WEEKDAYS_VI[wd]} đã có khung {row.open_time:%H:%M}–{row.close_time:%H:%M} trùng giờ")
    for wd in weekdays:
        db.session.add(OpeningHour(weekday=wd, open_time=open_time, close_time=close_time))
    db.session.commit()


def delete_opening_hours(row_id):
    row = db.session.get(OpeningHour, row_id)
    if not row:
        raise BusinessError("Không tìm thấy khung giờ")
    db.session.delete(row)
    db.session.commit()


def update_package_prices(prices):                                   # CHU2.3: {package_id: giá/người}
    packages = BuffetPackage.query.order_by(BuffetPackage.tier).all()
    for p in packages:
        v = prices.get(p.id)
        if v is None:
            raise BusinessError(f"Nhập giá cho {p.name}")
        if not MIN_PRICE <= v <= MAX_PRICE:
            raise BusinessError(f"Giá {p.name} phải từ {MIN_PRICE:,} đến {MAX_PRICE:,} đồng".replace(",", "."))
    for lo, hi in zip(packages, packages[1:]):
        if prices[hi.id] <= prices[lo.id]:
            raise BusinessError(f"Gói cao hơn phải có giá cao hơn: {hi.name} phải đắt hơn {lo.name}")
    for p in packages:
        p.price = prices[p.id]
        if re.fullmatch(r"Buffet [\d.]+K", p.name):        # tên theo giá thì đổi theo, tên tự đặt thì giữ
            p.name = package_label(p.price)
    db.session.commit()


# ------------------------------------------------------ Mật khẩu (XT1.3, ADM1.4)
MIN_PASSWORD = 6


def change_password(user, old, new, repeat):                         # XT1.3: tự đổi mật khẩu
    if not user.check_password(old or ""):
        raise BusinessError("Mật khẩu cũ không đúng")
    if len(new or "") < MIN_PASSWORD:
        raise BusinessError(f"Mật khẩu mới tối thiểu {MIN_PASSWORD} ký tự")
    if new != repeat:
        raise BusinessError("Hai lần nhập mật khẩu mới không khớp")
    if new == old:
        raise BusinessError("Mật khẩu mới phải khác mật khẩu cũ")
    user.set_password(new)
    db.session.commit()
