import sqlite3


def init_db():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()

    # 1. Kinolar jadvali (YANGILANGAN)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT UNIQUE,
            title TEXT,
            file_id TEXT,
            category TEXT,
            genre TEXT,
            year TEXT,
            views INTEGER DEFAULT 0
        )
    """)
    # 2. Kanallar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT UNIQUE,
            channel_url TEXT
        )
    """)
    # 3. Foydalanuvchilar jadvali (REFERAL QO'SHILDI)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER
        )
    """)
    # 4. Adminlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            admin_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


# --- ADMINLAR FUNKSIYALARI ---
def add_admin_to_db(admin_id):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO bot_admins (admin_id) VALUES (?)", (admin_id,))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success


def get_all_admins():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM bot_admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins


def delete_admin_from_db(admin_id):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_admins WHERE admin_id = ?", (admin_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# --- FOYDALANUVCHI VA REFERAL ---
def add_user_to_db(user_id, referrer_id=None):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_users_count():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_referral_count(user_id):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_users():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


# --- KINOLAR FUNKSIYALARI ---
def add_movie_to_db(code, title, file_id, category, genre, year):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO movies (code, title, file_id, category, genre, year) VALUES (?, ?, ?, ?, ?, ?)",
                       (code, title, file_id, category, genre, year))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success


def get_movie(code):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title, file_id, category, genre, year, views FROM movies WHERE code = ?", (code,))
    result = cursor.fetchone()
    if result:
        # Ko'rishlar sonini bittaga oshiramiz
        cursor.execute("UPDATE movies SET views = views + 1 WHERE code = ?", (code,))
        conn.commit()
    conn.close()
    return result


def get_random_movie():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, title FROM movies ORDER BY RANDOM() LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result


def get_top_movies():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, title, views FROM movies ORDER BY views DESC LIMIT 10")
    result = cursor.fetchall()
    conn.close()
    return result


def search_movies_by_title(search_text):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, title, category FROM movies WHERE title LIKE ?", (f"%{search_text}%",))
    results = cursor.fetchall()
    conn.close()
    return results


def delete_movie_from_db(code):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM movies WHERE code = ?", (code,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# --- KANALLAR FUNKSIYALARI ---
def add_channel_to_db(channel_id, channel_url):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO channels (channel_id, channel_url) VALUES (?, ?)", (channel_id, channel_url))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success


def get_all_channels():
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_url FROM channels")
    result = cursor.fetchall()
    conn.close()
    return result


def delete_channel_from_db(channel_id):
    conn = sqlite3.connect("kinolar.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()