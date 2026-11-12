import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-doi-chuoi-nay")
    BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024      # ảnh món tối đa 5 MB
    BACKUP_DIR = os.getenv("BACKUP_DIR") or os.path.join(BASE_DIR, "backups")
    PG_BIN_DIR = os.getenv("PG_BIN_DIR", "")   # thư mục chứa pg_dump và psql (nếu chưa có trong PATH)
