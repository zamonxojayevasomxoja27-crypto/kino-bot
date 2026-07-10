import sqlite3
import time

DB_NAME = "kinolar.db"


def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # 1. Kinolar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT UNIQUE,
            title TEXT,
            file_id TEXT,
            category TEXT,
            genre TEXT,
            year TEXT,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            added_at INTEGER
        )
    """)

    # 2. Kanallar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT UNIQUE,
            channel_url TEXT
        )
    """)

    # 3. Foydalanuvchilar jadvali (referal + VIP)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            vip_until INTEGER DEFAULT 0
        )
    """)

    # 4. Adminlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            admin_id INTEGER PRIMARY KEY
        )
    """)

    # 5. Kim qaysi kinoga like/dislike bosganini saqlaydi (qayta bosishni oldini olish uchun)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movie_reactions (
            user_id INTEGER,
            movie_code TEXT,
            reaction TEXT,
            PRIMARY KEY (user_id, movie_code)
        )
    """)

    conn.commit()

    # Eski bazalarda ustunlar yo'q bo'lishi mumkin (migratsiya)
    _ensure_column(cursor, "movies", "likes", "INTEGER DEFAULT 0")
    _ensure_column(cursor, "movies", "dislikes", "INTEGER DEFAULT 0")
    _ensure_column(cursor, "movies", "added_at", "INTEGER")
    _ensure_column(cursor, "users", "vip_until", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


def _ensure_column(cursor, table, column, coltype):
    """Agar ustun mavjud bo'lmasa qo'shadi (eski bazalarni buzmasdan yangilash uchun)."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = [row[1] for row in cursor.fetchall()]
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


# ================= ADMINLAR =================

def add_admin_to_db(admin_id):
    conn = get_conn()
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
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM bot_admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins


def delete_admin_from_db(admin_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_admins WHERE admin_id = ?", (admin_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ================= FOYDALANUVCHI VA REFERAL =================

def add_user_to_db(user_id, referrer_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (user_id, referrer_id) VALUES (?, ?)",
            (user_id, referrer_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_users_count():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_referral_count(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_users():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


# ================= VIP FUNKSIYALARI =================

def set_vip(user_id, days):
    """Foydalanuvchiga hozirgi vaqtdan boshlab `days` kunlik VIP beradi.
    Agar allaqachon VIP bo'lsa, muddat ustiga qo'shiladi (uzaytiradi)."""
    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("SELECT vip_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        # Agar foydalanuvchi bazada bo'lmasa (hali /start bosmagan), avval qo'shamiz
        cursor.execute(
            "INSERT INTO users (user_id, referrer_id, vip_until) VALUES (?, NULL, ?)",
            (user_id, now + days * 86400)
        )
    else:
        current_until = row[0] or 0
        base = current_until if current_until > now else now
        new_until = base + days * 86400
        cursor.execute("UPDATE users SET vip_until = ? WHERE user_id = ?", (new_until, user_id))
    conn.commit()
    conn.close()
    return True


def remove_vip(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET vip_until = 0 WHERE user_id = ?", (user_id,))
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def is_vip(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT vip_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    return row[0] > int(time.time())


def get_vip_until(user_id):
    """VIP tugash vaqtini unix timestamp sifatida qaytaradi, yoki 0 agar VIP bo'lmasa."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT vip_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return 0
    return row[0]


def get_all_vip_users():
    """Hozir faol VIP bo'lgan barcha foydalanuvchilarni qaytaradi: (user_id, vip_until)."""
    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("SELECT user_id, vip_until FROM users WHERE vip_until > ?", (now,))
    result = cursor.fetchall()
    conn.close()
    return result


# ================= KINOLAR FUNKSIYALARI =================

def add_movie_to_db(code, category, genre, year, title, file_id):
    """Eslatma: parametrlar tartibi main.py dagi FSM oqimiga mos: code, category, genre, year, title, file_id."""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO movies (code, title, file_id, category, genre, year, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(code), title, file_id, category, genre, year, int(time.time()))
        )
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success


def update_movie_in_db(code, category=None, genre=None, year=None, title=None, file_id=None):
    """Faqat berilgan (None bo'lmagan) maydonlarni yangilaydi. Kino topilsa True qaytaradi."""
    conn = get_conn()
    cursor = conn.cursor()

    fields = []
    values = []
    if category is not None:
        fields.append("category = ?")
        values.append(category)
    if genre is not None:
        fields.append("genre = ?")
        values.append(genre)
    if year is not None:
        fields.append("year = ?")
        values.append(year)
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if file_id is not None:
        fields.append("file_id = ?")
        values.append(file_id)

    if not fields:
        conn.close()
        return False

    values.append(str(code))
    cursor.execute(f"UPDATE movies SET {', '.join(fields)} WHERE code = ?", values)
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def get_movie(code):
    """Qaytaradi: (code, category, genre, year, title, file_id, views, likes, dislikes) yoki None.
    main.py bu tartibga mos: movie[0]=code, movie[2]=genre, movie[3]=year, movie[4]=title, movie[5]=file_id."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT code, category, genre, year, title, file_id, views, likes, dislikes
           FROM movies WHERE code = ?""",
        (str(code),)
    )
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE movies SET views = views + 1 WHERE code = ?", (str(code),))
        conn.commit()
    conn.close()
    return result


def get_movie_no_view_increment(code):
    """get_movie bilan bir xil, lekin views sonini oshirmaydi (masalan tahrirlashdan oldin ko'rish uchun)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT code, category, genre, year, title, file_id, views, likes, dislikes
           FROM movies WHERE code = ?""",
        (str(code),)
    )
    result = cursor.fetchone()
    conn.close()
    return result


def get_random_movie():
    """Qaytaradi: (code, category, genre, year, title, file_id) — get_movie bilan bir xil tartib (views/likes siz)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, category, genre, year, title, file_id FROM movies ORDER BY RANDOM() LIMIT 1"
    )
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE movies SET views = views + 1 WHERE code = ?", (result[0],))
        conn.commit()
    conn.close()
    return result


def get_top_movies(limit=10, offset=0):
    """Pagination uchun offset qo'shildi. Qaytaradi: (code, title, views)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, views FROM movies ORDER BY views DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    result = cursor.fetchall()
    conn.close()
    return result


def get_movies_count():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def search_movies_by_title(search_text, limit=10, offset=0):
    """Pagination bilan. Qaytaradi: (code, title, category)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE title LIKE ? ORDER BY views DESC LIMIT ? OFFSET ?",
        (f"%{search_text}%", limit, offset)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def search_movies_count(search_text):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE title LIKE ?", (f"%{search_text}%",))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_movies_by_genre(genre, limit=10, offset=0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE genre = ? ORDER BY views DESC LIMIT ? OFFSET ?",
        (genre, limit, offset)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_movies_by_genre_count(genre):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE genre = ?", (genre,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_genres():
    """Bazadagi barcha noyob janrlar ro'yxatini qaytaradi (bo'sh bo'lmaganlar)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT genre FROM movies WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
    )
    genres = [row[0] for row in cursor.fetchall()]
    conn.close()
    return genres


def get_movies_by_category(category, limit=10, offset=0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE category = ? ORDER BY views DESC LIMIT ? OFFSET ?",
        (category, limit, offset)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_movies_by_category_count(category):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE category = ?", (category,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_categories():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT category FROM movies WHERE category IS NOT NULL AND category != '' ORDER BY category"
    )
    categories = [row[0] for row in cursor.fetchall()]
    conn.close()
    return categories


def delete_movie_from_db(code):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM movies WHERE code = ?", (str(code),))
    deleted = cursor.rowcount
    cursor.execute("DELETE FROM movie_reactions WHERE movie_code = ?", (str(code),))
    conn.commit()
    conn.close()
    return deleted > 0


# ================= LIKE / DISLIKE =================

def react_to_movie(user_id, code, reaction):
    """reaction: 'like' yoki 'dislike'.
    Qaytaradi: (holat, yangi_likes, yangi_dislikes)
    holat: 'added', 'changed', 'removed' (agar xuddi shu tugma qayta bosilsa, reaksiya olib tashlanadi)."""
    conn = get_conn()
    cursor = conn.cursor()
    code = str(code)

    cursor.execute(
        "SELECT reaction FROM movie_reactions WHERE user_id = ? AND movie_code = ?",
        (user_id, code)
    )
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute(
            "INSERT INTO movie_reactions (user_id, movie_code, reaction) VALUES (?, ?, ?)",
            (user_id, code, reaction)
        )
        column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {column} = {column} + 1 WHERE code = ?", (code,))
        status = "added"
    elif existing[0] == reaction:
        cursor.execute(
            "DELETE FROM movie_reactions WHERE user_id = ? AND movie_code = ?",
            (user_id, code)
        )
        column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {column} = MAX({column} - 1, 0) WHERE code = ?", (code,))
        status = "removed"
    else:
        cursor.execute(
            "UPDATE movie_reactions SET reaction = ? WHERE user_id = ? AND movie_code = ?",
            (reaction, user_id, code)
        )
        old_column = "dislikes" if reaction == "like" else "likes"
        new_column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {old_column} = MAX({old_column} - 1, 0) WHERE code = ?", (code,))
        cursor.execute(f"UPDATE movies SET {new_column} = {new_column} + 1 WHERE code = ?", (code,))
        status = "changed"

    conn.commit()
    cursor.execute("SELECT likes, dislikes FROM movies WHERE code = ?", (code,))
    row = cursor.fetchone()
    conn.close()
    likes, dislikes = row if row else (0, 0)
    return status, likes, dislikes


def get_user_reaction(user_id, code):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT reaction FROM movie_reactions WHERE user_id = ? AND movie_code = ?",
        (user_id, str(code))
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


# ================= KANALLAR FUNKSIYALARI =================

def add_channel_to_db(channel_id, channel_url):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO channels (channel_id, channel_url) VALUES (?, ?)",
            (channel_id, channel_url)
        )
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success


def get_all_channels():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_url FROM channels")
    result = cursor.fetchall()
    conn.close()
    return result


def delete_channel_from_db(channel_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0
