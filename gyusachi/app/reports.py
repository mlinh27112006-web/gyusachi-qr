"""Truy vấn báo cáo cho Quản lý (QLTT1, QLTT5) và Chủ (CHU1).

Quy ước tính số liệu (đã thống nhất, đổi ở một chỗ này):
- Doanh thu = cộng các hoá đơn ĐÃ THU (Invoice.status == "PAID"), tính theo giờ thu tiền (paid_at).
- Số khách = người lớn + trẻ 1m–1m3 + trẻ dưới 1m của phiên bàn đã thu tiền.
- Số đơn, số món không tính món đã huỷ (đơn mà mọi món đều huỷ thì không tính).
  "Số món" là tổng số phần (cộng cột số lượng).
- Ca = khung giờ mở cửa của ngày (bảng opening_hours, thứ tự theo giờ mở). Để mỗi hoá đơn
  rơi vào đúng một ca, ca 1 tính từ 00:00 và mỗi ca kéo dài đến lúc ca sau bắt đầu
  (ca cuối kéo dài hết ngày). "Cả ngày" = cộng tất cả ca.
"""
from collections import OrderedDict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from . import db
from .models import (
    BuffetPackage, DiningTable, Invoice, MenuItem, OpeningHour, Order, OrderItem, Shift,
    TableSession, User,
)
from .services import ROLE_VI, BusinessError, calc_total, session_price
from .utils import STATUS_VI, vnd

KINDS = OrderedDict([("day", "ngày"), ("week", "tuần"), ("month", "tháng"), ("year", "năm")])
MAX_RANGE_DAYS = 3660


# ----------------------------------------------------------- ngày, ca
def parse_date(text, default):
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return default


def check_range(d_from, d_to):
    if d_from > d_to:
        raise BusinessError("“Từ ngày” phải trước hoặc bằng “Đến ngày”")
    if (d_to - d_from).days > MAX_RANGE_DAYS:
        raise BusinessError("Khoảng thời gian quá dài (tối đa 10 năm)")


def day_bounds(d):
    start = datetime.combine(d, time.min)
    return start, start + timedelta(days=1)


def range_bounds(d_from, d_to):
    return datetime.combine(d_from, time.min), datetime.combine(d_to, time.min) + timedelta(days=1)


def frames_of(d):
    return OpeningHour.query.filter_by(weekday=d.weekday()).order_by(OpeningHour.open_time).all()


def shift_choices():
    """Danh sách lựa chọn ca cho ô chọn: Cả ngày, Ca 1, Ca 2... (theo ngày nhiều ca nhất)."""
    most = 0
    for wd in range(7):
        most = max(most, OpeningHour.query.filter_by(weekday=wd).count())
    return [("all", "Cả ngày")] + [(str(i), f"Ca {i}") for i in range(1, most + 1)]


def shift_bounds(d, shift):
    """-> (start, end, nhãn). shift: 'all' hoặc '1', '2'..."""
    day_start, day_end = day_bounds(d)
    if shift in (None, "", "all"):
        return day_start, day_end, "Cả ngày"
    frames = frames_of(d)
    try:
        idx = int(shift) - 1
    except ValueError:
        raise BusinessError("Ca không hợp lệ")
    if not 0 <= idx < len(frames):
        raise BusinessError(f"Ngày {d:%d/%m/%Y} không có ca {shift}")
    start = day_start if idx == 0 else datetime.combine(d, frames[idx].open_time)
    end = day_end if idx == len(frames) - 1 else datetime.combine(d, frames[idx + 1].open_time)
    label = f"Ca {idx + 1} ({frames[idx].open_time:%H:%M}–{frames[idx].close_time:%H:%M})"
    return start, end, label


def current_shift(dt):
    """Ca đang diễn ra tại thời điểm dt: '1', '2'... hoặc 'all' nếu hôm nay không mở cửa."""
    frames = frames_of(dt.date())
    if not frames:
        return "all"
    started = sum(1 for f in frames if f.open_time <= dt.time())
    return str(max(started, 1))


# ----------------------------------------------------------- số liệu cơ bản
def _guests(s):
    return (s.adults or 0) + (s.kids_mid or 0) + (s.kids_free or 0)


def _paid(start, end):
    return (db.session.query(Invoice, TableSession)
            .select_from(Invoice)
            .join(TableSession, Invoice.session_id == TableSession.id)
            .filter(Invoice.status == "PAID", Invoice.paid_at >= start, Invoice.paid_at < end))


def revenue_totals(start, end):
    rows = _paid(start, end).all()
    return {"invoices": len(rows),
            "revenue": sum(inv.total for inv, _ in rows),
            "guests": sum(_guests(s) for _, s in rows)}


def paid_invoices(start, end):
    """Danh sách hoá đơn đã thu trong khoảng, mới nhất ở cuối."""
    rows = _paid(start, end).order_by(Invoice.paid_at).all()
    return [{"time": inv.paid_at, "table": s.table.code, "package": s.package.name,
             "guests": _guests(s), "total": inv.total,
             "method": "Tiền mặt" if inv.method == "CASH" else "Chuyển khoản"}
            for inv, s in rows]


def order_stats(start, end):
    orders, items = (db.session.query(func.count(func.distinct(Order.id)),
                                      func.coalesce(func.sum(OrderItem.quantity), 0))
                     .select_from(Order)
                     .join(OrderItem, OrderItem.order_id == Order.id)
                     .filter(OrderItem.status != "CANCELLED",
                             Order.created_at >= start, Order.created_at < end)
                     .one())
    return {"orders": int(orders or 0), "dishes": int(items or 0)}


def by_package(start, end):
    agg = {}
    for inv, s in _paid(start, end).all():
        a = agg.setdefault(s.package_id, {"tables": 0, "guests": 0, "revenue": 0})
        a["tables"] += 1
        a["guests"] += _guests(s)
        a["revenue"] += inv.total
    out = []
    for p in BuffetPackage.query.order_by(BuffetPackage.tier).all():
        a = agg.get(p.id, {"tables": 0, "guests": 0, "revenue": 0})
        out.append({"name": p.name, "price": p.price, **a})
    return out


def top_items(start, end, limit=10):
    rows = (db.session.query(MenuItem.name, func.sum(OrderItem.quantity))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .join(MenuItem, OrderItem.menu_item_id == MenuItem.id)
            .filter(OrderItem.status != "CANCELLED",
                    Order.created_at >= start, Order.created_at < end)
            .group_by(MenuItem.id, MenuItem.name)
            .order_by(func.sum(OrderItem.quantity).desc(), MenuItem.name)
            .limit(limit).all())
    return [{"rank": i, "name": n, "qty": int(q)} for i, (n, q) in enumerate(rows, start=1)]


def _bucket(d, kind):
    if kind == "week":
        iso = d.isocalendar()
        monday = d - timedelta(days=d.weekday())
        return (iso[0], iso[1]), f"Tuần {iso[1]}/{iso[0]} ({monday:%d/%m}–{monday + timedelta(days=6):%d/%m})"
    if kind == "month":
        return (d.year, d.month), f"Tháng {d.month}/{d.year}"
    if kind == "year":
        return d.year, f"Năm {d.year}"
    return d, f"{d:%d/%m/%Y}"


def revenue_by_period(d_from, d_to, kind="day"):
    """CHU1.1: doanh thu theo ngày / tuần / tháng / năm; kỳ không có hoá đơn vẫn hiện số 0."""
    check_range(d_from, d_to)
    if kind not in KINDS:
        kind = "day"
    buckets = OrderedDict()
    d = d_from
    while d <= d_to:
        key, label = _bucket(d, kind)
        buckets.setdefault(key, {"label": label, "invoices": 0, "guests": 0, "revenue": 0})
        d += timedelta(days=1)
    start, end = range_bounds(d_from, d_to)
    for inv, s in _paid(start, end).all():
        b = buckets[_bucket(inv.paid_at.date(), kind)[0]]
        b["invoices"] += 1
        b["guests"] += _guests(s)
        b["revenue"] += inv.total
    return list(buckets.values())


def sum_rows(rows, *keys):
    return {k: sum(r[k] for r in rows) for k in keys}


# ----------------------------------------------------------- so sánh (CHU1.4)
def period_summary(d_from, d_to, shift="all"):
    check_range(d_from, d_to)
    if d_from == d_to and shift not in (None, "", "all"):
        start, end, shift_label = shift_bounds(d_from, shift)
        label = f"{d_from:%d/%m/%Y} · {shift_label}"
    else:
        start, end = range_bounds(d_from, d_to)
        label = f"{d_from:%d/%m/%Y}" if d_from == d_to else f"{d_from:%d/%m/%Y} – {d_to:%d/%m/%Y}"
    t = revenue_totals(start, end)
    t.update(order_stats(start, end))
    t["label"] = label
    t["per_guest"] = t["revenue"] // t["guests"] if t["guests"] else 0
    return t


def compare_rows(a, b):
    spec = [("Doanh thu (đ)", "revenue", True), ("Số hoá đơn (bàn)", "invoices", False),
            ("Số khách", "guests", False), ("Doanh thu trung bình mỗi khách (đ)", "per_guest", True),
            ("Số đơn gọi món", "orders", False), ("Số món (phần)", "dishes", False)]
    rows = []
    for label, key, money in spec:
        diff = b[key] - a[key]
        pct = round(diff / a[key] * 100, 1) if a[key] else None
        rows.append({"label": label, "key": key, "a": a[key], "b": b[key], "diff": diff,
                     "pct": pct, "money": money})
    return rows


# ----------------------------------------------------------- tổng quan ca (QLTT1)
def overview(dt):
    shift = current_shift(dt)
    start, end, label = shift_bounds(dt.date(), shift)

    tables = DiningTable.query.all()
    count = {"EMPTY": 0, "IN_USE": 0, "WAITING_PAYMENT": 0}
    for t in tables:
        count[t.status] = count.get(t.status, 0) + 1

    open_sessions = TableSession.query.filter_by(is_open=True).all()
    expected = sum(calc_total(session_price(s), s.adults, s.kids_mid) for s in open_sessions)

    pending, cooking = [
        db.session.query(func.count(OrderItem.id)).filter(OrderItem.status == st).scalar() or 0
        for st in ("PENDING", "COOKING")
    ]

    # doanh thu theo giờ, từ giờ mở ca đến giờ hiện tại
    frames = frames_of(dt.date())
    first_hour = frames[int(shift) - 1].open_time.hour if shift != "all" and frames else min(10, dt.hour)
    hours = OrderedDict((h, 0) for h in range(first_hour, max(dt.hour, first_hour) + 1))
    for inv, _ in _paid(start, end).all():
        if inv.paid_at.hour in hours:
            hours[inv.paid_at.hour] += inv.total

    stuck = (TableSession.query.join(Invoice, Invoice.session_id == TableSession.id)
             .filter(TableSession.is_open.is_(True), Invoice.status == "PAID").all())

    return {
        "shift_label": label, "start": start, "tables_total": len(tables), "tables": count,
        "locked": sum(1 for t in tables if t.is_locked),
        "guests_in_house": sum(_guests(s) for s in open_sessions),
        "expected": expected, "pending": pending, "cooking": cooking,
        "totals": {**revenue_totals(start, end), **order_stats(start, end)},
        "packages": by_package(start, end),
        "hourly": [{"label": f"{h:02d}h", "revenue": v} for h, v in hours.items()],
        "stuck": stuck,
    }


# ----------------------------------------------------------- bảng để xuất file (CHU1.5)
def _range_subtitle(d_from, d_to):
    return f"Từ {d_from:%d/%m/%Y} đến {d_to:%d/%m/%Y}"


def table_revenue(d_from, d_to, kind, **_):
    kind = kind if kind in KINDS else "day"
    rows = revenue_by_period(d_from, d_to, kind)
    tot = sum_rows(rows, "invoices", "guests", "revenue")
    return {"title": f"Báo cáo doanh thu theo {KINDS[kind]}", "subtitle": _range_subtitle(d_from, d_to),
            "headers": ["Kỳ", "Số hoá đơn", "Số khách", "Doanh thu (đ)"],
            "rows": [[r["label"], r["invoices"], r["guests"], r["revenue"]] for r in rows],
            "footer": ["Tổng", tot["invoices"], tot["guests"], tot["revenue"]], "money_cols": [3]}


def table_packages(d_from, d_to, **_):
    check_range(d_from, d_to)
    rows = by_package(*range_bounds(d_from, d_to))
    tot = sum_rows(rows, "tables", "guests", "revenue")
    return {"title": "Thống kê theo gói buffet", "subtitle": _range_subtitle(d_from, d_to),
            "headers": ["Gói buffet", "Giá/người (đ)", "Số bàn", "Số khách", "Doanh thu (đ)"],
            "rows": [[r["name"], r["price"], r["tables"], r["guests"], r["revenue"]] for r in rows],
            "footer": ["Tổng", "", tot["tables"], tot["guests"], tot["revenue"]], "money_cols": [1, 4]}


def table_top_items(d_from, d_to, limit=10, **_):
    check_range(d_from, d_to)
    rows = top_items(*range_bounds(d_from, d_to), limit)
    return {"title": f"Top {limit} món được gọi nhiều nhất", "subtitle": _range_subtitle(d_from, d_to),
            "headers": ["Hạng", "Món", "Số phần"],
            "rows": [[r["rank"], r["name"], r["qty"]] for r in rows], "footer": None, "money_cols": []}


REPORT_TYPES = OrderedDict([
    ("revenue", ("Doanh thu theo kỳ", table_revenue)),
    ("packages", ("Thống kê theo gói buffet", table_packages)),
    ("top_items", ("Món bán chạy", table_top_items)),
])


def build_table(report, d_from, d_to, kind="day", limit=10):
    if report not in REPORT_TYPES:
        raise BusinessError("Chọn loại báo cáo")
    return REPORT_TYPES[report][1](d_from, d_to, kind=kind, limit=limit)


# ----------------------------------------------------------- xem dữ liệu chỉ đọc (CHU4.1)
BROWSE_TYPES = OrderedDict([
    ("invoices", "Hoá đơn"),
    ("sessions", "Phiên bàn (lượt khách)"),
    ("order_items", "Món đã gọi"),
    ("menu", "Thực đơn"),
    ("tables", "Bàn"),
    ("shifts", "Lịch ca"),
])
RANGED = {"invoices", "sessions", "order_items", "shifts"}     # có lọc theo thời gian
PER_PAGE = 50
TABLE_STATUS_VI = {"EMPTY": "Trống", "IN_USE": "Đang dùng", "WAITING_PAYMENT": "Chờ thanh toán"}


def _t(dt):
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def browse(kind, d_from, d_to, page=1):
    """Dữ liệu kinh doanh dạng bảng, CHỈ ĐỌC, phân trang 50 dòng. Lọc theo thời gian của từng loại:
    hoá đơn và phiên bàn theo giờ mở bàn, món đã gọi theo giờ gọi, lịch ca theo ngày làm."""
    if kind not in BROWSE_TYPES:
        kind = "invoices"
    check_range(d_from, d_to)
    start, end = range_bounds(d_from, d_to)
    page = max(1, page)

    if kind == "invoices":
        q = (db.session.query(Invoice, TableSession).select_from(Invoice)
             .join(TableSession, Invoice.session_id == TableSession.id)
             .filter(TableSession.opened_at >= start, TableSession.opened_at < end)
             .order_by(TableSession.opened_at.desc(), Invoice.id.desc()))
        headers = ["Giờ mở bàn", "Bàn", "Gói", "Người lớn", "Trẻ nửa giá", "Tổng tiền", "Hình thức", "Trạng thái", "Giờ thu"]
        fmt = lambda r: [_t(r[1].opened_at), r[1].table.code, r[1].package.name, r[0].adults, r[0].kids_mid,
                         vnd(r[0].total), {"CASH": "Tiền mặt", "TRANSFER": "Chuyển khoản"}.get(r[0].method, ""),
                         "Đã thu" if r[0].status == "PAID" else "Chưa thu", _t(r[0].paid_at)]
    elif kind == "sessions":
        q = (TableSession.query.filter(TableSession.opened_at >= start, TableSession.opened_at < end)
             .order_by(TableSession.opened_at.desc()))
        headers = ["Giờ mở", "Giờ đóng", "Bàn", "Gói", "Giá/người", "Người lớn", "Trẻ nửa giá", "Trẻ miễn phí", "Trạng thái"]
        fmt = lambda s: [_t(s.opened_at), _t(s.closed_at), s.table.code, s.package.name, vnd(session_price(s)),
                         s.adults, s.kids_mid, s.kids_free, "Đang mở" if s.is_open else "Đã đóng"]
    elif kind == "order_items":
        q = (db.session.query(OrderItem, Order).select_from(OrderItem)
             .join(Order, OrderItem.order_id == Order.id)
             .filter(Order.created_at >= start, Order.created_at < end)
             .order_by(Order.created_at.desc(), OrderItem.id.desc()))
        headers = ["Giờ gọi", "Bàn", "Món", "Số lượng", "Ghi chú", "Trạng thái", "Người gọi"]

        def fmt(r):
            item, order = r
            who = db.session.get(User, order.created_by) if order.created_by else None
            return [_t(order.created_at), order.session.table.code, item.menu_item.name, item.quantity,
                    item.note or "", STATUS_VI.get(item.status, item.status), who.full_name if who else "Khách"]
    elif kind == "menu":
        tiers = {p.tier: p.name for p in BuffetPackage.query.all()}
        q = MenuItem.query.order_by(MenuItem.category_id, MenuItem.name)
        headers = ["Món", "Nhóm", "Từ gói", "Tối đa/lần", "Trạng thái"]
        fmt = lambda m: [m.name, m.category.name, tiers.get(m.min_tier, m.min_tier), m.max_qty,
                         "Đang ẩn" if not m.is_active else ("Bếp báo hết" if m.is_sold_out else "Đang bán")]
    elif kind == "tables":
        q = DiningTable.query.order_by(DiningTable.code)
        headers = ["Bàn", "Số chỗ", "Trạng thái", "Khoá"]
        fmt = lambda t: [t.code, t.seats, TABLE_STATUS_VI.get(t.status, t.status), "Đã khoá" if t.is_locked else ""]
    else:  # shifts
        q = (Shift.query.filter(Shift.work_date >= d_from, Shift.work_date <= d_to)
             .order_by(Shift.work_date.desc(), Shift.start_time))
        headers = ["Ngày", "Nhân viên", "Vai trò", "Giờ làm", "Bàn phụ trách"]
        fmt = lambda s: [s.work_date.strftime("%d/%m/%Y"), s.user.full_name, ROLE_VI.get(s.user.role.name, s.user.role.name),
                         f"{s.start_time:%H:%M}–{s.end_time:%H:%M}", ", ".join(t.code for t in s.tables)]

    total = q.count()
    rows = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    return {"kind": kind, "title": BROWSE_TYPES[kind], "headers": headers, "rows": [fmt(r) for r in rows],
            "total": total, "page": page, "pages": max(1, -(-total // PER_PAGE)), "ranged": kind in RANGED}
