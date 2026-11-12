"""Báo cáo: doanh thu chỉ tính hoá đơn đã thu, chia ca, số đơn không tính món huỷ, so sánh."""
from datetime import date, datetime

import pytest

from app import reports
from app import services as sv
from app.models import OpeningHour
from app.services import BusinessError
from helpers import add_order, open_table, pay, paid_session, place

D = date(2026, 11, 11)


def at(h, m=0, day=11):
    return datetime(2026, 11, day, h, m)


def test_revenue_counts_only_paid_invoices_in_range():
    paid_session(at(11), at(12), tier=1, adults=2, code="B01")                                  # 438.000
    paid_session(at(17), at(18), tier=3, adults=2, kids_mid=1, code="B02")                      # 747.500
    paid_session(at(13), at(14), tier=1, adults=1, code="B03", status="UNPAID")                 # chưa thu: không tính
    paid_session(at(12, day=10), at(13, day=10), tier=1, adults=5, code="B04")                  # hôm trước
    assert reports.revenue_totals(*reports.day_bounds(D)) == {"invoices": 2, "revenue": 1185500, "guests": 5}


def test_shift_boundaries_split_the_day_exactly():
    s1, e1, l1 = reports.shift_bounds(D, "1")
    s2, e2, l2 = reports.shift_bounds(D, "2")
    assert (s1, e1) == (at(0), at(16, 30)) and (s2, e2) == (at(16, 30), datetime(2026, 11, 12))
    assert l1 == "Ca 1 (10:30–14:00)" and l2 == "Ca 2 (16:30–22:00)"
    assert reports.shift_bounds(D, "all")[:2] == (at(0), datetime(2026, 11, 12))
    for bad in ("3", "abc"):
        with pytest.raises(BusinessError):
            reports.shift_bounds(D, bad)


def test_single_shift_weekend():
    sat = date(2026, 11, 14)                           # Thứ 7 chỉ có một khung giờ
    assert reports.shift_bounds(sat, "1")[:2] == (datetime(2026, 11, 14), datetime(2026, 11, 15))
    with pytest.raises(BusinessError):
        reports.shift_bounds(sat, "2")


def test_every_invoice_falls_in_exactly_one_shift():
    paid_session(at(13), at(14, 30), code="B01")       # thu sau giờ đóng ca trưa nhưng trước ca tối: ca 1
    paid_session(at(21), at(22, 40), code="B02")       # thu sau giờ đóng cửa: vẫn thuộc ca 2
    day = reports.revenue_totals(*reports.day_bounds(D))["revenue"]
    ca1 = reports.revenue_totals(*reports.shift_bounds(D, "1")[:2])["revenue"]
    ca2 = reports.revenue_totals(*reports.shift_bounds(D, "2")[:2])["revenue"]
    assert ca1 == ca2 == 438000 and ca1 + ca2 == day


@pytest.mark.parametrize("when, expected", [(at(3), "1"), (at(12), "1"), (at(15), "1"), (at(17), "2"), (at(23), "2")])
def test_current_shift(when, expected):
    assert reports.current_shift(when) == expected


def test_current_shift_on_a_closed_day():
    OpeningHour.query.filter_by(weekday=6).delete()    # xoá khung giờ Chủ nhật
    from app import db
    db.session.commit()
    assert reports.current_shift(datetime(2026, 11, 15, 12, 0)) == "all"


def test_order_stats_ignore_cancelled_items_and_orders():
    sess = paid_session(at(11), at(13))
    add_order(sess, at(12), ("Trà đá", 2, "READY"), ("Kim chi", 1, "CANCELLED"))
    add_order(sess, at(12, 30), ("Trà đá", 1, "CANCELLED"))                 # huỷ toàn bộ: không tính là một đơn
    add_order(sess, at(12, day=10), ("Trà đá", 9, "READY"))                 # ngoài khoảng
    assert reports.order_stats(*reports.day_bounds(D)) == {"orders": 1, "dishes": 2}


def test_top_items_rank_and_exclude_cancelled():
    sess = paid_session(at(11), at(13))
    add_order(sess, at(12), ("Trà đá", 5, "READY"), ("Kim chi", 2, "READY"), ("Ba chỉ heo", 9, "CANCELLED"))
    add_order(sess, at(12, 30), ("Kim chi", 4, "READY"))
    rows = reports.top_items(*reports.day_bounds(D), limit=2)
    assert [(r["rank"], r["name"], r["qty"]) for r in rows] == [(1, "Kim chi", 6), (2, "Trà đá", 5)]


def test_by_package_lists_all_six_packages():
    paid_session(at(11), at(12), tier=1, adults=2, code="B01")                       # 438.000
    paid_session(at(12), at(13), tier=1, adults=1, kids_mid=2, code="B02")           # 438.000
    paid_session(at(17), at(18), tier=6, adults=1, code="B03")                       # 469.000
    rows = reports.by_package(*reports.day_bounds(D))
    assert len(rows) == 6
    assert (rows[0]["tables"], rows[0]["guests"], rows[0]["revenue"]) == (2, 5, 876000)
    assert (rows[5]["tables"], rows[5]["guests"], rows[5]["revenue"]) == (1, 1, 469000)
    assert all(r["revenue"] == 0 for r in rows[1:5])


def test_revenue_by_day_fills_empty_days():
    paid_session(at(12, day=9), at(13, day=9), adults=2, code="B01")
    paid_session(at(12), at(13), adults=1, code="B02")
    rows = reports.revenue_by_period(date(2026, 11, 9), D, "day")
    assert [r["label"] for r in rows] == ["09/11/2026", "10/11/2026", "11/11/2026"]
    assert [r["revenue"] for r in rows] == [438000, 0, 219000]


def test_revenue_by_week_month_year():
    paid_session(datetime(2026, 11, 4, 12), datetime(2026, 11, 4, 13), code="B01")
    paid_session(datetime(2026, 11, 12, 12), datetime(2026, 11, 12, 13), code="B02")
    weeks = reports.revenue_by_period(date(2026, 11, 2), date(2026, 11, 15), "week")
    assert len(weeks) == 2 and [w["revenue"] for w in weeks] == [438000, 438000]
    assert weeks[0]["label"].startswith("Tuần ") and "(02/11–08/11)" in weeks[0]["label"]
    months = reports.revenue_by_period(date(2026, 10, 30), date(2026, 11, 2), "month")
    assert [m["label"] for m in months] == ["Tháng 10/2026", "Tháng 11/2026"]
    years = reports.revenue_by_period(date(2025, 12, 31), date(2026, 1, 1), "year")
    assert [y["label"] for y in years] == ["Năm 2025", "Năm 2026"]
    assert reports.revenue_by_period(D, D, "ngu ngốc")[0]["label"] == "11/11/2026"     # loại kỳ lạ → theo ngày


def test_report_range_validation():
    with pytest.raises(BusinessError):
        reports.revenue_by_period(date(2026, 11, 12), date(2026, 11, 1))
    with pytest.raises(BusinessError):
        reports.revenue_by_period(date(2010, 1, 1), date(2026, 1, 1))                   # quá 10 năm


def test_compare_two_periods():
    paid_session(at(12, day=10), at(13, day=10), adults=2, code="B01")                  # hôm trước: 438.000
    paid_session(at(11), at(12), adults=2, code="B01")
    paid_session(at(12), at(13), adults=1, code="B02")                                  # hôm nay: 657.000, 3 khách
    a = reports.period_summary(date(2026, 11, 10), date(2026, 11, 10))
    b = reports.period_summary(D, D)
    rows = {r["key"]: r for r in reports.compare_rows(a, b)}
    assert rows["revenue"]["diff"] == 219000 and rows["revenue"]["pct"] == 50.0
    assert rows["guests"]["a"] == 2 and rows["guests"]["b"] == 3
    empty = reports.period_summary(date(2026, 11, 1), date(2026, 11, 1))
    assert reports.compare_rows(empty, b)[0]["pct"] is None                             # A bằng 0: không chia cho 0
    assert empty["per_guest"] == 0


def test_period_summary_for_a_single_shift():
    paid_session(at(11), at(12), adults=2, code="B01")                                  # ca 1
    paid_session(at(17), at(18), adults=1, code="B02")                                  # ca 2
    one = reports.period_summary(D, D, "2")
    assert one["revenue"] == 219000 and "Ca 2" in one["label"]
    two_days = reports.period_summary(D, date(2026, 11, 12), "2")                       # nhiều ngày: bỏ qua ca
    assert two_days["revenue"] == 657000


def test_overview_snapshot():
    s1 = open_table("B01", tier=1, adults=2)
    s2 = open_table("B02", tier=3, adults=2, kids_mid=1, kids_free=1)
    o1 = place(s1, ("Ba chỉ bò Mỹ", 2), ("Trà đá", 1))
    sv.set_item_status(o1.items[0].id, "COOKING")
    sv.request_payment(s2)
    s3 = open_table("B03", tier=1, adults=2)
    pay(s3)                                              # đã thu 438.000 nhưng chưa checkout

    o = reports.overview(datetime(2026, 11, 11, 12, 30))
    assert o["shift_label"].startswith("Ca 1") and o["tables_total"] == 10
    assert o["tables"] == {"EMPTY": 7, "IN_USE": 1, "WAITING_PAYMENT": 2}
    assert o["guests_in_house"] == 2 + 4 + 2
    assert o["expected"] == 438000 + 747500 + 438000
    assert (o["pending"], o["cooking"]) == (1, 1)
    assert o["totals"]["revenue"] == 438000 and o["totals"]["orders"] == 1 and o["totals"]["dishes"] == 3
    assert [s.id for s in o["stuck"]] == [s3.id]         # bàn đã thu tiền mà chưa checkout
    assert {h["label"]: h["revenue"] for h in o["hourly"]}["12h"] == 438000
