import asyncio
import html
import logging
import os
import sqlite3
import time

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery)

# ====================== SOZLAMALAR ======================
BOT_TOKEN = os.getenv("9273297548:AAG25UUvYdmaE7nZxS5JhsMKJonzuTdOhwg")
SUPER_ADMIN = 8849504131
BOT_NAME = "🍿DODA KINO"
OFFICIAL = "@dodakinorasmiy"
OFFICIAL_URL = "https://t.me/dodakinorasmiy"
SUPPORT = "@Madaniyatlikman"
SUPPORT_URL = "https://t.me/Madaniyatlikman"
PREMIUM_PRICE_SUM = 15000
PREMIUM_STARS = 135          # Telegram Stars narxi
PREMIUM_DAYS = 30
COLORED = True               # Rangli tugmalar (yangi Bot API kerak). Xato bersa False qiling
GENRES = ["Komediya", "Qo'rqinchli", "Drama", "Jangari", "Fantastika",
          "Romantik", "Multfilm", "Detektiv", "Tarixiy", "Sarguzasht",
          "Triller", "Anime"]
# ========================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# ---------------------- BAZA ----------------------
db = sqlite3.connect("dodakino.db", check_same_thread=False)
db.row_factory = sqlite3.Row


def q(sql, args=(), commit=False):
    cur = db.execute(sql, args)
    if commit:
        db.commit()
    return cur


def init_db():
    q("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, name TEXT, joined INTEGER,
        premium_until INTEGER DEFAULT 0, banned INTEGER DEFAULT 0)""")
    q("CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY, title TEXT, url TEXT)")
    q("""CREATE TABLE IF NOT EXISTS movies(
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, title TEXT,
        kind TEXT, file_id TEXT, ftype TEXT, genres TEXT, views INTEGER DEFAULT 0)""")
    q("CREATE TABLE IF NOT EXISTS searches(user_id INTEGER, query TEXT, ts INTEGER)")
    q("CREATE TABLE IF NOT EXISTS favs(user_id INTEGER, movie_id INTEGER, UNIQUE(user_id, movie_id))")
    q("CREATE TABLE IF NOT EXISTS likes(user_id INTEGER, movie_id INTEGER, UNIQUE(user_id, movie_id))")
    q("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
    q("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)", commit=True)


def now():
    return int(time.time())


def esc(t):
    return html.escape(str(t))


def is_admin(uid):
    return uid == SUPER_ADMIN or q("SELECT 1 FROM admins WHERE id=?", (uid,)).fetchone() is not None


def is_premium(uid):
    r = q("SELECT premium_until FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r["premium_until"] > now())


def add_premium(uid, days):
    q("INSERT OR IGNORE INTO users(id,name,joined) VALUES(?,?,?)", (uid, "", now()))
    cur = q("SELECT premium_until FROM users WHERE id=?", (uid,)).fetchone()["premium_until"]
    new = max(now(), cur) + days * 86400
    q("UPDATE users SET premium_until=? WHERE id=?", (new, uid), True)
    return new


def fmt_date(ts):
    return time.strftime("%d.%m.%Y", time.localtime(ts))


async def log(text):
    r = q("SELECT value FROM settings WHERE key='log_chat'").fetchone()
    if r:
        try:
            await bot.send_message(int(r["value"]), text)
        except Exception as e:
            logging.warning("log xato: %s", e)


async def allowed(uid):
    """Majburiy obunani tekshiradi. Premium va adminlar o'tkazib yuboriladi."""
    if is_admin(uid) or is_premium(uid):
        return True
    for ch in q("SELECT * FROM channels").fetchall():
        try:
            mem = await bot.get_chat_member(ch["id"], uid)
            if mem.status in ("left", "kicked"):
                return False
        except Exception as e:  # bot kanalda admin emas va hokazo
            logging.warning("obuna tekshiruvi xato (%s): %s", ch["id"], e)
    return True


# ---------------------- TUGMALAR ----------------------
def b(text, cb=None, url=None, style=None):
    kw = {"text": text}
    if cb:
        kw["callback_data"] = cb
    if url:
        kw["url"] = url
    if style and COLORED:
        kw["style"] = style  # primary / success / danger
    return InlineKeyboardButton(**kw)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_btn(cb="menu"):
    return [b("⬅️Ortga qaytish", cb, style="danger")]


def sub_kb():
    rows = []
    chs = q("SELECT * FROM channels").fetchall()
    for i, ch in enumerate(chs, 1):
        rows.append([b(f"✔️Obuna bo'lish{' ' + str(i) if len(chs) > 1 else ''}", url=ch["url"], style="primary")])
    rows.append([b("☑️Tekshirish", "check", style="success")])
    rows.append([b("💎Premium", "prem", style="danger")])
    return kb(rows)


def welcome_kb():
    return kb([
        [b("📊Menyu", "menu", style="primary")],
        [b("📺Rasmiy kanal", url=OFFICIAL_URL, style="success")],
        [b("🖍Yordam", url=SUPPORT_URL, style="danger")],
    ])


def menu_kb():
    return kb([
        [b("🔍Film va seriallar qidirish", "search", style="primary")],
        [b("📍Profil", "profile", style="success"), b("📊Statistika", "stats", style="success")],
        [b("💎Premium Obuna", "prem", style="danger")],
        [b("🖍Yordam", url=SUPPORT_URL, style="primary"), b("📒Qo'llanma", "guide", style="primary")],
        [b("📺Rasmiy kanal", url=OFFICIAL_URL, style="success")],
    ])


def genre_kb(selected, prefix="g", send_cb="g_send", send_text="📤Yuborish", extra=None):
    rows, row = [], []
    for i, g in enumerate(GENRES):
        mark = "✅ " if i in selected else ""
        row.append(b(mark + g, f"{prefix}:{i}", style="success" if i in selected else "primary"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([b(send_text, send_cb, style="success")])
    if extra:
        rows.extend(extra)
    return kb(rows)


# ---------------------- MATNLAR ----------------------
def sub_text(name):
    return (f"Assalomu aleykum {esc(name)}!\n"
            f"Xush kelibsiz! Botdan foydalanish uchun avval majburiy kanallarga obuna bo'lib "
            f"☑️Tekshirish tugmasini bosing.\n\n"
            f"📍Agar majburiy obunasiz va reklamalarsiz kino va seriallarni ko'rmoqchi bo'lsangiz "
            f"Premiumga obuna bo'ling.")


def welcome_text(name):
    return (f"Assalomu aleykum {esc(name)}!\n"
            f"{BOT_NAME} botiga xush kelibsiz.\n"
            f"Siz bu bot orqali film va serialni juda sifatli holda va janr, kod va nomi orqali "
            f"topishingiz mumkin. To'liq ma'lumot olish uchun /help buyrug'ini yuboring. "
            f"Menyu kerak bo'lsa /menu buyrug'i orqali yoki pastdagi menyu tugmasi orqali "
            f"ko'rib chiqishingiz mumkin. O'z vibeyingizni yarating.")


PREMIUM_INFO = (f"💎Premium bu nima?\n"
                f"Bot oylik tarifi, ya'ni VIP 💎Premium sizga bir oy davomida majburiy obuna va "
                f"reklamalarsiz kino va seriallarni ko'rish imkoniyatini beradi.\n"
                f"💎Premium {PREMIUM_DAYS} kun amal qiladi va narxi - 💳{PREMIUM_PRICE_SUM} so'm.\n"
                f"Telegram stars evaziga esa - ⭐️{PREMIUM_STARS}")

HELP_TEXT = (
    f"🖍 <b>{BOT_NAME} yordam</b>\n\n"
    "/start - botni ishga tushirish\n"
    "/menu - asosiy menyu\n"
    "/profile - qidiruv tarixi, sevimlilar va like bosgan filmlaringiz\n"
    "/help - shu bo'lim\n\n"
    "<b>Tugmalar:</b>\n"
    "🔍 Film va seriallar qidirish - nomi, kodi yoki janri bo'yicha qidirish\n"
    "📍 Profil - ID, qidiruv tarixi va shaxsiy statistikangiz\n"
    "📊 Statistika - bot obunachilari, qidiruvlar va premium egalari soni\n"
    "💎 Premium Obuna - majburiy obuna va reklamasiz foydalanish\n"
    "🖍 Yordam - admin bilan bog'lanish\n"
    "📒 Qo'llanma - barcha funksiyalar tartibi bilan\n"
    f"📺 Rasmiy kanal - {OFFICIAL}\n"
    f"⬅️ Ortga qaytish - oldingi bo'limga qaytadi\n\nMurojaat uchun: {SUPPORT}")

GUIDE_TEXT = (
    f"📒 <b>{BOT_NAME} qo'llanma</b>\n\n"
    "1️⃣ <b>Film va seriallar qidirish</b>\n"
    "   🔎 Nomi orqali - film nomini yozasiz, bot filmni yuboradi\n"
    "   🔢 Kod orqali - film kodini yozasiz, bot shu kodli filmni yuboradi\n"
    "   🎭 Janr - 1 yoki 2 ta janr tanlab 📤Yuborish bosing, 50 tagacha film chiqadi\n"
    "   ℹ️ Janrlar haqida - janrlar tavsifi\n"
    "2️⃣ <b>Profil</b> - Telegram ID, qidiruv tarixi va shaxsiy statistika\n"
    "3️⃣ <b>Statistika</b> - umumiy son-sanoqlar va 🏅 eng ko'p qidirilgan 20 ta film\n"
    "4️⃣ <b>Premium Obuna</b> - 30 kunlik reklamasiz va majburiy obunasiz foydalanish\n"
    "5️⃣ <b>Yordam</b> - admin bilan aloqa\n"
    f"6️⃣ <b>Rasmiy kanal</b> - {OFFICIAL}\n\n"
    "Film ostidagi ❤️ like va ⭐ sevimli tugmalari /profile da saqlanadi.")

GENRE_ABOUT = ("🎭 <b>Janrlar haqida</b>\n\n"
               "😂 Komediya - kulgili va yengil filmlar\n"
               "😱 Qo'rqinchli - dahshat va sirli voqealar\n"
               "🎭 Drama - hayotiy va hissiy voqealar\n"
               "💥 Jangari - janglar va shiddatli sahnalar\n"
               "🚀 Fantastika - kelajak, koinot va xayol\n"
               "💕 Romantik - sevgi hikoyalari\n"
               "🧸 Multfilm - bolalar va oila uchun\n"
               "🕵️ Detektiv - jinoyat va tergov\n"
               "🏰 Tarixiy - o'tmish voqealari\n"
               "🧭 Sarguzasht - sayohat va izlanish\n"
               "😰 Triller - zo'riqish va kutilmagan burilishlar\n"
               "🎌 Anime - yapon animatsiyasi\n\n"
               "Aralash janr uchun 2 tagacha janr tanlashingiz mumkin.")


# ---------------------- HOLATLAR ----------------------
class Search(StatesGroup):
    name = State()
    code = State()


class AddMovie(StatesGroup):
    file = State()
    title = State()
    code = State()
    kind = State()
    genres = State()


class AdminSt(StatesGroup):
    channel = State()
    log = State()
    gift = State()
    admin_add = State()
    admin_del = State()
    ban = State()
    bc_all = State()
    bc_ads = State()


# ---------------------- MIDDLEWARE ----------------------
FREE_CB = {"check", "prem", "pay", "start_back"}


class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if user is None:
            return await handler(event, data)
        r = q("SELECT banned FROM users WHERE id=?", (user.id,)).fetchone()
        if r and r["banned"]:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
            return
        if isinstance(event, Message):
            if event.successful_payment or (event.text and event.text.startswith("/start")):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery) and event.data in FREE_CB:
            return await handler(event, data)
        if await allowed(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer()
        await bot.send_message(user.id, sub_text(user.full_name), reply_markup=sub_kb())


class IsAdmin(BaseFilter):
    async def __call__(self, event):
        return is_admin(event.from_user.id)


# ---------------------- YORDAMCHILAR ----------------------
async def show(cb: CallbackQuery, text, markup=None):
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


async def send_start(user):
    if await allowed(user.id):
        await bot.send_message(user.id, welcome_text(user.full_name), reply_markup=welcome_kb())
    else:
        await bot.send_message(user.id, sub_text(user.full_name), reply_markup=sub_kb())


def movie_kb(movie_id, uid):
    likes = q("SELECT COUNT(*) c FROM likes WHERE movie_id=?", (movie_id,)).fetchone()["c"]
    liked = q("SELECT 1 FROM likes WHERE movie_id=? AND user_id=?", (movie_id, uid)).fetchone()
    fav = q("SELECT 1 FROM favs WHERE movie_id=? AND user_id=?", (movie_id, uid)).fetchone()
    return kb([[b(f"{'💔' if liked else '❤️'} {likes}", f"like:{movie_id}", style="danger"),
                b("🌟 Sevimlidan olish" if fav else "⭐ Sevimli", f"fav:{movie_id}", style="primary")]])


def genres_text(s):
    return ", ".join(x for x in (s or "").split(",") if x)


async def send_movie(uid, movie, log_search=True):
    q("UPDATE movies SET views=views+1 WHERE id=?", (movie["id"],))
    if log_search:
        q("INSERT INTO searches VALUES(?,?,?)", (uid, movie["title"], now()))
    db.commit()
    cap = (f"🎬 <b>{esc(movie['title'])}</b>\n"
           f"📂 Turi: {esc(movie['kind'])}\n"
           f"🔑 Kod: <code>{esc(movie['code'])}</code>\n"
           f"🎭 Janr: {esc(genres_text(movie['genres']))}\n\n"
           f"{BOT_NAME} | {OFFICIAL}")
    markup = movie_kb(movie["id"], uid)
    if movie["ftype"] == "video":
        await bot.send_video(uid, movie["file_id"], caption=cap, reply_markup=markup)
    else:
        await bot.send_document(uid, movie["file_id"], caption=cap, reply_markup=markup)


def movies_list_kb(rows, back="search"):
    btns = [[b(f"🎬 {r['title']}", f"mv:{r['id']}", style="primary")] for r in rows]
    btns.append(back_btn(back))
    return kb(btns)


# ====================== FOYDALANUVCHI ======================
router = Router()


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    new = q("SELECT 1 FROM users WHERE id=?", (u.id,)).fetchone() is None
    q("INSERT OR IGNORE INTO users(id,name,joined) VALUES(?,?,?)", (u.id, u.full_name, now()), True)
    if new:
        await log(f"🆕 Yangi foydalanuvchi: {esc(u.full_name)} (<code>{u.id}</code>)")
    await send_start(u)


@router.message(Command("menu"))
async def cmd_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🗂Menyu", reply_markup=menu_kb())


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(HELP_TEXT, reply_markup=kb([back_btn("menu")]))


async def profile_text(uid):
    u = q("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    total = q("SELECT COUNT(*) c FROM searches WHERE user_id=?", (uid,)).fetchone()["c"]
    hist = q("SELECT DISTINCT query FROM searches WHERE user_id=? ORDER BY ts DESC LIMIT 10", (uid,)).fetchall()
    favs = q("SELECT m.title FROM favs f JOIN movies m ON m.id=f.movie_id WHERE f.user_id=?", (uid,)).fetchall()
    lks = q("SELECT m.title FROM likes l JOIN movies m ON m.id=l.movie_id WHERE l.user_id=?", (uid,)).fetchall()
    prem = f"💎 Premium ({fmt_date(u['premium_until'])} gacha)" if u and is_premium(uid) else "Oddiy"
    lst = lambda rows, key: "\n".join(f"• {esc(r[key])}" for r in rows) or "—"
    return (f"📍 <b>Profil</b>\n🆔 ID: <code>{uid}</code>\n🏷 Status: {prem}\n"
            f"🔍 Jami qidiruvlar: {total}\n\n"
            f"🕘 <b>Qidiruv tarixi (oxirgi 10):</b>\n{lst(hist, 'query')}\n\n"
            f"⭐ <b>Sevimlilar:</b>\n{lst(favs, 'title')}\n\n"
            f"❤️ <b>Like bosganlar:</b>\n{lst(lks, 'title')}")


@router.message(Command("profile"))
async def cmd_profile(m: Message):
    await m.answer(await profile_text(m.from_user.id), reply_markup=kb([back_btn("menu")]))


@router.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await show(cb, await profile_text(cb.from_user.id), kb([back_btn("menu")]))


@router.callback_query(F.data == "check")
async def cb_check(cb: CallbackQuery):
    if await allowed(cb.from_user.id):
        try:
            await cb.message.delete()
        except Exception:
            pass
        await send_start(cb.from_user)
        await cb.answer()
    else:
        await cb.answer("❌ Siz majburiy kanallarga obuna bo'lmadingiz!", show_alert=True)


@router.callback_query(F.data == "start_back")
async def cb_start_back(cb: CallbackQuery):
    if await allowed(cb.from_user.id):
        await show(cb, welcome_text(cb.from_user.full_name), welcome_kb())
    else:
        await show(cb, sub_text(cb.from_user.full_name), sub_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, "🗂Menyu", menu_kb())


@router.callback_query(F.data == "guide")
async def cb_guide(cb: CallbackQuery):
    await show(cb, GUIDE_TEXT, kb([back_btn("menu")]))


# ---------- Premium ----------
@router.callback_query(F.data == "prem")
async def cb_prem(cb: CallbackQuery):
    uid = cb.from_user.id
    back = "menu" if await allowed(uid) else "start_back"
    if is_premium(uid):
        u = q("SELECT premium_until FROM users WHERE id=?", (uid,)).fetchone()
        await show(cb, f"💎 Sizda Premium obuna faol!\n📅 Amal qilish muddati: {fmt_date(u['premium_until'])} gacha",
                   kb([back_btn(back)]))
        return
    await show(cb, PREMIUM_INFO, kb([
        [b("⭐Premiumni stars orqali", "pay", style="success")],
        [b("Admin orqali olish", url=SUPPORT_URL, style="primary")],
        back_btn(back)]))


@router.callback_query(F.data == "pay")
async def cb_pay(cb: CallbackQuery):
    await cb.answer()
    await bot.send_message(cb.from_user.id,
                           f"Botga ⭐️{PREMIUM_STARS} stars to'lash tugmasini bosing. To'lovdan so'ng bot "
                           f"avtomatik ishga tushadi: obunasiz va reklamalarsiz.")
    await bot.send_invoice(
        chat_id=cb.from_user.id, title=f"{BOT_NAME} Premium",
        description=f"{PREMIUM_DAYS} kunlik Premium obuna", payload="premium_30",
        currency="XTR", provider_token="",
        prices=[LabeledPrice(label=f"Premium {PREMIUM_DAYS} kun", amount=PREMIUM_STARS)])


@router.pre_checkout_query()
async def pre_checkout(p: PreCheckoutQuery):
    await p.answer(ok=True)


@router.message(F.successful_payment)
async def paid(m: Message):
    until = add_premium(m.from_user.id, PREMIUM_DAYS)
    await m.answer(f"✅ To'lov qabul qilindi! 💎Premium {fmt_date(until)} gacha faol.\n"
                   f"Endi majburiy obuna va reklamalarsiz foydalanishingiz mumkin.", reply_markup=menu_kb())
    await log(f"💎 Premium (Stars): {esc(m.from_user.full_name)} <code>{m.from_user.id}</code> "
              f"⭐{PREMIUM_STARS}")


# ---------- Statistika ----------
@router.callback_query(F.data == "stats")
async def cb_stats(cb: CallbackQuery):
    users = q("SELECT COUNT(*) c FROM users").fetchone()["c"]
    srch = q("SELECT COUNT(*) c FROM searches").fetchone()["c"]
    prem = q("SELECT COUNT(*) c FROM users WHERE premium_until>?", (now(),)).fetchone()["c"]
    await show(cb, f"📊 <b>Bot statistikasi</b>\n\n👥 Obunachilar: {users}\n🔍 Qidirilgan filmlar: {srch}\n"
                   f"💎 Premium egalari: {prem}",
               kb([[b("🏅Eng ko'p qidirilgan filmlar", "top", style="success")], back_btn("menu")]))


@router.callback_query(F.data == "top")
async def cb_top(cb: CallbackQuery):
    rows = q("SELECT title, views FROM movies WHERE views>0 ORDER BY views DESC LIMIT 20").fetchall()
    text = "🏅 <b>Eng ko'p qidirilgan 20 ta film va serial</b>\n\n"
    text += "\n".join(f"{i}. {esc(r['title'])} — {r['views']}" for i, r in enumerate(rows, 1)) or "Hozircha ma'lumot yo'q."
    await show(cb, text, kb([back_btn("stats")]))


# ---------- Qidiruv ----------
async def search_menu_text_kb(state: FSMContext):
    data = await state.get_data()
    sel = data.get("genres", [])
    markup = genre_kb(sel, extra=[
        [b("🔎Nomi orqali qidirish", "s_name", style="primary"), b("🔢Kod orqali qidirish", "s_code", style="primary")],
        [b("ℹ️Janrlar haqida", "g_about", style="success")],
        back_btn("menu")])
    return "🔍 <b>Film va seriallar qidirish</b>\nJanr tanlang (eng ko'pi 2 ta) yoki nom/kod bo'yicha qidiring:", markup


@router.callback_query(F.data == "search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await search_menu_text_kb(state)
    await show(cb, text, markup)


@router.callback_query(F.data == "s_name")
async def cb_s_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Search.name)
    await show(cb, "🔎 Film nomini yuboring:", kb([back_btn("search")]))


@router.callback_query(F.data == "s_code")
async def cb_s_code(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Search.code)
    await show(cb, "🔢 Film kodini yuboring:", kb([back_btn("search")]))


@router.message(Search.name, F.text, ~F.text.startswith("/"))
async def by_name(m: Message, state: FSMContext):
    text = m.text.strip()
    q("INSERT INTO searches VALUES(?,?,?)", (m.from_user.id, text, now()), True)
    rows = q("SELECT * FROM movies WHERE title LIKE ? COLLATE NOCASE ORDER BY views DESC LIMIT 50",
             (f"%{text}%",)).fetchall()
    await state.clear()
    if not rows:
        await m.answer("😔 Bunday nomli film topilmadi.", reply_markup=kb([back_btn("search")]))
    elif len(rows) == 1:
        await send_movie(m.from_user.id, rows[0], log_search=False)
    else:
        await m.answer(f"🔎 {len(rows)} ta natija. Nomi ustiga bosing:", reply_markup=movies_list_kb(rows))


@router.message(Search.code, F.text, ~F.text.startswith("/"))
async def by_code(m: Message, state: FSMContext):
    code = m.text.strip()
    q("INSERT INTO searches VALUES(?,?,?)", (m.from_user.id, f"kod: {code}", now()), True)
    r = q("SELECT * FROM movies WHERE code=?", (code,)).fetchone()
    await state.clear()
    if not r:
        await m.answer("😔 Bunday kodli film topilmadi.", reply_markup=kb([back_btn("search")]))
    else:
        await send_movie(m.from_user.id, r, log_search=False)


@router.callback_query(F.data.startswith("g:"))
async def cb_genre(cb: CallbackQuery, state: FSMContext):
    i = int(cb.data.split(":")[1])
    data = await state.get_data()
    sel = data.get("genres", [])
    if i in sel:
        sel.remove(i)
    elif len(sel) >= 2:
        await cb.answer("Eng ko'pi bilan 2 ta janr tanlash mumkin", show_alert=True)
        return
    else:
        sel.append(i)
    await state.update_data(genres=sel)
    text, markup = await search_menu_text_kb(state)
    try:
        await cb.message.edit_reply_markup(reply_markup=markup)
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "g_send")
async def cb_g_send(cb: CallbackQuery, state: FSMContext):
    sel = (await state.get_data()).get("genres", [])
    if not sel:
        await cb.answer("Avval janr tanlang!", show_alert=True)
        return
    sql = "SELECT * FROM movies WHERE " + " AND ".join("genres LIKE ?" for _ in sel) + " ORDER BY id DESC LIMIT 50"
    rows = q(sql, tuple(f"%,{GENRES[i]},%" for i in sel)).fetchall()
    names = ", ".join(GENRES[i] for i in sel)
    if not rows:
        await cb.answer("Bu janrda hozircha film yo'q", show_alert=True)
        return
    await show(cb, f"🎭 <b>{esc(names)}</b> — {len(rows)} ta natija.\nNomi ustiga bosing:", movies_list_kb(rows))


@router.callback_query(F.data == "g_about")
async def cb_g_about(cb: CallbackQuery):
    await show(cb, GENRE_ABOUT, kb([back_btn("search")]))


@router.callback_query(F.data.startswith("mv:"))
async def cb_movie(cb: CallbackQuery):
    r = q("SELECT * FROM movies WHERE id=?", (int(cb.data[3:]),)).fetchone()
    await cb.answer()
    if r:
        await send_movie(cb.from_user.id, r)


@router.callback_query(F.data.startswith("like:"))
async def cb_like(cb: CallbackQuery):
    mid, uid = int(cb.data[5:]), cb.from_user.id
    if q("SELECT 1 FROM likes WHERE user_id=? AND movie_id=?", (uid, mid)).fetchone():
        q("DELETE FROM likes WHERE user_id=? AND movie_id=?", (uid, mid), True)
    else:
        q("INSERT OR IGNORE INTO likes VALUES(?,?)", (uid, mid), True)
    try:
        await cb.message.edit_reply_markup(reply_markup=movie_kb(mid, uid))
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("fav:"))
async def cb_fav(cb: CallbackQuery):
    mid, uid = int(cb.data[4:]), cb.from_user.id
    if q("SELECT 1 FROM favs WHERE user_id=? AND movie_id=?", (uid, mid)).fetchone():
        q("DELETE FROM favs WHERE user_id=? AND movie_id=?", (uid, mid), True)
        msg = "Sevimlilardan olib tashlandi"
    else:
        q("INSERT OR IGNORE INTO favs VALUES(?,?)", (uid, mid), True)
        msg = "⭐ Sevimlilarga qo'shildi"
    try:
        await cb.message.edit_reply_markup(reply_markup=movie_kb(mid, uid))
    except Exception:
        pass
    await cb.answer(msg)


# ====================== ADMIN ======================
admin = Router()
admin.message.filter(IsAdmin())
admin.callback_query.filter(IsAdmin())

ADMIN_TEXT = (
    f"🛠 <b>{BOT_NAME} — admin panel</b>\n\n"
    "<b>Buyruqlar:</b>\n"
    "/st - shu panel va barcha buyruqlar\n"
    "/m - barcha foydalanuvchilarga xabar yuborish\n"
    "/rek - premiumsizlarga reklama yuborish\n"
    "/add - barcha filmlar ro'yxati\n\n"
    "<b>Tugmalar:</b>\n"
    "➕ Film/serial qo'shish - video yuborasiz, nom, kod, turi va janrlarni tanlaysiz\n"
    "📡 Majburiy kanal - kanal qo'shish/o'chirish (bot kanalda admin bo'lishi shart)\n"
    "🧾 Log kanal - botdagi hodisalar yuboriladigan kanal\n"
    "🎁 Premium sovg'a - foydalanuvchiga premium berish\n"
    "🔎 Qidiruv tarixi - oxirgi qidiruvlar\n"
    "📊 Bot statistikasi - umumiy raqamlar\n"
    "👥 Foydalanuvchilar - foydalanuvchilar ro'yxati\n"
    "👮 Admin qo'shish/olib tashlash (faqat bosh admin)\n"
    "🚫 Ban - foydalanuvchini bloklash/blokdan chiqarish")


def admin_kb():
    return kb([
        [b("➕Film/serial qo'shish", "a_add", style="success")],
        [b("📡Majburiy kanal qo'shish", "a_ch", style="primary"), b("🗑Kanallar", "a_chl", style="danger")],
        [b("🧾Log kanal qo'shish", "a_log", style="primary"), b("🎁Premium sovg'a", "a_gift", style="success")],
        [b("🔎Qidiruv tarixi", "a_hist", style="primary"), b("📊Bot statistikasi", "stats", style="primary")],
        [b("👥Foydalanuvchilar", "a_users", style="success")],
        [b("👮Admin qo'shish", "a_adm", style="primary"), b("➖Adminni olish", "a_admdel", style="danger")],
        [b("🚫Ban / Unban", "a_ban", style="danger")],
    ])


@admin.message(Command("st", ignore_case=True))
async def cmd_st(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(ADMIN_TEXT, reply_markup=admin_kb())


@admin.callback_query(F.data == "a_panel")
async def a_panel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, ADMIN_TEXT, admin_kb())


PANEL_BACK = kb([[b("⬅️Ortga qaytish", "a_panel", style="danger")]])


# --- Film qo'shish ---
@admin.callback_query(F.data == "a_add")
async def a_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddMovie.file)
    await show(cb, "🎞 Film/serial videosini (yoki faylini) yuboring:", PANEL_BACK)


@admin.message(AddMovie.file, F.video | F.document)
async def add_file(m: Message, state: FSMContext):
    if m.video:
        await state.update_data(file_id=m.video.file_id, ftype="video")
    else:
        await state.update_data(file_id=m.document.file_id, ftype="document")
    await state.set_state(AddMovie.title)
    await m.answer("✏️ Nomini yuboring:")


@admin.message(AddMovie.title, F.text, ~F.text.startswith("/"))
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(AddMovie.code)
    await m.answer("🔑 Kodini yuboring (masalan: 101):")


@admin.message(AddMovie.code, F.text, ~F.text.startswith("/"))
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip()
    if q("SELECT 1 FROM movies WHERE code=?", (code,)).fetchone():
        await m.answer("⚠️ Bu kod band. Boshqa kod yuboring:")
        return
    await state.update_data(code=code)
    await state.set_state(AddMovie.kind)
    await m.answer("📂 Turini tanlang:", reply_markup=kb([[b("🎬Kino", "k:Kino", style="primary"),
                                                           b("📺Serial", "k:Serial", style="success")]]))


@admin.callback_query(AddMovie.kind, F.data.startswith("k:"))
async def add_kind(cb: CallbackQuery, state: FSMContext):
    await state.update_data(kind=cb.data[2:], agen=[])
    await state.set_state(AddMovie.genres)
    await show(cb, "🎭 Janrlarni tanlang (1 yoki 2 ta), so'ng 💾Saqlash:",
               genre_kb([], prefix="ag", send_cb="a_save", send_text="💾Saqlash"))


@admin.callback_query(AddMovie.genres, F.data.startswith("ag:"))
async def add_genre(cb: CallbackQuery, state: FSMContext):
    i = int(cb.data.split(":")[1])
    sel = (await state.get_data()).get("agen", [])
    if i in sel:
        sel.remove(i)
    elif len(sel) >= 2:
        await cb.answer("Eng ko'pi bilan 2 ta janr", show_alert=True)
        return
    else:
        sel.append(i)
    await state.update_data(agen=sel)
    await cb.message.edit_reply_markup(reply_markup=genre_kb(sel, "ag", "a_save", "💾Saqlash"))
    await cb.answer()


@admin.callback_query(AddMovie.genres, F.data == "a_save")
async def add_save(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    sel = d.get("agen", [])
    if not sel:
        await cb.answer("Kamida 1 ta janr tanlang!", show_alert=True)
        return
    genres = "," + ",".join(GENRES[i] for i in sel) + ","
    q("INSERT INTO movies(code,title,kind,file_id,ftype,genres) VALUES(?,?,?,?,?,?)",
      (d["code"], d["title"], d["kind"], d["file_id"], d["ftype"], genres), True)
    await state.clear()
    await show(cb, f"✅ Qo'shildi: <b>{esc(d['title'])}</b> (kod: {esc(d['code'])})", PANEL_BACK)
    await log(f"➕ Yangi {esc(d['kind'])}: {esc(d['title'])} | kod {esc(d['code'])} | admin {cb.from_user.id}")


# --- Majburiy kanallar ---
@admin.callback_query(F.data == "a_ch")
async def a_ch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSt.channel)
    await show(cb, "📡 Kanal usernameni yuboring (masalan: @dodakinorasmiy).\n"
                   "Bot avval shu kanalda admin bo'lishi kerak.", PANEL_BACK)


@admin.message(AdminSt.channel, F.text, ~F.text.startswith("/"))
async def ch_save(m: Message, state: FSMContext):
    uname = m.text.strip()
    try:
        chat = await bot.get_chat(uname)
        url = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or "")
        q("INSERT OR REPLACE INTO channels VALUES(?,?,?)", (chat.id, chat.title, url), True)
        await m.answer(f"✅ Majburiy kanal qo'shildi: {esc(chat.title)}", reply_markup=PANEL_BACK)
        await state.clear()
    except Exception as e:
        await m.answer(f"❌ Kanal topilmadi yoki bot admin emas: {esc(e)}")


@admin.callback_query(F.data == "a_chl")
async def a_chl(cb: CallbackQuery):
    rows = q("SELECT * FROM channels").fetchall()
    btns = [[b(f"🗑 {r['title']}", f"chdel:{r['id']}", style="danger")] for r in rows]
    btns.append([b("⬅️Ortga qaytish", "a_panel", style="danger")])
    await show(cb, "📡 Majburiy kanallar (o'chirish uchun bosing):" if rows else "Majburiy kanal yo'q.", kb(btns))


@admin.callback_query(F.data.startswith("chdel:"))
async def chdel(cb: CallbackQuery):
    q("DELETE FROM channels WHERE id=?", (int(cb.data[6:]),), True)
    await cb.answer("O'chirildi")
    await a_chl(cb)


# --- Log kanal ---
@admin.callback_query(F.data == "a_log")
async def a_log(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSt.log)
    await show(cb, "🧾 Log kanal usernameni yoki ID sini yuboring (bot kanalda admin bo'lsin):", PANEL_BACK)


@admin.message(AdminSt.log, F.text, ~F.text.startswith("/"))
async def log_save(m: Message, state: FSMContext):
    try:
        t = m.text.strip()
        chat = await bot.get_chat(int(t) if t.lstrip("-").isdigit() else t)
        q("INSERT OR REPLACE INTO settings VALUES('log_chat',?)", (str(chat.id),), True)
        await state.clear()
        await m.answer("✅ Log kanal saqlandi.", reply_markup=PANEL_BACK)
        await log("✅ Log kanal ulandi.")
    except Exception as e:
        await m.answer(f"❌ Xato: {esc(e)}")


# --- Premium sovg'a ---
@admin.callback_query(F.data == "a_gift")
async def a_gift(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSt.gift)
    await show(cb, "🎁 Foydalanuvchi ID va kunni yuboring. Masalan: <code>123456789 30</code>", PANEL_BACK)


@admin.message(AdminSt.gift, F.text, ~F.text.startswith("/"))
async def gift_do(m: Message, state: FSMContext):
    try:
        parts = m.text.split()
        uid, days = int(parts[0]), int(parts[1]) if len(parts) > 1 else PREMIUM_DAYS
    except Exception:
        await m.answer("❌ Format: ID kun")
        return
    until = add_premium(uid, days)
    await state.clear()
    await m.answer(f"✅ {uid} ga {days} kun Premium berildi.", reply_markup=PANEL_BACK)
    try:
        await bot.send_message(uid, f"🎁 Sizga 💎Premium sovg'a qilindi! {fmt_date(until)} gacha amal qiladi.")
    except Exception:
        pass
    await log(f"🎁 Premium sovg'a: {uid}, {days} kun, admin {m.from_user.id}")


# --- Tarix / foydalanuvchilar ---
@admin.callback_query(F.data == "a_hist")
async def a_hist(cb: CallbackQuery):
    rows = q("SELECT * FROM searches ORDER BY ts DESC LIMIT 40").fetchall()
    text = "🔎 <b>Oxirgi qidiruvlar</b>\n\n" + ("\n".join(
        f"<code>{r['user_id']}</code> — {esc(r['query'])}" for r in rows) or "Hozircha yo'q.")
    await show(cb, text, PANEL_BACK)


@admin.callback_query(F.data == "a_users")
async def a_users(cb: CallbackQuery):
    rows = q("SELECT * FROM users ORDER BY joined DESC LIMIT 50").fetchall()
    text = "👥 <b>Oxirgi 50 foydalanuvchi</b>\n\n" + "\n".join(
        f"<code>{r['id']}</code> {esc(r['name'])} {'💎' if r['premium_until'] > now() else ''}"
        f"{'🚫' if r['banned'] else ''}" for r in rows)
    await show(cb, text, PANEL_BACK)


# --- Adminlar ---
@admin.callback_query(F.data.in_({"a_adm", "a_admdel"}))
async def a_adm(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != SUPER_ADMIN:
        await cb.answer("Faqat bosh admin uchun", show_alert=True)
        return
    await state.set_state(AdminSt.admin_add if cb.data == "a_adm" else AdminSt.admin_del)
    await show(cb, "👮 Foydalanuvchi ID sini yuboring:", PANEL_BACK)


@admin.message(AdminSt.admin_add, F.text, ~F.text.startswith("/"))
async def adm_add(m: Message, state: FSMContext):
    if m.from_user.id == SUPER_ADMIN and m.text.strip().isdigit():
        q("INSERT OR IGNORE INTO admins VALUES(?)", (int(m.text),), True)
        await state.clear()
        await m.answer("✅ Admin qo'shildi.", reply_markup=PANEL_BACK)
    else:
        await m.answer("❌ ID raqam bo'lishi kerak.")


@admin.message(AdminSt.admin_del, F.text, ~F.text.startswith("/"))
async def adm_del(m: Message, state: FSMContext):
    if m.from_user.id == SUPER_ADMIN and m.text.strip().isdigit():
        q("DELETE FROM admins WHERE id=?", (int(m.text),), True)
        await state.clear()
        await m.answer("✅ Admin olib tashlandi.", reply_markup=PANEL_BACK)
    else:
        await m.answer("❌ ID raqam bo'lishi kerak.")


# --- Ban ---
@admin.callback_query(F.data == "a_ban")
async def a_ban(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSt.ban)
    await show(cb, "🚫 Ban/unban uchun foydalanuvchi ID sini yuboring:", PANEL_BACK)


@admin.message(AdminSt.ban, F.text, ~F.text.startswith("/"))
async def ban_do(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("❌ ID raqam bo'lishi kerak.")
        return
    uid = int(m.text)
    if uid == SUPER_ADMIN:
        await m.answer("Bosh adminni banlab bo'lmaydi.")
        return
    r = q("SELECT banned FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        await m.answer("Bunday foydalanuvchi topilmadi.")
        return
    new = 0 if r["banned"] else 1
    q("UPDATE users SET banned=? WHERE id=?", (new, uid), True)
    await state.clear()
    await m.answer("🚫 Banlandi." if new else "✅ Blokdan chiqarildi.", reply_markup=PANEL_BACK)


# --- /m, /rek, /add ---
@admin.message(Command("m"))
async def cmd_m(m: Message, state: FSMContext):
    await state.set_state(AdminSt.bc_all)
    await m.answer("📣 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring:")


@admin.message(Command("rek"))
async def cmd_rek(m: Message, state: FSMContext):
    await state.set_state(AdminSt.bc_ads)
    await m.answer("📢 Premiumsizlarga yuboriladigan reklamani yuboring:")


async def broadcast(m: Message, state: FSMContext, only_free):
    await state.clear()
    sql = "SELECT id FROM users WHERE banned=0"
    if only_free:
        sql += f" AND premium_until<={now()}"
    ids = [r["id"] for r in q(sql).fetchall()]
    await m.answer(f"⏳ {len(ids)} ta foydalanuvchiga yuborilmoqda...")
    ok = 0
    for uid in ids:
        try:
            await bot.copy_message(uid, m.chat.id, m.message_id)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await m.answer(f"✅ Yuborildi: {ok}/{len(ids)}")
    await log(f"📣 Xabar tarqatildi: {ok}/{len(ids)} (admin {m.from_user.id})")


@admin.message(AdminSt.bc_all)
async def bc_all(m: Message, state: FSMContext):
    await broadcast(m, state, False)


@admin.message(AdminSt.bc_ads)
async def bc_ads(m: Message, state: FSMContext):
    await broadcast(m, state, True)


@admin.message(Command("add"))
async def cmd_add(m: Message):
    rows = q("SELECT code, title, kind FROM movies ORDER BY id").fetchall()
    if not rows:
        await m.answer("Hozircha film yo'q.")
        return
    lines = [f"<code>{esc(r['code'])}</code> | {esc(r['title'])} ({esc(r['kind'])})" for r in rows]
    chunk = "🎞 <b>Barcha filmlar:</b>\n"
    for ln in lines:
        if len(chunk) + len(ln) > 3800:
            await m.answer(chunk)
            chunk = ""
        chunk += ln + "\n"
    await m.answer(chunk)


# ====================== ISHGA TUSHIRISH ======================
async def main():
    init_db()
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(Guard())
    dp.callback_query.outer_middleware(Guard())
    dp.include_router(admin)
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("%s ishga tushdi", BOT_NAME)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
