from datetime import datetime
from zoneinfo import ZoneInfo

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def now():
    """Giờ Việt Nam (không kèm tzinfo) để lưu vào DB và so sánh."""
    return datetime.now(VN).replace(tzinfo=None)


def vnd(n):
    """1234567 -> 1.234.567đ"""
    return f"{int(n or 0):,}".replace(",", ".") + "đ"


def num(n):
    """1234567 -> 1.234.567"""
    return f"{int(n or 0):,}".replace(",", ".")


def parse_money(text):
    """'299.000', '299,000đ', ' 299000 ' -> 299000; rỗng hoặc có dấu trừ -> None."""
    text = (text or "").strip()
    if not text or "-" in text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def package_label(price):
    """219000 -> 'Buffet 219K'; 249500 -> 'Buffet 249.5K'."""
    k = price / 1000
    return f"Buffet {int(k)}K" if price % 1000 == 0 else f"Buffet {k:g}K"


STATUS_VI = {
    "PENDING": "Đã gửi bếp",
    "COOKING": "Đang chế biến",
    "READY": "Sẵn sàng",
    "CANCELLED": "Đã huỷ",
}
