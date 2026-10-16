"""Database layer for the Laundry Shop Management System (SQLite, standard library only)."""
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("laundry.db")

STATUSES = ["Pending", "Washing", "Drying", "Ready for Pickup", "Claimed"]
PAYMENT_METHODS = ["Cash", "GCash", "Maya", "Bank Transfer", "Card"]
LAUNDRY_TYPES = ["Clothes", "Bedsheets / Linens", "Towels", "Comforter / Blanket", "Delicates", "Uniforms"]
ROLES = ["admin", "staff"]


# --------------------------------------------------------------------------- #
# Connection helpers
# --------------------------------------------------------------------------- #
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def today():
    return date.today().strftime("%Y-%m-%d")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return digest.hex(), salt


def payment_status(total, paid):
    if paid >= total - 0.005:
        return "Paid"
    if paid > 0:
        return "Partial"
    return "Unpaid"


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'staff'))
);
CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    contact    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    price_per_kg REAL NOT NULL CHECK (price_per_kg >= 0)
);
CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no     TEXT NOT NULL UNIQUE,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    laundry_type TEXT NOT NULL,
    weight_kg    REAL NOT NULL CHECK (weight_kg > 0),
    service_id   INTEGER NOT NULL REFERENCES services(id),
    price_per_kg REAL NOT NULL,          -- price snapshot so later price changes don't alter old orders
    total        REAL NOT NULL,
    order_date   TEXT NOT NULL,          -- YYYY-MM-DD
    status       TEXT NOT NULL DEFAULT 'Pending',
    claimed_date TEXT,
    created_by   INTEGER
);
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    amount      REAL NOT NULL CHECK (amount > 0),
    method      TEXT NOT NULL,
    paid_date   TEXT NOT NULL,           -- YYYY-MM-DD HH:MM:SS
    received_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date     ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_payments_order  ON payments(order_id);
"""

DEFAULT_SERVICES = [
    ("Wash Only", 30),
    ("Dry Only", 30),
    ("Wash & Dry", 50),
    ("Wash, Dry & Fold", 60),
    ("Express Wash, Dry & Fold", 90),
    ("Dry Cleaning", 150),
]


def init_db():
    with db() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            for username, full_name, pw, role in [
                ("admin", "Administrator", "admin123", "admin"),
                ("staff", "Staff Member", "staff123", "staff"),
            ]:
                h, s = hash_password(pw)
                c.execute(
                    "INSERT INTO users (username, full_name, password_hash, salt, role) VALUES (?,?,?,?,?)",
                    (username, full_name, h, s, role),
                )
        if c.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            c.executemany("INSERT INTO services (name, price_per_kg) VALUES (?,?)", DEFAULT_SERVICES)


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def authenticate(username, password):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        return None
    h, _ = hash_password(password, row["salt"])
    return row if secrets.compare_digest(h, row["password_hash"]) else None


def list_users():
    with db() as c:
        return c.execute("SELECT id, username, full_name, role FROM users ORDER BY role, username").fetchall()


def add_user(username, full_name, password, role):
    if not username or not full_name or not password:
        raise ValueError("Username, full name and password are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if role not in ROLES:
        raise ValueError("Role must be admin or staff.")
    h, s = hash_password(password)
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users (username, full_name, password_hash, salt, role) VALUES (?,?,?,?,?)",
                (username, full_name, h, s, role),
            )
    except sqlite3.IntegrityError:
        raise ValueError("That username is already taken.")


def set_password(user_id, password):
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    h, s = hash_password(password)
    with db() as c:
        c.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (h, s, user_id))


def delete_user(user_id):
    with db() as c:
        row = c.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["role"] == "admin":
            if c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                raise ValueError("You can't delete the last admin account.")
        c.execute("DELETE FROM users WHERE id=?", (user_id,))


# --------------------------------------------------------------------------- #
# Services (price list)
# --------------------------------------------------------------------------- #
def list_services():
    with db() as c:
        return c.execute("SELECT * FROM services ORDER BY id").fetchall()


def add_service(name, price):
    if not name:
        raise ValueError("Service name is required.")
    if price < 0:
        raise ValueError("Price can't be negative.")
    try:
        with db() as c:
            c.execute("INSERT INTO services (name, price_per_kg) VALUES (?,?)", (name, price))
    except sqlite3.IntegrityError:
        raise ValueError("A service with that name already exists.")


def update_service(service_id, name, price):
    if not name:
        raise ValueError("Service name is required.")
    if price < 0:
        raise ValueError("Price can't be negative.")
    try:
        with db() as c:
            c.execute("UPDATE services SET name=?, price_per_kg=? WHERE id=?", (name, price, service_id))
    except sqlite3.IntegrityError:
        raise ValueError("A service with that name already exists.")


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
def list_customers(search=""):
    like = f"%{search}%"
    with db() as c:
        return c.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id) AS order_count
               FROM customers c
               WHERE c.name LIKE ? OR c.contact LIKE ?
               ORDER BY c.name COLLATE NOCASE""",
            (like, like),
        ).fetchall()


def add_customer(name, contact):
    if not name:
        raise ValueError("Customer name is required.")
    with db() as c:
        return c.execute("INSERT INTO customers (name, contact) VALUES (?,?)", (name, contact)).lastrowid


def update_customer(customer_id, name, contact):
    if not name:
        raise ValueError("Customer name is required.")
    with db() as c:
        c.execute("UPDATE customers SET name=?, contact=? WHERE id=?", (name, contact, customer_id))


def find_or_create_customer(name, contact):
    with db() as c:
        row = c.execute(
            "SELECT id FROM customers WHERE lower(name)=lower(?) AND contact=?", (name, contact)
        ).fetchone()
        if row:
            return row["id"]
        return c.execute("INSERT INTO customers (name, contact) VALUES (?,?)", (name, contact)).lastrowid


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
ORDER_SELECT = """
SELECT o.*, c.name AS customer, c.contact AS contact, s.name AS service, u.full_name AS staff,
       COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.order_id = o.id), 0) AS paid
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN services  s ON s.id = o.service_id
LEFT JOIN users u ON u.id = o.created_by
"""


def compute_total(weight_kg, price_per_kg):
    return round(weight_kg * price_per_kg, 2)


def create_order(customer_id, laundry_type, weight_kg, service_id, order_date, user_id):
    if weight_kg <= 0:
        raise ValueError("Weight must be greater than 0.")
    with db() as c:
        svc = c.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        if svc is None:
            raise ValueError("Selected service no longer exists.")
        total = compute_total(weight_kg, svc["price_per_kg"])
        order_id = c.execute(
            """INSERT INTO orders (order_no, customer_id, laundry_type, weight_kg, service_id,
                                   price_per_kg, total, order_date, status, created_by)
               VALUES (?,?,?,?,?,?,?,?, 'Pending', ?)""",
            ("TMP" + secrets.token_hex(4), customer_id, laundry_type, weight_kg, service_id,
             svc["price_per_kg"], total, order_date, user_id),
        ).lastrowid
        order_no = f"LS-{order_date.replace('-', '')}-{order_id:04d}"
        c.execute("UPDATE orders SET order_no=? WHERE id=?", (order_no, order_id))
    return order_id


def list_orders(search="", status="All"):
    q, params = ORDER_SELECT + " WHERE 1=1", []
    if search:
        q += " AND (o.order_no LIKE ? OR c.name LIKE ?)"
        params += [f"%{search}%"] * 2
    if status and status != "All":
        q += " AND o.status = ?"
        params.append(status)
    q += " ORDER BY o.id DESC"
    with db() as c:
        return c.execute(q, params).fetchall()


def get_order(order_id):
    with db() as c:
        return c.execute(ORDER_SELECT + " WHERE o.id = ?", (order_id,)).fetchone()


def customer_orders(customer_id):
    with db() as c:
        return c.execute(ORDER_SELECT + " WHERE o.customer_id = ? ORDER BY o.id DESC", (customer_id,)).fetchall()


def update_status(order_id, status):
    if status not in STATUSES:
        raise ValueError("Invalid status.")
    with db() as c:
        c.execute(
            "UPDATE orders SET status=?, claimed_date=? WHERE id=?",
            (status, today() if status == "Claimed" else None, order_id),
        )


def delete_order(order_id):
    with db() as c:
        c.execute("DELETE FROM orders WHERE id=?", (order_id,))


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #
def add_payment(order_id, amount, method, user_id):
    if amount <= 0:
        raise ValueError("Payment amount must be greater than 0.")
    if method not in PAYMENT_METHODS:
        raise ValueError("Please choose a payment method.")
    order = get_order(order_id)
    if order is None:
        raise ValueError("Order not found.")
    balance = round(order["total"] - order["paid"], 2)
    if amount > balance + 0.005:
        raise ValueError(f"Payment exceeds the remaining balance of {balance:,.2f}.")
    with db() as c:
        c.execute(
            "INSERT INTO payments (order_id, amount, method, paid_date, received_by) VALUES (?,?,?,?,?)",
            (order_id, round(amount, 2), method, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )


def order_payments(order_id):
    with db() as c:
        return c.execute("SELECT * FROM payments WHERE order_id=? ORDER BY id", (order_id,)).fetchall()


# --------------------------------------------------------------------------- #
# Reports (start/end are inclusive 'YYYY-MM-DD' strings)
# --------------------------------------------------------------------------- #
def sales_summary(start, end):
    with db() as c:
        o = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total),0) billed FROM orders WHERE order_date BETWEEN ? AND ?",
            (start, end),
        ).fetchone()
        collected = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(paid_date) BETWEEN ? AND ?", (start, end)
        ).fetchone()[0]
        completed = c.execute(
            "SELECT COUNT(*) FROM orders WHERE status='Claimed' AND claimed_date BETWEEN ? AND ?", (start, end)
        ).fetchone()[0]
    return {"orders": o["n"], "billed": o["billed"], "collected": collected, "completed": completed}


def daily_breakdown(start, end):
    with db() as c:
        orders = c.execute(
            """SELECT order_date d, COUNT(*) n, SUM(total) billed FROM orders
               WHERE order_date BETWEEN ? AND ? GROUP BY order_date""", (start, end)).fetchall()
        pays = c.execute(
            """SELECT date(paid_date) d, SUM(amount) s FROM payments
               WHERE date(paid_date) BETWEEN ? AND ? GROUP BY date(paid_date)""", (start, end)).fetchall()
    days = {}
    for r in orders:
        days.setdefault(r["d"], {"orders": 0, "billed": 0.0, "collected": 0.0}).update(
            orders=r["n"], billed=r["billed"])
    for r in pays:
        days.setdefault(r["d"], {"orders": 0, "billed": 0.0, "collected": 0.0})["collected"] = r["s"]
    return sorted(days.items(), reverse=True)


def completed_orders(start, end):
    with db() as c:
        return c.execute(
            ORDER_SELECT + " WHERE o.status='Claimed' AND o.claimed_date BETWEEN ? AND ? ORDER BY o.claimed_date DESC, o.id DESC",
            (start, end),
        ).fetchall()
