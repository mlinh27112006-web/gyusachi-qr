from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from .. import db
from ..models import CancelRequest, MenuItem, Order, OrderItem
from ..permissions import perm_required
from ..services import BusinessError, decide_cancel, set_item_status, set_sold_out

bp = Blueprint("kitchen", __name__, url_prefix="/kitchen")


@bp.route("/")                                         # BEP1.1: bảng đơn
@perm_required("CAN_COOK")
def board():
    items = (OrderItem.query.join(Order)
             .filter(OrderItem.status.in_(["PENDING", "COOKING"]))
             .order_by(Order.created_at, OrderItem.id).all())
    cancels = CancelRequest.query.filter_by(status="PENDING").order_by(CancelRequest.created_at).all()
    return render_template("kitchen/board.html", items=items, cancels=cancels)


@bp.post("/items/<int:item_id>/<action>")              # cooking | ready
@perm_required("CAN_COOK")
def move_item(item_id, action):
    status = {"cooking": "COOKING", "ready": "READY"}.get(action)
    try:
        set_item_status(item_id, status)
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("kitchen.board"))


@bp.post("/cancels/<int:req_id>/<decision>")           # approve | reject
@perm_required("CAN_COOK")
def cancel_decision(req_id, decision):
    try:
        decide_cancel(req_id, decision == "approve", current_user)
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("kitchen.board"))


@bp.route("/menu")                                     # BEP1.5: báo hết món
@perm_required("CAN_COOK")
def menu():
    return render_template("kitchen/menu.html",
                           items=MenuItem.query.filter_by(is_active=True)
                           .order_by(MenuItem.category_id, MenuItem.name).all())


@bp.post("/menu/<int:item_id>/toggle")
@perm_required("CAN_COOK")
def toggle_sold_out(item_id):
    item = db.get_or_404(MenuItem, item_id)
    set_sold_out(item_id, not item.is_sold_out)
    return redirect(url_for("kitchen.menu"))
