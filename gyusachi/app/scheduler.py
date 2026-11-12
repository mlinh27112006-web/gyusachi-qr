"""Bộ lập lịch rất đơn giản: mỗi phút kiểm tra xem đã đến giờ sao lưu định kỳ chưa (ADM2.1)."""
import threading
import time


def start_scheduler(app, interval=60):
    def loop():
        while True:
            time.sleep(interval)
            try:
                with app.app_context():
                    from .admin_service import run_scheduled_backup_if_due
                    run_scheduled_backup_if_due()
            except Exception:           # bộ lập lịch không bao giờ được làm sập ứng dụng
                pass

    thread = threading.Thread(target=loop, daemon=True, name="gyusachi-scheduler")
    thread.start()
    return thread
