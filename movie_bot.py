import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

from database import (init_db, add_movie_to_db, get_movie, get_random_movie, get_top_movies, search_movies_by_title,
                      add_channel_to_db, get_all_channels, delete_channel_from_db,
                      delete_movie_from_db, add_user_to_db, get_users_count, get_referral_count, get_all_users,
                      add_admin_to_db, get_all_admins, delete_admin_from_db)

TOKEN = "8855313774:AAEoKsvi3jzJPAUJO-JI_tv69uXP-qiajzE"
SUPER_ADMIN = 7094369151  # O'chirib bo'lmaydigan Asosiy Yaratuvchi (Siz)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


# ================= HOLATLAR (FSM) =================
class AddMovie(StatesGroup):
    waiting_for_code = State()
    waiting_for_category = State()
    waiting_for_genre = State()
    waiting_for_year = State()
    waiting_for_title = State()
    waiting_for_video = State()


class AddChannel(StatesGroup):
    waiting_for_id = State()
    waiting_for_url = State()


class DeleteMovie(StatesGroup):
    waiting_for_code = State()


class Broadcast(StatesGroup):
    waiting_for_message = State()


class AddAdminState(StatesGroup):
    waiting_for_admin_id = State()


class DeleteAdminState(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_password = State()


# ================= ADMIN TEKSHIRUVI =================
async def is_admin(user_id):
    if user_id == SUPER_ADMIN:
        return True
    return user_id in get_all_admins()


# ================= TUGMALAR =================
def get_admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Kino qo'shish", "❌ Kino o'chirish")
    kb.row("📢 Kanallarni boshqarish", "📊 Statistika")
    kb.row("✉️ Reklama yuborish")
    kb.row("🧑‍✈️ Yangi Admin qo'shish", "🗑️ Adminni o'chirish")
    return kb


def get_user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔍 Nomi bo'yicha qidirish", "🎲 Tasodifiy kino")
    kb.row("🏆 Top-10 Kinolar", "🔗 Takliflar (Referal)")
    return kb


def get_category_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🎬 Kino", "📺 Serial")
    kb.row("⛩ Anime", "🎭 Dorama")
    kb.add("❌ Bekor qilish")
    return kb


def get_genre_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("💥 Jangari", "😂 Komediya", "😭 Melodrama")
    kb.row("😱 Qo'rqinchli", "🕵️ Detektiv", "🧙‍♂️ Fantastika")
    kb.add("❌ Bekor qilish")
    return kb


async def get_dynamic_keyboard(user_id):
    return get_admin_keyboard() if await is_admin(user_id) else get_user_keyboard()


# ================= OBUNA TEKSHIRUV =================
async def check_user_sub(user_id):
    if await is_admin(user_id):
        return []
    channels = get_all_channels()
    not_subbed = []
    for ch_id, ch_url in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_subbed.append(ch_url)
        except Exception:
            pass
    return not_subbed


async def show_sub_channels(message, not_subscribed, payload=""):
    inline_kb = types.InlineKeyboardMarkup(row_width=1)
    for i, url in enumerate(not_subscribed, 1):
        inline_kb.add(types.InlineKeyboardButton(f"📢 {i}-kanalga obuna bo'lish", url=url))
    bot_user = await bot.get_me()
    inline_kb.add(types.InlineKeyboardButton(text="✅ Obunani tekshirish",
                                             url=f"https://t.me/{bot_user.username}?start={payload}"))
    await message.answer("⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:",
                         reply_markup=inline_kb)


# ================= START VA REFERAL =================
@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    args = message.get_args()
    referrer_id = None

    # Referal tizimi orqali kirdi
    if args and args.startswith("ref_"):
        try:
            ref_id = int(args.split("_")[1])
            if ref_id != message.from_user.id:
                referrer_id = ref_id
        except ValueError:
            pass

    is_new = add_user_to_db(message.from_user.id, referrer_id)
    if is_new and referrer_id:
        try:
            await bot.send_message(referrer_id,
                                   "🎉 Tabriklaymiz! Sizning taklif havolangiz orqali yangi foydalanuvchi botga qo'shildi.")
        except Exception:
            pass

    if args and args.isdigit():
        message.text = args
        return await search_movie(message)

    if await is_admin(message.from_user.id):
        await message.answer("Xush kelibsiz, Admin! Kerakli panelni tanlang:", reply_markup=get_admin_keyboard())
    else:
        await message.answer("🎬 Salom! Kino kodini to'g'ridan-to'g'ri yuboring yoki quyidagi menyudan foydalaning:",
                             reply_markup=get_user_keyboard())


# ================= FOYDALANUVCHI MENYUSI (VIP BILAN) =================
@dp.message_handler(lambda message: message.text == "🔗 Takliflar (Referal)")
async def referal_system(message: types.Message):
    count = get_referral_count(message.from_user.id)
    bot_user = await bot.get_me()
    ref_link = f"https://t.me/{bot_user.username}?start=ref_{message.from_user.id}"

    text = f"👥 *Sizning shaxsiy taklif havolangiz:*\n\n`{ref_link}`\n\n"
    text += f"📈 Siz taklif qilgan odamlar soni: *{count}* ta.\n\n"

    # VIP Statusini ko'rsatish
    if count >= 3:
        text += "👑 *Sizning maqomingiz:* `💎 VIP Foydalanuvchi`\nSiz uchun barcha majburiy kanallar va reklamalar o'chirilgan! Kinolarni to'g'ridan-to'g'ri ko'rishingiz mumkin."
    else:
        text += f"🎁 *Aksiya:* Yana *{3 - count}* ta odam taklif qiling va botdan mutlaqo *majburiy obunalarsiz* foydalanish huquqini (VIP) qo'lga kiriting!"

    await message.answer(text, parse_mode="Markdown")


@dp.message_handler(lambda message: message.text == "🎲 Tasodifiy kino")
async def send_random_movie(message: types.Message):
    movie = get_random_movie()
    if movie:
        await message.answer(
            f"🎲 Sizga tasodifiy tanlangan kino kodi: `{movie[0]}`\n🎬 Nomi: {movie[1]}\n\nKo'rish uchun shu kodni yuboring!",
            parse_mode="Markdown")
    else:
        await message.answer("Hozircha bazada kinolar yo'q.")


@dp.message_handler(lambda message: message.text == "🏆 Top-10 Kinolar")
async def send_top_movies(message: types.Message):
    movies = get_top_movies()
    if not movies:
        return await message.answer("Hozircha ko'rilgan kinolar yo'q.")

    text = "🔥 *Eng ko'p ko'rilgan Top-10 kinolar:*\n\n"
    for i, (code, title, views) in enumerate(movies, 1):
        text += f"{i}. 🎬 {title} — 👁 {views} marta (Kod: `{code}`)\n"
    text += "\nKo'rish uchun kino kodini yuboring."
    await message.answer(text, parse_mode="Markdown")


@dp.message_handler(lambda message: message.text == "🔍 Nomi bo'yicha qidirish")
async def ask_search_title(message: types.Message):
    await message.answer("Kino nomini yoki undagi biror so'zni kiriting (Masalan: Baki):",
                         reply_markup=types.ReplyKeyboardRemove())


# Nomi orqali qidirish funksiyasi (VIP tekshiruvi bilan)
@dp.message_handler(lambda message: not message.text.isdigit() and message.text not in [
    "➕ Kino qo'shish", "❌ Kino o'chirish", "📢 Kanallarni boshqarish", "📊 Statistika",
    "✉️ Reklama yuborish", "🧑‍✈️ Yangi Admin qo'shish", "🗑️ Adminni o'chirish",
    "🔍 Nomi bo'yicha qidirish", "🎲 Tasodifiy kino", "🏆 Top-10 Kinolar", "🔗 Takliflar (Referal)", "❌ Bekor qilish"])
async def search_by_title_logic(message: types.Message):
    add_user_to_db(message.from_user.id)

    # VIP TEKSHIRUV: Agar referallar soni 3 ta yoki undan ko'p bo'lsa, obunani umuman tekshirmaydi
    ref_count = get_referral_count(message.from_user.id)
    if ref_count >= 3:
        not_subscribed = []  # VIP Foydalanuvchi - obuna kerak emas
    else:
        not_subscribed = await check_user_sub(message.from_user.id)

    if not_subscribed:
        return await show_sub_channels(message, not_subscribed, "search")

    search_text = message.text
    results = search_movies_by_title(search_text)
    reply_kb = await get_dynamic_keyboard(message.from_user.id)

    if not results:
        await message.answer(f"😔 Kechirasiz, `{search_text}` bo'yicha hech narsa topilmadi.", reply_markup=reply_kb,
                             parse_mode="Markdown")
    else:
        text = f"🔍 `{search_text}` so'zi bo'yicha topildi:\n\n"
        for code, title, cat in results:
            text += f"🔑 Kod: `{code}` — [{cat}] 🎬 {title}\n"
        text += "\nKo'rish uchun raqamni (kodni) yuboring."
        await message.answer(text, reply_markup=reply_kb, parse_mode="Markdown")


# ================= KOD ORQALI KINO BERISH (VIP TEKSHIRUVI BILAN) =================
@dp.message_handler(lambda message: message.text.isdigit())
async def search_movie(message: types.Message):
    add_user_to_db(message.from_user.id)

    # VIP TEKSHIRUV: Agar referallar soni 3 ta yoki undan ko'p bo'lsa, obunani umuman tekshirmaydi
    ref_count = get_referral_count(message.from_user.id)
    if ref_count >= 3:
        not_subscribed = []  # VIP Foydalanuvchi - obuna kerak emas
    else:
        not_subscribed = await check_user_sub(message.from_user.id)

    if not_subscribed:
        return await show_sub_channels(message, not_subscribed, message.text)

    movie = get_movie(message.text)
    reply_kb = await get_dynamic_keyboard(message.from_user.id)

    if movie:
        title, file_id, category, genre, year, views = movie
        caption = f"🎬 Nomi: {title}\n"
        caption += f"📌 Toifa: {category}\n"
        caption += f"🎭 Janr: {genre}\n"
        caption += f"📅 Yili: {year}\n"
        caption += f"👁 Ko'rildi: {views} marta\n"

        await message.answer_video(video=file_id, caption=caption, reply_markup=reply_kb)
    else:
        await message.answer("Afsuski, bu kod bilan hech narsa topilmadi. 😔", reply_markup=reply_kb)


# ================= ADMIN: KINO QO'SHISH =================
@dp.message_handler(lambda message: message.text == "❌ Bekor qilish", state="*")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Amal bekor qilindi.", reply_markup=await get_dynamic_keyboard(message.from_user.id))


@dp.message_handler(lambda message: message.text == "➕ Kino qo'shish")
async def start_add_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Yangi kod kiriting (masalan: 101):",
                             reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Bekor qilish"))
        await AddMovie.waiting_for_code.set()


@dp.message_handler(state=AddMovie.waiting_for_code)
async def process_movie_code(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting:")
    await state.update_data(movie_code=message.text)
    await message.answer("Bu qanday toifa?", reply_markup=get_category_keyboard())
    await AddMovie.waiting_for_category.set()


@dp.message_handler(state=AddMovie.waiting_for_category)
async def process_movie_category(message: types.Message, state: FSMContext):
    await state.update_data(movie_category=message.text)
    await message.answer("Kino janrini tanlang:", reply_markup=get_genre_keyboard())
    await AddMovie.waiting_for_genre.set()


@dp.message_handler(state=AddMovie.waiting_for_genre)
async def process_movie_genre(message: types.Message, state: FSMContext):
    await state.update_data(movie_genre=message.text)
    await message.answer("Kino chiqqan yilni kiriting (Masalan: 2024):",
                         reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Bekor qilish"))
    await AddMovie.waiting_for_year.set()


@dp.message_handler(state=AddMovie.waiting_for_year)
async def process_movie_year(message: types.Message, state: FSMContext):
    await state.update_data(movie_year=message.text)
    await message.answer("Kino nomini kiriting:")
    await AddMovie.waiting_for_title.set()


@dp.message_handler(state=AddMovie.waiting_for_title)
async def process_movie_title(message: types.Message, state: FSMContext):
    await state.update_data(movie_title=message.text)
    await message.answer("Endi kinoning o'zini (video) yuboring:")
    await AddMovie.waiting_for_video.set()


@dp.message_handler(content_types=['video'], state=AddMovie.waiting_for_video)
async def process_movie_video(message: types.Message, state: FSMContext):
    data = await state.get_data()
    inserted = add_movie_to_db(data['movie_code'], data['movie_title'], message.video.file_id,
                               data['movie_category'], data['movie_genre'], data['movie_year'])
    await state.finish()
    text = f"✅ Muvaffaqiyatli saqlandi!\n🔑 Kod: {data['movie_code']}\n🎬 {data['movie_title']} ({data['movie_category']})" if inserted else "❌ Xato: Bu kod allaqachon mavjud."
    await message.answer(text, reply_markup=get_admin_keyboard())


# ================= QOLGAN ADMIN FUNKSIYALARI =================
@dp.message_handler(lambda message: message.text == "❌ Kino o'chirish")
async def start_del_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan kodni kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteMovie.waiting_for_code.set()


@dp.message_handler(state=DeleteMovie.waiting_for_code)
async def process_del_movie(message: types.Message, state: FSMContext):
    success = delete_movie_from_db(message.text)
    await state.finish()
    await message.answer("✅ O'chirildi!" if success else "❌ Topilmadi.", reply_markup=get_admin_keyboard())


@dp.message_handler(lambda message: message.text == "📊 Statistika")
async def show_stats(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer(f"📊 Jami foydalanuvchilar: `{get_users_count()}` ta", parse_mode="Markdown")


@dp.message_handler(lambda message: message.text == "✉️ Reklama yuborish")
async def start_broadcast(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Reklama postini yuboring:", reply_markup=types.ReplyKeyboardRemove())
        await Broadcast.waiting_for_message.set()


@dp.message_handler(state=Broadcast.waiting_for_message, content_types=types.ContentType.ANY)
async def process_broadcast(message: types.Message, state: FSMContext):
    await state.finish()
    users = get_all_users()
    await message.answer(f"📢 Yuborilmoqda ({len(users)} kishiga)...")
    c = 0
    for u in users:
        try:
            await message.copy_to(chat_id=u)
            c += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Yetkazildi: {c} ta", reply_markup=get_admin_keyboard())


# --- KANALLAR ---
@dp.message_handler(lambda message: message.text == "📢 Kanallarni boshqarish")
async def manage_channels(message: types.Message):
    if await is_admin(message.from_user.id):
        chs = get_all_channels()
        text = "Kanallar:\n"
        for i, (cid, curl) in enumerate(chs, 1): text += f"{i}. `{cid}`\n"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("➕ Qo'shish", callback_data="add_ch"))
        if chs: kb.add(types.InlineKeyboardButton("❌ O'chirish", callback_data="del_ch_list"))
        await message.answer(text if chs else "Kanal yo'q.", reply_markup=kb, parse_mode="Markdown")


@dp.callback_query_handler(lambda c: c.data == 'add_ch')
async def cb_add_ch(cb: types.CallbackQuery):
    await bot.answer_callback_query(cb.id)
    await bot.send_message(cb.from_user.id, "Kanal ID (masalan: -100123...):")
    await AddChannel.waiting_for_id.set()


@dp.message_handler(state=AddChannel.waiting_for_id)
async def pr_ch_id(message: types.Message, state: FSMContext):
    await state.update_data(id=message.text)
    await message.answer("Kanal linki:")
    await AddChannel.waiting_for_url.set()


@dp.message_handler(state=AddChannel.waiting_for_url)
async def pr_ch_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    add_channel_to_db(data['id'], message.text)
    await state.finish()
    await message.answer("✅ Kanal qo'shildi", reply_markup=get_admin_keyboard())


@dp.callback_query_handler(lambda c: c.data == 'del_ch_list')
async def cb_del_ch(cb: types.CallbackQuery):
    kb = types.InlineKeyboardMarkup()
    for cid, curl in get_all_channels(): kb.add(
        types.InlineKeyboardButton(f"O'chirish: {curl}", callback_data=f"del_{cid}"))
    await bot.send_message(cb.from_user.id, "Tanlang:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith('del_'))
async def cb_del_action(cb: types.CallbackQuery):
    delete_channel_from_db(cb.data.replace('del_', ''))
    await bot.answer_callback_query(cb.id, "O'chirildi!")
    await bot.send_message(cb.from_user.id, "Yangilandi.", reply_markup=get_admin_keyboard())


# --- ADMIN QO'SHISH VA O'CHIRISH (PAROL BILAN) ---
@dp.message_handler(lambda message: message.text == "🧑‍✈️ Yangi Admin qo'shish")
async def start_add_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Yangi admin ID raqamini yuboring:", reply_markup=types.ReplyKeyboardRemove())
        await AddAdminState.waiting_for_admin_id.set()


@dp.message_handler(state=AddAdminState.waiting_for_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        add_admin_to_db(int(message.text))
        await message.answer("✅ Admin qo'shildi!", reply_markup=get_admin_keyboard())
    await state.finish()


@dp.message_handler(lambda message: message.text == "🗑️ Adminni o'chirish")
async def start_delete_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan admin ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteAdminState.waiting_for_admin_id.set()


@dp.message_handler(state=DeleteAdminState.waiting_for_admin_id)
async def process_delete_admin_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    target = int(message.text)
    if target == SUPER_ADMIN:
        await state.finish()
        return await message.answer("🛑 Asosiy yaratuvchini o'chirib bo'lmaydi!", reply_markup=get_admin_keyboard())
    await state.update_data(target_id=target)
    await message.answer("🔐 Tasdiqlash parolini kiriting:")
    await DeleteAdminState.waiting_for_password.set()


@dp.message_handler(state=DeleteAdminState.waiting_for_password)
async def process_delete_admin_pwd(message: types.Message, state: FSMContext):
    if message.text != "shibalang":
        await state.finish()
        return await message.answer("❌ Parol xato!", reply_markup=get_admin_keyboard())
    data = await state.get_data()
    delete_admin_from_db(data['target_id'])
    await state.finish()
    await message.answer("✅ Admin o'chirildi.", reply_markup=get_admin_keyboard())


if __name__ == "__main__":
    import os
from aiogram import executor
from aiohttp import web

# Barcha dp, bot va handler kodlaringiz yuqorida o'zgarishsiz qoladi

async def handle(request):
    return web.Response(text="Bot is running 24/7!")

async def on_startup(dp):
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render taqdim etadigan portni avtomatik aniqlash
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server port {port} da muvaffaqiyatli ishga tushdi!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
