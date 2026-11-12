import io
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from .. import audit, db, reports
from ..exporters import to_pdf, to_xlsx
from ..models import AuditLog, BuffetPackage, OpeningHour, User
from ..permissions import perm_required
from ..services import (
    MANAGER_ROLES, WEEKDAYS_VI, BusinessError, add_opening_hours, create_staff, delete_opening_hours,
    get_restaurant, manager_users, set_staff_locked, update_package_prices, update_restaurant, update_staff,
)
from ..utils import now, parse_money

bp = Blueprint("owner", __name__, url_prefix="/owner")


def _range_args():
    today = now().date()
    d_from = reports.parse_date(request.args.get("from"), today - timedelta(days=6))
    d_to = reports.parse_date(request.args.get("to"), today)
    return d_from, d_to


def _limit():
    try:
        return max(1, min(50, int(request.args.get("limit", 10))))
    except ValueError:
        return 10


def _kind():
    kind = request.args.get("kind", "day")
    return kind if kind in reports.KINDS else "day"


@bp.route("/reports")                                          # CHU1.1, CHU1.2, CHU1.3
@perm_required("CAN_VIEW_BUSINESS_REPORT")
def report():
    d_from, d_to, kind, limit = *_range_args(), _kind(), _limit()
    period, packages, top = [], [], []
    try:
        period = reports.revenue_by_period(d_from, d_to, kind)
        start, end = reports.range_bounds(d_from, d_to)
        packages = reports.by_package(start, end)
        top = reports.top_items(start, end, limit)
    except BusinessError as e:
        flash(str(e))
    totals = reports.sum_rows(period, "invoices", "guests", "revenue") if period else \
        {"invoices": 0, "guests": 0, "revenue": 0}
    return render_template("owner/report.html", d_from=d_from, d_to=d_to, kind=kind, limit=limit,
                           kinds=reports.KINDS, period=period, packages=packages, top=top, totals=totals)


@bp.route("/compare")                                          # CHU1.4
@perm_required("CAN_VIEW_BUSINESS_REPORT")
def compare():
    today = now().date()
    a_from = reports.parse_date(request.args.get("a_from"), today - timedelta(days=13))
    a_to = reports.parse_date(request.args.get("a_to"), today - timedelta(days=7))
    b_from = reports.parse_date(request.args.get("b_from"), today - timedelta(days=6))
    b_to = reports.parse_date(request.args.get("b_to"), today)
    a_shift, b_shift = request.args.get("a_shift", "all"), request.args.get("b_shift", "all")
    a = b = rows = None
    try:
        a = reports.period_summary(a_from, a_to, a_shift)
        b = reports.period_summary(b_from, b_to, b_shift)
        rows = reports.compare_rows(a, b)
    except BusinessError as e:
        flash(str(e))
    return render_template("owner/compare.html", a=a, b=b, rows=rows, shifts=reports.shift_choices(),
                           a_from=a_from, a_to=a_to, b_from=b_from, b_to=b_to,
                           a_shift=a_shift, b_shift=b_shift)


@bp.route("/export")                                           # CHU1.5.1: chọn báo cáo + định dạng
@perm_required("CAN_VIEW_BUSINESS_REPORT")
def export():
    d_from, d_to = _range_args()
    return render_template("owner/export.html", d_from=d_from, d_to=d_to, kinds=reports.KINDS,
                           types=reports.REPORT_TYPES, limit=_limit())


@bp.route("/export/file")                                      # CHU1.5.2: tạo file để tải về
@perm_required("CAN_VIEW_BUSINESS_REPORT")
def export_file():
    d_from, d_to = _range_args()
    report_type, fmt = request.args.get("report", ""), request.args.get("format", "")
    if fmt not in ("xlsx", "pdf"):
        flash("Chọn định dạng Excel hoặc PDF")
        return redirect(url_for("owner.export"))
    try:
        table = reports.build_table(report_type, d_from, d_to, _kind(), _limit())
        table["generated"] = now().strftime("%d/%m/%Y %H:%M")
        table["org"] = get_restaurant().name
        data = to_pdf(table) if fmt == "pdf" else to_xlsx(table)
    except (BusinessError, RuntimeError) as e:
        flash(str(e))
        return redirect(url_for("owner.export"))
    db.session.add(AuditLog(user_id=current_user.id, action="REPORT_EXPORT",
                            detail=f"{report_type} {d_from}..{d_to} {fmt}"))
    db.session.commit()
    mime = ("application/pdf" if fmt == "pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                     download_name=f"bao-cao-{report_type}-{d_from}-{d_to}.{fmt}")


# ------------------------------------------------------------ Cấu hình kinh doanh (CHU2)
def _run(action, fn, *args, ok_msg):
    """Gọi hàm nghiệp vụ: báo lỗi nếu sai, ghi nhật ký và báo thành công nếu đúng."""
    try:
        fn(*args)
    except BusinessError as e:
        flash(str(e))
        return
    db.session.add(AuditLog(user_id=current_user.id, action=action, detail=ok_msg))
    db.session.commit()
    flash(ok_msg)


@bp.route("/config")
@perm_required("CAN_CONFIG_BUSINESS")
def config():
    hours = {wd: [] for wd in range(7)}
    for row in OpeningHour.query.order_by(OpeningHour.weekday, OpeningHour.open_time).all():
        hours[row.weekday].append(row)
    return render_template("owner/config.html", info=get_restaurant(), hours=hours, weekdays=WEEKDAYS_VI,
                           packages=BuffetPackage.query.order_by(BuffetPackage.tier).all())


@bp.post("/config/restaurant")                                  # CHU2.1
@perm_required("CAN_CONFIG_BUSINESS")
def config_restaurant():
    _run("CONFIG_RESTAURANT", update_restaurant, request.form.get("name", ""),
         request.form.get("address", ""), ok_msg="Đã cập nhật thông tin nhà hàng")
    return redirect(url_for("owner.config"))


@bp.post("/config/hours/add")                                   # CHU2.2
@perm_required("CAN_CONFIG_BUSINESS")
def config_hours_add():
    try:
        days = [int(x) for x in request.form.getlist("weekdays")]
        open_t = datetime.strptime(request.form["open"], "%H:%M").time()
        close_t = datetime.strptime(request.form["close"], "%H:%M").time()
    except (KeyError, ValueError):
        flash("Chọn ngày áp dụng, giờ mở và giờ đóng")
        return redirect(url_for("owner.config"))
    names = ", ".join(WEEKDAYS_VI[d] for d in sorted(set(days)) if d in range(7))
    _run("CONFIG_HOURS_ADD", add_opening_hours, days, open_t, close_t,
         ok_msg=f"Đã thêm khung giờ {open_t:%H:%M}–{close_t:%H:%M} cho {names}")
    return redirect(url_for("owner.config"))


@bp.post("/config/hours/<int:row_id>/delete")
@perm_required("CAN_CONFIG_BUSINESS")
def config_hours_delete(row_id):
    _run("CONFIG_HOURS_DELETE", delete_opening_hours, row_id, ok_msg="Đã xoá khung giờ mở cửa")
    return redirect(url_for("owner.config"))


@bp.post("/config/prices")                                      # CHU2.3
@perm_required("CAN_CONFIG_BUSINESS")
def config_prices():
    prices = {}
    for p in BuffetPackage.query.all():
        value = parse_money(request.form.get(f"price_{p.id}"))
        if value is not None:
            prices[p.id] = value
    _run("CONFIG_PRICES", update_package_prices, prices, ok_msg="Đã cập nhật giá 6 gói buffet")
    return redirect(url_for("owner.config"))


# ------------------------------------------------------------ Tài khoản Quản lý (CHU3)
@bp.route("/managers")
@perm_required("CAN_MANAGE_MANAGERS")
def managers():
    return render_template("owner/managers.html", users=manager_users())


@bp.post("/managers/add")                                       # CHU3.1: vai trò cố định là Quản lý
@perm_required("CAN_MANAGE_MANAGERS")
def manager_add():
    f = request.form
    _run("CHU_MANAGER_ADD", create_staff, f.get("username", ""), f.get("password", ""),
         f.get("full_name", ""), "QUAN_LY", MANAGER_ROLES,
         ok_msg=f"Đã tạo tài khoản Quản lý {f.get('username', '').strip().lower()}")
    return redirect(url_for("owner.managers"))


@bp.route("/managers/<int:user_id>/edit", methods=["GET", "POST"])   # CHU3.2
@perm_required("CAN_MANAGE_MANAGERS")
def manager_edit(user_id):
    user = db.get_or_404(User, user_id)
    if user.role.name not in MANAGER_ROLES:
        abort(403)
    if request.method == "POST":
        _run("CHU_MANAGER_EDIT", update_staff, user_id, request.form.get("full_name", ""), "QUAN_LY",
             MANAGER_ROLES, ok_msg=f"Đã cập nhật tài khoản {user.username}")
        return redirect(url_for("owner.managers"))
    return render_template("owner/manager_edit.html", user=user)


@bp.post("/managers/<int:user_id>/lock")                        # CHU3.2: khoá hoặc mở khoá
@perm_required("CAN_MANAGE_MANAGERS")
def manager_lock(user_id):
    user = db.get_or_404(User, user_id)
    locking = not user.is_locked
    _run("CHU_MANAGER_LOCK" if locking else "CHU_MANAGER_UNLOCK", set_staff_locked, user_id, locking,
         MANAGER_ROLES, ok_msg=f"Đã {'khoá' if locking else 'mở khoá'} tài khoản {user.username}")
    return redirect(url_for("owner.managers"))


# ------------------------------------------------------------ Giám sát (CHU4)
@bp.route("/data")                                              # CHU4.1: dữ liệu kinh doanh, chỉ đọc
@perm_required("CAN_VIEW_BUSINESS_REPORT")
def data():
    d_from, d_to = _range_args()
    kind = request.args.get("type", "invoices")
    page = request.args.get("page", 1, type=int)
    table = None
    try:
        table = reports.browse(kind, d_from, d_to, page)
    except BusinessError as e:
        flash(str(e))
    return render_template("owner/data.html", d_from=d_from, d_to=d_to, kind=kind if kind in reports.BROWSE_TYPES else "invoices",
                           types=reports.BROWSE_TYPES, table=table)


@bp.route("/logs")                                              # CHU4.2: nhật ký của Quản lý
@perm_required("CAN_VIEW_LOGS")
def logs():
    d_from, d_to = _range_args()
    managers_ = manager_users()
    user_id = request.args.get("user", type=int)
    if user_id and user_id not in {m.id for m in managers_}:
        flash("Chỉ xem được nhật ký của tài khoản Quản lý")
        user_id = None
    total, rows = 0, []
    try:
        total, rows = audit.search_logs(d_from, d_to, user_id)
    except BusinessError as e:
        flash(str(e))
    return render_template("owner/logs.html", d_from=d_from, d_to=d_to, managers=managers_,
                           user_id=user_id, total=total, rows=rows)
