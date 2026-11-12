"""Danh mục quyền (permission) và vai trò hệ thống, dùng cho màn Admin (ADM1)."""

PERM_VI = {
    "CAN_OPEN_TABLE": "Mở bàn, sửa số khách, đổi bàn",
    "CAN_ORDER_FOR_TABLE": "Gọi món hộ khách",
    "CAN_REQUEST_PAYMENT": "Yêu cầu thanh toán",
    "CAN_COOK": "Xem và xử lý đơn ở bếp, báo hết món",
    "CAN_CREATE_INVOICE": "Lập hoá đơn",
    "CAN_CHECKOUT": "Xác nhận thu tiền và checkout",
    "CAN_MANAGE_MENU": "Quản lý menu",
    "CAN_MANAGE_TABLES": "Quản lý bàn và mã QR",
    "CAN_MANAGE_STAFF": "Quản lý nhân sự và phân ca",
    "CAN_VIEW_SHIFT_REPORT": "Xem tổng quan ca và báo cáo ca",
    "CAN_VIEW_BUSINESS_REPORT": "Xem báo cáo và dữ liệu kinh doanh (Chủ)",
    "CAN_CONFIG_BUSINESS": "Cấu hình nhà hàng: giờ mở cửa, giá gói (Chủ)",
    "CAN_MANAGE_MANAGERS": "Quản lý tài khoản Quản lý (Chủ)",
    "CAN_VIEW_LOGS": "Xem nhật ký thao tác của Quản lý (Chủ)",
    "CAN_MANAGE_ROLES": "Quản lý vai trò, quyền, tài khoản (Admin)",
    "CAN_BACKUP": "Sao lưu, phục hồi, dọn dẹp dữ liệu (Admin)",
    "CAN_VIEW_SYSTEM_LOGS": "Xem nhật ký hệ thống: thao tác, lỗi, đăng nhập (Admin)",
    "CAN_CONFIG_SYSTEM": "Cấu hình kỹ thuật: máy in, tham số hệ thống (Admin)",
}

# Vai trò mà mã nguồn dựa vào tên để hoạt động: không đổi tên, không xoá.
SYSTEM_ROLES = ("PHUC_VU", "BEP", "THU_NGAN", "QUAN_LY", "CHU", "ADMIN")

# Vai trò tự tạo không có màn hình riêng: sau đăng nhập đưa vào màn đầu tiên mà quyền của vai trò cho phép.
HOME_BY_PERM = [
    ("CAN_MANAGE_ROLES", "admin.users"),
    ("CAN_VIEW_BUSINESS_REPORT", "owner.report"),
    ("CAN_VIEW_SHIFT_REPORT", "manager.overview"),
    ("CAN_OPEN_TABLE", "waiter.tables"),
    ("CAN_COOK", "kitchen.board"),
    ("CAN_CREATE_INVOICE", "cashier.pending"),
    ("CAN_MANAGE_MENU", "manager.menu"),
    ("CAN_MANAGE_TABLES", "manager.tables"),
]
