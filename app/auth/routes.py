from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..models import LoginLog, User
from ..services import get_setting
from ..utils import now

bp = Blueprint("auth", __name__)

# Vai trò nào vào màn nào sau khi đăng nhập. Chưa có màn thì rơi về auth.coming_soon.
HOME_BY_ROLE = {
    "PHUC_VU": "waiter.tables",
    "BEP": "kitchen.board",
    "THU_NGAN": "cashier.pending",
    "QUAN_LY": "manager.tables",
    "ADMIN": "manager.tables",
}


def _home_for(user):
    return url_for(HOME_BY_ROLE.get(user.role.name, "auth.coming_soon"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and request.method == "GET":
        return redirect(_home_for(current_user))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = User.query.filter_by(username=username).first()

        if user and (user.is_locked or (user.locked_until and user.locked_until > now())):
            flash("Tài khoản đang bị khoá. Hãy thử lại sau hoặc liên hệ quản lý.")
        elif user and user.check_password(request.form.get("password", "")):
            user.failed_attempts = 0
            db.session.add(LoginLog(username=username, success=True))
            db.session.commit()
            login_user(user)
            return redirect(_home_for(user))
        else:
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= int(get_setting("max_login_attempts", 5)):
                    user.locked_until = now() + timedelta(minutes=15)   # XT1.1.2
                    user.failed_attempts = 0
            db.session.add(LoginLog(username=username, success=False))
            db.session.commit()
            flash("Sai tên đăng nhập hoặc mật khẩu")
    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/coming-soon")
@login_required
def coming_soon():
    return render_template("auth/coming_soon.html")
