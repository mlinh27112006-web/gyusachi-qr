from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
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
    from .utils import now, vnd, STATUS_VI

    app.jinja_env.filters["vnd"] = vnd
    app.jinja_env.filters["status_vi"] = lambda s: STATUS_VI.get(s, s)
    app.context_processor(lambda: {"now": now})

    from .auth.routes import bp as auth_bp
    from .customer.routes import bp as customer_bp
    from .kitchen.routes import bp as kitchen_bp
    from .waiter.routes import bp as waiter_bp
    from .cashier.routes import bp as cashier_bp
    from .manager.routes import bp as manager_bp

    for bp in (auth_bp, customer_bp, kitchen_bp, waiter_bp, cashier_bp, manager_bp):
        app.register_blueprint(bp)
    # owner (CHU), admin (ADM): thêm blueprint vào đây khi làm tới

    from . import events  # noqa: F401

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    return app
