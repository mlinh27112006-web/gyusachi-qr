from datetime import datetime
from zoneinfo import ZoneInfo

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def now():
    """Giờ Việt Nam (không kèm tzinfo) để lưu vào DB và so sánh."""
    return datetime.now(VN).replace(tzinfo=None)


def vnd(n):
    """1234567 -> 1.234.567đ"""
    return f"{int(n or 0):,}".replace(",", ".") + "đ"


STATUS_VI = {
    "PENDING": "Đã gửi bếp",
    "COOKING": "Đang chế biến",
    "READY": "Sẵn sàng",
    "CANCELLED": "Đã huỷ",
}
