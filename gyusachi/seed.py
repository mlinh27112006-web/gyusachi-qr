"""Nạp dữ liệu mẫu theo quy tắc đã chốt trong tài liệu phân rã.

Chạy sau khi đã `flask --app run db upgrade`. Chạy lần đầu thì nạp dữ liệu mẫu; chạy lại khi đã có
dữ liệu thì chỉ thêm các quyền mới (sau khi cập nhật bản mới), không ghi đè chỉnh sửa của Admin:
    python seed.py
"""
from datetime import time

from app import create_app, db
from app.models import (
    BuffetPackage, Category, DiningTable, MenuItem, OpeningHour, Permission,
    RestaurantInfo, Role, Setting, User,
)

PERMS = [
    "CAN_OPEN_TABLE", "CAN_ORDER_FOR_TABLE", "CAN_REQUEST_PAYMENT", "CAN_COOK",
    "CAN_CREATE_INVOICE", "CAN_CHECKOUT", "CAN_MANAGE_MENU", "CAN_MANAGE_TABLES",
    "CAN_MANAGE_STAFF", "CAN_VIEW_SHIFT_REPORT", "CAN_VIEW_BUSINESS_REPORT",
    "CAN_CONFIG_BUSINESS", "CAN_MANAGE_ROLES", "CAN_BACKUP", "CAN_VIEW_LOGS",
    "CAN_MANAGE_MANAGERS", "CAN_VIEW_SYSTEM_LOGS", "CAN_CONFIG_SYSTEM",
]

ROLE_PERMS = {
    "PHUC_VU":  ["CAN_OPEN_TABLE", "CAN_ORDER_FOR_TABLE", "CAN_REQUEST_PAYMENT"],
    "BEP":      ["CAN_COOK"],
    "THU_NGAN": ["CAN_CREATE_INVOICE", "CAN_CHECKOUT"],
    "QUAN_LY":  ["CAN_MANAGE_MENU", "CAN_MANAGE_TABLES", "CAN_MANAGE_STAFF",
                 "CAN_VIEW_SHIFT_REPORT", "CAN_CHECKOUT"],
    "CHU":      ["CAN_VIEW_BUSINESS_REPORT", "CAN_CONFIG_BUSINESS", "CAN_MANAGE_STAFF",
                 "CAN_VIEW_LOGS", "CAN_MANAGE_MANAGERS"],
    "ADMIN":    PERMS,
}

# (username, họ tên, vai trò, mật khẩu): ĐỔI mật khẩu khi dùng thật
USERS = [
    ("admin",    "Quản trị hệ thống", "ADMIN",    "admin123"),
    ("phucvu",   "Phục vụ mẫu",       "PHUC_VU",  "123456"),
    ("bep",      "Bếp mẫu",           "BEP",      "123456"),
    ("thungan",  "Thu ngân mẫu",      "THU_NGAN", "123456"),
    ("quanly",   "Quản lý mẫu",       "QUAN_LY",  "123456"),
    ("chu",      "Chủ nhà hàng",      "CHU",      "123456"),
]

# 6 gói buffet; tier càng cao càng đắt, gói cao gọi được cả món của gói thấp
PACKAGES = [219000, 269000, 299000, 349000, 399000, 469000]

# (danh mục, tên món, gói thấp nhất 1..6, tối đa mỗi lần)
MENU = [
    ("Thịt bò",       "Ba chỉ bò Mỹ",            1, 5),
    ("Thịt bò",       "Lõi vai bò",              3, 4),
    ("Thịt bò",       "Lưỡi bò",                 4, 3),
    ("Thịt bò",       "Bò Wagyu A5",             6, 2),
    ("Heo và gà",     "Ba chỉ heo",              1, 5),
    ("Heo và gà",     "Gà nướng sốt teriyaki",   1, 5),
    ("Hải sản",       "Mực nướng",               2, 4),
    ("Hải sản",       "Tôm nướng bơ tỏi",        3, 4),
    ("Lẩu",           "Lẩu kim chi",             1, 2),
    ("Lẩu",           "Lẩu nấm",                 1, 2),
    ("Món phụ",       "Kim chi",                 1, 3),
    ("Món phụ",       "Cơm trắng",               1, 5),
    ("Đồ uống",       "Trà đá",                  1, 5),
    ("Đồ uống",       "Nước ngọt",               1, 5),
]


def top_up_permissions():
    """Database đã có dữ liệu: chỉ thêm các quyền MỚI (chưa có trong bảng) và cấp theo mặc định.

    Quyền đã tồn tại thì không đụng tới, nên các chỉnh sửa của Admin ở màn "Vai trò và quyền"
    không bị ghi đè khi chạy lại seed.py."""
    existing = {p.code: p for p in Permission.query.all()}
    new_codes = [c for c in PERMS if c not in existing]
    added = []
    for code in new_codes:
        existing[code] = Permission(code=code)
        db.session.add(existing[code])
        added.append(f"quyền {code}")
    db.session.flush()
    for role_name, codes in ROLE_PERMS.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            continue
        have = {p.code for p in role.permissions}
        for code in codes:
            if code in new_codes and code not in have:
                role.permissions.append(existing[code])
                added.append(f"{role_name} += {code}")
    db.session.commit()
    return added


def populate():
    """Nạp toàn bộ dữ liệu mẫu (cần đang trong app context và database còn trống). Dùng cả cho kiểm thử."""
    perms = {c: Permission(code=c) for c in PERMS}
    db.session.add_all(perms.values())
    roles = {n: Role(name=n, permissions=[perms[c] for c in cs]) for n, cs in ROLE_PERMS.items()}
    db.session.add_all(roles.values())
    db.session.flush()

    for username, full_name, role, pw in USERS:
        u = User(username=username, full_name=full_name, role_id=roles[role].id)
        u.set_password(pw)
        db.session.add(u)

    db.session.add(RestaurantInfo(name="GYUSACHI", address="(cập nhật địa chỉ)", phone=""))

    for tier, price in enumerate(PACKAGES, start=1):
        db.session.add(BuffetPackage(name=f"Buffet {price // 1000}K", price=price, tier=tier))

    # giờ mở cửa: weekday 0-4 (Thứ 2 đến Thứ 6) hai khung; 5-6 (Thứ 7, CN) một khung
    for d in range(5):
        db.session.add(OpeningHour(weekday=d, open_time=time(10, 30), close_time=time(14, 0)))
        db.session.add(OpeningHour(weekday=d, open_time=time(16, 30), close_time=time(22, 0)))
    for d in (5, 6):
        db.session.add(OpeningHour(weekday=d, open_time=time(10, 30), close_time=time(22, 0)))

    db.session.add_all([
        Setting(key="cancel_minutes", value="5"),            # huỷ món trong 5 phút
        Setting(key="max_login_attempts", value="5"),
        Setting(key="session_timeout_minutes", value="30"),
    ])

    cats = {}
    for cat, name, tier, mx in MENU:
        if cat not in cats:
            cats[cat] = Category(name=cat)
            db.session.add(cats[cat])
            db.session.flush()
        db.session.add(MenuItem(category_id=cats[cat].id, name=name, min_tier=tier, max_qty=mx))

    db.session.add_all([DiningTable(code=f"B{i:02d}") for i in range(1, 11)])
    db.session.commit()


def main():
    app = create_app()
    with app.app_context():
        if Role.query.first():
            added = top_up_permissions()
            print("Đã có dữ liệu nên không nạp lại. (Muốn nạp lại từ đầu: xoá database rồi migrate lại.)")
            print("Đã thêm quyền mới:" if added else "Không có quyền mới nào cần thêm.")
            for line in added:
                print("  +", line)
            return

        populate()
        print("Đã nạp dữ liệu mẫu.")
        print("Tài khoản mẫu:", ", ".join(f"{u}/{p}" for u, _, _, p in USERS))
        print("Nhớ đổi mật khẩu trước khi đưa vào dùng thật.")


if __name__ == "__main__":
    main()
