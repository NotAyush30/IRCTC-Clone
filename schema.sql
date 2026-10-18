CREATE DATABASE IF NOT EXISTS IRCTC;
USE IRCTC;

CREATE TABLE IF NOT EXISTS Users (
    user_id VARCHAR(10) PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(50) UNIQUE NOT NULL,
    phone VARCHAR(15)
);

CREATE TABLE IF NOT EXISTS Stations (
    station_id VARCHAR(10) PRIMARY KEY,
    station_name VARCHAR(50) UNIQUE NOT NULL,
    city VARCHAR(30),
    state VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS Trains (
    train_id VARCHAR(10) PRIMARY KEY,
    train_number INT UNIQUE NOT NULL,
    train_name VARCHAR(50) NOT NULL,
    source_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    departure_time TIME,
    arrival_time TIME,
    FOREIGN KEY (source_station_id) REFERENCES Stations(station_id),
    FOREIGN KEY (destination_station_id) REFERENCES Stations(station_id),
    CONSTRAINT chk_train_route CHECK (source_station_id <> destination_station_id)
);

CREATE TABLE IF NOT EXISTS TrainClasses (
    train_class_id VARCHAR(10) PRIMARY KEY,
    train_id VARCHAR(10) NOT NULL,
    class_name VARCHAR(20) NOT NULL,
    fare INT NOT NULL,
    total_seats INT NOT NULL,
    FOREIGN KEY (train_id) REFERENCES Trains(train_id),
    UNIQUE (train_id, class_name),
    CONSTRAINT chk_fare CHECK (fare > 0),
    CONSTRAINT chk_total_seats CHECK (total_seats >= 0)
);

CREATE TABLE IF NOT EXISTS Bookings (
    booking_id VARCHAR(10) PRIMARY KEY,
    user_id VARCHAR(10) NOT NULL,
    train_class_id VARCHAR(10) NOT NULL,
    journey_date DATE NOT NULL,
    seat_count INT NOT NULL,
    pnr_number VARCHAR(15) UNIQUE NOT NULL,
    booking_status VARCHAR(20) NOT NULL DEFAULT 'Confirmed',
    cancellation_reason VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (train_class_id) REFERENCES TrainClasses(train_class_id),
    INDEX idx_bookings_class_date (train_class_id, journey_date, booking_status),
    CONSTRAINT chk_seat_count CHECK (seat_count > 0),
    CONSTRAINT chk_booking_status CHECK (booking_status IN ('Confirmed', 'Cancelled', 'Waiting'))
);

CREATE TABLE IF NOT EXISTS PasswordResets (
    email VARCHAR(50) PRIMARY KEY,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_sent DATETIME NOT NULL,
    FOREIGN KEY (email) REFERENCES Users(email) ON DELETE CASCADE
);

INSERT IGNORE INTO Stations (station_id, station_name, city, state) VALUES
('S01', 'Ahmedabad Junction', 'Ahmedabad', 'Gujarat'),
('S02', 'Rajkot Junction',    'Rajkot',    'Gujarat'),
('S03', 'Vadodara Junction',  'Vadodara',  'Gujarat'),
('S04', 'Surat',              'Surat',     'Gujarat'),
('S05', 'Jamnagar',           'Jamnagar',  'Gujarat'),
('S06', 'Mumbai Central',     'Mumbai',    'Maharashtra'),
('S07', 'New Delhi',          'Delhi',     'Delhi'),
('S08', 'Bhopal Junction',    'Bhopal',    'Madhya Pradesh'),
('S09', 'Jaipur Junction',    'Jaipur',    'Rajasthan'),
('S10', 'Howrah Junction',    'Kolkata',   'West Bengal');

INSERT IGNORE INTO Trains (train_id, train_number, train_name, source_station_id, destination_station_id, departure_time, arrival_time) VALUES
('T01', 12951, 'Mumbai Rajdhani',          'S06', 'S07', '16:35:00', '08:35:00'),
('T02', 12952, 'Delhi Mumbai Rajdhani',    'S07', 'S06', '16:55:00', '08:15:00'),
('T03', 12926, 'Paschim Express',          'S07', 'S06', '16:10:00', '17:40:00'),
('T04', 12957, 'Swarna Jayanti Rajdhani',  'S01', 'S07', '19:40:00', '10:05:00'),
('T05', 12958, 'Delhi Ahmedabad Rajdhani', 'S07', 'S01', '19:55:00', '10:30:00'),
('T06', 12009, 'Shatabdi Express',         'S01', 'S06', '06:10:00', '12:40:00'),
('T07', 12010, 'Mumbai Ahmedabad Shatabdi','S06', 'S01', '14:40:00', '21:10:00'),
('T08', 12155, 'Bhopal Express',           'S08', 'S07', '22:00:00', '07:30:00'),
('T09', 12156, 'Delhi Bhopal Express',     'S07', 'S08', '21:15:00', '06:45:00'),
('T10', 12915, 'Ashram Express',           'S01', 'S09', '18:30:00', '06:00:00');

INSERT IGNORE INTO TrainClasses (train_class_id, train_id, class_name, fare, total_seats) VALUES
('TC01', 'T01', 'sleeper',   900, 100),
('TC02', 'T01', '3ac',      1800,  60),
('TC03', 'T01', '2ac',      2500,  40),
('TC04', 'T01', '1ac',      4200,  20),
('TC05', 'T02', '3ac',      1800,  60),
('TC06', 'T02', '2ac',      2500,  40),
('TC07', 'T03', 'sleeper',   850, 120),
('TC08', 'T03', '3ac',      1750,  70),
('TC09', 'T04', '3ac',      1700,  50),
('TC10', 'T04', '2ac',      2400,  36),
('TC11', 'T05', '3ac',      1700,  50),
('TC12', 'T05', '2ac',      2400,  36),
('TC13', 'T06', 'chair-car', 700,  80),
('TC14', 'T07', 'chair-car', 700,  80),
('TC15', 'T08', 'sleeper',   600, 150),
('TC16', 'T08', '3ac',      1500,  60),
('TC17', 'T09', 'sleeper',   600, 150),
('TC18', 'T09', '3ac',      1500,  60),
('TC19', 'T10', 'sleeper',   550, 140),
('TC20', 'T10', '2ac',      1900,  40);
