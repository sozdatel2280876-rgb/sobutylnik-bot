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


def _sqlite_column_exists(table_name, column_name):
    rows = _fetchall(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in rows]
    return column_name in columns


def _ensure_sqlite_schema_compat():
    if not _sqlite_column_exists("users", "created_at"):
        _exec("ALTER TABLE users ADD COLUMN created_at TEXT")
        _exec("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

    if not _sqlite_column_exists("likes", "created_at"):
        _exec("ALTER TABLE likes ADD COLUMN created_at TEXT")
        _exec("UPDATE likes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

    if not _sqlite_column_exists("skips", "created_at"):
        _exec("ALTER TABLE skips ADD COLUMN created_at TEXT")
        _exec("UPDATE skips SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

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
            lon REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            lon DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

    _exec(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS reports (
            id BIGSERIAL PRIMARY KEY,
            reporter_id BIGINT NOT NULL,
            target_id BIGINT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _exec(
        """
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            banned_by INTEGER,
            banned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id BIGINT PRIMARY KEY,
            reason TEXT NOT NULL,
            banned_by BIGINT,
            banned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _exec(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            user_id INTEGER NOT NULL,
            reminder_type TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, reminder_type)
        )
        """,
        query_pg="""
        CREATE TABLE IF NOT EXISTS reminders (
            user_id BIGINT NOT NULL,
            reminder_type TEXT NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, reminder_type)
        )
        """,
    )

    _exec(
        "SELECT 1",
        query_pg="""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """,
    )

    if not IS_POSTGRES:
        _ensure_sqlite_schema_compat()

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


def is_banned(user_id):
    row = _fetchone(
        "SELECT 1 FROM banned_users WHERE user_id = ?",
        (user_id,),
        query_pg="SELECT 1 FROM banned_users WHERE user_id = %s",
    )
    return row is not None


def ban_user(user_id, banned_by, reason):
    _exec(
        """
        INSERT INTO banned_users (user_id, reason, banned_by, banned_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            reason=excluded.reason,
            banned_by=excluded.banned_by,
            banned_at=CURRENT_TIMESTAMP
        """,
        (user_id, reason, banned_by),
        query_pg="""
        INSERT INTO banned_users (user_id, reason, banned_by, banned_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT(user_id) DO UPDATE SET
            reason=excluded.reason,
            banned_by=excluded.banned_by,
            banned_at=NOW()
        """,
    )
    _commit_if_needed()


def unban_user(user_id):
    _exec(
        "DELETE FROM banned_users WHERE user_id = ?",
        (user_id,),
        query_pg="DELETE FROM banned_users WHERE user_id = %s",
    )
    _commit_if_needed()


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
                  FROM banned_users b
                  WHERE b.user_id = u.user_id
              )
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
              AND NOT EXISTS (
                  SELECT 1
                  FROM reports r
                  WHERE r.reporter_id = %s
                    AND r.target_id = u.user_id
                    AND r.status = 'open'
              )
            """,
            (user_id, user_id, like_days, user_id, skip_days, user_id),
        )

    return _fetchall(
        """
        SELECT u.*
        FROM users u
        WHERE u.user_id != ?
          AND NOT EXISTS (
              SELECT 1
              FROM banned_users b
              WHERE b.user_id = u.user_id
          )
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
          AND NOT EXISTS (
              SELECT 1
              FROM reports r
              WHERE r.reporter_id = ?
                AND r.target_id = u.user_id
                AND r.status = 'open'
          )
        """,
        (user_id, user_id, f"-{like_days} days", user_id, f"-{skip_days} days", user_id),
    )


def like_exists(user_from, user_to):
    row = _fetchone(
        "SELECT 1 FROM likes WHERE user_from = ? AND user_to = ?",
        (user_from, user_to),
        query_pg="SELECT 1 FROM likes WHERE user_from = %s AND user_to = %s",
    )
    return row is not None


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


def add_report(reporter_id, target_id, reason):
    existing = _fetchone(
        """
        SELECT id
        FROM reports
        WHERE reporter_id = ? AND target_id = ? AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """,
        (reporter_id, target_id),
        query_pg="""
        SELECT id
        FROM reports
        WHERE reporter_id = %s AND target_id = %s AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """,
    )

    if existing:
        report_id = existing[0]
        _exec(
            """
            UPDATE reports
            SET reason = ?, created_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reason, report_id),
            query_pg="""
            UPDATE reports
            SET reason = %s, created_at = NOW()
            WHERE id = %s
            """,
        )
    else:
        _exec(
            """
            INSERT INTO reports (reporter_id, target_id, reason, status, created_at)
            VALUES (?, ?, ?, 'open', CURRENT_TIMESTAMP)
            """,
            (reporter_id, target_id, reason),
            query_pg="""
            INSERT INTO reports (reporter_id, target_id, reason, status, created_at)
            VALUES (%s, %s, %s, 'open', NOW())
            """,
        )
    _commit_if_needed()


def resolve_reports_for_user(target_id):
    _exec(
        """
        UPDATE reports
        SET status = 'resolved'
        WHERE target_id = ? AND status = 'open'
        """,
        (target_id,),
        query_pg="""
        UPDATE reports
        SET status = 'resolved'
        WHERE target_id = %s AND status = 'open'
        """,
    )
    _commit_if_needed()


def get_open_reports(limit=20):
    if IS_POSTGRES:
        return _fetchall(
            """
            SELECT target_id, COUNT(*) AS reports_count, MAX(created_at) AS last_report_at
            FROM reports
            WHERE status = 'open'
            GROUP BY target_id
            ORDER BY reports_count DESC, last_report_at DESC
            LIMIT %s
            """,
            (int(limit),),
        )

    return _fetchall(
        """
        SELECT target_id, COUNT(*) AS reports_count, MAX(created_at) AS last_report_at
        FROM reports
        WHERE status = 'open'
        GROUP BY target_id
        ORDER BY reports_count DESC, last_report_at DESC
        LIMIT ?
        """,
        (int(limit),),
    )


def get_inactive_users_for_like_reminder(days=3, remind_cooldown_hours=24, limit=200):
    days = int(days)
    remind_cooldown_hours = int(remind_cooldown_hours)
    limit = int(limit)

    if IS_POSTGRES:
        return _fetchall(
            """
            SELECT u.user_id
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM banned_users b WHERE b.user_id = u.user_id
            )
              AND COALESCE(
                    (SELECT MAX(l.created_at) FROM likes l WHERE l.user_from = u.user_id),
                    u.created_at
                  ) <= NOW() - (%s || ' days')::INTERVAL
              AND NOT EXISTS (
                    SELECT 1
                    FROM reminders r
                    WHERE r.user_id = u.user_id
                      AND r.reminder_type = 'inactive_like'
                      AND r.sent_at > NOW() - (%s || ' hours')::INTERVAL
              )
            LIMIT %s
            """,
            (days, remind_cooldown_hours, limit),
        )

    return _fetchall(
        """
        SELECT u.user_id
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM banned_users b WHERE b.user_id = u.user_id
        )
          AND COALESCE(
                (SELECT MAX(datetime(l.created_at)) FROM likes l WHERE l.user_from = u.user_id),
                datetime(u.created_at)
              ) <= datetime('now', ?)
          AND NOT EXISTS (
                SELECT 1
                FROM reminders r
                WHERE r.user_id = u.user_id
                  AND r.reminder_type = 'inactive_like'
                  AND datetime(r.sent_at) > datetime('now', ?)
          )
        LIMIT ?
        """,
        (f"-{days} days", f"-{remind_cooldown_hours} hours", limit),
    )


def mark_reminder_sent(user_id, reminder_type="inactive_like"):
    _exec(
        """
        INSERT INTO reminders (user_id, reminder_type, sent_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, reminder_type)
        DO UPDATE SET sent_at = CURRENT_TIMESTAMP
        """,
        (user_id, reminder_type),
        query_pg="""
        INSERT INTO reminders (user_id, reminder_type, sent_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT(user_id, reminder_type)
        DO UPDATE SET sent_at = NOW()
        """,
    )
    _commit_if_needed()


def get_stats_snapshot():
    users_total = int(
        _fetchone(
            "SELECT COUNT(*) FROM users",
            query_pg="SELECT COUNT(*) FROM users",
        )[0]
        or 0
    )
    banned_total = int(
        _fetchone(
            "SELECT COUNT(*) FROM banned_users",
            query_pg="SELECT COUNT(*) FROM banned_users",
        )[0]
        or 0
    )
    open_reports_total = int(
        _fetchone(
            "SELECT COUNT(*) FROM reports WHERE status = 'open'",
            query_pg="SELECT COUNT(*) FROM reports WHERE status = 'open'",
        )[0]
        or 0
    )

    if IS_POSTGRES:
        likes_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM likes WHERE created_at > NOW() - INTERVAL '1 day'",
                query_pg="SELECT COUNT(*) FROM likes WHERE created_at > NOW() - INTERVAL '1 day'",
            )[0]
            or 0
        )
        skips_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM skips WHERE created_at > NOW() - INTERVAL '1 day'",
                query_pg="SELECT COUNT(*) FROM skips WHERE created_at > NOW() - INTERVAL '1 day'",
            )[0]
            or 0
        )
        reports_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM reports WHERE created_at > NOW() - INTERVAL '1 day'",
                query_pg="SELECT COUNT(*) FROM reports WHERE created_at > NOW() - INTERVAL '1 day'",
            )[0]
            or 0
        )
    else:
        likes_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM likes WHERE datetime(created_at) > datetime('now', '-1 day')"
            )[0]
            or 0
        )
        skips_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM skips WHERE datetime(created_at) > datetime('now', '-1 day')"
            )[0]
            or 0
        )
        reports_24h = int(
            _fetchone(
                "SELECT COUNT(*) FROM reports WHERE datetime(created_at) > datetime('now', '-1 day')"
            )[0]
            or 0
        )

    match_rows = int(
        _fetchone(
            "SELECT COUNT(*) FROM matches",
            query_pg="SELECT COUNT(*) FROM matches",
        )[0]
        or 0
    )
    matches_total = match_rows // 2

    return {
        "users_total": users_total,
        "banned_total": banned_total,
        "open_reports_total": open_reports_total,
        "likes_24h": likes_24h,
        "skips_24h": skips_24h,
        "reports_24h": reports_24h,
        "matches_total": matches_total,
    }


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
