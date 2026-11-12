"""Nhật ký thao tác (bảng audit_logs). Nguồn chung cho CHU4.2 và sau này ADM3.1."""
from . import db
from .models import AuditLog, ErrorLog, LoginLog, Role, User
from .reports import check_range, range_bounds

ACTION_VI = {
    # Quản lý
    "MENU_CATEGORY_ADD": "Thêm nhóm món",
    "MENU_CATEGORY_RENAME": "Đổi tên nhóm món",
    "MENU_CATEGORY_DELETE": "Xoá nhóm món",
    "MENU_DISH_ADD": "Thêm món",
    "MENU_DISH_EDIT": "Sửa món",
    "MENU_DISH_RULES": "Đổi gói và số lượng tối đa của món",
    "MENU_MAXQTY_ALL": "Đặt số lượng tối đa cho tất cả món",
    "MENU_DISH_TOGGLE": "Ẩn hoặc bán lại món",
    "STAFF_ADD": "Tạo tài khoản nhân viên",
    "STAFF_EDIT": "Sửa tài khoản nhân viên",
    "STAFF_LOCK": "Khoá tài khoản nhân viên",
    "STAFF_UNLOCK": "Mở khoá tài khoản nhân viên",
    "SHIFT_ADD": "Xếp ca",
    "SHIFT_DELETE": "Xoá ca",
    "MANAGER_CHECKOUT": "Checkout thay Thu ngân",
    # Chủ
    "CONFIG_RESTAURANT": "Cập nhật thông tin nhà hàng",
    "CONFIG_HOURS_ADD": "Thêm khung giờ mở cửa",
    "CONFIG_HOURS_DELETE": "Xoá khung giờ mở cửa",
    "CONFIG_PRICES": "Cập nhật giá gói buffet",
    "CHU_MANAGER_ADD": "Tạo tài khoản Quản lý",
    "CHU_MANAGER_EDIT": "Sửa tài khoản Quản lý",
    "CHU_MANAGER_LOCK": "Khoá tài khoản Quản lý",
    "CHU_MANAGER_UNLOCK": "Mở khoá tài khoản Quản lý",
    "REPORT_EXPORT": "Xuất báo cáo",
    # Admin
    "ADMIN_ROLE_ADD": "Tạo vai trò",
    "ADMIN_ROLE_RENAME": "Đổi tên vai trò",
    "ADMIN_ROLE_DELETE": "Xoá vai trò",
    "ADMIN_PERMS_SET": "Cập nhật quyền của vai trò",
    "ADMIN_USER_ADD": "Tạo tài khoản",
    "ADMIN_USER_EDIT": "Sửa tài khoản",
    "ADMIN_USER_LOCK": "Khoá tài khoản",
    "ADMIN_USER_UNLOCK": "Mở khoá tài khoản",
    "ADMIN_PASSWORD_RESET": "Đặt lại mật khẩu cho tài khoản",
    "BACKUP_RUN": "Sao lưu dữ liệu",
    "BACKUP_SCHEDULE": "Cài lịch sao lưu",
    "BACKUP_RESTORE": "Phục hồi dữ liệu",
    "DATA_CLEANUP": "Dọn dẹp dữ liệu cũ",
    "SETTINGS_UPDATE": "Cập nhật tham số hệ thống",
    "PRINTER_UPDATE": "Cập nhật cấu hình máy in",
    # mọi người dùng
    "PASSWORD_CHANGE": "Tự đổi mật khẩu",
}

LOGIN_EVENT_VI = {"LOGIN": "Đăng nhập", "LOGIN_FAIL": "Đăng nhập sai", "LOGOUT": "Đăng xuất",
                  "TIMEOUT": "Hết phiên (tự đăng xuất)"}
LEVELS = ("INFO", "WARNING", "ERROR")
LEVEL_VI = {"INFO": "Thông tin", "WARNING": "Cảnh báo", "ERROR": "Lỗi"}


# ---------------------------------------------------------------- ghi nhật ký
def log_audit(user_id, action, detail=""):
    db.session.add(AuditLog(user_id=user_id, action=action, detail=detail))
    db.session.commit()


def log_error(level, message, path=None, user_id=None):
    """Ghi nhật ký lỗi hệ thống; tuyệt đối không được làm hỏng luồng đang chạy."""
    try:
        db.session.add(ErrorLog(level=level if level in LEVELS else "ERROR", message=str(message)[:4000],
                                path=(path or "")[:255] or None, user_id=user_id))
        db.session.commit()
    except Exception:
        db.session.rollback()


def log_login(username, event, success=True):
    try:
        db.session.add(LoginLog(username=(username or "")[:50], event=event, success=success))
        db.session.commit()
    except Exception:
        db.session.rollback()


def label(action):
    return ACTION_VI.get(action, action)


def search_logs(d_from, d_to, user_id=None, role_names=("QUAN_LY",), action=None, limit=300):
    """CHU4.2.1 và ADM3.1: nhật ký thao tác trong khoảng ngày, mới nhất trước.

    user_id: một người cụ thể; không có thì lọc theo role_names (None = mọi vai trò).
    action: mã thao tác (ví dụ MENU_DISH_ADD). Trả về (tổng số dòng khớp, tối đa `limit` dòng)."""
    check_range(d_from, d_to)
    start, end = range_bounds(d_from, d_to)
    q = (db.session.query(AuditLog, User)
         .select_from(AuditLog)
         .join(User, AuditLog.user_id == User.id)
         .join(Role, User.role_id == Role.id)
         .filter(AuditLog.created_at >= start, AuditLog.created_at < end))
    if user_id:
        q = q.filter(User.id == user_id)
    elif role_names:
        q = q.filter(Role.name.in_(role_names))
    if action:
        q = q.filter(AuditLog.action == action)
    total = q.count()
    rows = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return total, [{"time": log.created_at, "user": u.full_name, "username": u.username,
                    "action": label(log.action), "detail": log.detail or ""} for log, u in rows]


def search_errors(d_from, d_to, level=None, limit=300):                 # ADM3.2
    check_range(d_from, d_to)
    start, end = range_bounds(d_from, d_to)
    q = ErrorLog.query.filter(ErrorLog.created_at >= start, ErrorLog.created_at < end)
    if level in LEVELS:
        q = q.filter(ErrorLog.level == level)
    total = q.count()
    rows = q.order_by(ErrorLog.created_at.desc(), ErrorLog.id.desc()).limit(limit).all()
    return total, [{"time": r.created_at, "level": r.level, "level_vi": LEVEL_VI.get(r.level, r.level),
                    "message": r.message, "path": r.path or ""} for r in rows]


def search_logins(d_from, d_to, username=None, limit=300):               # ADM3.3
    check_range(d_from, d_to)
    start, end = range_bounds(d_from, d_to)
    q = LoginLog.query.filter(LoginLog.created_at >= start, LoginLog.created_at < end)
    if username:
        q = q.filter(LoginLog.username == username)
    total = q.count()
    rows = q.order_by(LoginLog.created_at.desc(), LoginLog.id.desc()).limit(limit).all()

    def event_of(r):
        return r.event or ("LOGIN" if r.success else "LOGIN_FAIL")     # dòng cũ chưa có cột event

    return total, [{"time": r.created_at, "username": r.username or "", "event": event_of(r),
                    "event_vi": LOGIN_EVENT_VI.get(event_of(r), event_of(r))} for r in rows]
