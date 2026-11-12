import secrets

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager
from .utils import now

# ---------------- Tài khoản, vai trò, quyền (XT1, ADM1) ----------------
role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.ForeignKey("permissions.id"), primary_key=True),
)


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)   # CAN_CHECKOUT...


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)   # PHUC_VU, BEP...
    permissions = db.relationship("Permission", secondary=role_permissions)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role_id = db.Column(db.ForeignKey("roles.id"), nullable=False)
    is_locked = db.Column(db.Boolean, default=False)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    role = db.relationship("Role")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def has_perm(self, code):
        return any(p.code == code for p in self.role.permissions)


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    # tài khoản bị khoá giữa chừng thì phiên đăng nhập hiện tại cũng hết hiệu lực
    return None if user and user.is_locked else user


class LoginLog(db.Model):                      # ADM3.3
    __tablename__ = "login_logs"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    success = db.Column(db.Boolean, default=False)
    event = db.Column(db.String(20))             # LOGIN / LOGIN_FAIL / LOGOUT / TIMEOUT
    created_at = db.Column(db.DateTime, default=now)


class ErrorLog(db.Model):                      # ADM3.2
    __tablename__ = "error_logs"
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False, default="ERROR")   # INFO / WARNING / ERROR
    message = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(255))
    user_id = db.Column(db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now)


class AuditLog(db.Model):                      # ADM3.1, CHU4.2
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.ForeignKey("users.id"))
    action = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now)


# ---------------- Cấu hình nhà hàng (CHU2, ADM4) ----------------
class Setting(db.Model):                       # cancel_minutes=5, max_login_attempts...
    __tablename__ = "settings"
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)


class RestaurantInfo(db.Model):                # CHU2.1
    __tablename__ = "restaurant_info"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    phone = db.Column(db.String(30))


class OpeningHour(db.Model):                   # CHU2.2
    __tablename__ = "opening_hours"
    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False)   # 0=Thứ 2 ... 6=Chủ nhật
    open_time = db.Column(db.Time, nullable=False)
    close_time = db.Column(db.Time, nullable=False)


class BuffetPackage(db.Model):                 # CHU2.3: 6 gói
    __tablename__ = "buffet_packages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Integer, nullable=False)              # VND/người
    tier = db.Column(db.Integer, unique=True, nullable=False)  # 1..6, càng cao càng đắt


shift_tables = db.Table(                       # bàn phụ trách của Phục vụ trong một ca
    "shift_tables",
    db.Column("shift_id", db.ForeignKey("shifts.id"), primary_key=True),
    db.Column("table_id", db.ForeignKey("dining_tables.id"), primary_key=True),
)


class Shift(db.Model):                         # QLTT4.4 phân ca
    __tablename__ = "shifts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.ForeignKey("users.id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    user = db.relationship("User")
    tables = db.relationship("DiningTable", secondary=shift_tables,
                             order_by="DiningTable.code")


# ---------------- Menu (QLTT2) ----------------
class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class MenuItem(db.Model):
    __tablename__ = "menu_items"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.ForeignKey("categories.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    min_tier = db.Column(db.Integer, default=1)        # gói thấp nhất được gọi món này
    max_qty = db.Column(db.Integer, default=5)         # tối đa mỗi lần gọi
    is_active = db.Column(db.Boolean, default=True)    # ẩn / ngừng bán
    is_sold_out = db.Column(db.Boolean, default=False) # bếp báo hết (BEP1.5)
    category = db.relationship("Category")


# ---------------- Bàn và phiên bàn (QLTT3, PV1) ----------------
class DiningTable(db.Model):
    __tablename__ = "dining_tables"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)    # "B05"
    seats = db.Column(db.Integer, default=4)
    qr_token = db.Column(
        db.String(32), unique=True, nullable=False,
        default=lambda: secrets.token_urlsafe(8),
    )
    status = db.Column(db.String(20), default="EMPTY")   # EMPTY / IN_USE / WAITING_PAYMENT
    is_locked = db.Column(db.Boolean, default=False)     # khoá bàn (QLTT3.4)


class TableSession(db.Model):
    __tablename__ = "table_sessions"
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.ForeignKey("dining_tables.id"), nullable=False)
    package_id = db.Column(db.ForeignKey("buffet_packages.id"), nullable=False)
    package_price = db.Column(db.Integer)           # giá/người chốt lúc mở bàn (đổi giá sau đó không ảnh hưởng)
    adults = db.Column(db.Integer, nullable=False)
    kids_mid = db.Column(db.Integer, default=0)     # trẻ 1m–1m3, tính nửa giá
    kids_free = db.Column(db.Integer, default=0)    # trẻ dưới 1m, miễn phí
    opened_by = db.Column(db.ForeignKey("users.id"))
    opened_at = db.Column(db.DateTime, default=now)
    closed_at = db.Column(db.DateTime)
    is_open = db.Column(db.Boolean, default=True)
    table = db.relationship("DiningTable")
    package = db.relationship("BuffetPackage")


# ---------------- Đơn gọi món (KH4, BEP1) ----------------
class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.ForeignKey("table_sessions.id"), nullable=False)
    created_by = db.Column(db.ForeignKey("users.id"))   # NULL = khách tự gọi
    created_at = db.Column(db.DateTime, default=now)
    session = db.relationship("TableSession")
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.ForeignKey("orders.id"), nullable=False)
    menu_item_id = db.Column(db.ForeignKey("menu_items.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(200))
    status = db.Column(db.String(20), default="PENDING")  # PENDING/COOKING/READY/CANCELLED
    menu_item = db.relationship("MenuItem")


class CancelRequest(db.Model):
    __tablename__ = "cancel_requests"
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.ForeignKey("order_items.id"), nullable=False)
    requested_by = db.Column(db.ForeignKey("users.id"))   # NULL = khách
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default="PENDING")  # PENDING/APPROVED/REJECTED
    created_at = db.Column(db.DateTime, default=now)
    decided_by = db.Column(db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)
    order_item = db.relationship("OrderItem")


class StaffCall(db.Model):                      # KH4.6
    __tablename__ = "staff_calls"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.ForeignKey("table_sessions.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    handled = db.Column(db.Boolean, default=False)
    session = db.relationship("TableSession")


# ---------------- Thanh toán (TN1) ----------------
class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.ForeignKey("table_sessions.id"), unique=True, nullable=False)
    package_price = db.Column(db.Integer, nullable=False)   # giá gói tại thời điểm tính
    adults = db.Column(db.Integer, nullable=False)
    kids_mid = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, nullable=False)
    method = db.Column(db.String(20))                       # CASH / TRANSFER
    status = db.Column(db.String(20), default="UNPAID")     # UNPAID / PAID (PAID: không sửa)
    paid_at = db.Column(db.DateTime)
    cashier_id = db.Column(db.ForeignKey("users.id"))
    session = db.relationship("TableSession")
