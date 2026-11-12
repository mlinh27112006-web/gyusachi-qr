from functools import wraps

from flask import abort, current_app
from flask_login import current_user


def perm_required(code):
    """Chỉ cho vào khi đã đăng nhập và vai trò có quyền `code`."""

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not current_user.has_perm(code):
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return deco
