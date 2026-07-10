import logging
import asyncio
import os
import html
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.utils.exceptions import BotBlocked, ChatNotFound, UserDeactivated, TelegramAPIError
from aiohttp import web

# Bazadan kerakli funksiyalarni chaqiramiz
from database import (
    init_db, add_movie_to_db, update_movie_in_db, get_movie, get_movie_no_view_increment,
    get_random_movie, get_top_movies, get_movies_count, search_movies_by_title, search_movies_count,
    get_movies_by_genre, get_movies_by_genre_count, get_all_genres,
    get_movies_by_category, get_movies_by_category_count, get_all_categories,
    add_channel_to_db, get_all_channels, delete_channel_from_db,
    delete_movie_from_db, add_user_to_db, get_users_count, get_referral_count, get_all_users,
    add_admin_to_db, get_all_admins, delete_admin_from_db,
    set_vip, remove_vip, is_vip, get_vip_until, get_all_vip_users,
    react_to_movie, get_user_reaction,
)

# ================= SOZLAMALAR VA ADMINLAR =================
BOT_TOKEN = os.environ.get("TOKEN")

# Adminni o'chirishni tasdiqlash uchun parol endi environment variable orqali olinadi.
# Agar o'rnatilmagan bo'lsa, funksiya butunlay o'chirilib qo'yiladi (xavfsizroq default).
DELETE_ADMIN_PASSWORD = os.environ.get("DELETE_ADMIN_PASSWORD")

# Matnlar avtomatik chiroyli (HTML) formatda chiqishi uchun sozlandi
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)

SUPER_ADMIN = 7094369151         # Bu siz (O'chirib bo'lmaydigan Asosiy Yaratuvchi)
REGULAR_ADMINS = [6123381970]    # Bu sizning do'stingizning ID si (Oddiy admin)

PAGE_SIZE = 8          # Har bir sahifada nechta kino ko'rsatilishi
VIP_REQUIRED_REFS = 3  # Nechta do'st taklif qilsa VIP beriladi (avtomatik referal-VIP)

logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


# ================= HOLATLAR (FSM) =================
class AddMovie(StatesGroup):
    waiting_for_code = State()
    waiting_for_category = State()
    waiting_for_genre = State()
    waiting_for_year = State()
    waiting_for_title = State()
    waiting_for_link = State()


class EditMovie(StatesGroup):
    waiting_for_code = State()
    waiting_for_field = State()
    waiting_for_new_value = State()
    waiting_for_new_video = State()


class AddChannel(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_link = State()


class DeleteChannel(StatesGroup):
    waiting_for_channel_id = State()


class DeleteMovie(StatesGroup):
    waiting_for_code = State()


class BroadcastState(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()


class AddAdminState(StatesGroup):
    waiting_for_admin_id = State()


class DeleteAdminState(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_password = State()


class AddVipState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()


class RemoveVipState(StatesGroup):
    waiting_for_user_id = State()


# ================= BAZANI ISHGA TUSHIRISH =================
init_db()


# ================= ADMINLIKNI TEKSHIRISH =================
async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN or user_id in REGULAR_ADMINS:
        return True
    admins = get_all_admins()
    return user_id in admins


# ================= MAJBURIY OBUNA TEKSHIRUVI =================
async def check_sub(user_id: int) -> bool:
    """VIP foydalanuvchilar majburiy obunadan ozod qilinadi."""
    if is_vip(user_id):
        return True
    channels = get_all_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch[0], user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            return False
    return True


def esc(text) -> str:
    """HTML maxsus belgilarini xavfsiz qochirish (kino nomi/janr kabi foydalanuvchi/admin
    kiritgan matnlarni caption ichiga qo'yishdan oldin ishlatiladi)."""
    if text is None:
        return ""
    return html.escape(str(text))


# ================= KEYBOARDLAR (TUGMALAR) =================
def get_main_keyboard(is_user_admin=False, user_vip=False):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("🔍 Kino qidirish", "🎲 Tasodifiy kino")
    keyboard.add("⭐ Top kinolar", "🎭 Janrlar")
    keyboard.add("📊 Statistika", "👑 VIP")

    if is_user_admin:
        keyboard.add("🛡 Admin panel")

    return keyboard


def get_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("➕ Kino qo'shish", "✏️ Kinoni tahrirlash")
    keyboard.add("🗑️ Kinoni o'chirish", "📢 Reklama yuborish")
    keyboard.add("➕ Kanal qo'shish", "🗑️ Kanalni o'chirish")
    keyboard.add("👑 VIP berish", "👑 VIP olish")
    keyboard.add("➕ Admin qo'shish", "🗑️ Adminni o'chirish")
    keyboard.add("📊 To'liq Statistika")
    keyboard.add("🔙 Foydalanuvchi paneli")
    return keyboard


def get_sub_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    channels = get_all_channels()
    for idx, ch in enumerate(channels, 1):
        keyboard.add(types.InlineKeyboardButton(text=f"🔗 {idx}-Kanalga obuna bo'lish", url=ch[1]))
    keyboard.add(types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription"))
    return keyboard


def get_movie_reaction_keyboard(code, likes=0, dislikes=0, user_reaction=None):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    like_text = f"👍 {likes}" + (" ✓" if user_reaction == "like" else "")
    dislike_text = f"👎 {dislikes}" + (" ✓" if user_reaction == "dislike" else "")
    keyboard.add(
        types.InlineKeyboardButton(text=like_text, callback_data=f"react_like_{code}"),
        types.InlineKeyboardButton(text=dislike_text, callback_data=f"react_dislike_{code}"),
    )
    keyboard.add(
        types.InlineKeyboardButton(text="↗️ Ulashish", switch_inline_query=str(code)),
    )
    return keyboard


def get_pagination_keyboard(prefix, page, total_pages, extra=""):
    """prefix: callback_data uchun (masalan 'top', 'search_XXX', 'genre_XXX').
    extra alohida so'z sifatida callback_data ga qo'shiladi (masalan qidiruv matni)."""
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    if page > 1:
        buttons.append(types.InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"page_{prefix}_{page-1}_{extra}"))
    buttons.append(types.InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        buttons.append(types.InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"page_{prefix}_{page+1}_{extra}"))
    if buttons:
        keyboard.add(*buttons)
    return keyboard


def get_genre_keyboard(genres, callback_prefix="genre_select"):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(text=g, callback_data=f"{callback_prefix}_{g}") for g in genres]
    keyboard.add(*buttons)
    return keyboard


def get_edit_field_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(text="📝 Nomi", callback_data="editfield_title"),
        types.InlineKeyboardButton(text="🏷 Kategoriya", callback_data="editfield_category"),
    )
    keyboard.add(
        types.InlineKeyboardButton(text="🎭 Janr", callback_data="editfield_genre"),
        types.InlineKeyboardButton(text="📅 Yil", callback_data="editfield_year"),
    )
    keyboard.add(
        types.InlineKeyboardButton(text="🎥 Video fayl", callback_data="editfield_video"),
    )
    keyboard.add(
        types.InlineKeyboardButton(text="✅ Tugatish", callback_data="editfield_done"),
    )
    return keyboard


# ================= YORDAMCHI: KINO CAPTION =================
def build_movie_caption(movie):
    """movie: (code, category, genre, year, title, file_id, views, likes, dislikes) — get_movie natijasi."""
    code, category, genre, year, title, file_id = movie[0], movie[1], movie[2], movie[3], movie[4], movie[5]
    views = movie[6] if len(movie) > 6 else 0
    return (
        f"🎬 <b>{esc(title)}</b>\n\n"
        f"🔢 <b>Kino kodi:</b> <code>{esc(code)}</code>\n"
        f"🏷 <b>Kategoriya:</b> {esc(category)}\n"
        f"🎭 <b>Janr:</b> {esc(genre)}\n"
        f"📅 <b>Yil:</b> {esc(year)}\n"
        f"👁 <b>Ko'rishlar:</b> {views}\n\n"
        f"<i>🍿 Yoqimli tomosha tilaymiz!</i>"
    )


async def send_movie(chat_id, movie, reply_markup_below=None):
    """Kinoni video sifatida, like/dislike tugmalari bilan yuboradi."""
    code = movie[0]
    likes = movie[7] if len(movie) > 7 else 0
    dislikes = movie[8] if len(movie) > 8 else 0
    user_reaction = get_user_reaction(chat_id, code)
    caption = build_movie_caption(movie)
    reaction_kb = get_movie_reaction_keyboard(code, likes, dislikes, user_reaction)
    await bot.send_video(chat_id=chat_id, video=movie[5], caption=caption, reply_markup=reaction_kb)
    if reply_markup_below is not None:
        await bot.send_message(chat_id=chat_id, text="👇", reply_markup=reply_markup_below)


# ================= HANDLERLAR (BOT FUNKSIYALARI) =================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() and int(args) != user_id else None

    is_new_user = add_user_to_db(user_id, referrer_id)

    # Agar yangi foydalanuvchi referal orqali kelgan bo'lsa va taklif qilgan odam
    # yetarlicha do'st taklif qilgan bo'lsa, unga avtomatik VIP beramiz
    if is_new_user and referrer_id:
        ref_count = get_referral_count(referrer_id)
        if ref_count > 0 and ref_count % VIP_REQUIRED_REFS == 0:
            set_vip(referrer_id, 30)
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 <b>Tabriklaymiz!</b> Siz {VIP_REQUIRED_REFS} ta do'stingizni taklif qildingiz "
                    f"va <b>30 kunlik VIP status</b> qo'lga kiritdingiz!\n"
                    f"Endi reklama va majburiy obunasiz botdan foydalanasiz 👑"
                )
            except (BotBlocked, ChatNotFound, UserDeactivated, TelegramAPIError):
                pass

    admin_status = await is_admin(user_id)
    user_vip = is_vip(user_id)

    if not await check_sub(user_id):
        await message.answer(
            "<b>🛑 Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart!</b>\n"
            "<i>Obuna bo'lgach, «Tasdiqlash» tugmasini bosing.</i>\n\n"
            f"💡 <i>Yoki {VIP_REQUIRED_REFS} ta do'stingizni taklif qilib VIP oling va bu talabdan ozod bo'ling!</i>",
            reply_markup=get_sub_keyboard()
        )
    else:
        vip_note = "\n👑 <i>Sizda VIP status faol!</i>" if user_vip else ""
        await message.answer(
            f"👋 <b>Assalomu alaykum, {esc(message.from_user.full_name)}!</b>\n\n"
            f"🎬 <i>Eng sara va qiziqarli kinolar olamiga xush kelibsiz!</i>\n"
            f"🍿 O'zingizga yoqqan kinoni topish uchun quyidagi menyudan foydalaning.{vip_note}",
            reply_markup=get_main_keyboard(is_user_admin=admin_status, user_vip=user_vip)
        )


@dp.callback_query_handler(text="check_subscription")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_sub(call.from_user.id):
        admin_status = await is_admin(call.from_user.id)
        user_vip = is_vip(call.from_user.id)
        await call.answer("✅ Rahmat! Obuna tasdiqlandi.", show_alert=True)
        await call.message.delete()
        await call.message.answer(
            "🎉 <b>Ajoyib! Siz barcha kanallarga a'zo bo'ldingiz.</b>\n\n"
            "Barcha imkoniyatlar ochildi. Marhamat, kinolarni qidiring:",
            reply_markup=get_main_keyboard(is_user_admin=admin_status, user_vip=user_vip)
        )
    else:
        await call.answer("❌ Kechirasiz, hali hamma kanallarga obuna bo'lmagansiz!", show_alert=True)


@dp.callback_query_handler(text="noop")
async def cb_noop(call: types.CallbackQuery):
    await call.answer()


# Admin panelga kirish
@dp.message_handler(lambda message: message.text == "🛡 Admin panel" or message.text == "/admin")
async def cmd_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("<b>🛠 Xush kelibsiz, Boshqaruvchi!</b>\n<i>Kerakli bo'limni tanlang:</i>", reply_markup=get_admin_keyboard())


# Orqaga qaytish
@dp.message_handler(lambda message: message.text == "🔙 Foydalanuvchi paneli")
async def back_to_user(message: types.Message):
    admin_status = await is_admin(message.from_user.id)
    user_vip = is_vip(message.from_user.id)
    await message.answer("<b>🏠 Asosiy sahifaga qaytdingiz:</b>", reply_markup=get_main_keyboard(is_user_admin=admin_status, user_vip=user_vip))


@dp.message_handler(lambda message: message.text == "📊 Statistika")
async def user_stats(message: types.Message):
    total = get_users_count()
    ref = get_referral_count(message.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"

    remaining = VIP_REQUIRED_REFS - (ref % VIP_REQUIRED_REFS) if not is_vip(message.from_user.id) else 0
    vip_line = ""
    if is_vip(message.from_user.id):
        until = get_vip_until(message.from_user.id)
        until_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y")
        vip_line = f"👑 <b>VIP muddati:</b> {until_str} gacha\n"
    else:
        vip_line = f"💡 <b>VIP olishga:</b> yana {remaining} ta do'st kerak\n"

    text = (
        f"<b>📊 Loyiha Statistikasi:</b>\n\n"
        f"👥 <b>Umumiy foydalanuvchilar:</b> {total} ta\n"
        f"🤝 <b>Siz taklif qilgan do'stlar:</b> {ref} ta\n"
        f"{vip_line}\n"
        f"<i>🔗 Sizning shaxsiy taklif havolangiz:</i>\n<code>{esc(ref_link)}</code>\n\n"
        f"💡 <i>Do'stlaringizga yuboring va botimizni qo'llab-quvvatlang!</i>"
    )
    await message.answer(text)


@dp.message_handler(lambda message: message.text == "👑 VIP")
async def vip_info(message: types.Message):
    user_id = message.from_user.id
    ref = get_referral_count(user_id)
    if is_vip(user_id):
        until = get_vip_until(user_id)
        until_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        text = (
            f"👑 <b>Sizda VIP status faol!</b>\n\n"
            f"⏳ <b>Muddati:</b> {until_str} gacha\n\n"
            f"✅ Reklamalarsiz\n"
            f"✅ Majburiy obunasiz\n"
            f"✅ Cheklovlarsiz foydalanish"
        )
    else:
        remaining = VIP_REQUIRED_REFS - (ref % VIP_REQUIRED_REFS)
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        text = (
            f"👑 <b>VIP Status</b>\n\n"
            f"VIP foydalanuvchilar reklama va majburiy obunasiz botdan foydalanadi!\n\n"
            f"🤝 <b>Hozirgi takliflaringiz:</b> {ref} ta\n"
            f"🎯 <b>VIP olishga qoldi:</b> {remaining} ta do'st\n\n"
            f"🔗 <b>Taklif havolangiz:</b>\n<code>{esc(ref_link)}</code>"
        )
    await message.answer(text)


@dp.message_handler(lambda message: message.text == "🎲 Tasodifiy kino")
async def random_movie(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer("<b>🛑 Avval kanallarga obuna bo'ling!</b>", reply_markup=get_sub_keyboard())

    movie = get_random_movie()
    if movie:
        # get_random_movie 6 ta maydon qaytaradi, likes/dislikes uchun to'liq qayta o'qiymiz
        full_movie = get_movie_no_view_increment(movie[0])
        await send_movie(message.chat.id, full_movie)
    else:
        await message.answer("<i>Hozircha bazada kinolar mavjud emas.</i>")


@dp.message_handler(lambda message: message.text == "⭐ Top kinolar")
async def top_movies(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer("<b>🛑 Avval kanallarga obuna bo'ling!</b>", reply_markup=get_sub_keyboard())
    await show_top_movies_page(message.chat.id, page=1)


async def show_top_movies_page(chat_id, page=1, message_id=None):
    total = get_movies_count()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    movies = get_top_movies(PAGE_SIZE, offset)

    if movies:
        res = "<b>🔥 Eng ko'p izlangan kinolar:</b>\n\n"
        for idx, m in enumerate(movies, offset + 1):
            res += f"<b>{idx}.</b> {esc(m[1])} — (Kod: <code>{esc(m[0])}</code>) 👁 {m[2]} marta\n"
    else:
        res = "<i>Hozircha reyting shakllanmadi.</i>"

    kb = get_pagination_keyboard("top", page, total_pages)

    if message_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=res, reply_markup=kb)
    else:
        await bot.send_message(chat_id=chat_id, text=res, reply_markup=kb)


@dp.message_handler(lambda message: message.text == "🎭 Janrlar")
async def show_genres(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer("<b>🛑 Avval kanallarga obuna bo'ling!</b>", reply_markup=get_sub_keyboard())

    genres = get_all_genres()
    if not genres:
        return await message.answer("<i>Hozircha janrlar mavjud emas.</i>")
    await message.answer("<b>🎭 Janrni tanlang:</b>", reply_markup=get_genre_keyboard(genres))


@dp.callback_query_handler(lambda c: c.data.startswith("genre_select_"))
async def cb_genre_select(call: types.CallbackQuery):
    genre = call.data[len("genre_select_"):]
    await call.answer()
    await show_genre_movies_page(call.message.chat.id, genre, page=1)


async def show_genre_movies_page(chat_id, genre, page=1, message_id=None):
    total = get_movies_by_genre_count(genre)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    movies = get_movies_by_genre(genre, PAGE_SIZE, offset)

    if movies:
        res = f"<b>🎭 «{esc(genre)}» janridagi kinolar:</b>\n\n"
        for m in movies:
            res += f"🎬 {esc(m[1])} — Kodi: <code>{esc(m[0])}</code>\n"
    else:
        res = f"<i>«{esc(genre)}» janrida kinolar topilmadi.</i>"

    kb = get_pagination_keyboard(f"genre", page, total_pages, extra=genre)

    if message_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=res, reply_markup=kb)
    else:
        await bot.send_message(chat_id=chat_id, text=res, reply_markup=kb)


@dp.message_handler(lambda message: message.text == "🔍 Kino qidirish")
async def search_movie_prompt(message: types.Message):
    await message.answer("<b>🔍 Kino nomini yoki maxsus KODINI kiriting:</b>\n<i>(Masalan: 124 yoki Forsaj)</i>")


# ================= PAGINATSIYA CALLBACK'LARI =================
@dp.callback_query_handler(lambda c: c.data.startswith("page_"))
async def cb_pagination(call: types.CallbackQuery):
    # Format: page_<prefix>_<page>_<extra>
    parts = call.data.split("_", 3)
    # parts[0] = "page", parts[1] = prefix, parts[2] = page number, parts[3] = extra (bo'lishi mumkin yoki yo'q)
    prefix = parts[1]
    page = int(parts[2])
    extra = parts[3] if len(parts) > 3 else ""

    await call.answer()

    if prefix == "top":
        await show_top_movies_page(call.message.chat.id, page=page, message_id=call.message.message_id)
    elif prefix == "genre":
        await show_genre_movies_page(call.message.chat.id, extra, page=page, message_id=call.message.message_id)
    elif prefix == "category":
        await show_category_movies_page(call.message.chat.id, extra, page=page, message_id=call.message.message_id)
    elif prefix == "search":
        await show_search_results_page(call.message.chat.id, extra, page=page, message_id=call.message.message_id)


async def show_category_movies_page(chat_id, category, page=1, message_id=None):
    total = get_movies_by_category_count(category)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    movies = get_movies_by_category(category, PAGE_SIZE, offset)

    if movies:
        res = f"<b>🏷 «{esc(category)}» kategoriyasidagi kinolar:</b>\n\n"
        for m in movies:
            res += f"🎬 {esc(m[1])} — Kodi: <code>{esc(m[0])}</code>\n"
    else:
        res = f"<i>«{esc(category)}» kategoriyasida kinolar topilmadi.</i>"

    kb = get_pagination_keyboard("category", page, total_pages, extra=category)

    if message_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=res, reply_markup=kb)
    else:
        await bot.send_message(chat_id=chat_id, text=res, reply_markup=kb)


async def show_search_results_page(chat_id, search_text, page=1, message_id=None):
    total = search_movies_count(search_text)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    movies = search_movies_by_title(search_text, PAGE_SIZE, offset)

    if movies:
        res = f"🎉 <b>«{esc(search_text)}» so'zi bo'yicha topilgan kinolar:</b>\n\n"
        for m in movies:
            res += f"🎬 {esc(m[1])} — Kodi: <code>{esc(m[0])}</code>\n"
    else:
        res = "<b>❌ Hech qanday kino topilmadi.</b>"

    kb = get_pagination_keyboard("search", page, total_pages, extra=search_text)

    if message_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=res, reply_markup=kb)
    else:
        await bot.send_message(chat_id=chat_id, text=res, reply_markup=kb)


# ================= LIKE / DISLIKE CALLBACK =================
@dp.callback_query_handler(lambda c: c.data.startswith("react_"))
async def cb_react(call: types.CallbackQuery):
    # Format: react_like_<code> yoki react_dislike_<code>
    _, reaction, code = call.data.split("_", 2)
    status, likes, dislikes = react_to_movie(call.from_user.id, code, reaction)

    user_reaction = get_user_reaction(call.from_user.id, code)
    new_kb = get_movie_reaction_keyboard(code, likes, dislikes, user_reaction)

    try:
        await call.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        pass

    feedback = {
        "added": "✅ Rahmat, fikringiz qabul qilindi!",
        "changed": "✅ Fikringiz yangilandi!",
        "removed": "↩️ Fikringiz olib tashlandi.",
    }.get(status, "✅")
    await call.answer(feedback)


# ================= ADMIN: KINO QO'SHISH =================
@dp.message_handler(lambda message: message.text == "➕ Kino qo'shish")
async def start_add_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("<b>📝 Yangi kino qo'shish:</b>\n\nKino kodini kiriting (faqat raqam):", reply_markup=types.ReplyKeyboardRemove())
        await AddMovie.waiting_for_code.set()


@dp.message_handler(state=AddMovie.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Iltimos, faqat raqam kiriting:")
    existing = get_movie_no_view_increment(message.text)
    if existing:
        return await message.answer(f"⚠️ Bu kod (<code>{esc(message.text)}</code>) allaqachon band. Boshqa kod kiriting:")
    await state.update_data(code=message.text)
    await message.answer("Kino kategoriyasini kiriting (Masalan: <i>Tarjima, Premyera</i>):")
    await AddMovie.waiting_for_category.set()


@dp.message_handler(state=AddMovie.waiting_for_category)
async def process_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("Kino janrini kiriting (Masalan: <i>Jangari, Komediya</i>):")
    await AddMovie.waiting_for_genre.set()


@dp.message_handler(state=AddMovie.waiting_for_genre)
async def process_genre(message: types.Message, state: FSMContext):
    await state.update_data(genre=message.text)
    await message.answer("Kino yilini kiriting (Masalan: <i>2024</i>):")
    await AddMovie.waiting_for_year.set()


@dp.message_handler(state=AddMovie.waiting_for_year)
async def process_year(message: types.Message, state: FSMContext):
    await state.update_data(year=message.text)
    await message.answer("Kino nomini to'liq kiriting:")
    await AddMovie.waiting_for_title.set()


@dp.message_handler(state=AddMovie.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("<b>🎥 Kinoning video faylini (yoki document) telegramga yuboring:</b>")
    await AddMovie.waiting_for_link.set()


@dp.message_handler(state=AddMovie.waiting_for_link, content_types=['video', 'document'])
async def process_video(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    data = await state.get_data()
    success = add_movie_to_db(data['code'], data['category'], data['genre'], data['year'], data['title'], file_id)
    await state.finish()
    if success:
        await message.answer("<b>✅ Kino muvaffaqiyatli bazaga yuklandi!</b>", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>❌ Xatolik: bu kod band bo'lib qoldi. Qaytadan urinib ko'ring.</b>", reply_markup=get_admin_keyboard())


@dp.message_handler(state=AddMovie.waiting_for_link, content_types=types.ContentType.ANY)
async def process_video_wrong_type(message: types.Message, state: FSMContext):
    await message.answer("⚠️ Iltimos, video yoki hujjat (document) shaklida yuboring.")


# ================= ADMIN: KINO TAHRIRLASH =================
@dp.message_handler(lambda message: message.text == "✏️ Kinoni tahrirlash")
async def start_edit_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Tahrirlamoqchi bo'lgan kino kodini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await EditMovie.waiting_for_code.set()


@dp.message_handler(state=EditMovie.waiting_for_code)
async def process_edit_code(message: types.Message, state: FSMContext):
    movie = get_movie_no_view_increment(message.text)
    if not movie:
        return await message.answer("❌ Bu kod bo'yicha kino topilmadi. Qaytadan kiriting:")
    await state.update_data(code=message.text)
    caption = build_movie_caption(movie)
    await message.answer(f"{caption}\n\n<b>Qaysi maydonni o'zgartirmoqchisiz?</b>", reply_markup=get_edit_field_keyboard())
    await EditMovie.waiting_for_field.set()


@dp.callback_query_handler(lambda c: c.data.startswith("editfield_"), state=EditMovie.waiting_for_field)
async def cb_edit_field(call: types.CallbackQuery, state: FSMContext):
    field = call.data[len("editfield_"):]
    await call.answer()

    if field == "done":
        await state.finish()
        await bot.send_message(call.from_user.id, "<b>✅ Tahrirlash yakunlandi.</b>", reply_markup=get_admin_keyboard())
        return

    await state.update_data(field=field)

    field_names = {
        "title": "yangi nomini",
        "category": "yangi kategoriyasini",
        "genre": "yangi janrini",
        "year": "yangi yilini",
        "video": "yangi video faylini",
    }

    if field == "video":
        await bot.send_message(call.from_user.id, f"<b>🎥 Kinoning {field_names[field]} yuboring:</b>")
        await EditMovie.waiting_for_new_video.set()
    else:
        await bot.send_message(call.from_user.id, f"<b>✏️ Kinoning {field_names[field]} kiriting:</b>")
        await EditMovie.waiting_for_new_value.set()


@dp.message_handler(state=EditMovie.waiting_for_new_value)
async def process_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data['field']
    code = data['code']

    kwargs = {field: message.text}
    update_movie_in_db(code, **kwargs)

    movie = get_movie_no_view_increment(code)
    caption = build_movie_caption(movie)
    await message.answer(
        f"<b>✅ Yangilandi!</b>\n\n{caption}\n\n<b>Yana biror maydonni o'zgartirasizmi?</b>",
        reply_markup=get_edit_field_keyboard()
    )
    await EditMovie.waiting_for_field.set()


@dp.message_handler(state=EditMovie.waiting_for_new_video, content_types=['video', 'document'])
async def process_edit_video(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    data = await state.get_data()
    code = data['code']
    update_movie_in_db(code, file_id=file_id)

    movie = get_movie_no_view_increment(code)
    caption = build_movie_caption(movie)
    await message.answer(
        f"<b>✅ Video yangilandi!</b>\n\n{caption}\n\n<b>Yana biror maydonni o'zgartirasizmi?</b>",
        reply_markup=get_edit_field_keyboard()
    )
    await EditMovie.waiting_for_field.set()


@dp.message_handler(state=EditMovie.waiting_for_new_video, content_types=types.ContentType.ANY)
async def process_edit_video_wrong_type(message: types.Message, state: FSMContext):
    await message.answer("⚠️ Iltimos, video yoki hujjat (document) shaklida yuboring.")


# ================= ADMIN: KINO O'CHIRISH =================
@dp.message_handler(lambda message: message.text == "🗑️ Kinoni o'chirish")
async def start_delete_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan kino kodini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteMovie.waiting_for_code.set()


@dp.message_handler(state=DeleteMovie.waiting_for_code)
async def process_delete_movie(message: types.Message, state: FSMContext):
    deleted = delete_movie_from_db(message.text)
    await state.finish()
    if deleted:
        await message.answer("<b>🗑️ Kino bazadan butunlay o'chirildi.</b>", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>❌ Bu kod bo'yicha kino topilmadi.</b>", reply_markup=get_admin_keyboard())


# ================= ADMIN: KANAL BOSHQARUVI =================
@dp.message_handler(lambda message: message.text == "➕ Kanal qo'shish")
async def start_add_channel(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Kanal ID sini kiriting (Masalan: <code>-100123456789</code>):", reply_markup=types.ReplyKeyboardRemove())
        await AddChannel.waiting_for_channel_id.set()


@dp.message_handler(state=AddChannel.waiting_for_channel_id)
async def process_ch_id(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal havolasini kiriting (Masalan: <i>https://t.me/...</i>):")
    await AddChannel.waiting_for_channel_link.set()


@dp.message_handler(state=AddChannel.waiting_for_channel_link)
async def process_ch_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Bot kanalga admin qilib qo'yilganini tekshirib ko'ramiz, aks holda check_sub doim False qaytaradi
    warning = ""
    try:
        member = await bot.get_chat_member(chat_id=data['ch_id'], user_id=bot.id)
        if member.status not in ['administrator', 'creator']:
            warning = "\n\n⚠️ <b>Diqqat:</b> Bot bu kanalda admin emasga o'xshaydi. Obuna tekshiruvi ishlamasligi mumkin — botni kanalga admin qiling!"
    except Exception:
        warning = "\n\n⚠️ <b>Diqqat:</b> Botning bu kanaldagi holatini tekshirib bo'lmadi. Bot kanalga admin qilib qo'shilganini tekshiring!"

    success = add_channel_to_db(data['ch_id'], message.text)
    await state.finish()
    if success:
        await message.answer(f"<b>✅ Kanal majburiy obuna ro'yxatiga qo'shildi!</b>{warning}", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>❌ Bu kanal allaqachon ro'yxatda bor.</b>", reply_markup=get_admin_keyboard())


@dp.message_handler(lambda message: message.text == "🗑️ Kanalni o'chirish")
async def start_delete_channel(message: types.Message):
    if await is_admin(message.from_user.id):
        channels = get_all_channels()
        if not channels:
            return await message.answer("<i>Hozircha ulangan kanallar yo'q.</i>", reply_markup=get_admin_keyboard())
        listing = "\n".join(f"• <code>{esc(ch[0])}</code> — {esc(ch[1])}" for ch in channels)
        await message.answer(f"<b>Hozirgi kanallar:</b>\n{listing}\n\nO'chirmoqchi bo'lgan kanal ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteChannel.waiting_for_channel_id.set()


@dp.message_handler(state=DeleteChannel.waiting_for_channel_id)
async def process_delete_channel(message: types.Message, state: FSMContext):
    deleted = delete_channel_from_db(message.text)
    await state.finish()
    if deleted:
        await message.answer("<b>🗑️ Kanal majburiy obunadan olib tashlandi.</b>", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>❌ Bu ID bo'yicha kanal topilmadi.</b>", reply_markup=get_admin_keyboard())


# ================= ADMIN: REKLAMA (BROADCAST) =================
@dp.message_handler(lambda message: message.text == "📢 Reklama yuborish")
async def start_broadcast(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer(
            "<b>Barcha foydalanuvchilarga yuboriladigan xabarni yozing:</b>\n<i>(Matn, rasm, video bo'lishi mumkin)</i>",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await BroadcastState.waiting_for_message.set()


@dp.message_handler(state=BroadcastState.waiting_for_message, content_types=types.ContentType.ANY)
async def preview_broadcast(message: types.Message, state: FSMContext):
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    total = get_users_count()

    confirm_kb = types.InlineKeyboardMarkup(row_width=2)
    confirm_kb.add(
        types.InlineKeyboardButton(text="✅ Ha, yuborish", callback_data="broadcast_confirm"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel"),
    )
    await message.answer(
        f"👆 <b>Yuqoridagi xabar {total} ta foydalanuvchiga yuboriladi.</b>\n\nTasdiqlaysizmi?",
        reply_markup=confirm_kb
    )
    await BroadcastState.waiting_for_confirmation.set()


@dp.callback_query_handler(lambda c: c.data in ("broadcast_confirm", "broadcast_cancel"), state=BroadcastState.waiting_for_confirmation)
async def cb_broadcast_decision(call: types.CallbackQuery, state: FSMContext):
    await call.answer()

    if call.data == "broadcast_cancel":
        await state.finish()
        await call.message.edit_text("❌ Reklama bekor qilindi.")
        await bot.send_message(call.from_user.id, "Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    data = await state.get_data()
    src_chat_id = data['chat_id']
    src_message_id = data['message_id']

    users = get_all_users()
    await call.message.edit_text("⏳ <i>Reklama tarqatish boshlandi, biroz kuting...</i>")

    sent = 0
    blocked = 0
    failed = 0
    for user_id in users:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=src_chat_id, message_id=src_message_id)
            sent += 1
        except (BotBlocked, UserDeactivated, ChatNotFound):
            blocked += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.05)

    await state.finish()
    await bot.send_message(
        call.from_user.id,
        f"<b>✅ Yuborish yakunlandi!</b>\n\n"
        f"📤 Yetib bordi: {sent} ta\n"
        f"🚫 Bloklangan/faol emas: {blocked} ta\n"
        f"⚠️ Boshqa xatolik: {failed} ta",
        reply_markup=get_admin_keyboard()
    )


# ================= ADMIN: STATISTIKA =================
@dp.message_handler(lambda message: message.text == "📊 To'liq Statistika")
async def full_stats(message: types.Message):
    if await is_admin(message.from_user.id):
        total = get_users_count()
        channels = len(get_all_channels())
        movies = get_movies_count()
        vip_count = len(get_all_vip_users())
        await message.answer(
            f"<b>📈 To'liq Statistika:</b>\n\n"
            f"👥 Foydalanuvchilar: {total} ta\n"
            f"🎬 Kinolar: {movies} ta\n"
            f"🔗 Ulangan kanallar: {channels} ta\n"
            f"👑 Faol VIP'lar: {vip_count} ta"
        )


# ================= ADMIN: VIP BOSHQARUVI =================
@dp.message_handler(lambda message: message.text == "👑 VIP berish")
async def start_add_vip(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("VIP beriladigan foydalanuvchining Telegram ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await AddVipState.waiting_for_user_id.set()


@dp.message_handler(state=AddVipState.waiting_for_user_id)
async def process_add_vip_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID faqat raqamlardan iborat bo'ladi:")
    await state.update_data(user_id=int(message.text))
    await message.answer("Nechchi kunlik VIP berilsin? (Masalan: <i>30</i>):")
    await AddVipState.waiting_for_days.set()


@dp.message_handler(state=AddVipState.waiting_for_days)
async def process_add_vip_days(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        return await message.answer("⚠️ Musbat raqam kiriting:")
    days = int(message.text)
    data = await state.get_data()
    target_id = data['user_id']

    set_vip(target_id, days)
    await state.finish()

    until = get_vip_until(target_id)
    until_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y")

    await message.answer(
        f"<b>✅ VIP berildi!</b>\nFoydalanuvchi: <code>{target_id}</code>\nMuddat: {until_str} gacha",
        reply_markup=get_admin_keyboard()
    )
    try:
        await bot.send_message(
            target_id,
            f"🎉 <b>Sizga {days} kunlik VIP status berildi!</b>\n"
            f"Endi reklama va majburiy obunasiz botdan foydalanasiz 👑"
        )
    except (BotBlocked, ChatNotFound, UserDeactivated, TelegramAPIError):
        pass


@dp.message_handler(lambda message: message.text == "👑 VIP olish")
async def start_remove_vip(message: types.Message):
    if await is_admin(message.from_user.id):
        vip_users = get_all_vip_users()
        if not vip_users:
            return await message.answer("<i>Hozircha faol VIP foydalanuvchilar yo'q.</i>", reply_markup=get_admin_keyboard())
        listing = "\n".join(
            f"• <code>{uid}</code> — {datetime.fromtimestamp(until).strftime('%d.%m.%Y')} gacha"
            for uid, until in vip_users
        )
        await message.answer(
            f"<b>Hozirgi VIP foydalanuvchilar:</b>\n{listing}\n\nVIP bekor qilinadigan foydalanuvchi ID sini kiriting:",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await RemoveVipState.waiting_for_user_id.set()


@dp.message_handler(state=RemoveVipState.waiting_for_user_id)
async def process_remove_vip(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID faqat raqamlardan iborat bo'ladi:")
    target_id = int(message.text)
    removed = remove_vip(target_id)
    await state.finish()
    if removed:
        await message.answer(f"<b>✅ VIP bekor qilindi.</b>\nFoydalanuvchi: <code>{target_id}</code>", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>❌ Bu foydalanuvchi topilmadi.</b>", reply_markup=get_admin_keyboard())


# ================= ADMIN: ADMINLARNI BOSHQARISH =================
@dp.message_handler(lambda message: message.text == "➕ Admin qo'shish")
async def start_add_admin(message: types.Message):
    if message.from_user.id == SUPER_ADMIN:
        await message.answer("Yangi adminning Telegram ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await AddAdminState.waiting_for_admin_id.set()
    else:
        await message.answer("🛑 <b>Bu funksiyaga faqat Bosh Yaratuvchi kirishi mumkin!</b>")


@dp.message_handler(state=AddAdminState.waiting_for_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID faqat raqamlardan iborat bo'ladi:")
    success = add_admin_to_db(int(message.text))
    await state.finish()
    if success:
        await message.answer("<b>✅ Yangi admin muvaffaqiyatli qo'shildi!</b>", reply_markup=get_admin_keyboard())
    else:
        await message.answer("<b>⚠️ Bu foydalanuvchi allaqachon admin.</b>", reply_markup=get_admin_keyboard())


@dp.message_handler(lambda message: message.text == "🗑️ Adminni o'chirish")
async def start_delete_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    if not DELETE_ADMIN_PASSWORD:
        return await message.answer(
            "🛑 <b>Bu funksiya faollashtirilmagan.</b>\n"
            "<i>Ishlashi uchun server sozlamalarida DELETE_ADMIN_PASSWORD o'rnatilishi kerak.</i>"
        )
    await message.answer("O'chirmoqchi bo'lgan admin ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
    await DeleteAdminState.waiting_for_admin_id.set()


@dp.message_handler(state=DeleteAdminState.waiting_for_admin_id)
async def process_delete_admin_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID faqat raqamlardan iborat bo'ladi:")
    target = int(message.text)
    if target == SUPER_ADMIN:
        await state.finish()
        return await message.answer("<b>🛑 Asosiy yaratuvchini o'chirib bo'lmaydi!</b>", reply_markup=get_admin_keyboard())
    await state.update_data(target_id=target)
    await message.answer("🔐 <b>Tasdiqlash parolini kiriting:</b>")
    await DeleteAdminState.waiting_for_password.set()


@dp.message_handler(state=DeleteAdminState.waiting_for_password)
async def process_delete_admin_pwd(message: types.Message, state: FSMContext):
    # Parolni foydalanuvchi yuboribgina qolganidan keyin ham chatdan o'chirib tashlaymiz (iz qolmasin)
    try:
        await message.delete()
    except Exception:
        pass

    if message.text != DELETE_ADMIN_PASSWORD:
        await state.finish()
        return await message.answer("<b>❌ Parol xato!</b>", reply_markup=get_admin_keyboard())
    data = await state.get_data()
    delete_admin_from_db(data['target_id'])
    await state.finish()
    await message.answer("<b>🗑 Admin huquqlari bekor qilindi.</b>", reply_markup=get_admin_keyboard())


# ================= KINO QIDIRISH (Oddiy text yozganda ishlaydi) =================
@dp.message_handler()
async def search_movie(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer("<b>🛑 Avval kanallarga obuna bo'ling!</b>", reply_markup=get_sub_keyboard())

    text = message.text.strip()
    admin_status = await is_admin(message.from_user.id)
    user_vip = is_vip(message.from_user.id)
    main_kb = get_main_keyboard(is_user_admin=admin_status, user_vip=user_vip)

    if text.isdigit():
        movie = get_movie(text)
        if movie:
            await send_movie(message.chat.id, movie, reply_markup_below=main_kb)
        else:
            await message.answer("<b>❌ Bu kod bo'yicha kino topilmadi.</b>", reply_markup=main_kb)
    else:
        await show_search_results_page(message.chat.id, text, page=1)
        await message.answer("👆", reply_markup=main_kb)


# ================= RENDER WEB SERVER =================
async def handle(request):
    return web.Response(text="Bot is running 24/7!")


async def on_startup(dp):
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server port {port} da muvaffaqiyatli ishga tushdi!")


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
