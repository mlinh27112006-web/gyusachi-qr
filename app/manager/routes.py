import io

import qrcode
from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for,
)

from .. import db
from ..models import DiningTable
from ..permissions import perm_required

bp = Blueprint("manager", __name__, url_prefix="/manager")


@bp.route("/tables")                                   # QLTT3: danh sách bàn + QR
@perm_required("CAN_MANAGE_TABLES")
def tables():
    return render_template("manager/tables.html",
                           tables=DiningTable.query.order_by(DiningTable.code).all(),
                           base_url=current_app.config["BASE_URL"])


@bp.post("/tables/add")                                # QLTT3.1
@perm_required("CAN_MANAGE_TABLES")
def add_table():
    code = request.form.get("code", "").strip().upper()
    if not code:
        flash("Nhập mã bàn")
    elif DiningTable.query.filter_by(code=code).first():
        flash("Mã bàn đã tồn tại")
    else:
        db.session.add(DiningTable(code=code, seats=int(request.form.get("seats") or 4)))
        db.session.commit()
    return redirect(url_for("manager.tables"))


@bp.post("/tables/<int:table_id>/lock")                # QLTT3.4
@perm_required("CAN_MANAGE_TABLES")
def lock(table_id):
    table = db.get_or_404(DiningTable, table_id)
    if table.status != "EMPTY":
        flash("Chỉ khoá được bàn đang trống")
    else:
        table.is_locked = not table.is_locked
        db.session.commit()
    return redirect(url_for("manager.tables"))


@bp.route("/qr/<int:table_id>.png")                    # QLTT3.1.2: ảnh QR để in dán lên bàn
@perm_required("CAN_MANAGE_TABLES")
def qr_image(table_id):
    table = db.get_or_404(DiningTable, table_id)
    url = f"{current_app.config['BASE_URL'].rstrip('/')}/t/{table.qr_token}"
    img = qrcode.make(url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")
