from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ..models import DiningTable, Category, Order, OrderItem
from ..services import (
    BusinessError, call_staff, create_order, current_session, get_setting,
    is_open_now, menu_for_session, request_cancel,
)
from ..utils import now
from datetime import timedelta

bp = Blueprint("customer", __name__)


def _table(token):
    return DiningTable.query.filter_by(qr_token=token).first_or_404()


@bp.route("/t/<token>")                              # KH1.1: quét QR
def home(token):
    table = _table(token)
    if table.is_locked:
        return render_template("customer/message.html", msg="Bàn này hiện không sử dụng"), 403
    if not is_open_now():
        return render_template("customer/message.html", msg="Nhà hàng chưa mở cửa")
    sess = current_session(table)
    if not sess:
        return render_template("customer/message.html",
                               msg="Bàn chưa được mở. Vui lòng chờ nhân viên đến.")
    return render_template("customer/home.html", table=table, sess=sess)


@bp.route("/t/<token>/menu")                         # KH2
def menu(token):
    table = _table(token)
    sess = current_session(table)
    if not sess:
        return redirect(url_for("customer.home", token=token))
    cat = request.args.get("category", type=int)
    items = menu_for_session(sess, cat, request.args.get("q", "").strip() or None)
    return render_template(
        "customer/menu.html", table=table, sess=sess, items=items,
        categories=Category.query.order_by(Category.id).all(), active_cat=cat,
        keyword=request.args.get("q", ""),
        post_url=url_for("customer.place_order", token=token),
        success_url=url_for("customer.orders", token=token),
    )


@bp.post("/t/<token>/order")                         # KH4.1
def place_order(token):
    sess = current_session(_table(token))
    if not sess:
        return jsonify(error="Bàn chưa được mở"), 400
    try:
        order = create_order(sess, (request.get_json() or {}).get("items", []))
    except (BusinessError, KeyError, ValueError) as e:
        return jsonify(error=str(e) if isinstance(e, BusinessError) else "Dữ liệu không hợp lệ"), 400
    return jsonify(order_id=order.id)


@bp.route("/t/<token>/orders")                       # KH4.2: theo dõi đơn
def orders(token):
    table = _table(token)
    sess = current_session(table)
    if not sess:
        return redirect(url_for("customer.home", token=token))
    items = (OrderItem.query.join(Order).filter(Order.session_id == sess.id)
             .order_by(Order.created_at.desc(), OrderItem.id).all())
    minutes = int(get_setting("cancel_minutes", 5))
    limit = now() - timedelta(minutes=minutes)
    return render_template("customer/orders.html", table=table, sess=sess, items=items,
                           cancel_minutes=minutes, limit=limit)


@bp.post("/t/<token>/cancel/<int:item_id>")          # KH4.3
def cancel(token, item_id):
    _table(token)
    try:
        request_cancel(item_id, (request.get_json() or {}).get("reason", ""))
    except BusinessError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@bp.post("/t/<token>/call-staff")                    # KH4.6
def call(token):
    sess = current_session(_table(token))
    if not sess:
        return jsonify(error="Bàn chưa được mở"), 400
    call_staff(sess)
    return jsonify(ok=True)
