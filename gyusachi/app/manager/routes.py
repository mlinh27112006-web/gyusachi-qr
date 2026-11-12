import io
import os
import uuid
from datetime import date, datetime, timedelta

import qrcode
from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user
from PIL import Image

from .. import db, reports
from ..models import (
    AuditLog, BuffetPackage, Category, DiningTable, MenuItem, Shift, TableSession, User,
)
from ..permissions import perm_required
from ..utils import now
from ..services import (
    BusinessError, KEEP, ROLE_VI, STAFF_ROLES, add_category, checkout, create_dish, create_shift,
    create_staff, delete_category, delete_shift, rename_category, set_all_max_qty,
    set_dish_active, set_dish_rules, set_staff_locked, staff_users, update_dish, update_staff,
)

bp = Blueprint("manager", __name__, url_prefix="/manager")

ALLOWED_IMAGES = {"png", "jpg", "jpeg", "webp"}
UPLOAD_PREFIX = "uploads/menu/"


def _int(name, default=0):
    try:
        return int(request.form.get(name, default) or default)
    except ValueError:
        return default


def _audit(action, detail=""):
    db.session.add(AuditLog(user_id=current_user.id, action=action, detail=detail))
    db.session.commit()


# ------------------------------------------------------------ ảnh món
def _upload_dir():
    folder = os.path.join(current_app.static_folder, "uploads", "menu")
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_image(fs):
    """Lưu ảnh tải lên, trả về đường dẫn dùng trong <img src>; None nếu không chọn ảnh."""
    if not fs or not fs.filename:
        return None
    ext = fs.filename.rsplit(".", 1)[-1].lower() if "." in fs.filename else ""
    if ext not in ALLOWED_IMAGES:
        raise BusinessError("Ảnh phải là PNG, JPG hoặc WEBP")
    try:
        Image.open(fs.stream).verify()          # chắc chắn đây là ảnh thật
    except Exception:
        raise BusinessError("File ảnh không hợp lệ")
    fs.stream.seek(0)
    name = f"{uuid.uuid4().hex}.{ext}"
    fs.save(os.path.join(_upload_dir(), name))
    return url_for("static", filename=UPLOAD_PREFIX + name)


def _delete_image(url):
    """Xoá file ảnh cũ, chỉ khi nó nằm trong thư mục ảnh món do hệ thống quản lý."""
    marker = "/static/" + UPLOAD_PREFIX
    if url and marker in url:
        path = os.path.join(_upload_dir(), os.path.basename(url))
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------ Bàn và QR (QLTT3)
@bp.route("/tables")
@perm_required("CAN_MANAGE_TABLES")
def tables():
    return render_template("manager/tables.html",
                           tables=DiningTable.query.order_by(DiningTable.code).all(),
                           base_url=current_app.config["BASE_URL"])


@bp.post("/tables/add")
@perm_required("CAN_MANAGE_TABLES")
def add_table():
    code = request.form.get("code", "").strip().upper()
    if not code:
        flash("Nhập mã bàn")
    elif DiningTable.query.filter_by(code=code).first():
        flash("Mã bàn đã tồn tại")
    else:
        db.session.add(DiningTable(code=code, seats=_int("seats", 4) or 4))
        db.session.commit()
    return redirect(url_for("manager.tables"))


@bp.post("/tables/<int:table_id>/lock")
@perm_required("CAN_MANAGE_TABLES")
def lock(table_id):
    table = db.get_or_404(DiningTable, table_id)
    if table.status != "EMPTY":
        flash("Chỉ khoá được bàn đang trống")
    else:
        table.is_locked = not table.is_locked
        db.session.commit()
    return redirect(url_for("manager.tables"))


@bp.route("/qr/<int:table_id>.png")
@perm_required("CAN_MANAGE_TABLES")
def qr_image(table_id):
    table = db.get_or_404(DiningTable, table_id)
    url = f"{current_app.config['BASE_URL'].rstrip('/')}/t/{table.qr_token}"
    img = qrcode.make(url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ------------------------------------------------------------ Quản trị menu (QLTT2)
@bp.route("/menu")
@perm_required("CAN_MANAGE_MENU")
def menu():
    categories = Category.query.order_by(Category.id).all()
    items = MenuItem.query.order_by(MenuItem.category_id, MenuItem.name).all()
    by_cat = {c.id: [] for c in categories}
    for it in items:
        by_cat.setdefault(it.category_id, []).append(it)
    return render_template("manager/menu.html", categories=categories, by_cat=by_cat,
                           packages=BuffetPackage.query.order_by(BuffetPackage.tier).all())


def _run(action, fn, *args, ok_msg=None, **kwargs):
    """Gọi một hàm nghiệp vụ: báo lỗi nếu sai, ghi nhật ký nếu đúng."""
    try:
        result = fn(*args, **kwargs)
    except BusinessError as e:
        flash(str(e))
        return None, False
    _audit(action, ok_msg or "")
    if ok_msg:
        flash(ok_msg)
    return result, True


@bp.post("/menu/categories/add")                                  # QLTT2.1.1
@perm_required("CAN_MANAGE_MENU")
def category_add():
    name = request.form.get("name", "").strip()
    _run("MENU_CATEGORY_ADD", add_category, name, ok_msg=f"Đã thêm nhóm món “{name}”")
    return redirect(url_for("manager.menu"))


@bp.post("/menu/categories/<int:cat_id>/rename")                  # QLTT2.1.2
@perm_required("CAN_MANAGE_MENU")
def category_rename(cat_id):
    _run("MENU_CATEGORY_RENAME", rename_category, cat_id, request.form.get("name", ""),
         ok_msg="Đã đổi tên nhóm món")
    return redirect(url_for("manager.menu"))


@bp.post("/menu/categories/<int:cat_id>/delete")                  # QLTT2.1.3
@perm_required("CAN_MANAGE_MENU")
def category_delete(cat_id):
    _run("MENU_CATEGORY_DELETE", delete_category, cat_id, ok_msg="Đã xoá nhóm món")
    return redirect(url_for("manager.menu"))


@bp.post("/menu/dishes/add")                                      # QLTT2.2
@perm_required("CAN_MANAGE_MENU")
def dish_add():
    image_url = None
    try:
        image_url = _save_image(request.files.get("image"))
        create_dish(request.form.get("name", ""), _int("category_id"),
                    request.form.get("description", ""), image_url,
                    min_tier=_int("min_tier", 1), max_qty=_int("max_qty", 5))
    except BusinessError as e:
        _delete_image(image_url)                 # đã lưu ảnh nhưng món không tạo được: dọn lại
        flash(str(e))
    else:
        _audit("MENU_DISH_ADD", request.form.get("name", ""))
        flash("Đã thêm món và cho hiện trên menu")
    return redirect(url_for("manager.menu"))


@bp.route("/menu/dishes/<int:item_id>/edit", methods=["GET", "POST"])   # QLTT2.3
@perm_required("CAN_MANAGE_MENU")
def dish_edit(item_id):
    item = db.get_or_404(MenuItem, item_id)
    if request.method == "POST":
        old_url, new_url = item.image_url, None
        try:
            new_url = _save_image(request.files.get("image"))
            if new_url:
                image = new_url
            elif request.form.get("remove_image"):
                image = None
            else:
                image = KEEP
            update_dish(item.id, request.form.get("name", ""), _int("category_id"),
                        request.form.get("description", ""), image_url=image)
        except BusinessError as e:
            _delete_image(new_url)
            flash(str(e))
            return redirect(url_for("manager.dish_edit", item_id=item.id))
        if image is not KEEP:
            _delete_image(old_url)
        _audit("MENU_DISH_EDIT", f"#{item.id} {item.name}")
        flash("Đã lưu thay đổi, menu của khách cập nhật theo")
        return redirect(url_for("manager.menu"))
    return render_template("manager/dish_edit.html", item=item,
                           categories=Category.query.order_by(Category.id).all())


@bp.post("/menu/dishes/<int:item_id>/rules")                      # QLTT2.4 + QLTT2.5
@perm_required("CAN_MANAGE_MENU")
def dish_rules(item_id):
    _run("MENU_DISH_RULES", set_dish_rules, item_id, _int("min_tier", 1), _int("max_qty", 5),
         ok_msg="Đã lưu gói và số lượng tối đa")
    return redirect(url_for("manager.menu") + f"#dish{item_id}")


@bp.post("/menu/max-qty-all")                                     # QLTT2.5.1: tất cả món
@perm_required("CAN_MANAGE_MENU")
def max_qty_all():
    _run("MENU_MAXQTY_ALL", set_all_max_qty, _int("max_qty", 5),
         ok_msg="Đã đặt số lượng tối đa cho tất cả món")
    return redirect(url_for("manager.menu"))


@bp.post("/menu/dishes/<int:item_id>/toggle")                     # QLTT2.6
@perm_required("CAN_MANAGE_MENU")
def dish_toggle(item_id):
    item = db.get_or_404(MenuItem, item_id)
    _run("MENU_DISH_TOGGLE", set_dish_active, item_id, not item.is_active,
         ok_msg="Đã cho bán lại món" if not item.is_active else "Đã ẩn món khỏi menu")
    return redirect(url_for("manager.menu") + f"#dish{item_id}")


# ------------------------------------------------------------ Tổng quan ca (QLTT1)
@bp.route("/overview")                                            # QLTT1.1
@perm_required("CAN_VIEW_SHIFT_REPORT")
def overview():
    return render_template("manager/overview.html", o=reports.overview(now()))


@bp.post("/overview/checkout/<int:sess_id>")                      # QLTT1.2: dùng chung TN2.1
@perm_required("CAN_CHECKOUT")
def overview_checkout(sess_id):
    sess = db.get_or_404(TableSession, sess_id)
    code = sess.table.code
    _run("MANAGER_CHECKOUT", checkout, sess, ok_msg=f"Đã checkout bàn {code}, bàn trở về trạng thái trống")
    return redirect(url_for("manager.overview"))


# ------------------------------------------------------------ Báo cáo theo ca / ngày (QLTT5)
@bp.route("/reports")
@perm_required("CAN_VIEW_SHIFT_REPORT")
def shift_report():
    day = reports.parse_date(request.args.get("date"), now().date())
    shift = request.args.get("shift", "all")
    try:
        start, end, label = reports.shift_bounds(day, shift)
    except BusinessError as e:
        flash(str(e))
        shift = "all"
        start, end, label = reports.shift_bounds(day, "all")
    totals = {**reports.revenue_totals(start, end), **reports.order_stats(start, end)}
    return render_template(
        "manager/report.html", day=day, shift=shift, label=label, start=start, end=end,
        totals=totals, invoices=reports.paid_invoices(start, end),
        packages=reports.by_package(start, end), shifts=reports.shift_choices(),
    )


# ------------------------------------------------------------ Nhân sự (QLTT4.1 đến QLTT4.3)
@bp.route("/staff")
@perm_required("CAN_MANAGE_STAFF")
def staff():
    return render_template("manager/staff.html", users=staff_users(), roles=STAFF_ROLES, role_vi=ROLE_VI)


@bp.post("/staff/add")                                            # QLTT4.1
@perm_required("CAN_MANAGE_STAFF")
def staff_add():
    f = request.form
    _run("STAFF_ADD", create_staff, f.get("username", ""), f.get("password", ""),
         f.get("full_name", ""), f.get("role", ""),
         ok_msg=f"Đã tạo tài khoản {f.get('username', '').strip().lower()}")
    return redirect(url_for("manager.staff"))


@bp.route("/staff/<int:user_id>/edit", methods=["GET", "POST"])    # QLTT4.2
@perm_required("CAN_MANAGE_STAFF")
def staff_edit(user_id):
    user = db.get_or_404(User, user_id)
    if user.role.name not in STAFF_ROLES:
        abort(403)
    if request.method == "POST":
        _, ok = _run("STAFF_EDIT", update_staff, user_id, request.form.get("full_name", ""),
                     request.form.get("role", ""), ok_msg=f"Đã cập nhật tài khoản {user.username}")
        return redirect(url_for("manager.staff") if ok else url_for("manager.staff_edit", user_id=user_id))
    return render_template("manager/staff_edit.html", user=user, roles=STAFF_ROLES, role_vi=ROLE_VI)


@bp.post("/staff/<int:user_id>/lock")                             # QLTT4.3
@perm_required("CAN_MANAGE_STAFF")
def staff_lock(user_id):
    user = db.get_or_404(User, user_id)
    locking = not user.is_locked
    _run("STAFF_LOCK" if locking else "STAFF_UNLOCK", set_staff_locked, user_id, locking,
         ok_msg=f"Đã {'khoá' if locking else 'mở khoá'} tài khoản {user.username}")
    return redirect(url_for("manager.staff"))


# ------------------------------------------------------------ Phân ca (QLTT4.4)
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


@bp.route("/schedule")
@perm_required("CAN_MANAGE_STAFF")
def schedule():
    today = now().date()
    anchor = reports.parse_date(request.args.get("week"), today)
    monday = anchor - timedelta(days=anchor.weekday())
    by_day = {monday + timedelta(days=i): [] for i in range(7)}
    for sh in (Shift.query.filter(Shift.work_date >= monday, Shift.work_date <= monday + timedelta(days=6))
               .order_by(Shift.work_date, Shift.start_time).all()):
        by_day[sh.work_date].append(sh)
    return render_template(
        "manager/schedule.html", monday=monday, sunday=monday + timedelta(days=6), by_day=by_day, today=today, weekdays=WEEKDAYS,
        prev_week=monday - timedelta(days=7), next_week=monday + timedelta(days=7),
        staff=staff_users(only_active=True), role_vi=ROLE_VI,
        tables=DiningTable.query.order_by(DiningTable.code).all(),
        default_date=max(today, monday),
    )


@bp.post("/schedule/add")
@perm_required("CAN_MANAGE_STAFF")
def schedule_add():
    f = request.form
    try:
        user_id = int(f["user_id"])
        work_date = date.fromisoformat(f["work_date"])
        start = datetime.strptime(f["start"], "%H:%M").time()
        end = datetime.strptime(f["end"], "%H:%M").time()
        table_ids = [int(x) for x in f.getlist("table_ids")]
    except (KeyError, ValueError):
        flash("Chọn đủ nhân viên, ngày, giờ bắt đầu và giờ kết thúc")
        return redirect(url_for("manager.schedule"))
    _run("SHIFT_ADD", create_shift, user_id, work_date, start, end, table_ids, ok_msg="Đã xếp ca")
    return redirect(url_for("manager.schedule", week=work_date.isoformat()))


@bp.post("/schedule/<int:shift_id>/delete")
@perm_required("CAN_MANAGE_STAFF")
def schedule_delete(shift_id):
    _run("SHIFT_DELETE", delete_shift, shift_id, ok_msg="Đã xoá ca")
    return redirect(url_for("manager.schedule", week=request.form.get("week", "")))
