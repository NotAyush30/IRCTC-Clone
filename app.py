import hmac
import os
import random
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import wraps

import mysql.connector
import requests
from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# Reads the .env file (if present) into os.environ before we use it below.
load_dotenv()


def require_env(name, allow_empty=False):
    """Return an environment variable or stop with a clear message."""
    value = os.environ.get(name)
    if value is None or (value == "" and not allow_empty):
        raise RuntimeError(
            f"Missing environment variable {name}. "
            f"Add it to your .env file (see .env.example)."
        )
    return value


app = Flask(__name__)
app.secret_key = require_env("SECRET_KEY")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": require_env("DB_USER"),
    "password": require_env("DB_PASSWORD", allow_empty=True),
    "database": os.environ.get("DB_NAME", "IRCTC"),
    "connection_timeout": 5,
}

OTP_VALID_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60

PHONE_PATTERN = re.compile(r"^[0-9+\- ]{0,15}$")


# ---------------------------------------------------------------- database

def get_db():
    return mysql.connector.connect(**DB_CONFIG)


@contextmanager
def db_connection():
    """Open a connection and always close it, even if an error happens."""
    db = get_db()
    try:
        yield db
    finally:
        db.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def get_stations():
    with db_connection() as db:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT station_id, station_name FROM Stations ORDER BY station_name"
        )
        return cur.fetchall()


def generate_pnr(cur):
    while True:
        pnr = "".join(random.choices("0123456789", k=10))
        cur.execute("SELECT 1 FROM Bookings WHERE pnr_number=%s", (pnr,))
        if not cur.fetchone():
            return pnr


def parse_journey_date(value):
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    today = date.today()
    if d < today or d > today + timedelta(days=120):
        return None
    return d


def parse_passengers(value):
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if 1 <= n <= 10 else None


@app.context_processor
def inject_date_limits():
    today = date.today()
    return {
        "today": today.isoformat(),
        "max_date": (today + timedelta(days=120)).isoformat(),
    }


# ------------------------------------------------------------------- CSRF
# CSRF = another website tricking your browser into submitting a form to us.
# Defence: every form carries a secret token that only our own pages know.

def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


# Lets templates write {{ csrf_token() }}
app.jinja_env.globals["csrf_token"] = get_csrf_token


@app.before_request
def check_csrf_token():
    # Runs before every request. GET requests only read data, so only POST is checked.
    if request.method != "POST":
        return None
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if expected and hmac.compare_digest(sent.encode(), expected.encode()):
        return None
    return (
        "<h1>Form expired</h1>"
        "<p>Your session has expired or the form was invalid. "
        "Please go back, reload the page and try again.</p>"
        "<p><a href='/'>Back to home</a></p>",
        400,
    )


# ------------------------------------------------------------ error pages

@app.errorhandler(mysql.connector.Error)
def handle_db_error(e):
    # Any database error we did not handle inside a route ends up here
    # (for example MySQL is not running or the password is wrong).
    app.logger.error("Database error: %s", e)
    return (
        "<h1>Database error</h1>"
        "<p>Could not talk to the database. Make sure MySQL is running and "
        "the settings in your .env file are correct.</p>"
        "<p><a href='/'>Back to home</a></p>",
        500,
    )


@app.errorhandler(404)
def handle_not_found(e):
    return "<h1>Page not found</h1><p><a href='/'>Back to home</a></p>", 404


# ------------------------------------------------------------------ email

def send_otp_email(to_email, otp):
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_SENDER_EMAIL")
    if not api_key or not sender_email:
        app.logger.error("Email not configured: set BREVO_API_KEY and MAIL_SENDER_EMAIL")
        return False

    payload = {
        "sender": {
            "name": os.environ.get("MAIL_SENDER_NAME", "Railway Reservation System"),
            "email": sender_email,
        },
        "to": [{"email": to_email}],
        "subject": "Your password reset OTP",
        "htmlContent": (
            f"<p>Your OTP to reset your password is "
            f"<b style='font-size:20px'>{otp}</b>.</p>"
            f"<p>It is valid for {OTP_VALID_MINUTES} minutes. "
            f"If you did not request this, ignore this email.</p>"
        ),
    }
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"api-key": api_key, "accept": "application/json"},
            timeout=10,
        )
        if r.status_code not in (200, 201):
            app.logger.error("Email error: %s %s", r.status_code, r.text)
            return False
        return True
    except requests.RequestException as e:
        app.logger.error("Email error: %s", e)
        return False


# ------------------------------------------------------- public / account

@app.route("/")
@app.route("/home")
def home():
    return render_template("home.html", stations=get_stations())


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        # Server-side checks: the HTML form checks can be bypassed.
        error = None
        if not username or len(username) > 50:
            error = "Name is required (maximum 50 characters)."
        elif "@" not in email or len(email) > 50:
            error = "Please enter a valid email (maximum 50 characters)."
        elif not PHONE_PATTERN.match(phone):
            error = "Phone may contain digits, +, - and spaces (maximum 15 characters)."
        elif not 6 <= len(password) <= 128:
            error = "Password must be between 6 and 128 characters."
        if error:
            flash(error)
            return render_template("register.html")

        try:
            with db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "INSERT INTO Users (user_id, username, password, email, phone) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    ("U" + uuid.uuid4().hex[:8], username,
                     generate_password_hash(password), email, phone),
                )
                db.commit()
            flash("Registered successfully! Please login.")
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            flash("This email is already registered.")
        except mysql.connector.Error as e:
            app.logger.error("Register error: %s", e)
            flash("Could not register right now. Please try again later.")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        with db_connection() as db:
            cur = db.cursor(dictionary=True)
            cur.execute("SELECT * FROM Users WHERE email=%s", (email,))
            user = cur.fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()  # drop any old session data before logging in
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------- password reset

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        with db_connection() as db:
            cur = db.cursor(dictionary=True)
            cur.execute("SELECT user_id FROM Users WHERE email=%s", (email,))
            user = cur.fetchone()
            if user:
                cur.execute(
                    "SELECT TIMESTAMPDIFF(SECOND, last_sent, NOW()) AS age "
                    "FROM PasswordResets WHERE email=%s",
                    (email,),
                )
                row = cur.fetchone()
                if row is None or row["age"] >= OTP_RESEND_SECONDS:
                    otp = f"{secrets.randbelow(10 ** 6):06d}"
                    cur.execute(
                        "INSERT INTO PasswordResets "
                        "(email, otp_hash, expires_at, attempts, last_sent) "
                        "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE), 0, NOW()) "
                        "ON DUPLICATE KEY UPDATE otp_hash=VALUES(otp_hash), "
                        "expires_at=VALUES(expires_at), attempts=0, "
                        "last_sent=VALUES(last_sent)",
                        (email, generate_password_hash(otp), OTP_VALID_MINUTES),
                    )
                    db.commit()
                    if not send_otp_email(email, otp):
                        cur.execute(
                            "DELETE FROM PasswordResets WHERE email=%s", (email,)
                        )
                        db.commit()
                        flash("Could not send the OTP right now. Please try again later.")
                        return redirect(url_for("forgot_password"))
        # Same message whether or not the email exists, so nobody can use
        # this page to find out which emails are registered.
        session["reset_email"] = email
        session.pop("reset_ok", None)
        flash("If this email is registered, an OTP has been sent to it.")
        return redirect(url_for("verify_otp"))
    return render_template("forgot-password.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        with db_connection() as db:
            cur = db.cursor(dictionary=True)
            cur.execute(
                "SELECT otp_hash, attempts, expires_at > NOW() AS valid "
                "FROM PasswordResets WHERE email=%s",
                (email,),
            )
            row = cur.fetchone()
            if not row:
                flash("No active OTP found. Please request a new one.")
                return redirect(url_for("forgot_password"))
            if not row["valid"]:
                flash("This OTP has expired. Please request a new one.")
                return redirect(url_for("forgot_password"))
            if row["attempts"] >= OTP_MAX_ATTEMPTS:
                flash("Too many incorrect attempts. Please request a new OTP.")
                return redirect(url_for("forgot_password"))
            if check_password_hash(row["otp_hash"], otp):
                session["reset_ok"] = True
                return redirect(url_for("reset_password"))
            cur.execute(
                "UPDATE PasswordResets SET attempts = attempts + 1 WHERE email=%s",
                (email,),
            )
            db.commit()
            flash("Incorrect OTP. Please try again.")
    return render_template("verify-otp.html", email=email)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    if not email or not session.get("reset_ok"):
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not 6 <= len(password) <= 128:
            flash("Password must be between 6 and 128 characters.")
        elif password != confirm:
            flash("Passwords do not match.")
        else:
            with db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "UPDATE Users SET password=%s WHERE email=%s",
                    (generate_password_hash(password), email),
                )
                cur.execute("DELETE FROM PasswordResets WHERE email=%s", (email,))
                db.commit()
            session.pop("reset_email", None)
            session.pop("reset_ok", None)
            flash("Password updated. Please login.")
            return redirect(url_for("login"))
    return render_template("reset-password.html")


# --------------------------------------------------------------- PNR status

@app.route("/pnr-status", methods=["GET", "POST"])
def pnr_status():
    ticket = None
    if request.method == "POST":
        pnr = request.form.get("pnr", "").strip()
        with db_connection() as db:
            cur = db.cursor(dictionary=True)
            cur.execute("""
                SELECT b.pnr_number, t.train_number, t.train_name,
                       s1.station_name AS source_station,
                       s2.station_name AS destination_station,
                       t.departure_time, t.arrival_time, b.journey_date,
                       tc.class_name, tc.fare, b.seat_count, b.booking_status
                FROM Bookings b
                JOIN TrainClasses tc ON b.train_class_id = tc.train_class_id
                JOIN Trains t ON tc.train_id = t.train_id
                JOIN Stations s1 ON t.source_station_id = s1.station_id
                JOIN Stations s2 ON t.destination_station_id = s2.station_id
                WHERE b.pnr_number = %s
            """, (pnr,))
            ticket = cur.fetchone()
        if not ticket:
            flash("PNR not found.")
    return render_template("pnr-status.html", ticket=ticket)


# ------------------------------------------------------------- booking flow

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/book-ticket")
@login_required
def book_ticket():
    return render_template("book-ticket.html", stations=get_stations())


@app.route("/search-trains", methods=["GET", "POST"])
@login_required
def search_trains():
    if request.method == "GET":
        return redirect(url_for("book_ticket"))

    f = request.form
    journey_date = parse_journey_date(f.get("date"))
    passengers = parse_passengers(f.get("passengers"))
    from_id = f.get("from", "")
    to_id = f.get("to", "")
    class_name = f.get("class", "")

    if journey_date is None:
        flash("Please choose a valid journey date within the next 120 days.")
        return redirect(url_for("book_ticket"))
    if passengers is None:
        flash("Passengers must be between 1 and 10.")
        return redirect(url_for("book_ticket"))
    if not from_id or not to_id or not class_name:
        flash("Please choose the departure station, destination and class.")
        return redirect(url_for("book_ticket"))
    if from_id == to_id:
        flash("Departure and destination stations must be different.")
        return redirect(url_for("book_ticket"))

    with db_connection() as db:
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT t.train_number, t.train_name,
                   s1.station_name AS source_station,
                   s2.station_name AS destination_station,
                   t.departure_time, t.arrival_time,
                   tc.train_class_id, tc.class_name, tc.fare,
                   tc.total_seats - COALESCE((
                       SELECT SUM(b.seat_count) FROM Bookings b
                       WHERE b.train_class_id = tc.train_class_id
                         AND b.journey_date = %s
                         AND b.booking_status = 'Confirmed'
                   ), 0) AS available_seats
            FROM Trains t
            JOIN Stations s1 ON t.source_station_id = s1.station_id
            JOIN Stations s2 ON t.destination_station_id = s2.station_id
            JOIN TrainClasses tc ON t.train_id = tc.train_id
            WHERE s1.station_id = %s
              AND s2.station_id = %s
              AND tc.class_name = %s
            HAVING available_seats >= %s
        """, (journey_date, from_id, to_id, class_name, passengers))
        trains = cur.fetchall()

    return render_template("search-results.html", trains=trains,
                           date=journey_date.isoformat(), passengers=passengers)


@app.route("/book", methods=["POST"])
@login_required
def book():
    f = request.form
    journey_date = parse_journey_date(f.get("date"))
    seats = parse_passengers(f.get("passengers"))
    train_class_id = f.get("train_class_id", "")
    if journey_date is None or seats is None or not train_class_id:
        flash("Invalid journey date or passenger count.")
        return redirect(url_for("book_ticket"))

    db = get_db()
    cur = db.cursor()
    try:
        # FOR UPDATE locks this class row so two people booking at the same
        # moment cannot both take the last seats.
        cur.execute(
            "SELECT total_seats FROM TrainClasses WHERE train_class_id = %s FOR UPDATE",
            (train_class_id,),
        )
        row = cur.fetchone()
        if not row:
            db.rollback()
            flash("Invalid train class.")
            return redirect(url_for("book_ticket"))

        cur.execute(
            "SELECT COALESCE(SUM(seat_count), 0) FROM Bookings "
            "WHERE train_class_id = %s AND journey_date = %s "
            "AND booking_status = 'Confirmed'",
            (train_class_id, journey_date),
        )
        booked = int(cur.fetchone()[0])

        if row[0] - booked < seats:
            db.rollback()
            flash("Not enough seats available for this date.")
            return redirect(url_for("book_ticket"))

        pnr = generate_pnr(cur)
        cur.execute("""
            INSERT INTO Bookings (booking_id, user_id, train_class_id,
                                  journey_date, seat_count, pnr_number,
                                  booking_status)
            VALUES (%s, %s, %s, %s, %s, %s, 'Confirmed')
        """, ("B" + uuid.uuid4().hex[:8], session["user_id"],
              train_class_id, journey_date, seats, pnr))

        db.commit()
        flash(f"Booking confirmed! Your PNR is {pnr}")
        return redirect(url_for("my_bookings"))
    except mysql.connector.Error:
        db.rollback()
        app.logger.exception("Booking error")
        flash("Booking failed. Please try again.")
        return redirect(url_for("book_ticket"))
    finally:
        db.close()


@app.route("/my-bookings")
@login_required
def my_bookings():
    with db_connection() as db:
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT b.booking_id, b.pnr_number, t.train_number, t.train_name,
                   s1.station_name AS source_station,
                   s2.station_name AS destination_station,
                   t.departure_time, t.arrival_time, b.journey_date,
                   tc.class_name, tc.fare, b.seat_count, b.booking_status
            FROM Bookings b
            JOIN TrainClasses tc ON b.train_class_id = tc.train_class_id
            JOIN Trains t ON tc.train_id = t.train_id
            JOIN Stations s1 ON t.source_station_id = s1.station_id
            JOIN Stations s2 ON t.destination_station_id = s2.station_id
            WHERE b.user_id = %s
            ORDER BY b.journey_date
        """, (session["user_id"],))
        bookings = cur.fetchall()
    return render_template("my-bookings.html", bookings=bookings)


@app.route("/cancellation", methods=["GET", "POST"])
@login_required
def cancellation():
    if request.method == "POST":
        pnr = request.form.get("pnr", "").strip()
        reason = request.form.get("reason", "").strip()[:255]

        try:
            with db_connection() as db:
                cur = db.cursor()
                cur.execute("""
                    UPDATE Bookings
                    SET booking_status = 'Cancelled', cancellation_reason = %s
                    WHERE pnr_number = %s AND user_id = %s
                      AND booking_status = 'Confirmed'
                      AND journey_date >= CURDATE()
                """, (reason, pnr, session["user_id"]))
                if cur.rowcount == 0:
                    db.rollback()
                    flash("No cancellable booking found for this PNR.")
                else:
                    db.commit()
                    flash("Ticket cancelled successfully.")
        except mysql.connector.Error:
            app.logger.exception("Cancellation error")
            flash("Cancellation failed.")
    return render_template("cancellation.html")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
