"""Cấu hình của Chủ (giờ mở cửa, giá gói, thông tin nhà hàng) và quản trị menu của Quản lý."""
from datetime import time

import pytest

from app import db
from app import services as sv
from app.models import BuffetPackage, Category, MenuItem, OpeningHour
from app.services import BusinessError
from app.utils import package_label, parse_money
from helpers import dish, pkg


# ---------------------------------------------------------------- giờ mở cửa
def hours(weekday):
    return OpeningHour.query.filter_by(weekday=weekday).count()


def test_add_a_frame_between_the_two_shifts():
    sv.add_opening_hours([0, 1], time(14, 0), time(16, 30))        # sát hai khung có sẵn thì không tính là trùng
    assert hours(0) == 3 and hours(1) == 3 and hours(2) == 2


def test_overlapping_or_invalid_frames_are_refused():
    for days, start, end in (([0], time(13, 0), time(15, 0)),      # trùng khung 10:30–14:00
                             ([], time(14, 0), time(15, 0)),       # chưa chọn ngày
                             ([7], time(14, 0), time(15, 0)),      # ngày không hợp lệ
                             ([0], time(16, 0), time(16, 0)),      # giờ đóng không sau giờ mở
                             ([0], time(18, 0), time(9, 0))):
        with pytest.raises(BusinessError):
            sv.add_opening_hours(days, start, end)
    assert hours(0) == 2


def test_adding_to_several_days_is_all_or_nothing():
    for row in OpeningHour.query.filter_by(weekday=6).all():       # Chủ nhật trống
        sv.delete_opening_hours(row.id)
    with pytest.raises(BusinessError):
        sv.add_opening_hours([6, 2], time(12, 0), time(13, 0))     # Thứ 4 đã có khung trùng giờ
    assert hours(6) == 0                                           # Chủ nhật cũng không bị thêm
    sv.add_opening_hours([6], time(12, 0), time(13, 0))
    assert hours(6) == 1


def test_a_day_without_frames_is_closed(clock):
    from datetime import datetime
    for row in OpeningHour.query.filter_by(weekday=2).all():       # Thứ 4
        sv.delete_opening_hours(row.id)
    clock.t = datetime(2026, 11, 11, 12, 0)
    assert sv.is_open_now() is False


# ---------------------------------------------------------------- giá gói
def current_prices():
    return {p.id: p.price for p in BuffetPackage.query.all()}


def test_prices_must_increase_with_package_level():
    base = current_prices()
    cases = {
        "gói cao bằng gói thấp": {**base, pkg(2).id: pkg(1).price},
        "gói cao rẻ hơn gói thấp": {**base, pkg(6).id: pkg(1).price - 1},
        "dưới mức tối thiểu": {**base, pkg(1).id: 500},
        "quá mức tối đa": {**base, pkg(6).id: 99_000_000},
    }
    for label, prices in cases.items():
        with pytest.raises(BusinessError):
            sv.update_package_prices(prices)
    missing = dict(base)
    missing.pop(pkg(3).id)
    with pytest.raises(BusinessError):
        sv.update_package_prices(missing)
    assert current_prices() == base                                # lần lỗi không đổi gì


def test_price_update_renames_default_names_only():
    pkg(6).name = "VIP Đặc biệt"                                   # tên tự đặt
    db.session.commit()
    new = {p.id: p.price + 10000 for p in BuffetPackage.query.all()}
    sv.update_package_prices(new)
    assert pkg(1).name == "Buffet 229K" and pkg(6).name == "VIP Đặc biệt"
    assert pkg(1).price == 229000


def test_money_helpers():
    assert [parse_money(x) for x in ("299.000", "299,000đ", " 299000 ", "1.250.000 đ", "", "abc", "-5000")] == \
        [299000, 299000, 299000, 1250000, None, None, None]
    assert [package_label(p) for p in (219000, 249500, 469000)] == ["Buffet 219K", "Buffet 249.5K", "Buffet 469K"]


# ---------------------------------------------------------------- thông tin nhà hàng
def test_restaurant_info():
    with pytest.raises(BusinessError):
        sv.update_restaurant("   ", "địa chỉ")
    sv.update_restaurant("GYUSACHI Quận 1", "1 Lê Lợi")
    info = sv.get_restaurant()
    assert (info.name, info.address) == ("GYUSACHI Quận 1", "1 Lê Lợi")


# ---------------------------------------------------------------- quản trị menu
def cat(name):
    return Category.query.filter_by(name=name).one()


def test_category_rules():
    new = sv.add_category("Tráng miệng")
    with pytest.raises(BusinessError):
        sv.add_category("Tráng miệng")                             # trùng tên
    with pytest.raises(BusinessError):
        sv.add_category("  ")
    with pytest.raises(BusinessError):
        sv.rename_category(new.id, "Lẩu")                          # trùng nhóm có sẵn
    sv.rename_category(new.id, "Món ngọt")
    with pytest.raises(BusinessError, match="còn món"):
        sv.delete_category(cat("Lẩu").id)                          # nhóm còn món thì không xoá được
    sv.delete_category(new.id)
    assert Category.query.filter_by(name="Món ngọt").count() == 0


def test_dish_rules():
    c = sv.add_category("Tráng miệng")
    d = sv.create_dish("Kem matcha", c.id, "Mát lạnh", None, min_tier=4, max_qty=2)
    assert (d.min_tier, d.max_qty, d.is_active) == (4, 2, True)
    with pytest.raises(BusinessError):
        sv.create_dish("kem matcha", c.id, "", None)               # trùng tên trong cùng nhóm
    for tier, qty in ((9, 2), (1, 0), (1, 100)):
        with pytest.raises(BusinessError):
            sv.create_dish(f"Món {tier}-{qty}", c.id, "", None, min_tier=tier, max_qty=qty)
    sv.set_dish_rules(d.id, 2, 3)
    assert (d.min_tier, d.max_qty) == (2, 3)
    sv.set_all_max_qty(4)
    assert {m.max_qty for m in MenuItem.query.all()} == {4}
    with pytest.raises(BusinessError):
        sv.set_all_max_qty(0)
    sv.update_dish(dish("Trà đá").id, "Trà đá lạnh", cat("Đồ uống").id, "")
    assert dish("Trà đá lạnh").description is None
    with pytest.raises(BusinessError):
        sv.update_dish(dish("Trà đá lạnh").id, "Nước ngọt", cat("Đồ uống").id, "")      # trùng món khác cùng nhóm
