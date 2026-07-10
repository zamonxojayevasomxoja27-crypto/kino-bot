import os
import time
import psycopg2
import psycopg2.extensions
from psycopg2 import errors as pg_errors
from psycopg2.pool import SimpleConnectionPool

# Render "Internal Database URL" ni DATABASE_URL nomli environment variable orqali beradi.
# Masalan: postgresql://user:password@host/dbname
DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL environment variable topilmadi. "
                "Render'da PostgreSQL yaratib, uning Internal Database URL manzilini "
                "DATABASE_URL nomi bilan Environment bo'limiga qo'shing."
            )
        _pool = SimpleConnectionPool(1, 10, dsn=DATABASE_URL, sslmode="require")
    return _pool


def get_conn():
    return _get_pool().getconn()


def _put_conn(conn):
    _get_pool().putconn(conn)


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
            added_at BIGINT
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
            user_id BIGINT PRIMARY KEY,
            referrer_id BIGINT,
            vip_until BIGINT DEFAULT 0
        )
    """)

    # 4. Adminlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            admin_id BIGINT PRIMARY KEY
        )
    """)

    # 5. Kim qaysi kinoga like/dislike bosganini saqlaydi (qayta bosishni oldini olish uchun)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movie_reactions (
            user_id BIGINT,
            movie_code TEXT,
            reaction TEXT,
            PRIMARY KEY (user_id, movie_code)
        )
    """)

    # 6. Serial qismlari (har bir kino/serial bir yoki bir necha qismdan iborat bo'lishi mumkin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id SERIAL PRIMARY KEY,
            movie_code TEXT NOT NULL,
            episode_number INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            UNIQUE (movie_code, episode_number)
        )
    """)

    # 7. Foydalanuvchining har bir serialda qaysi qismda to'xtaganini eslab qolish
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_progress (
            user_id BIGINT NOT NULL,
            movie_code TEXT NOT NULL,
            last_episode INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, movie_code)
        )
    """)

    conn.commit()

    # Eski bazalarda ustunlar yo'q bo'lishi mumkin (migratsiya)
    _ensure_column(cursor, conn, "movies", "likes", "INTEGER DEFAULT 0")
    _ensure_column(cursor, conn, "movies", "dislikes", "INTEGER DEFAULT 0")
    _ensure_column(cursor, conn, "movies", "added_at", "BIGINT")
    _ensure_column(cursor, conn, "users", "vip_until", "BIGINT DEFAULT 0")

    conn.commit()

    # Eski bazada mavjud bo'lgan kinolarning file_id'sini episodes jadvaliga 1-qism sifatida ko'chiramiz
    # (faqat hali episodes jadvalida yozuvi yo'q kinolar uchun, xavfsiz migratsiya)
    cursor.execute("""
        INSERT INTO episodes (movie_code, episode_number, file_id)
        SELECT code, 1, file_id FROM movies
        WHERE file_id IS NOT NULL
        ON CONFLICT (movie_code, episode_number) DO NOTHING
    """)
    conn.commit()

    cursor.close()
    _put_conn(conn)


def _ensure_column(cursor, conn, table, column, coltype):
    """Agar ustun mavjud bo'lmasa qo'shadi (eski bazalarni buzmasdan yangilash uchun)."""
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_name = %s AND column_name = %s""",
        (table, column)
    )
    if cursor.fetchone() is None:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()


# ================= ADMINLAR =================

def add_admin_to_db(admin_id):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO bot_admins (admin_id) VALUES (%s)", (admin_id,))
        conn.commit()
        success = True
    except pg_errors.UniqueViolation:
        conn.rollback()
        success = False
    cursor.close()
    _put_conn(conn)
    return success


def get_all_admins():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM bot_admins")
    admins = [row[0] for row in cursor.fetchall()]
    cursor.close()
    _put_conn(conn)
    return admins


def delete_admin_from_db(admin_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bot_admins WHERE admin_id = %s", (admin_id,))
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return deleted > 0


# ================= FOYDALANUVCHI VA REFERAL =================

def add_user_to_db(user_id, referrer_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (user_id, referrer_id) VALUES (%s, %s)",
            (user_id, referrer_id)
        )
        conn.commit()
        return True
    except pg_errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        cursor.close()
        _put_conn(conn)


def get_users_count():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users")
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_referral_count(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users WHERE referrer_id = %s", (user_id,))
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_all_users():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    cursor.close()
    _put_conn(conn)
    return users


# ================= VIP FUNKSIYALARI =================

def set_vip(user_id, days):
    """Foydalanuvchiga hozirgi vaqtdan boshlab `days` kunlik VIP beradi.
    Agar allaqachon VIP bo'lsa, muddat ustiga qo'shiladi (uzaytiradi)."""
    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if row is None:
        # Agar foydalanuvchi bazada bo'lmasa (hali /start bosmagan), avval qo'shamiz
        cursor.execute(
            "INSERT INTO users (user_id, referrer_id, vip_until) VALUES (%s, NULL, %s)",
            (user_id, now + days * 86400)
        )
    else:
        current_until = row[0] or 0
        base = current_until if current_until > now else now
        new_until = base + days * 86400
        cursor.execute("UPDATE users SET vip_until = %s WHERE user_id = %s", (new_until, user_id))
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return True


def remove_vip(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET vip_until = 0 WHERE user_id = %s", (user_id,))
    updated = cursor.rowcount
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return updated > 0


def is_vip(user_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    if not row or not row[0]:
        return False
    return row[0] > int(time.time())


def get_vip_until(user_id):
    """VIP tugash vaqtini unix timestamp sifatida qaytaradi, yoki 0 agar VIP bo'lmasa."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    if not row or not row[0]:
        return 0
    return row[0]


def get_all_vip_users():
    """Hozir faol VIP bo'lgan barcha foydalanuvchilarni qaytaradi: (user_id, vip_until)."""
    conn = get_conn()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("SELECT user_id, vip_until FROM users WHERE vip_until > %s", (now,))
    result = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return result


# ================= KINOLAR FUNKSIYALARI =================

def add_movie_to_db(code, category, genre, year, title, file_id):
    """Kino/serial yozuvini yaratadi va birinchi qismini (episode 1) file_id bilan saqlaydi.
    Eslatma: parametrlar tartibi main.py dagi FSM oqimiga mos: code, category, genre, year, title, file_id."""
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO movies (code, title, file_id, category, genre, year, added_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (str(code), title, file_id, category, genre, year, int(time.time()))
        )
        cursor.execute(
            """INSERT INTO episodes (movie_code, episode_number, file_id)
               VALUES (%s, 1, %s)""",
            (str(code), file_id)
        )
        conn.commit()
        success = True
    except pg_errors.UniqueViolation:
        conn.rollback()
        success = False
    cursor.close()
    _put_conn(conn)
    return success


# ================= SERIAL QISMLARI (EPISODES) =================

def add_episode(movie_code, file_id, episode_number=None):
    """Berilgan kino kodiga yangi qism qo'shadi.
    episode_number berilmasa, avtomatik keyingi raqam (oxirgi qism + 1) tanlanadi.
    Qaytaradi: qo'shilgan qism raqami, yoki None (agar kino kodi mavjud bo'lmasa)."""
    conn = get_conn()
    cursor = conn.cursor()
    code = str(movie_code)

    cursor.execute("SELECT 1 FROM movies WHERE code = %s", (code,))
    if cursor.fetchone() is None:
        cursor.close()
        _put_conn(conn)
        return None

    if episode_number is None:
        cursor.execute(
            "SELECT COALESCE(MAX(episode_number), 0) + 1 FROM episodes WHERE movie_code = %s",
            (code,)
        )
        episode_number = cursor.fetchone()[0]

    cursor.execute(
        """INSERT INTO episodes (movie_code, episode_number, file_id)
           VALUES (%s, %s, %s)
           ON CONFLICT (movie_code, episode_number) DO UPDATE SET file_id = EXCLUDED.file_id""",
        (code, episode_number, file_id)
    )

    if episode_number == 1:
        cursor.execute("UPDATE movies SET file_id = %s WHERE code = %s", (file_id, code))

    conn.commit()
    cursor.close()
    _put_conn(conn)
    return episode_number


def get_episodes_count(movie_code):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM episodes WHERE movie_code = %s", (str(movie_code),))
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_episode(movie_code, episode_number):
    """Bitta qismning file_id sini qaytaradi, yoki None."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_id FROM episodes WHERE movie_code = %s AND episode_number = %s",
        (str(movie_code), episode_number)
    )
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    return row[0] if row else None


def get_all_episode_numbers(movie_code):
    """Kino/serialning barcha mavjud qism raqamlarini tartiblangan holda qaytaradi."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT episode_number FROM episodes WHERE movie_code = %s ORDER BY episode_number",
        (str(movie_code),)
    )
    numbers = [row[0] for row in cursor.fetchall()]
    cursor.close()
    _put_conn(conn)
    return numbers


def delete_episode(movie_code, episode_number):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM episodes WHERE movie_code = %s AND episode_number = %s",
        (str(movie_code), episode_number)
    )
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return deleted > 0


# ================= FOYDALANUVCHI KO'RISH PROGRESSI =================

def save_progress(user_id, movie_code, episode_number):
    """Foydalanuvchi qaysi serialning qaysi qismini ko'rib turganini eslab qoladi."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO watch_progress (user_id, movie_code, last_episode)
           VALUES (%s, %s, %s)
           ON CONFLICT (user_id, movie_code) DO UPDATE SET last_episode = EXCLUDED.last_episode""",
        (user_id, str(movie_code), episode_number)
    )
    conn.commit()
    cursor.close()
    _put_conn(conn)


def get_progress(user_id, movie_code):
    """Foydalanuvchining shu serialda oxirgi ko'rgan qismini qaytaradi. Agar hech qachon ko'rmagan bo'lsa, None."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_episode FROM watch_progress WHERE user_id = %s AND movie_code = %s",
        (user_id, str(movie_code))
    )
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    return row[0] if row else None


def update_movie_in_db(code, category=None, genre=None, year=None, title=None, file_id=None):
    """Faqat berilgan (None bo'lmagan) maydonlarni yangilaydi. Kino topilsa True qaytaradi."""
    conn = get_conn()
    cursor = conn.cursor()

    fields = []
    values = []
    if category is not None:
        fields.append("category = %s")
        values.append(category)
    if genre is not None:
        fields.append("genre = %s")
        values.append(genre)
    if year is not None:
        fields.append("year = %s")
        values.append(year)
    if title is not None:
        fields.append("title = %s")
        values.append(title)
    if file_id is not None:
        fields.append("file_id = %s")
        values.append(file_id)

    if not fields:
        cursor.close()
        _put_conn(conn)
        return False

    values.append(str(code))
    cursor.execute(f"UPDATE movies SET {', '.join(fields)} WHERE code = %s", values)
    updated = cursor.rowcount
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return updated > 0


def get_movie(code):
    """Qaytaradi: (code, category, genre, year, title, file_id, views, likes, dislikes) yoki None.
    main.py bu tartibga mos: movie[0]=code, movie[2]=genre, movie[3]=year, movie[4]=title, movie[5]=file_id."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT code, category, genre, year, title, file_id, views, likes, dislikes
           FROM movies WHERE code = %s""",
        (str(code),)
    )
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE movies SET views = views + 1 WHERE code = %s", (str(code),))
        conn.commit()
    cursor.close()
    _put_conn(conn)
    return result


def get_movie_no_view_increment(code):
    """get_movie bilan bir xil, lekin views sonini oshirmaydi (masalan tahrirlashdan oldin ko'rish uchun)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT code, category, genre, year, title, file_id, views, likes, dislikes
           FROM movies WHERE code = %s""",
        (str(code),)
    )
    result = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
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
        cursor.execute("UPDATE movies SET views = views + 1 WHERE code = %s", (result[0],))
        conn.commit()
    cursor.close()
    _put_conn(conn)
    return result


def get_top_movies(limit=10, offset=0):
    """Pagination uchun offset qo'shildi. Qaytaradi: (code, title, views)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, views FROM movies ORDER BY views DESC LIMIT %s OFFSET %s",
        (limit, offset)
    )
    result = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return result


def get_movies_count():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies")
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def search_movies_by_title(search_text, limit=10, offset=0):
    """Pagination bilan. Qaytaradi: (code, title, category)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE title ILIKE %s ORDER BY views DESC LIMIT %s OFFSET %s",
        (f"%{search_text}%", limit, offset)
    )
    results = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return results


def search_movies_count(search_text):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE title ILIKE %s", (f"%{search_text}%",))
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_movies_by_genre(genre, limit=10, offset=0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE genre = %s ORDER BY views DESC LIMIT %s OFFSET %s",
        (genre, limit, offset)
    )
    results = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return results


def get_movies_by_genre_count(genre):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE genre = %s", (genre,))
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_all_genres():
    """Bazadagi barcha noyob janrlar ro'yxatini qaytaradi (bo'sh bo'lmaganlar)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT genre FROM movies WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
    )
    genres = [row[0] for row in cursor.fetchall()]
    cursor.close()
    _put_conn(conn)
    return genres


def get_movies_by_category(category, limit=10, offset=0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, title, category FROM movies WHERE category = %s ORDER BY views DESC LIMIT %s OFFSET %s",
        (category, limit, offset)
    )
    results = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return results


def get_movies_by_category_count(category):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM movies WHERE category = %s", (category,))
    count = cursor.fetchone()[0]
    cursor.close()
    _put_conn(conn)
    return count


def get_all_categories():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT category FROM movies WHERE category IS NOT NULL AND category != '' ORDER BY category"
    )
    categories = [row[0] for row in cursor.fetchall()]
    cursor.close()
    _put_conn(conn)
    return categories


def delete_movie_from_db(code):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM movies WHERE code = %s", (str(code),))
    deleted = cursor.rowcount
    cursor.execute("DELETE FROM movie_reactions WHERE movie_code = %s", (str(code),))
    cursor.execute("DELETE FROM episodes WHERE movie_code = %s", (str(code),))
    cursor.execute("DELETE FROM watch_progress WHERE movie_code = %s", (str(code),))
    conn.commit()
    cursor.close()
    _put_conn(conn)
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
        "SELECT reaction FROM movie_reactions WHERE user_id = %s AND movie_code = %s",
        (user_id, code)
    )
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute(
            "INSERT INTO movie_reactions (user_id, movie_code, reaction) VALUES (%s, %s, %s)",
            (user_id, code, reaction)
        )
        column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {column} = {column} + 1 WHERE code = %s", (code,))
        status = "added"
    elif existing[0] == reaction:
        cursor.execute(
            "DELETE FROM movie_reactions WHERE user_id = %s AND movie_code = %s",
            (user_id, code)
        )
        column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {column} = GREATEST({column} - 1, 0) WHERE code = %s", (code,))
        status = "removed"
    else:
        cursor.execute(
            "UPDATE movie_reactions SET reaction = %s WHERE user_id = %s AND movie_code = %s",
            (reaction, user_id, code)
        )
        old_column = "dislikes" if reaction == "like" else "likes"
        new_column = "likes" if reaction == "like" else "dislikes"
        cursor.execute(f"UPDATE movies SET {old_column} = GREATEST({old_column} - 1, 0) WHERE code = %s", (code,))
        cursor.execute(f"UPDATE movies SET {new_column} = {new_column} + 1 WHERE code = %s", (code,))
        status = "changed"

    conn.commit()
    cursor.execute("SELECT likes, dislikes FROM movies WHERE code = %s", (code,))
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    likes, dislikes = row if row else (0, 0)
    return status, likes, dislikes


def get_user_reaction(user_id, code):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT reaction FROM movie_reactions WHERE user_id = %s AND movie_code = %s",
        (user_id, str(code))
    )
    row = cursor.fetchone()
    cursor.close()
    _put_conn(conn)
    return row[0] if row else None


# ================= KANALLAR FUNKSIYALARI =================

def add_channel_to_db(channel_id, channel_url):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO channels (channel_id, channel_url) VALUES (%s, %s)",
            (channel_id, channel_url)
        )
        conn.commit()
        success = True
    except pg_errors.UniqueViolation:
        conn.rollback()
        success = False
    cursor.close()
    _put_conn(conn)
    return success


def get_all_channels():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_url FROM channels")
    result = cursor.fetchall()
    cursor.close()
    _put_conn(conn)
    return result


def delete_channel_from_db(channel_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = %s", (channel_id,))
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    _put_conn(conn)
    return deleted > 0
