import time
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..audit import log_audit, log_error, log_login
from ..models import User
from ..perms import HOME_BY_PERM
from ..services import BusinessError, change_password, get_setting
from ..utils import now

bp = Blueprint("auth", __name__)

# Vai trò hệ thống vào màn nào sau khi đăng nhập. Vai trò tự tạo thì lấy màn đầu tiên mà quyền cho phép.
HOME_BY_ROLE = {
    "PHUC_VU": "waiter.tables",
    "BEP": "kitchen.board",
    "THU_NGAN": "cashier.pending",
    "QUAN_LY": "manager.overview",
    "CHU": "owner.report",
    "ADMIN": "admin.users",
}


def _home_for(user):
    endpoint = HOME_BY_ROLE.get(user.role.name)
    if not endpoint:
        endpoint = next((ep for perm, ep in HOME_BY_PERM if user.has_perm(perm)), None)
    return url_for(endpoint or "auth.coming_soon")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and request.method == "GET":
        return redirect(_home_for(current_user))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = User.query.filter_by(username=username).first()

        if user and (user.is_locked or (user.locked_until and user.locked_until > now())):
            log_login(username, "LOGIN_FAIL", success=False)
            flash("Tài khoản đang bị khoá. Hãy thử lại sau hoặc liên hệ quản lý.")
        elif user and user.check_password(request.form.get("password", "")):
            user.failed_attempts = 0
            db.session.commit()
            login_user(user)
            session["last_seen"] = time.time()
            log_login(username, "LOGIN")
            return redirect(_home_for(user))
        else:
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                limit = int(get_setting("max_login_attempts", 5))
                if user.failed_attempts >= limit:
                    user.locked_until = now() + timedelta(minutes=15)       # XT1.1.2
                    user.failed_attempts = 0
                    log_error("WARNING", f"Tài khoản {username} bị khoá tạm 15 phút do nhập sai mật khẩu {limit} lần")
                db.session.commit()
            log_login(username, "LOGIN_FAIL", success=False)
            flash("Sai tên đăng nhập hoặc mật khẩu")
    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    log_login(current_user.username, "LOGOUT")
    logout_user()
    session.pop("last_seen", None)
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])                    # XT1.3
@login_required
def password():
    if request.method == "POST":
        f = request.form
        try:
            change_password(current_user, f.get("old", ""), f.get("new", ""), f.get("repeat", ""))
        except BusinessError as e:
            flash(str(e))
        else:
            log_audit(current_user.id, "PASSWORD_CHANGE", "")
            flash("Đã đổi mật khẩu")
            return redirect(_home_for(current_user))
    return render_template("auth/password.html")


@bp.route("/coming-soon")
@login_required
def coming_soon():
    return render_template("auth/coming_soon.html")
