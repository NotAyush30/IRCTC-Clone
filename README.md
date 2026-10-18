# Railway Reservation System

A DBMS college project: a small web application for searching trains and
booking tickets, built with Flask and MySQL.

## Features

- User registration and login (passwords are stored as hashes)
- Password reset with an emailed OTP
- Train search by route, date and class, with seats left for that date
- Ticket booking with an automatically generated PNR
- My Bookings page and ticket cancellation
- PNR status lookup

## Technologies

- Python 3 and Flask (backend)
- MySQL 8.0.16 or newer (database; older versions ignore CHECK constraints)
- HTML and CSS inside Jinja templates (frontend)

## Database

Six tables, created by `schema.sql`:

| Table | Purpose |
|-------|---------|
| Users | Registered users |
| Stations | Railway stations |
| Trains | Trains with source and destination stations |
| TrainClasses | Classes per train, with fare and total seats |
| Bookings | Bookings made by users for a journey date |
| PasswordResets | Temporary OTPs for password reset |

Seats left are not stored. They are calculated as the class's total seats
minus the confirmed bookings for that date.

## Project structure

```
app.py              Flask routes and database code
schema.sql          Tables and sample data
requirements.txt    Python packages
templates/
    base.html       Shared header, navigation, styles and footer
```
