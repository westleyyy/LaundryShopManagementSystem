"""Laundry Shop Management System - web version (Flask).

Run:   flask --app app run        (or: python app.py)
Open:  http://127.0.0.1:5000
Default logins: admin / admin123  and  staff / staff123  (change them in the Admin page!)
"""
import math
import secrets
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

import db

# ---- Edit these to match your shop (they appear on receipts) ----------------
SHOP_NAME = "LAUNDRY SHOP"
SHOP_ADDRESS = "Your shop address here"
SHOP_CONTACT = "Tel: 0900-000-0000"
# -----------------------------------------------------------------------------

app = Flask(__name__)
_key_file = Path(__file__).with_name("secret.key")
if not _key_file.exists():
    _key_file.write_text(secrets.token_hex(32))
app.secret_key = _key_file.read_text().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
db.init_db()


# ------------------------------- helpers ------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent, real = request.form.get("_csrf", ""), session.get("_csrf", "")
        if not real or not secrets.compare_digest(sent, real):
            abort(400, "Invalid or missing form token. Go back, refresh the page and try again.")


@app.template_filter("peso")
def peso(value):
    return f"₱{value or 0:,.2f}"


@app.context_processor
def inject_globals():
    return dict(
        user=session.get("user"), csrf_token=csrf_token, statuses=db.STATUSES,
        methods=db.PAYMENT_METHODS, pay_status=db.payment_status,
        shop_name=SHOP_NAME, shop_address=SHOP_ADDRESS, shop_contact=SHOP_CONTACT,
        balance_of=lambda o: max(round(o["total"] - o["paid"], 2), 0),
    )


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*a, **kw):
        if session["user"]["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapper


def num(text, field):
    try:
        value = float(str(text).replace(",", "").strip())
    except ValueError:
        raise ValueError(f"{field} must be a number.")
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a number.")
    return value


def parse_date(text, field):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{field} must be in YYYY-MM-DD format.")


def order_or_404(order_id):
    order = db.get_order(order_id)
    if order is None:
        abort(404)
    return order


# -------------------------------- auth --------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db.authenticate(request.form.get("username", ""), request.form.get("password", ""))
        if u:
            session.clear()
            session["user"] = {"id": u["id"], "name": u["full_name"], "role": u["role"], "username": u["username"]}
            return redirect(url_for("orders"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------- orders -------------------------------------
@app.route("/")
@login_required
def orders():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "All")
    rows = db.list_orders(q, status)
    outstanding = sum(max(r["total"] - r["paid"], 0) for r in rows)
    return render_template("orders.html", rows=rows, q=q, status=status, outstanding=outstanding)


@app.route("/orders/new", methods=["GET", "POST"])
@login_required
def new_order():
    services = db.list_services()
    if request.method == "POST":
        f = request.form
        try:
            name = f.get("name", "").strip()
            if not name:
                raise ValueError("Customer name is required.")
            ltype = f.get("laundry_type", "")
            if ltype not in db.LAUNDRY_TYPES:
                raise ValueError("Please choose a laundry type.")
            weight = num(f.get("weight", ""), "Weight")
            if weight <= 0:
                raise ValueError("Weight must be greater than 0.")
            service = next((s for s in services if str(s["id"]) == f.get("service_id")), None)
            if service is None:
                raise ValueError("Please choose a service type.")
            order_date = parse_date(f.get("order_date", ""), "Order date")
            total = db.compute_total(weight, service["price_per_kg"])
            pay_text = f.get("pay_amount", "").strip()
            pay = num(pay_text, "Initial payment") if pay_text else 0
            if pay < 0 or pay > total + 0.005:
                raise ValueError("Initial payment can't be negative or more than the total.")
            cid = db.find_or_create_customer(name, f.get("contact", "").strip())
            oid = db.create_order(cid, ltype, weight, service["id"], order_date, session["user"]["id"])
            if pay > 0:
                db.add_payment(oid, pay, f.get("pay_method", ""), session["user"]["id"])
        except ValueError as e:
            flash(str(e), "error")
        else:
            flash("Order saved.", "success")
            return redirect(url_for("order_detail", order_id=oid))
    customers = [{"name": c["name"], "contact": c["contact"]} for c in db.list_customers()]
    prices = {str(s["id"]): s["price_per_kg"] for s in services}
    return render_template("order_new.html", services=services, customers=customers, prices=prices,
                           laundry_types=db.LAUNDRY_TYPES, form=request.form, today=db.today())


@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    return render_template("order_detail.html", o=order_or_404(order_id), payments=db.order_payments(order_id))


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
def order_status(order_id):
    o = order_or_404(order_id)
    new = request.form.get("status", "")
    if request.form.get("action") == "next":
        i = db.STATUSES.index(o["status"])
        new = db.STATUSES[min(i + 1, len(db.STATUSES) - 1)]
    try:
        db.update_status(order_id, new)
        flash(f"Status updated to {new}.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/payment", methods=["POST"])
@login_required
def order_payment(order_id):
    order_or_404(order_id)
    try:
        db.add_payment(order_id, num(request.form.get("amount", ""), "Amount"),
                       request.form.get("method", ""), session["user"]["id"])
        flash("Payment recorded.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/delete", methods=["POST"])
@admin_required
def order_delete(order_id):
    order_or_404(order_id)
    db.delete_order(order_id)
    flash("Order deleted.", "success")
    return redirect(url_for("orders"))


@app.route("/orders/<int:order_id>/receipt")
@login_required
def receipt(order_id):
    return render_template("receipt.html", o=order_or_404(order_id), payments=db.order_payments(order_id))


# ------------------------------ customers -----------------------------------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        try:
            db.add_customer(request.form.get("name", "").strip(), request.form.get("contact", "").strip())
            flash("Customer added.", "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("customers"))
    q = request.args.get("q", "").strip()
    return render_template("customers.html", rows=db.list_customers(q), q=q)


@app.route("/customers/<int:customer_id>", methods=["GET", "POST"])
@login_required
def customer_detail(customer_id):
    customer = next((c for c in db.list_customers() if c["id"] == customer_id), None)
    if customer is None:
        abort(404)
    if request.method == "POST":
        try:
            db.update_customer(customer_id, request.form.get("name", "").strip(), request.form.get("contact", "").strip())
            flash("Customer updated.", "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("customer_detail", customer_id=customer_id))
    return render_template("customer_detail.html", c=customer, history=db.customer_orders(customer_id))


# -------------------------------- reports -----------------------------------
@app.route("/reports")
@admin_required
def reports():
    day, month = request.args.get("day", db.today()), request.args.get("month", db.today()[:7])
    try:
        day = parse_date(day, "Day")
        month = datetime.strptime(month.strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        flash("Use YYYY-MM-DD for the day and YYYY-MM for the month.", "error")
        day, month = db.today(), db.today()[:7]
    start, end = f"{month}-01", f"{month}-31"
    return render_template("reports.html", day=day, month=month,
                           daily=db.sales_summary(day, day), monthly=db.sales_summary(start, end),
                           breakdown=db.daily_breakdown(start, end), completed=db.completed_orders(start, end))


# --------------------------------- admin ------------------------------------
@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html", users=db.list_users(), services=db.list_services(), roles=db.ROLES)


def _admin_action(fn, ok_message):
    try:
        fn()
        flash(ok_message, "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin"))


@app.route("/admin/users", methods=["POST"])
@admin_required
def admin_add_user():
    f = request.form
    return _admin_action(lambda: db.add_user(f.get("username", "").strip(), f.get("full_name", "").strip(),
                                             f.get("password", ""), f.get("role", "")), "User added.")


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_reset_password(user_id):
    return _admin_action(lambda: db.set_password(user_id, request.form.get("password", "")), "Password updated.")


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user"]["id"]:
        flash("You can't delete the account you are logged in with.", "error")
        return redirect(url_for("admin"))
    return _admin_action(lambda: db.delete_user(user_id), "User deleted.")


@app.route("/admin/services", methods=["POST"])
@admin_required
def admin_add_service():
    f = request.form
    return _admin_action(lambda: db.add_service(f.get("name", "").strip(), num(f.get("price", ""), "Price")),
                         "Service added.")


@app.route("/admin/services/<int:service_id>", methods=["POST"])
@admin_required
def admin_edit_service(service_id):
    f = request.form
    return _admin_action(lambda: db.update_service(service_id, f.get("name", "").strip(), num(f.get("price", ""), "Price")),
                         "Service updated.")


if __name__ == "__main__":
    app.run(debug=True)
