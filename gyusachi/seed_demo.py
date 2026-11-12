"""Tạo dữ liệu DEMO để các màn Báo cáo, Tổng quan, So sánh, Lịch ca và Nhật ký có số liệu để xem.

Chạy sau `python seed.py`:
    python seed_demo.py

Sinh khoảng 14 ngày hoá đơn đã thu, kèm đơn gọi món (có vài món bị huỷ) trong các khung giờ
mở cửa. Chỉ dùng để thử/trình bày; KHÔNG chạy trên dữ liệu thật. Chạy lại sẽ bị bỏ qua
nếu đã có hoá đơn.
"""
import random
from datetime import datetime, time, timedelta

from app import create_app, db
from app.models import (
    AuditLog, BuffetPackage, DiningTable, ErrorLog, Invoice, LoginLog, MenuItem, OpeningHour, Order,
    OrderItem, Shift, TableSession, User,
)
from app.services import calc_total
from app.utils import now

DAYS = 14
random.seed(2026)


def main():
    app = create_app()
    with app.app_context():
        if Invoice.query.first():
            print("Đã có hoá đơn, bỏ qua. (Dữ liệu demo chỉ nạp được khi chưa có hoá đơn.)")
            return
        waiter = User.query.filter_by(username="phucvu").first()
        cashier = User.query.filter_by(username="thungan").first()
        tables = DiningTable.query.all()
        packages = BuffetPackage.query.order_by(BuffetPackage.tier).all()
        items = MenuItem.query.all()
        if not (waiter and cashier and tables and packages and items):
            print("Chưa có dữ liệu gốc. Hãy chạy `python seed.py` trước.")
            return

        # gói rẻ bán nhiều hơn gói đắt
        weights = [30, 25, 20, 12, 8, 5][: len(packages)]
        current = now()
        n_sessions = 0

        for back in range(DAYS - 1, -1, -1):
            day = (current - timedelta(days=back)).date()
            frames = (OpeningHour.query.filter_by(weekday=day.weekday())
                      .order_by(OpeningHour.open_time).all())
            for fr in frames:
                open_dt = datetime.combine(day, fr.open_time)
                close_dt = datetime.combine(day, fr.close_time)
                span = max(int((close_dt - open_dt).total_seconds() // 60) - 90, 30)
                for _ in range(random.randint(3, 8)):
                    opened = open_dt + timedelta(minutes=random.randint(0, span))
                    paid = opened + timedelta(minutes=random.randint(60, 110))
                    if paid > current:                    # không tạo hoá đơn ở tương lai
                        continue
                    pkg = random.choices(packages, weights=weights)[0]
                    adults = random.randint(1, 5)
                    kids_mid = random.choice([0, 0, 0, 1, 2])
                    kids_free = random.choice([0, 0, 0, 1])

                    sess = TableSession(
                        table_id=random.choice(tables).id, package_id=pkg.id, package_price=pkg.price, adults=adults,
                        kids_mid=kids_mid, kids_free=kids_free, opened_by=waiter.id,
                        opened_at=opened, closed_at=paid, is_open=False,
                    )
                    db.session.add(sess)
                    db.session.flush()

                    allowed = [i for i in items if i.min_tier <= pkg.tier]
                    for k in range(random.randint(1, 3)):
                        order = Order(session_id=sess.id,
                                      created_at=opened + timedelta(minutes=5 + 20 * k))
                        for it in random.sample(allowed, min(len(allowed), random.randint(2, 5))):
                            order.items.append(OrderItem(
                                menu_item_id=it.id,
                                quantity=random.randint(1, it.max_qty),
                                status="CANCELLED" if random.random() < 0.06 else "READY",
                            ))
                        db.session.add(order)

                    db.session.add(Invoice(
                        session_id=sess.id, package_price=pkg.price, adults=adults, kids_mid=kids_mid,
                        total=calc_total(pkg.price, adults, kids_mid), status="PAID",
                        method=random.choice(["CASH", "TRANSFER"]), paid_at=paid, cashier_id=cashier.id,
                    ))
                    n_sessions += 1

        # lịch ca mẫu cho 4 ngày tới: Phục vụ mẫu phụ trách nửa số bàn mỗi ca, Bếp và Thu ngân đủ ca
        by_code = sorted(tables, key=lambda t: t.code)
        half = len(by_code) // 2
        bep = User.query.filter_by(username="bep").first()
        for ahead in range(0, 4):
            day = (current + timedelta(days=ahead)).date()
            for start, end, group in ((time(10, 30), time(14, 0), by_code[:half]),
                                      (time(16, 30), time(22, 0), by_code[half:])):
                db.session.add(Shift(user_id=waiter.id, work_date=day, start_time=start, end_time=end, tables=group))
                db.session.add(Shift(user_id=cashier.id, work_date=day, start_time=start, end_time=end))
                if bep:
                    db.session.add(Shift(user_id=bep.id, work_date=day, start_time=start, end_time=end))

        # nhật ký mẫu 7 ngày gần nhất để các màn nhật ký (Chủ, Admin) có dữ liệu
        manager = User.query.filter_by(username="quanly").first()
        admin = User.query.filter_by(username="admin").first()
        names = [(manager, "MENU_DISH_ADD", "Kem matcha"), (manager, "MENU_DISH_RULES", "Bò Wagyu A5"),
                 (manager, "STAFF_ADD", "Đã tạo tài khoản phucvu2"), (manager, "SHIFT_ADD", "Đã xếp ca"),
                 (manager, "MENU_DISH_TOGGLE", "Đã ẩn món khỏi menu"), (admin, "BACKUP_RUN", "gyusachi-demo.sql")]
        for back in range(7):
            base = current - timedelta(days=back)
            for k, (who, action, detail) in enumerate(names):
                if who:
                    db.session.add(AuditLog(user_id=who.id, action=action, detail=detail,
                                            created_at=base.replace(hour=9 + k, minute=random.randint(0, 59))))
            for uname in ("phucvu", "bep", "thungan", "quanly"):
                t = base.replace(hour=9, minute=random.randint(0, 40))
                db.session.add(LoginLog(username=uname, success=True, event="LOGIN", created_at=t))
                db.session.add(LoginLog(username=uname, success=True, event="LOGOUT", created_at=t + timedelta(hours=7)))
            db.session.add(LoginLog(username="phucvu", success=False, event="LOGIN_FAIL",
                                    created_at=base.replace(hour=8, minute=55)))
        db.session.add(ErrorLog(level="WARNING", message="Tài khoản phucvu bị khoá tạm 15 phút do nhập sai mật khẩu 5 lần",
                                created_at=current - timedelta(days=1, hours=2)))
        db.session.add(ErrorLog(level="ERROR", message="OperationalError: connection to server was lost", path="/kitchen/",
                                created_at=current - timedelta(days=2, hours=1)))
        db.session.add(ErrorLog(level="INFO", message="Sao lưu tự động thành công: gyusachi-demo.sql",
                                created_at=current - timedelta(hours=8)))
        db.session.commit()
        print(f"Đã tạo {n_sessions} phiên bàn đã thu tiền trong {DAYS} ngày gần đây (dữ liệu demo).")


if __name__ == "__main__":
    main()
