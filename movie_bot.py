import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiohttp import web
from database import (init_db, add_movie_to_db, get_movie, get_random_movie, get_top_movies, search_movies_by_title,
                      add_channel_to_db, get_all_channels, delete_channel_from_db,
                      delete_movie_from_db, add_user_to_db, get_users_count, get_referral_count, get_all_users,
                      add_admin_to_db, get_all_admins, delete_admin_from_db)

# Render muhitidagi muhit o'zgaruvchisidan yangi tokenni olamiz
BOT_TOKEN = os.environ.get("TOKEN")

bot = Bot(token=BOT_TOKEN)
SUPER_ADMIN = 7094369151  # Yangilangan Asosiy Yaratuvchi ID si
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

class AddChannel(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_link = State()

class DeleteChannel(StatesGroup):
    waiting_for_channel_id = State()

class DeleteMovie(StatesGroup):
    waiting_for_code = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class AddAdminState(StatesGroup):
    waiting_for_admin_id = State()

class DeleteAdminState(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_password = State()

# ================= KEYBOARDLAR =================
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("🔍 Kino qidirish", "🎲 Tasodifiy kino")
    keyboard.add("⭐ Top kinolar", "📊 Statistika")
    return keyboard

def get_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("➕ Kino qo'shish", "🗑️ Kinoni o'chirish")
    keyboard.add("➕ Kanal qo'shish", "🗑️ Kanalni o'chirish")
    keyboard.add("📢 Reklama yuborish", "📊 To'liq Statistika")
    keyboard.add("➕ Admin qo'shish", "🗑️ Adminni o'chirish")
    keyboard.add("🔙 Foydalanuvchi paneli")
    return keyboard

# ================= BAZANI INICIALIZATSIYA QILISH =================
init_db()

# ================= ADMINLIKNI TEKSHIRISH =================
async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN:
        return True
    admins = get_all_admins()
    return user_id in [admin[0] for admin in admins]

# ================= MAJBURIY OBUNA TEKSHIRUVI =================
async def check_sub(user_id: int) -> bool:
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

def get_sub_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    channels = get_all_channels()
    for idx, ch in enumerate(channels, 1):
        keyboard.add(types.InlineKeyboardButton(text=f"🔗 {idx}-Kanalga obuna bo'lish", url=ch[1]))
    keyboard.add(types.InlineKeyboardButton(text=f"✅ Tekshirish", callback_data="check_subscription"))
    return keyboard

# ================= HANDLERLAR =================
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()
    referrer_id = int(args) if args and args.isdigit() else None
    add_user_to_db(user_id, referrer_id)
    if not await check_sub(user_id):
        await message.answer(" 🛑  Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz shart:", reply_markup=get_sub_keyboard())
    else:
        await message.answer(f" 👋  Salom, {message.from_user.full_name}! Kinolar olamiga xush kelibsiz!", reply_markup=get_main_keyboard())

@dp.callback_query_handler(text="check_subscription")
async def cb_check_sub(call: types.CallbackQuery):
    if await check_sub(call.from_user.id):
        await call.answer(" ✅  Rahmat! Obuna tasdiqlandi.", show_alert=True)
        await call.message.edit_text(" 🎉  Siz muvaffaqiyatli ro'yxatdan o'tdingiz. Quyidagi menyudan foydalaning:")
        await call.message.answer("Asosiy panel:", reply_markup=get_main_keyboard())
    else:
        await call.answer(" ❌  Siz hali hamma kanallarga obuna bo'lmagansiz!", show_alert=True)

@dp.message_handler(commands=['admin'])
async def cmd_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer(" 🛠️  Admin paneliga xush kelibsiz:", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "🔙 Foydalanuvchi paneli")
async def back_to_user(message: types.Message):
    await message.answer("Foydalanuvchi paneli:", reply_markup=get_main_keyboard())

@dp.message_handler(lambda message: message.text == "📊 Statistika")
async def user_stats(message: types.Message):
    total = get_users_count()
    ref = get_referral_count(message.from_user.id)
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={message.from_user.id}"
    await message.answer(f" 📊  Bot foydalanuvchilari: {total} ta\n 👥  Siz taklif qilgan do'stlar: {ref} ta\n\n 🔗  Sizning referal havolangiz:\n{ref_link}")

@dp.message_handler(lambda message: message.text == "🎲 Tasodifiy kino")
async def random_movie(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer(" 🛑  Avval kanallarga obuna bo'ling!", reply_markup=get_sub_keyboard())
    movie = get_random_movie()
    if movie:
        caption = f"🎬 {movie[4]}\n\n 🔢 Kod: {movie[0]}\n 📁 Janr: {movie[2]}\n 📅 Yil: {movie[3]}"
        await message.answer_video(video=movie[5], caption=caption)
    else:
        await message.answer("Bazada kino mavjud emas.")

@dp.message_handler(lambda message: message.text == "⭐ Top kinolar")
async def top_movies(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer(" 🛑  Avval kanallarga obuna bo'ling!", reply_markup=get_sub_keyboard())
    movies = get_top_movies(10)
    if movies:
        res = " 🔥  Eng ko'p ko'rilgan top 10 ta kino:\n\n"
        for m in movies:
            res += f" 🔹  {m[1]} (Kod: {m[0]}) - 👁️ {m[2]} marta\n"
        await message.answer(res)
    else:
        await message.answer("Top kinolar ro'yxati bo'sh.")

@dp.message_handler(lambda message: message.text == "🔍 Kino qidirish")
async def search_movie_prompt(message: types.Message):
    await message.answer("Kino nomini kiriting:")

@dp.message_handler(lambda message: message.text == "➕ Kino qo'shish")
async def start_add_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Kino kodini kiriting (faqat raqam):", reply_markup=types.ReplyKeyboardRemove())
        await AddMovie.waiting_for_code.set()

@dp.message_handler(state=AddMovie.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Iltimos, faqat raqam kiriting:")
    await state.update_data(code=int(message.text))
    await message.answer("Kino kategoriyasini kiriting (masalan: Tarjima, Premyera):")
    await AddMovie.waiting_for_category.set()

@dp.message_handler(state=AddMovie.waiting_for_category)
async def process_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("Kino janrini kiriting (masalan: Jangari, Komediya):")
    await AddMovie.waiting_for_genre.set()

@dp.message_handler(state=AddMovie.waiting_for_genre)
async def process_genre(message: types.Message, state: FSMContext):
    await state.update_data(genre=message.text)
    await message.answer("Kino yilini kiriting:")
    await AddMovie.waiting_for_year.set()

@dp.message_handler(state=AddMovie.waiting_for_year)
async def process_year(message: types.Message, state: FSMContext):
    await state.update_data(year=message.text)
    await message.answer("Kino nomini (sarlavhasini) kiriting:")
    await AddMovie.waiting_for_title.set()

@dp.message_handler(state=AddMovie.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Kinoning videosini yoki faylini yuboring (Telegram orqali):")
    await AddMovie.waiting_for_link.set()

@dp.message_handler(state=AddMovie.waiting_for_link, content_types=['video', 'document'])
async def process_video(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    data = await state.get_data()
    add_movie_to_db(data['code'], data['category'], data['genre'], data['year'], data['title'], file_id)
    await state.finish()
    await message.answer(" ✅  Kino muvaffaqiyatli bazaga qo'shildi!", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "🗑️ Kinoni o'chirish")
async def start_delete_movie(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan kino kodini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteMovie.waiting_for_code.set()

@dp.message_handler(state=DeleteMovie.waiting_for_code)
async def process_delete_movie(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Faqat raqam kiriting:")
    code = int(message.text)
    delete_movie_from_db(code)
    await state.finish()
    await message.answer(" 🗑️  Kino bazadan o'chirildi.", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "➕ Kanal qo'shish")
async def start_add_channel(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Kanal ID sini kiriting (masalan: -100123456789):", reply_markup=types.ReplyKeyboardRemove())
        await AddChannel.waiting_for_channel_id.set()

@dp.message_handler(state=AddChannel.waiting_for_channel_id)
async def process_ch_id(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal havolasini kiriting (masalan: https://t.me/...):")
    await AddChannel.waiting_for_channel_link.set()

@dp.message_handler(state=AddChannel.waiting_for_channel_link)
async def process_ch_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    add_channel_to_db(data['ch_id'], message.text)
    await state.finish()
    await message.answer(" ✅  Kanal majburiy obuna ro'yxatiga qo'shildi!", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "🗑️ Kanalni o'chirish")
async def start_delete_channel(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan kanal ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteChannel.waiting_for_channel_id.set()

@dp.message_handler(state=DeleteChannel.waiting_for_channel_id)
async def process_delete_channel(message: types.Message, state: FSMContext):
    delete_channel_from_db(message.text)
    await state.finish()
    await message.answer(" 🗑️  Kanal majburiy obunadan o'chirildi.", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "📢 Reklama yuborish")
async def start_broadcast(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Reklama xabarini yuboring (matn, rasm, video va h.z.):", reply_markup=types.ReplyKeyboardRemove())
        await BroadcastState.waiting_for_message.set()

@dp.message_handler(state=BroadcastState.waiting_for_message, content_types=types.ContentType.ANY)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = get_all_users()
    count = 0
    await message.answer(" 📢  Reklama tarqatilmoqda, kuting...")
    for user in users:
        try:
            await message.copy_to(chat_id=user[0])
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await state.finish()
    await message.answer(f" ✅  Reklama {count} ta foydalanuvchiga yetkazildi.", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "📊 To'liq Statistika")
async def full_stats(message: types.Message):
    if await is_admin(message.from_user.id):
        total = get_users_count()
        channels = len(get_all_channels())
        await message.answer(f" 📊  Bot foydalanuvchilari: {total} ta\n 🔗  Ulangan kanallar: {channels} ta")

@dp.message_handler(lambda message: message.text == "➕ Admin qo'shish")
async def start_add_admin(message: types.Message):
    if message.from_user.id == SUPER_ADMIN:
        await message.answer("Yangi adminning Telegram ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await AddAdminState.waiting_for_admin_id.set()

@dp.message_handler(state=AddAdminState.waiting_for_admin_id)
async def process_add_admin(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID faqat raqamlardan iborat bo'ladi:")
    add_admin_to_db(int(message.text))
    await state.finish()
    await message.answer(" ✅  Yangi admin muvaffaqiyatli qo'shildi!", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "🗑️ Adminni o'chirish")
async def start_delete_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("O'chirmoqchi bo'lgan admin ID sini kiriting:", reply_markup=types.ReplyKeyboardRemove())
        await DeleteAdminState.waiting_for_admin_id.set()

@dp.message_handler(state=DeleteAdminState.waiting_for_admin_id)
async def process_delete_admin_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return
    target = int(message.text)
    if target == SUPER_ADMIN:
        await state.finish()
        return await message.answer(" 🛑  Asosiy yaratuvchini o'chirib bo'lmaydi! ", reply_markup=get_admin_keyboard())
    await state.update_data(target_id=target)
    await message.answer(" 🔐  Tasdiqlash parolini kiriting:")
    await DeleteAdminState.waiting_for_password.set()

@dp.message_handler(state=DeleteAdminState.waiting_for_password)
async def process_delete_admin_pwd(message: types.Message, state: FSMContext):
    if message.text != "shibalang":
        await state.finish()
        return await message.answer(" ❌  Parol xato!", reply_markup=get_admin_keyboard())
    data = await state.get_data()
    delete_admin_from_db(data['target_id'])
    await state.finish()
    await message.answer(" 🗑  Admin o'chirildi.", reply_markup=get_admin_keyboard())

@dp.message_handler()
async def search_movie(message: types.Message):
    if not await check_sub(message.from_user.id):
        return await message.answer(" 🛑  Avval kanallarga obuna bo'ling!", reply_markup=get_sub_keyboard())
    
    text = message.text
    if text.isdigit():
        movie = get_movie(int(text))
        if movie:
            caption = f"🎬 {movie[4]}\n\n 🔢 Kod: {movie[0]}\n 📁 Janr: {movie[2]}\n 📅 Yil: {movie[3]}"
            await message.answer_video(video=movie[5], caption=caption)
        else:
            await message.answer(" ❌  Bu kod bilan kino topilmadi.")
    else:
        movies = search_movies_by_title(text)
        if movies:
            res = f" 🎉  '{text}' so'zi bo'yicha topilgan kinolar:\n\n"
            for m in movies:
                res += f" 🎬  {m[1]} - 🔢 Kod: <code>{m[0]}</code>\n"
            await message.answer(res, parse_mode="HTML")
        else:
            await message.answer(" ❌  Hech qanday kino topilmadi.")

# ================= RENDER VEB SERVER VA ISHGA TUSHIRISH =================
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
