import sqlite3

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()


def _ensure_likes_created_at_column():
    cursor.execute("PRAGMA table_info(likes)")
    columns = [row[1] for row in cursor.fetchall()]
    if "created_at" not in columns:
        cursor.execute("ALTER TABLE likes ADD COLUMN created_at TEXT")
        cursor.execute(
            "UPDATE likes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )


def init_db():
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age TEXT NOT NULL,
            city TEXT NOT NULL,
            about TEXT NOT NULL,
            photo TEXT NOT NULL,
            lat REAL,
            lon REAL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS likes (
            user_from INTEGER NOT NULL,
            user_to INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_from, user_to)
        )
        """
    )

    _ensure_likes_created_at_column()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            UNIQUE(user1, user2)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS skips (
            user_from INTEGER NOT NULL,
            user_to INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_from, user_to)
        )
        """
    )

    conn.commit()


def add_user(user_id, name, age, city, about, photo, lat, lon):
    cursor.execute(
        """
        INSERT INTO users (user_id, name, age, city, about, photo, lat, lon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            age=excluded.age,
            city=excluded.city,
            about=excluded.about,
            photo=excluded.photo,
            lat=excluded.lat,
            lon=excluded.lon
        """,
        (user_id, name, age, city, about, photo, lat, lon),
    )
    conn.commit()


def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()


def get_search_candidates(user_id, like_cooldown_days=5, skip_cooldown_days=1):
    like_interval = f"-{int(like_cooldown_days)} days"
    skip_interval = f"-{int(skip_cooldown_days)} days"
    cursor.execute(
        """
        SELECT u.*
        FROM users u
        WHERE u.user_id != ?
          AND NOT EXISTS (
              SELECT 1
              FROM likes l
              WHERE l.user_from = ?
                AND l.user_to = u.user_id
                AND datetime(l.created_at) > datetime('now', ?)
          )
          AND NOT EXISTS (
              SELECT 1
              FROM skips s
              WHERE s.user_from = ?
                AND s.user_to = u.user_id
                AND datetime(s.created_at) > datetime('now', ?)
          )
        """,
        (user_id, user_id, like_interval, user_id, skip_interval),
    )
    return cursor.fetchall()


def add_like(user_from, user_to):
    cursor.execute(
        """
        INSERT INTO likes (user_from, user_to, created_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = CURRENT_TIMESTAMP
        """,
        (user_from, user_to),
    )
    conn.commit()


def add_skip(user_from, user_to):
    cursor.execute(
        """
        INSERT INTO skips (user_from, user_to, created_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = CURRENT_TIMESTAMP
        """,
        (user_from, user_to),
    )
    conn.commit()


def is_match(user1, user2):
    cursor.execute(
        "SELECT 1 FROM likes WHERE user_from = ? AND user_to = ?",
        (user2, user1),
    )
    return cursor.fetchone() is not None


def create_match(user1, user2):
    cursor.execute(
        "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
        (user1, user2),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
        (user2, user1),
    )
    conn.commit()


def get_matches(user_id):
    cursor.execute("SELECT user2 FROM matches WHERE user1 = ?", (user_id,))
    return cursor.fetchall()
