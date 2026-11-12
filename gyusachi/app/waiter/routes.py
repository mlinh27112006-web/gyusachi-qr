from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from .. import db
from ..models import BuffetPackage, Category, DiningTable, Shift, StaffCall, TableSession
from ..permissions import perm_required
from ..utils import now
from ..services import (
    BusinessError, change_table, create_order, handle_staff_call, menu_for_session,
    open_table, request_payment, update_guests,
)

bp = Blueprint("waiter", __name__, url_prefix="/waiter")


def _int(name, default=0):
    try:
        return int(request.form.get(name, default) or default)
    except ValueError:
        return default


@bp.route("/tables")                                   # PV1.1: sơ đồ bàn
@perm_required("CAN_OPEN_TABLE")
def tables():
    sessions = {s.table_id: s for s in TableSession.query.filter_by(is_open=True).all()}
    my_shifts = (Shift.query.filter_by(user_id=current_user.id, work_date=now().date())
                 .order_by(Shift.start_time).all())
    return render_template(
        "waiter/tables.html",
        my_shifts=my_shifts, mine={t.id for sh in my_shifts for t in sh.tables},
        tables=DiningTable.query.order_by(DiningTable.code).all(),
        sessions=sessions,
        packages=BuffetPackage.query.order_by(BuffetPackage.tier).all(),
        calls=StaffCall.query.filter_by(handled=False).order_by(StaffCall.created_at).all(),
    )


@bp.post("/tables/<int:table_id>/open")                # PV1.2: số khách + chọn gói
@perm_required("CAN_OPEN_TABLE")
def open_(table_id):
    try:
        open_table(table_id, _int("package_id"), _int("adults"), _int("kids_mid"),
                   _int("kids_free"), current_user)
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("waiter.tables"))


@bp.post("/sessions/<int:sess_id>/guests")             # PV1.3
@perm_required("CAN_OPEN_TABLE")
def guests(sess_id):
    try:
        update_guests(db.get_or_404(TableSession, sess_id), _int("adults"),
                      _int("kids_mid"), _int("kids_free"))
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("waiter.tables"))


@bp.post("/sessions/<int:sess_id>/move")               # PV1.4
@perm_required("CAN_OPEN_TABLE")
def move(sess_id):
    try:
        change_table(db.get_or_404(TableSession, sess_id), _int("new_table_id"))
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("waiter.tables"))


@bp.route("/sessions/<int:sess_id>/menu")              # PV1.2.4: gọi món hộ khách
@perm_required("CAN_ORDER_FOR_TABLE")
def menu(sess_id):
    sess = db.get_or_404(TableSession, sess_id)
    cat = request.args.get("category", type=int)
    return render_template(
        "waiter/order.html", sess=sess, table=sess.table,
        items=menu_for_session(sess, cat, request.args.get("q", "").strip() or None),
        categories=Category.query.order_by(Category.id).all(), active_cat=cat,
        keyword=request.args.get("q", ""),
        post_url=url_for("waiter.order", sess_id=sess.id),
        success_url=url_for("waiter.tables"),
    )


@bp.post("/sessions/<int:sess_id>/order")
@perm_required("CAN_ORDER_FOR_TABLE")
def order(sess_id):
    sess = db.get_or_404(TableSession, sess_id)
    try:
        o = create_order(sess, (request.get_json() or {}).get("items", []), user=current_user)
    except (BusinessError, KeyError, ValueError) as e:
        return jsonify(error=str(e) if isinstance(e, BusinessError) else "Dữ liệu không hợp lệ"), 400
    return jsonify(order_id=o.id)


@bp.post("/sessions/<int:sess_id>/request-payment")    # PV3.2
@perm_required("CAN_REQUEST_PAYMENT")
def req_pay(sess_id):
    try:
        request_payment(db.get_or_404(TableSession, sess_id))
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("waiter.tables"))


@bp.post("/calls/<int:call_id>/done")
@perm_required("CAN_OPEN_TABLE")
def call_done(call_id):
    handle_staff_call(call_id)
    return redirect(url_for("waiter.tables"))
