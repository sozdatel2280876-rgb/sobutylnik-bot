import os
import sqlite3

DB_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = bool(DB_URL)

if IS_POSTGRES:
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError("Install psycopg to use DATABASE_URL") from exc

    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

    conn = psycopg.connect(DB_URL)
    conn.autocommit = True
else:
    conn = sqlite3.connect("database.db", check_same_thread=False)


def _exec(query_sqlite, params=(), query_pg=None):
    query = query_pg if IS_POSTGRES and query_pg else query_sqlite
    cur = conn.cursor()
    try:
        cur.execute(query, params)
    finally:
        cur.close()


def _fetchone(query_sqlite, params=(), query_pg=None):
    query = query_pg if IS_POSTGRES and query_pg else query_sqlite
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        cur.close()


def _fetchall(query_sqlite, params=(), query_pg=None):
    query = query_pg if IS_POSTGRES and query_pg else query_sqlite
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        cur.close()


def _commit_if_needed():
    if not IS_POSTGRES:
        conn.commit()


def _ensure_likes_created_at_column_sqlite():
    row_data = _fetchall("PRAGMA table_info(likes)")
    columns = [row[1] for row in row_data]
    if "created_at" not in columns:
        _exec("ALTER TABLE likes ADD COLUMN created_at TEXT")
        _exec("UPDATE likes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        _commit_if_needed()


def init_db():
    _exec(
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
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            age TEXT NOT NULL,
            city TEXT NOT NULL,
            about TEXT NOT NULL,
            photo TEXT NOT NULL,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION
        )
        """,
    )

    _exec(
        """
        CREATE TABLE IF NOT EXISTS likes (
            user_from INTEGER NOT NULL,
            user_to INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_from, user_to)
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS likes (
            user_from BIGINT NOT NULL,
            user_to BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_from, user_to)
        )
        """,
    )

    if not IS_POSTGRES:
        _ensure_likes_created_at_column_sqlite()

    _exec(
        """
        CREATE TABLE IF NOT EXISTS matches (
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            UNIQUE(user1, user2)
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS matches (
            user1 BIGINT NOT NULL,
            user2 BIGINT NOT NULL,
            UNIQUE(user1, user2)
        )
        """,
    )

    _exec(
        """
        CREATE TABLE IF NOT EXISTS skips (
            user_from INTEGER NOT NULL,
            user_to INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_from, user_to)
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS skips (
            user_from BIGINT NOT NULL,
            user_to BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_from, user_to)
        )
        """,
    )

    _commit_if_needed()


def add_user(user_id, name, age, city, about, photo, lat, lon):
    _exec(
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
        query_pg="""
        INSERT INTO users (user_id, name, age, city, about, photo, lat, lon)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            age=excluded.age,
            city=excluded.city,
            about=excluded.about,
            photo=excluded.photo,
            lat=excluded.lat,
            lon=excluded.lon
        """,
    )
    _commit_if_needed()


def get_user(user_id):
    return _fetchone(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
        query_pg="SELECT * FROM users WHERE user_id = %s",
    )


def get_search_candidates(user_id, like_cooldown_days=5, skip_cooldown_days=1):
    like_days = int(like_cooldown_days)
    skip_days = int(skip_cooldown_days)

    if IS_POSTGRES:
        return _fetchall(
            """
            SELECT u.*
            FROM users u
            WHERE u.user_id != %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM likes l
                  WHERE l.user_from = %s
                    AND l.user_to = u.user_id
                    AND l.created_at > NOW() - (%s || ' days')::INTERVAL
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM skips s
                  WHERE s.user_from = %s
                    AND s.user_to = u.user_id
                    AND s.created_at > NOW() - (%s || ' days')::INTERVAL
              )
            """,
            (user_id, user_id, like_days, user_id, skip_days),
        )

    return _fetchall(
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
        (user_id, user_id, f"-{like_days} days", user_id, f"-{skip_days} days"),
    )


def add_like(user_from, user_to):
    _exec(
        """
        INSERT INTO likes (user_from, user_to, created_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = CURRENT_TIMESTAMP
        """,
        (user_from, user_to),
        query_pg="""
        INSERT INTO likes (user_from, user_to, created_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = NOW()
        """,
    )
    _commit_if_needed()


def add_skip(user_from, user_to):
    _exec(
        """
        INSERT INTO skips (user_from, user_to, created_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = CURRENT_TIMESTAMP
        """,
        (user_from, user_to),
        query_pg="""
        INSERT INTO skips (user_from, user_to, created_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT(user_from, user_to)
        DO UPDATE SET created_at = NOW()
        """,
    )
    _commit_if_needed()


def is_match(user1, user2):
    row = _fetchone(
        "SELECT 1 FROM likes WHERE user_from = ? AND user_to = ?",
        (user2, user1),
        query_pg="SELECT 1 FROM likes WHERE user_from = %s AND user_to = %s",
    )
    return row is not None


def create_match(user1, user2):
    _exec(
        "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
        (user1, user2),
        query_pg="INSERT INTO matches (user1, user2) VALUES (%s, %s) ON CONFLICT DO NOTHING",
    )
    _exec(
        "INSERT OR IGNORE INTO matches (user1, user2) VALUES (?, ?)",
        (user2, user1),
        query_pg="INSERT INTO matches (user1, user2) VALUES (%s, %s) ON CONFLICT DO NOTHING",
    )
    _commit_if_needed()


def get_matches(user_id):
    return _fetchall(
        "SELECT user2 FROM matches WHERE user1 = ?",
        (user_id,),
        query_pg="SELECT user2 FROM matches WHERE user1 = %s",
    )
