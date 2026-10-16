# Laundry Shop Management System - Web Version (Flask)

Same features as the desktop version, now as a website: login (admin/staff), customers with order history,
orders with live price calculation, status tracking, payments/balances, printable receipts, reports, and search/filter.

## Run in VS Code
1. File > Open Folder, choose this folder. Install the Microsoft "Python" extension.
2. Open the terminal (Ctrl+`) and run:
   ```
   pip install -r requirements.txt
   python app.py
   ```
3. Open http://127.0.0.1:5000 in your browser.

The database (`laundry.db`) and a session key (`secret.key`) are created automatically on first run.
If you use Git/GitHub, add `laundry.db` and `secret.key` to `.gitignore`.

## Default logins (change them in Admin)
| Role  | Username | Password |
|-------|----------|----------|
| Admin | admin    | admin123 |
| Staff | staff    | staff123 |

Staff: Orders and Customers. Admin: also Reports and Admin (users, services/prices).

## Files
- `app.py` - routes (Flask)
- `db.py` - SQLite database logic
- `templates/` - HTML pages, `static/style.css` - styling
- Edit shop name/address/contact at the top of `app.py` (shown on receipts)

## Using it on other devices (same Wi-Fi)
Run `flask --app app run --host 0.0.0.0` and open `http://<your-PC-IP>:5000` on the other device.
This is fine for a demo; for real deployment, use a production server (e.g. gunicorn/waitress) and turn off debug mode.
