from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import db
from ..models import DiningTable, Invoice, OrderItem, Order, TableSession
from ..permissions import perm_required
from ..services import BusinessError, checkout, confirm_paid, create_invoice
from flask_login import current_user

bp = Blueprint("cashier", __name__, url_prefix="/cashier")


@bp.route("/")                                         # TN1.1: bàn chờ thanh toán
@perm_required("CAN_CREATE_INVOICE")
def pending():
    sessions = (TableSession.query.join(DiningTable, TableSession.table_id == DiningTable.id)
                .filter(TableSession.is_open.is_(True), DiningTable.status == "WAITING_PAYMENT")
                .order_by(DiningTable.code).all())
    return render_template("cashier/pending.html", sessions=sessions)


@bp.post("/sessions/<int:sess_id>/invoice")            # TN1.2
@perm_required("CAN_CREATE_INVOICE")
def make_invoice(sess_id):
    sess = db.get_or_404(TableSession, sess_id)
    try:
        create_invoice(sess, current_user)
    except BusinessError as e:
        flash(str(e))
        return redirect(url_for("cashier.pending"))
    return redirect(url_for("cashier.invoice", sess_id=sess.id))


@bp.route("/sessions/<int:sess_id>/invoice")
@perm_required("CAN_CREATE_INVOICE")
def invoice(sess_id):
    sess = db.get_or_404(TableSession, sess_id)
    inv = Invoice.query.filter_by(session_id=sess.id).first_or_404()
    items = (OrderItem.query.join(Order).filter(Order.session_id == sess.id,
                                                OrderItem.status != "CANCELLED")
             .order_by(OrderItem.id).all())
    return render_template("cashier/invoice.html", sess=sess, inv=inv, items=items)


@bp.post("/invoices/<int:inv_id>/pay")                 # TN1.3, TN1.4
@perm_required("CAN_CHECKOUT")
def pay(inv_id):
    inv = db.get_or_404(Invoice, inv_id)
    try:
        confirm_paid(inv, request.form.get("method"))
    except BusinessError as e:
        flash(str(e))
    return redirect(url_for("cashier.invoice", sess_id=inv.session_id))


@bp.post("/sessions/<int:sess_id>/checkout")           # TN2.1
@perm_required("CAN_CHECKOUT")
def do_checkout(sess_id):
    try:
        checkout(db.get_or_404(TableSession, sess_id))
    except BusinessError as e:
        flash(str(e))
        return redirect(url_for("cashier.invoice", sess_id=sess_id))
    flash("Đã checkout, bàn trống")
    return redirect(url_for("cashier.pending"))
