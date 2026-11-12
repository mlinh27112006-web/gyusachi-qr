import time

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, logout_user
from flask_socketio import SocketIO

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
socketio = SocketIO()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Vui lòng đăng nhập để tiếp tục"
    socketio.init_app(app, async_mode="threading")

    from . import models  # noqa: F401  (đăng ký bảng cho migrate)
    from .utils import now, num, vnd, STATUS_VI

    app.jinja_env.filters["vnd"] = vnd
    app.jinja_env.filters["num"] = num
    app.jinja_env.filters["status_vi"] = lambda s: STATUS_VI.get(s, s)
    app.context_processor(lambda: {"now": now})

    @app.context_processor
    def inject_restaurant():
        from types import SimpleNamespace
        try:
            info = models.RestaurantInfo.query.first()
        except Exception:                       # chưa có bảng (chưa migrate): dùng tên mặc định
            db.session.rollback()
            info = None
        return {"restaurant": info or SimpleNamespace(name="GYUSACHI", address="", phone="")}

    from .auth.routes import bp as auth_bp
    from .customer.routes import bp as customer_bp
    from .kitchen.routes import bp as kitchen_bp
    from .waiter.routes import bp as waiter_bp
    from .cashier.routes import bp as cashier_bp
    from .manager.routes import bp as manager_bp
    from .owner.routes import bp as owner_bp
    from .admin.routes import bp as admin_bp

    for bp in (auth_bp, customer_bp, kitchen_bp, waiter_bp, cashier_bp, manager_bp, owner_bp, admin_bp):
        app.register_blueprint(bp)

    from . import events  # noqa: F401

    @app.before_request
    def enforce_session_timeout():                       # XT1.4: tự đăng xuất khi hết phiên (không thao tác)
        if request.endpoint in (None, "static") or not current_user.is_authenticated:
            return None
        from .audit import log_login
        from .services import get_setting
        try:
            limit = int(get_setting("session_timeout_minutes", 30)) * 60
        except ValueError:
            limit = 30 * 60
        last, t = session.get("last_seen"), time.time()
        if last is not None and t - last > limit:
            username = current_user.username
            logout_user()
            session.pop("last_seen", None)
            log_login(username, "TIMEOUT")
            flash("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại")
            return redirect(url_for("auth.login"))
        session["last_seen"] = t
        return None

    @app.errorhandler(500)
    def server_error(e):                                 # ADM3.2: ghi lỗi hệ thống vào nhật ký lỗi
        from .audit import log_error
        db.session.rollback()
        original = getattr(e, "original_exception", None) or e
        try:
            uid = current_user.id if current_user.is_authenticated else None
        except Exception:
            uid = None
        log_error("ERROR", f"{type(original).__name__}: {original}", path=request.path, user_id=uid)
        return render_template("error.html"), 500

    @app.cli.command("backup")
    def backup_command():
        """Sao lưu database ngay (dùng với Task Scheduler hoặc cron): flask --app run backup"""
        from .admin_service import run_backup_now
        try:
            print("Đã sao lưu:", run_backup_now())
        except Exception as e:
            print("Lỗi:", e)
            raise SystemExit(1)

    @app.errorhandler(413)
    def too_large(_e):
        return "Ảnh quá lớn (tối đa 5 MB). Quay lại và chọn ảnh nhỏ hơn.", 413

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    return app
