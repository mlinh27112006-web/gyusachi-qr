from datetime import timedelta

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from .. import admin_service as svc
from .. import audit, backup, db, reports
from ..models import Permission, Role, User
from ..perms import PERM_VI, SYSTEM_ROLES
from ..permissions import perm_required
from ..services import ROLE_VI, BusinessError
from ..utils import now

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ------------------------------------------------------------ tiện ích
def _int(source, name, default=None):
    try:
        return int(str(source.get(name, "")).strip())
    except ValueError:
        return default


def _range_args():
    today = now().date()
    return (reports.parse_date(request.args.get("from"), today - timedelta(days=6)),
            reports.parse_date(request.args.get("to"), today))


def _run(action, fn, *args, ok_msg):
    """Gọi hàm nghiệp vụ: lỗi thì báo, đúng thì ghi nhật ký thao tác và báo thành công."""
    try:
        result = fn(*args)
    except BusinessError as e:
        flash(str(e))
        return None, False
    audit.log_audit(current_user.id, action, ok_msg)
    flash(ok_msg)
    return result, True


# ------------------------------------------------------------ ADM1: tài khoản
@bp.route("/users")
@perm_required("CAN_MANAGE_ROLES")
def users():
    return render_template("admin/users.html", users=svc.all_users(), roles=svc.all_roles(), role_vi=ROLE_VI)


@bp.post("/users/add")                                                 # ADM1.3.1
@perm_required("CAN_MANAGE_ROLES")
def user_add():
    f = request.form
    _run("ADMIN_USER_ADD", svc.create_account, f.get("username", ""), f.get("password", ""),
         f.get("full_name", ""), _int(f, "role_id"),
         ok_msg=f"Đã tạo tài khoản {f.get('username', '').strip().lower()}")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])        # ADM1.3.2
@perm_required("CAN_MANAGE_ROLES")
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    if request.method == "POST":
        _, ok = _run("ADMIN_USER_EDIT", svc.edit_account, user_id, request.form.get("full_name", ""),
                     _int(request.form, "role_id"), current_user.id,
                     ok_msg=f"Đã cập nhật tài khoản {user.username}")
        return redirect(url_for("admin.users") if ok else url_for("admin.user_edit", user_id=user_id))
    return render_template("admin/user_edit.html", user=user, roles=svc.all_roles(), role_vi=ROLE_VI)


@bp.post("/users/<int:user_id>/lock")                                  # ADM1.3.3
@perm_required("CAN_MANAGE_ROLES")
def user_lock(user_id):
    user = db.get_or_404(User, user_id)
    locking = not user.is_locked
    _run("ADMIN_USER_LOCK" if locking else "ADMIN_USER_UNLOCK", svc.lock_account, user_id, locking,
         current_user.id, ok_msg=f"Đã {'khoá' if locking else 'mở khoá'} tài khoản {user.username}")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/password")                              # ADM1.4.1
@perm_required("CAN_MANAGE_ROLES")
def user_password(user_id):
    user = db.get_or_404(User, user_id)
    _run("ADMIN_PASSWORD_RESET", svc.reset_password, user_id, request.form.get("password", ""),
         ok_msg=f"Đã đặt lại mật khẩu cho tài khoản {user.username}")
    return redirect(url_for("admin.user_edit", user_id=user_id))


# ------------------------------------------------------------ ADM1: vai trò và quyền
@bp.route("/roles")
@perm_required("CAN_MANAGE_ROLES")
def roles():
    order = list(PERM_VI)
    perms = sorted(Permission.query.all(), key=lambda p: order.index(p.code) if p.code in order else 999)
    roles_ = svc.all_roles()
    counts = {r.id: User.query.filter_by(role_id=r.id).count() for r in roles_}
    granted = {r.id: {p.code for p in r.permissions} for r in roles_}
    return render_template("admin/roles.html", roles=roles_, perms=perms, perm_vi=PERM_VI, counts=counts,
                           granted=granted, system_roles=SYSTEM_ROLES, role_vi=ROLE_VI)


@bp.post("/roles/add")                                                 # ADM1.1.1
@perm_required("CAN_MANAGE_ROLES")
def role_add():
    name = request.form.get("name", "").strip()
    _run("ADMIN_ROLE_ADD", svc.create_role, name, ok_msg=f"Đã tạo vai trò “{name}”")
    return redirect(url_for("admin.roles"))


@bp.post("/roles/<int:role_id>/rename")                                # ADM1.1.2
@perm_required("CAN_MANAGE_ROLES")
def role_rename(role_id):
    _run("ADMIN_ROLE_RENAME", svc.rename_role, role_id, request.form.get("name", ""), ok_msg="Đã đổi tên vai trò")
    return redirect(url_for("admin.roles"))


@bp.post("/roles/<int:role_id>/delete")                                # ADM1.1.3
@perm_required("CAN_MANAGE_ROLES")
def role_delete(role_id):
    role = db.get_or_404(Role, role_id)
    _run("ADMIN_ROLE_DELETE", svc.delete_role, role_id, ok_msg=f"Đã xoá vai trò “{role.name}”")
    return redirect(url_for("admin.roles"))


@bp.post("/roles/permissions")                                         # ADM1.2.1
@perm_required("CAN_MANAGE_ROLES")
def role_permissions():
    matrix = {r.id: set(request.form.getlist(f"role_{r.id}")) for r in svc.all_roles() if r.name != "ADMIN"}
    _run("ADMIN_PERMS_SET", svc.set_permission_matrix, matrix, ok_msg="Đã cập nhật bảng quyền của các vai trò")
    return redirect(url_for("admin.roles"))


# ------------------------------------------------------------ ADM2: sao lưu, phục hồi, dọn dẹp
@bp.route("/backups")
@perm_required("CAN_BACKUP")
def backups():
    bin_dir = current_app.config.get("PG_BIN_DIR") or None
    tools_error = None
    try:
        backup.find_tool("pg_dump", bin_dir)
        backup.find_tool("psql", bin_dir)
    except backup.BackupError as e:
        tools_error = str(e)

    months = _int(request.args, "months")
    preview = None
    if months is not None:
        try:
            cutoff, rows = svc.cleanup_preview(months)
            preview = {"months": months, "cutoff": cutoff, "rows": rows, "total": sum(n for _l, n in rows)}
        except BusinessError as e:
            flash(str(e))
    files = svc.list_backups()
    for b in files:
        b["size_text"] = backup.human_size(b["size"])
    return render_template("admin/backups.html", files=files, schedule=svc.backup_schedule(),
                           tools_error=tools_error, preview=preview, months=months if months else 12,
                           min_months=svc.MIN_KEEP_MONTHS)


@bp.post("/backups/run")                                               # ADM2.1.1 thủ công
@perm_required("CAN_BACKUP")
def backup_run():
    try:
        name = svc.run_backup_now()
    except BusinessError as e:
        flash(str(e))
    else:
        audit.log_audit(current_user.id, "BACKUP_RUN", name)
        flash(f"Đã sao lưu: {name}")
    return redirect(url_for("admin.backups"))


@bp.post("/backups/schedule")                                          # ADM2.1.1 định kỳ
@perm_required("CAN_BACKUP")
def backup_schedule():
    f = request.form
    _run("BACKUP_SCHEDULE", svc.update_backup_schedule, f.get("mode", ""), f.get("time", ""), _int(f, "keep"),
         ok_msg="Đã lưu lịch sao lưu")
    return redirect(url_for("admin.backups"))


@bp.route("/backups/download/<name>")
@perm_required("CAN_BACKUP")
def backup_download(name):
    try:
        path = svc.backup_path(name)
    except BusinessError:
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)


@bp.post("/backups/restore")                                           # ADM2.2.1, ADM2.2.2
@perm_required("CAN_BACKUP")
def backup_restore():
    name = request.form.get("name", "")
    try:
        safety = svc.restore_backup_file(name, request.form.get("confirm", ""))
    except BusinessError as e:
        flash(str(e))
        return redirect(url_for("admin.backups"))
    try:                                           # tài khoản đang dùng có thể không còn trong bản phục hồi
        audit.log_audit(current_user.id, "BACKUP_RESTORE", f"{name} (bản an toàn trước đó: {safety})")
    except Exception:
        db.session.rollback()
    flash(f"Đã phục hồi từ {name}. Bản an toàn trước khi phục hồi: {safety}")
    return redirect(url_for("admin.backups"))


@bp.post("/backups/cleanup")                                           # ADM2.3.1
@perm_required("CAN_BACKUP")
def backup_cleanup():
    months = _int(request.form, "months")
    try:
        cutoff, rows = svc.run_cleanup(months, request.form.get("confirm", ""))
    except BusinessError as e:
        flash(str(e))
        return redirect(url_for("admin.backups", months=months or ""))
    total = sum(n for _l, n in rows)
    audit.log_audit(current_user.id, "DATA_CLEANUP", f"Giữ {months} tháng, đã xoá {total} dòng cũ hơn {cutoff:%d/%m/%Y}")
    flash(f"Đã xoá {total} dòng dữ liệu cũ hơn {cutoff:%d/%m/%Y}. Bản sao lưu trước khi xoá nằm trong danh sách bên dưới.")
    return redirect(url_for("admin.backups"))


# ------------------------------------------------------------ ADM3: nhật ký
@bp.route("/logs")                                                     # ADM3.1
@perm_required("CAN_VIEW_SYSTEM_LOGS")
def logs():
    d_from, d_to = _range_args()
    user_id, action = request.args.get("user", type=int), request.args.get("action") or None
    if action and action not in audit.ACTION_VI:
        action = None
    total, rows = 0, []
    try:
        total, rows = audit.search_logs(d_from, d_to, user_id=user_id, role_names=None, action=action)
    except BusinessError as e:
        flash(str(e))
    return render_template("admin/logs.html", d_from=d_from, d_to=d_to, users=svc.all_users(), user_id=user_id,
                           actions=audit.ACTION_VI, action=action, total=total, rows=rows)


@bp.route("/errors")                                                   # ADM3.2
@perm_required("CAN_VIEW_SYSTEM_LOGS")
def errors():
    d_from, d_to = _range_args()
    level = request.args.get("level") or None
    total, rows = 0, []
    try:
        total, rows = audit.search_errors(d_from, d_to, level)
    except BusinessError as e:
        flash(str(e))
    return render_template("admin/errors.html", d_from=d_from, d_to=d_to, level=level, levels=audit.LEVEL_VI,
                           total=total, rows=rows)


@bp.route("/logins")                                                   # ADM3.3
@perm_required("CAN_VIEW_SYSTEM_LOGS")
def logins():
    d_from, d_to = _range_args()
    username = request.args.get("username") or None
    total, rows = 0, []
    try:
        total, rows = audit.search_logins(d_from, d_to, username)
    except BusinessError as e:
        flash(str(e))
    return render_template("admin/logins.html", d_from=d_from, d_to=d_to, users=svc.all_users(),
                           username=username, total=total, rows=rows)


# ------------------------------------------------------------ ADM4: cấu hình kỹ thuật
@bp.route("/settings")
@perm_required("CAN_CONFIG_SYSTEM")
def settings():
    return render_template("admin/settings.html", params=svc.get_params(), specs=svc.PARAM_SPECS,
                           printer=svc.get_printer(), printer_types=svc.PRINTER_TYPES)


@bp.post("/settings/params")                                           # ADM4.2.1
@perm_required("CAN_CONFIG_SYSTEM")
def settings_params():
    values = {key: _int(request.form, key) for key in svc.PARAM_SPECS}
    _run("SETTINGS_UPDATE", svc.update_params, values, ok_msg="Đã cập nhật tham số hệ thống")
    return redirect(url_for("admin.settings"))


@bp.post("/settings/printer")                                          # ADM4.1.1
@perm_required("CAN_CONFIG_SYSTEM")
def settings_printer():
    f = request.form
    _run("PRINTER_UPDATE", svc.update_printer, f.get("type", ""), f.get("address", ""), _int(f, "port"),
         ok_msg="Đã lưu cấu hình máy in")
    return redirect(url_for("admin.settings"))


@bp.post("/settings/printer/test")
@perm_required("CAN_CONFIG_SYSTEM")
def settings_printer_test():
    try:
        svc.test_printer()
    except BusinessError as e:
        flash(str(e))
    else:
        flash("Kết nối máy in thành công")
    return redirect(url_for("admin.settings"))
