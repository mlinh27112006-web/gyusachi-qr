"""Nghiệp vụ của Admin: vai trò và quyền (ADM1), sao lưu và dọn dẹp (ADM2), tham số và máy in (ADM4)."""
import socket
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import delete, func, select

from . import backup, db
from .audit import log_error
from .models import (
    AuditLog, CancelRequest, ErrorLog, Invoice, LoginLog, Order, OrderItem, Permission, Role,
    Shift, StaffCall, TableSession, User, shift_tables,
)
from .perms import SYSTEM_ROLES
from .services import (
    MIN_PASSWORD, BusinessError, _clean, create_staff, get_setting, set_setting, set_staff_locked,
    update_staff,
)
from .utils import now


# ================================================================ ADM1: vai trò
def all_roles():
    return Role.query.order_by(Role.id).all()


def create_role(name):                                                # ADM1.1.1
    name = _clean(name, 50)
    if not name:
        raise BusinessError("Nhập tên vai trò")
    if Role.query.filter(func.lower(Role.name) == name.lower()).first():
        raise BusinessError("Vai trò đã tồn tại")
    role = Role(name=name)
    db.session.add(role)
    db.session.commit()
    return role


def rename_role(role_id, name):                                       # ADM1.1.2
    role = db.session.get(Role, role_id)
    name = _clean(name, 50)
    if not role:
        raise BusinessError("Không tìm thấy vai trò")
    if role.name in SYSTEM_ROLES:
        raise BusinessError("Vai trò hệ thống không đổi tên được vì chương trình dựa vào tên này")
    if not name:
        raise BusinessError("Nhập tên mới cho vai trò")
    if Role.query.filter(func.lower(Role.name) == name.lower(), Role.id != role.id).first():
        raise BusinessError("Đã có vai trò trùng tên")
    role.name = name
    db.session.commit()


def delete_role(role_id):                                             # ADM1.1.3: chặn nếu còn tài khoản
    role = db.session.get(Role, role_id)
    if not role:
        raise BusinessError("Không tìm thấy vai trò")
    if role.name in SYSTEM_ROLES:
        raise BusinessError("Vai trò hệ thống không xoá được")
    n = User.query.filter_by(role_id=role.id).count()
    if n:
        raise BusinessError(f"Còn {n} tài khoản đang dùng vai trò này, không xoá được")
    db.session.delete(role)
    db.session.commit()


def set_permission_matrix(matrix):                                    # ADM1.2.1: {role_id: {mã quyền}}
    perms = {p.code: p for p in Permission.query.all()}
    roles = {r.id: r for r in Role.query.all()}
    for rid, codes in matrix.items():
        role = roles.get(rid)
        if not role or role.name == "ADMIN":          # Admin luôn đủ quyền để không tự khoá mình
            continue
        if set(codes) - set(perms):
            raise BusinessError("Có quyền không hợp lệ")
        role.permissions = [perms[c] for c in sorted(codes)]
    db.session.commit()


# ================================================================ ADM1: tài khoản
def all_users():
    return (User.query.join(Role, User.role_id == Role.id)
            .order_by(Role.name, User.full_name).all())


def _role_names():
    return tuple(r.name for r in Role.query.all())


def _other_active_admins(exclude_id):
    return (User.query.join(Role, User.role_id == Role.id)
            .filter(Role.name == "ADMIN", User.is_locked.is_(False), User.id != exclude_id).count())


def create_account(username, password, full_name, role_id):           # ADM1.3.1: mọi vai trò, kể cả Chủ
    role = db.session.get(Role, role_id)
    if not role:
        raise BusinessError("Chọn vai trò")
    return create_staff(username, password, full_name, role.name, (role.name,))


def edit_account(user_id, full_name, role_id, acting_user_id):        # ADM1.3.2
    user = db.session.get(User, user_id)
    role = db.session.get(Role, role_id)
    if not user or not role:
        raise BusinessError("Không tìm thấy tài khoản hoặc vai trò")
    if user.role.name == "ADMIN" and role.name != "ADMIN":
        if user.id == acting_user_id:
            raise BusinessError("Bạn không tự hạ vai trò của chính mình")
        if not _other_active_admins(user.id):
            raise BusinessError("Phải còn ít nhất một Admin đang hoạt động")
    return update_staff(user_id, full_name, role.name, _role_names())


def lock_account(user_id, locked, acting_user_id):                    # ADM1.3.3
    user = db.session.get(User, user_id)
    if not user:
        raise BusinessError("Không tìm thấy tài khoản")
    if locked:
        if user.id == acting_user_id:
            raise BusinessError("Bạn không tự khoá tài khoản của chính mình")
        if user.role.name == "ADMIN" and not _other_active_admins(user.id):
            raise BusinessError("Phải còn ít nhất một Admin đang hoạt động")
    return set_staff_locked(user_id, locked, _role_names())


def reset_password(user_id, new_password):                            # ADM1.4.1
    user = db.session.get(User, user_id)
    if not user:
        raise BusinessError("Không tìm thấy tài khoản")
    if len(new_password or "") < MIN_PASSWORD:
        raise BusinessError(f"Mật khẩu mới tối thiểu {MIN_PASSWORD} ký tự")
    user.set_password(new_password)                    # lưu dạng đã mã hoá
    user.failed_attempts, user.locked_until = 0, None  # mở luôn khoá tạm do nhập sai
    db.session.commit()


# ================================================================ ADM4: tham số và máy in
PARAM_SPECS = {          # khoá: (nhỏ nhất, lớn nhất, mặc định, nhãn)
    "session_timeout_minutes": (5, 1440, 30, "Thời gian hết phiên đăng nhập (phút)"),
    "max_login_attempts": (3, 20, 5, "Số lần nhập sai mật khẩu tối đa"),
    "cancel_minutes": (1, 60, 5, "Số phút cho phép huỷ món"),
}


def get_params():
    out = {}
    for key, (lo, hi, default, _label) in PARAM_SPECS.items():
        try:
            out[key] = int(get_setting(key, default))
        except ValueError:
            out[key] = default
    return out


def update_params(values):                                            # ADM4.2.1
    for key, (lo, hi, _d, label) in PARAM_SPECS.items():
        v = values.get(key)
        if v is None or not lo <= v <= hi:
            raise BusinessError(f"{label} phải từ {lo} đến {hi}")
    for key in PARAM_SPECS:
        set_setting(key, values[key])


PRINTER_TYPES = {"NETWORK": "Máy in mạng (LAN, Wi-Fi)", "USB": "Máy in USB", "BLUETOOTH": "Máy in Bluetooth"}


def get_printer():
    return {"type": get_setting("printer_type", ""), "address": get_setting("printer_address", ""),
            "port": get_setting("printer_port", "")}


def update_printer(ptype, address, port):                             # ADM4.1.1
    if not ptype:                                                      # để trống = chưa dùng máy in
        for key in ("printer_type", "printer_address", "printer_port"):
            set_setting(key, "")
        return
    if ptype not in PRINTER_TYPES:
        raise BusinessError("Chọn loại kết nối")
    address = _clean(address, 200)
    if not address:
        raise BusinessError("Nhập địa chỉ máy in (địa chỉ IP với máy in mạng, tên máy in với USB hoặc Bluetooth)")
    if ptype == "NETWORK":
        if port is None or not 1 <= port <= 65535:
            raise BusinessError("Cổng phải từ 1 đến 65535 (máy in nhiệt thường dùng cổng 9100)")
        port_text = str(port)
    else:
        port_text = ""
    set_setting("printer_type", ptype)
    set_setting("printer_address", address)
    set_setting("printer_port", port_text)


def test_printer():
    p = get_printer()
    if p["type"] != "NETWORK":
        raise BusinessError("Chỉ kiểm tra được kết nối với máy in mạng")
    try:
        socket.create_connection((p["address"], int(p["port"])), timeout=3).close()
    except (OSError, ValueError):
        raise BusinessError(f"Không kết nối được tới {p['address']}:{p['port']}")


# ================================================================ ADM2: sao lưu, phục hồi, dọn dẹp
def _cfg():
    c = current_app.config
    return c["SQLALCHEMY_DATABASE_URI"], c["BACKUP_DIR"], (c.get("PG_BIN_DIR") or None)


def list_backups():
    return backup.list_backups(current_app.config["BACKUP_DIR"])


def backup_path(filename):
    try:
        return backup.safe_path(current_app.config["BACKUP_DIR"], filename)
    except backup.BackupError as e:
        raise BusinessError(str(e))


def run_backup_now(prefix=backup.PREFIX_AUTO):                        # ADM2.1.1 (thủ công)
    url, directory, bin_dir = _cfg()
    try:
        name = backup.run_backup(url, directory, bin_dir, prefix)
    except backup.BackupError as e:
        log_error("ERROR", f"Sao lưu thất bại: {e}")
        raise BusinessError(str(e))
    if prefix == backup.PREFIX_AUTO:
        backup.prune_backups(directory, backup_schedule()["keep"])
    return name


def backup_schedule():
    try:
        keep = int(get_setting("backup_keep", 7))
    except ValueError:
        keep = 7
    return {"mode": get_setting("backup_mode", "manual"), "time": get_setting("backup_time", "02:00"), "keep": keep,
            "last_auto": get_setting("backup_last_auto", "")}


def update_backup_schedule(mode, hhmm, keep):                         # ADM2.1.1 (định kỳ)
    if mode not in ("manual", "daily"):
        raise BusinessError("Chọn cách chạy: thủ công hoặc hằng ngày")
    try:
        datetime.strptime(hhmm or "", "%H:%M")
    except ValueError:
        raise BusinessError("Giờ sao lưu không hợp lệ")
    if keep is None or not 1 <= keep <= 60:
        raise BusinessError("Số bản sao lưu giữ lại phải từ 1 đến 60")
    set_setting("backup_mode", mode)
    set_setting("backup_time", hhmm)
    set_setting("backup_keep", keep)


def run_scheduled_backup_if_due():
    """Gọi định kỳ bởi bộ lập lịch: mỗi ngày chỉ sao lưu một lần, sau giờ đã hẹn."""
    sch = backup_schedule()
    if sch["mode"] != "daily":
        return None
    today = now().date().isoformat()
    if sch["last_auto"] == today or now().strftime("%H:%M") < sch["time"]:
        return None
    set_setting("backup_last_auto", today)             # đánh dấu trước để lỗi không bị lặp liên tục
    try:
        name = run_backup_now()
    except BusinessError:
        return None                                    # run_backup_now đã ghi nhật ký lỗi
    log_error("INFO", f"Sao lưu tự động thành công: {name}")
    return name


def restore_backup_file(filename, confirm_text):                      # ADM2.2.1 + ADM2.2.2
    if (confirm_text or "").strip().upper() != "PHUC HOI":
        raise BusinessError("Gõ đúng chữ PHUC HOI để xác nhận phục hồi")
    url, directory, bin_dir = _cfg()
    try:
        backup.safe_path(directory, filename)
        safety = backup.run_backup(url, directory, bin_dir, prefix="pre-restore")   # bản an toàn
        db.session.remove()
        db.engine.dispose()                            # nhả hết kết nối đang giữ bảng
        backup.restore_backup(url, directory, filename, bin_dir)
    except backup.BackupError as e:
        db.session.remove()
        db.engine.dispose()
        log_error("ERROR", f"Phục hồi thất bại ({filename}): {e}")
        raise BusinessError(str(e))
    db.engine.dispose()
    return safety


MIN_KEEP_MONTHS = 3


def _cleanup_targets(cutoff):
    old_sessions = select(TableSession.id).where(TableSession.is_open.is_(False), TableSession.closed_at < cutoff)
    old_orders = select(Order.id).where(Order.session_id.in_(old_sessions))
    old_items = select(OrderItem.id).where(OrderItem.order_id.in_(old_orders))
    return [                                           # thứ tự xoá: bảng con trước, bảng cha sau
        ("Yêu cầu huỷ món", CancelRequest, CancelRequest.order_item_id.in_(old_items)),
        ("Món đã gọi", OrderItem, OrderItem.order_id.in_(old_orders)),
        ("Đơn gọi món", Order, Order.session_id.in_(old_sessions)),
        ("Lượt gọi nhân viên", StaffCall, StaffCall.session_id.in_(old_sessions)),
        ("Hoá đơn", Invoice, Invoice.session_id.in_(old_sessions)),
        ("Phiên bàn", TableSession, TableSession.id.in_(old_sessions)),
        ("Ca làm việc", Shift, Shift.work_date < cutoff.date()),
        ("Nhật ký thao tác", AuditLog, AuditLog.created_at < cutoff),
        ("Nhật ký đăng nhập", LoginLog, LoginLog.created_at < cutoff),
        ("Nhật ký lỗi", ErrorLog, ErrorLog.created_at < cutoff),
    ]


def _cutoff(months):
    if months is None or months < MIN_KEEP_MONTHS:
        raise BusinessError(f"Phải giữ dữ liệu ít nhất {MIN_KEEP_MONTHS} tháng")
    if months > 120:
        raise BusinessError("Số tháng giữ dữ liệu tối đa là 120")
    return now() - timedelta(days=30 * months)       # mỗi tháng tính 30 ngày


def cleanup_preview(months):                                          # xem trước, chưa xoá gì
    cutoff = _cutoff(months)
    rows = [(label, db.session.scalar(select(func.count()).select_from(model).where(cond)) or 0)
            for label, model, cond in _cleanup_targets(cutoff)]
    return cutoff, rows


def run_cleanup(months, confirm_text):                                # ADM2.3.1
    if (confirm_text or "").strip().upper() != "XOA DU LIEU":
        raise BusinessError("Gõ đúng chữ XOA DU LIEU để xác nhận")
    cutoff, rows = cleanup_preview(months)
    if not any(n for _l, n in rows):
        raise BusinessError("Không có dữ liệu nào quá hạn lưu trữ")
    run_backup_now(prefix="pre-cleanup")               # bắt buộc có bản sao lưu trước; lỗi thì dừng, không xoá
    try:
        for label, model, cond in _cleanup_targets(cutoff):
            if model is Shift:                         # bảng nối bàn phụ trách phải xoá trước
                db.session.execute(delete(shift_tables).where(shift_tables.c.shift_id.in_(
                    select(Shift.id).where(cond))).execution_options(synchronize_session=False))
            db.session.execute(delete(model).where(cond).execution_options(synchronize_session=False))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log_error("ERROR", f"Dọn dẹp dữ liệu thất bại: {e}")
        raise BusinessError("Dọn dẹp thất bại, dữ liệu được giữ nguyên")
    return cutoff, rows
