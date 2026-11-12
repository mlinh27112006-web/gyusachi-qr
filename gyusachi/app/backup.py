"""Sao lưu và phục hồi PostgreSQL bằng pg_dump và psql (ADM2.1, ADM2.2).

Module thuần Python (không phụ thuộc Flask) để dễ kiểm thử. Mật khẩu database truyền qua biến môi
trường PGPASSWORD, không bao giờ xuất hiện trong dòng lệnh hay thông báo lỗi.
"""
import os
import re
import shutil
import subprocess
from datetime import datetime
from urllib.parse import unquote, urlparse

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.sql$")
PREFIX_AUTO = "gyusachi"            # bản sao lưu thường (thủ công hoặc định kỳ)
PREFIX_SAFETY = ("pre-restore", "pre-cleanup")   # bản an toàn tự tạo trước thao tác nguy hiểm


class BackupError(Exception):
    pass


def parse_db_url(url):
    if not url:
        raise BackupError("Chưa cấu hình DATABASE_URL")
    u = urlparse(url)
    if not u.path or u.path == "/":
        raise BackupError("DATABASE_URL thiếu tên database")
    return {"user": unquote(u.username or ""), "password": unquote(u.password or ""),
            "host": u.hostname or "localhost", "port": u.port or 5432, "dbname": u.path.lstrip("/")}


def find_tool(name, bin_dir=None):
    if bin_dir:
        path = os.path.join(bin_dir, name + (".exe" if os.name == "nt" else ""))
        if os.path.exists(path):
            return path
    found = shutil.which(name)
    if found:
        return found
    raise BackupError(f"Không tìm thấy {name}. Hãy cài PostgreSQL (kèm công cụ dòng lệnh) và đặt "
                      f"PG_BIN_DIR trong file .env trỏ tới thư mục bin của PostgreSQL.")


def _run(cmd, password):
    env = dict(os.environ, PGPASSWORD=password)
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise BackupError("Quá thời gian chờ (10 phút)")


def _clip(text):
    text = (text or "").strip()
    return text[-400:] if text else "không có thông báo lỗi"


def run_backup(db_url, backup_dir, bin_dir=None, prefix=PREFIX_AUTO, when=None):
    """Tạo file .sql đầy đủ (có lệnh xoá và tạo lại bảng). Trả về tên file."""
    c = parse_db_url(db_url)
    tool = find_tool("pg_dump", bin_dir)
    os.makedirs(backup_dir, exist_ok=True)
    name = f"{prefix}-{(when or datetime.now()):%Y%m%d-%H%M%S}.sql"
    path = os.path.join(backup_dir, name)
    cmd = [tool, "-h", c["host"], "-p", str(c["port"]), "-U", c["user"],
           "--no-owner", "--no-privileges", "--clean", "--if-exists", "-f", path, c["dbname"]]
    proc = _run(cmd, c["password"])
    if proc.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
        if os.path.exists(path):
            os.remove(path)
        raise BackupError("pg_dump thất bại: " + _clip(proc.stderr))
    return name


def safe_path(backup_dir, filename):
    """Chỉ chấp nhận tên file .sql đơn giản nằm trong thư mục sao lưu (chặn ../ và đường dẫn lạ)."""
    if not NAME_RE.fullmatch(filename or ""):
        raise BackupError("Tên bản sao lưu không hợp lệ")
    path = os.path.join(backup_dir, filename)
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(backup_dir) or not os.path.isfile(path):
        raise BackupError("Không tìm thấy bản sao lưu")
    return path


def restore_backup(db_url, backup_dir, filename, bin_dir=None):
    """Phục hồi trong MỘT giao dịch: lỗi giữa chừng thì database giữ nguyên như cũ."""
    path = safe_path(backup_dir, filename)
    c = parse_db_url(db_url)
    tool = find_tool("psql", bin_dir)
    cmd = [tool, "-h", c["host"], "-p", str(c["port"]), "-U", c["user"], "-d", c["dbname"],
           "-v", "ON_ERROR_STOP=1", "-1", "-q", "-f", path]
    proc = _run(cmd, c["password"])
    if proc.returncode != 0:
        raise BackupError("Phục hồi thất bại, dữ liệu hiện tại được giữ nguyên: " + _clip(proc.stderr))


def kind_of(name):
    if name.startswith(PREFIX_SAFETY):
        return "Bản an toàn (tự tạo)"
    return "Bản sao lưu"


def list_backups(backup_dir):
    if not os.path.isdir(backup_dir):
        return []
    out = []
    for name in os.listdir(backup_dir):
        full = os.path.join(backup_dir, name)
        if NAME_RE.fullmatch(name) and os.path.isfile(full):
            st = os.stat(full)
            out.append({"name": name, "size": st.st_size, "time": datetime.fromtimestamp(st.st_mtime),
                        "kind": kind_of(name)})
    return sorted(out, key=lambda b: b["time"], reverse=True)


def prune_backups(backup_dir, keep):
    """Giữ `keep` bản sao lưu thường mới nhất (không động tới bản an toàn). Trả về số file đã xoá."""
    regular = [b for b in list_backups(backup_dir) if b["name"].startswith(PREFIX_AUTO + "-")]
    removed = 0
    for b in regular[max(keep, 1):]:
        os.remove(os.path.join(backup_dir, b["name"]))
        removed += 1
    return removed


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
