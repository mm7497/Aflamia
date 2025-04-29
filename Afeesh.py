import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest
import logging
import sqlite3
from datetime import datetime
import cloudscraper
from selectolax.parser import HTMLParser
from retrying import retry
import urllib.parse
import random

# إعداد التسجيل لتتبع الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# قائمة User-Agents لمحاكاة أجهزة مختلفة
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0",
]

# دالة لاختيار User-Agent عشوائي
def get_random_user_agent():
    return random.choice(USER_AGENTS)

# المتغيرات الأساسية
BASE_URL = "https://ak.sv"
SEARCH_URL = BASE_URL + "/search"
WECIMA_BASE_URL = "https://wecima.film"
WECIMA_SEARCH_URL = WECIMA_BASE_URL + "/search/"
TOKEN = "7514489443:AAEXW3fXRNNGdJwKOD6vXyK-jxx5ZrRTPIw"
ADMIN_ID = 7234864373
CHANNEL_ID = "-1002253732336"  # معرّف القناة الخاصة
HEADERS = {
    "Referer": BASE_URL,
    "Accept-Language": "ar",
    "Accept-Encoding": "gzip, deflate"
}
WECIMA_HEADERS = {
    "Referer": WECIMA_BASE_URL,
    "Accept-Language": "ar",
    "Accept-Encoding": "gzip, deflate"
}
LOADING_STICKER = "CAACAgIAAxkBAAEOXddoDE2NEQho0cVVpFJNUenNGZJwkwACVQADr8ZRGmTn_PAl6RC_NgQ"

# حالات ConversationHandler
(DOWNLOAD_MOVIE_QUERY, DOWNLOAD_SERIES_QUERY, WATCH_MOVIE_QUERY, WATCH_SERIES_QUERY) = range(4)

# دالة للتحقق من صحة رابط التحميل
def is_valid_download_link(link):
    if not link:
        return False
    if ".mp4" in link or ".mkv" in link or "download" in link.lower():
        return True
    if link == BASE_URL or link.startswith(BASE_URL + "/?") or link.startswith(BASE_URL + "/#"):
        return False
    try:
        response = requests.head(link, allow_redirects=True, timeout=5)
        content_type = response.headers.get("content-type", "").lower()
        return "video" in content_type or "application/octet-stream" in content_type
    except Exception as e:
        logger.error(f"خطأ أثناء التحقق من الرابط {link}: {e}")
        return False

# دالة لاستقبال الستيكرات وتسجيل معرفها
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("هذا الأمر مخصص للأدمن فقط!")
        return
    sticker = update.message.sticker
    if sticker:
        sticker_id = sticker.file_id
        logger.info(f"Sticker ID: {sticker_id}")
        await update.message.reply_text(f"معرف الستيكر: {sticker_id}\nأضف هذا المعرف إلى LOADING_STICKER في الكود.")
    else:
        await update.message.reply_text("لم يتم إرسال ستيكر! أرسل ستيكرًا متحركًا.")

# إعداد قاعدة بيانات SQLite
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS search_history (
        user_id INTEGER, 
        query TEXT, 
        mode TEXT, 
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

# إضافة مستخدم إلى قاعدة البيانات
def add_user(user_id, username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

# إضافة سجل بحث
def add_search_history(user_id, query, mode):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO search_history (user_id, query, mode) VALUES (?, ?, ?)", (user_id, query, mode))
    conn.commit()
    conn.close()

# جلب جميع المستخدمين
def get_all_users():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    return [user[0] for user in users]

# جلب آخر 5 عمليات بحث للمستخدم
def get_user_search_history(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT query, mode, timestamp FROM search_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
    history = c.fetchall()
    conn.close()
    return history

# التحقق من اشتراك المستخدم في القناة
async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"خطأ في التحقق من الاشتراك: {e}")
        return False

# رسالة الاشتراك الإجباري
async def prompt_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 انضم إلى القناة", url="https://t.me/+7JRCObwnBRVhODU0")],
        [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = (
        f"⚠️ لاستخدام البوت، يجب عليك الاشتراك في قناتنا أولاً!\n"
        "📢 انضم إلى القناة ثم اضغط على 'تحقق من الاشتراك'.\n"
        f"🕒 الوقت: {datetime.now().strftime('%H:%M:%S')}"
    )
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)

# دالة التحقق من الاشتراك عبر الزر
async def check_subscription_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if is_subscribed:
        user_name = query.from_user.first_name
        add_user(user_id, user_name)
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"عضو جديد انضم! 🎉\nالاسم: {user_name}\nالمعرف: {user_id}"
        )
        welcome_message = (
            f"مرحبًا {user_name}! 🎉\n"
            "أنا هنا لمساعدتك في تحميل أو مشاهدة الأفلام والمسلسلات.\n"
            "اختر ما تريد:\n"
            "🎬 /download_movie - لتحميل فيلم\n"
            "📺 /download_series - لتحميل مسلسل\n"
            "👀 /watch_movie - لمشاهدة فيلم\n"
            "📽 /watch_series - لمشاهدة مسلسل\n"
            "📜 /history - لعرض سجل البحث\n"
            "🚫 /cancel - لإلغاء أي عملية"
        )
        await query.edit_message_text(welcome_message)
    else:
        await prompt_subscription(update, context)

# الدالة الرئيسية للترحيب بالمستخدم
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    user = update.message.from_user
    user_name = user.first_name
    add_user(user_id, user_name)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"عضو جديد انضم! 🎉\nالاسم: {user_name}\nالمعرف: {user_id}"
    )
    welcome_message = (
        f"مرحبًا {user_name}! 🎉\n"
        "أنا هنا لمساعدتك في تحميل أو مشاهدة الأفلام والمسلسلات.\n"
        "اختر ما تريد:\n"
        "🎬 /download_movie - لتحميل فيلم\n"
        "📺 /download_series - لتحميل مسلسل\n"
        "👀 /watch_movie - لمشاهدة فيلم\n"
        "📽 /watch_series - لمشاهدة مسلسل\n"
        "📜 /history - لعرض سجل البحث\n"
        "🚫 /cancel - لإلغاء أي عملية"
    )
    await update.message.reply_text(welcome_message)

# دالة عرض سجل البحث
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    history = get_user_search_history(user_id)
    if not history:
        await update.message.reply_text("لم تقم بأي عمليات بحث بعد! ابدأ باستخدام الأوامر المتاحة.")
        return
    message = "📜 سجل البحث الأخير (آخر 5 عمليات):\n"
    for query, mode, timestamp in history:
        mode_text = {
            "download_movie": "تحميل فيلم",
            "download_series": "تحميل مسلسل",
            "watch_movie": "مشاهدة فيلم",
            "watch_series": "مشاهدة مسلسل"
        }.get(mode, mode)
        message += f"🔍 البحث: {query}\nنوع: {mode_text}\nوقت البحث: {timestamp}\n\n"
    await update.message.reply_text(message)

# دالة إرسال رسالة جماعية
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("هذا الأمر مخصص للأدمن فقط!")
        return
    if not context.args:
        await update.message.reply_text("يرجى كتابة الرسالة بعد الأمر، مثال:\n/broadcast مرحبًا بكم!")
        return
    message = " ".join(context.args)
    users = get_all_users()
    success_count = 0
    fail_count = 0
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            success_count += 1
        except Exception as e:
            logger.error(f"فشل إرسال الرسالة إلى {user_id}: {e}")
            fail_count += 1
    await update.message.reply_text(
        f"تم إرسال الرسالة إلى {success_count} مستخدم بنجاح.\n"
        f"فشل إرسال الرسالة إلى {fail_count} مستخدم."
    )

# دوال التحميل
async def start_download_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    # مسح الحالات الأخرى
    context.user_data.pop("download_series_mode", None)
    context.user_data.pop("watch_movie_mode", None)
    context.user_data.pop("watch_series_mode", None)
    context.user_data["download_movie_mode"] = True
    await update.message.reply_text("اكتب اسم الفيلم الذي تريد تحميله 👇")
    return DOWNLOAD_MOVIE_QUERY

async def download_movie_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    if not context.user_data.get("download_movie_mode"):
        await update.message.reply_text("يرجى بدء عملية تحميل فيلم باستخدام /download_movie.")
        return ConversationHandler.END
    query = update.message.text.strip()
    add_search_history(user_id, query, "download_movie")
    user_agent = get_random_user_agent()
    context.user_data["current_user_agent"] = user_agent
    logger.info(f"بدء عملية بحث لتحميل فيلم: '{query}' بـ User-Agent: {user_agent}")
    await search_movies_handler(update, context, query)
    return ConversationHandler.END

async def start_download_series(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    # مسح الحالات الأخرى
    context.user_data.pop("download_movie_mode", None)
    context.user_data.pop("watch_movie_mode", None)
    context.user_data.pop("watch_series_mode", None)
    context.user_data["download_series_mode"] = True
    await update.message.reply_text("اكتب اسم المسلسل الذي تريد تحميله 👇")
    return DOWNLOAD_SERIES_QUERY

async def download_series_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    if not context.user_data.get("download_series_mode"):
        await update.message.reply_text("يرجى بدء عملية تحميل مسلسل باستخدام /download_series.")
        return ConversationHandler.END
    query = update.message.text.strip()
    add_search_history(user_id, query, "download_series")
    user_agent = get_random_user_agent()
    context.user_data["current_user_agent"] = user_agent
    logger.info(f"بدء عملية بحث لتحميل مسلسل: '{query}' بـ User-Agent: {user_agent}")
    await search_series_handler(update, context, query)
    return ConversationHandler.END

async def search_movies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
        headers = {**HEADERS, "User-Agent": user_agent}
        params = {"q": query}
        response = requests.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select('.entry-box.entry-box-1')
        if not results:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
                "جرب كتابة اسم الفيلم بشكل مختلف أو ابحث عن ممثل.\n"
                "👀 أو ممكن تشاهد بدون تحميل من قايمة /start"
            )
            return
        context.user_data["movie_results"] = []
        keyboard = []
        for idx, item in enumerate(results):
            title_element = item.select_one('.entry-title a')
            if not title_element:
                continue
            title = title_element.text.strip()
            link = title_element['href']
            context.user_data["movie_results"].append({"title": title, "link": link})
            keyboard.append([InlineKeyboardButton(title, callback_data=f"movie_{idx}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر الفيلم المناسب للتحميل:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن الأفلام للتحميل (User-Agent: {user_agent}): {e}")
        await update.message.reply_text(
            "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
            "جرب كتابة اسم الفيلم بشكل مختلف أو ابحث عن ممثل."
        )

async def search_series_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
        headers = {**HEADERS, "User-Agent": user_agent}
        params = {"q": query}
        response = requests.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        results = soup.select(".widget .entry-box")
        if not results:
            await update.message.reply_text("لم يتم العثور على نتائج. حاول البحث باسم آخر.\n"
                                           "📽 أو جرب مشاهدة المسلسل من /start")
            return
        context.user_data["search_results"] = []
        keyboard = []
        for idx, result in enumerate(results):
            title_element = result.select_one(".entry-title a")
            if title_element:
                title = title_element.text.strip()
                link = title_element["href"]
                context.user_data["search_results"].append({"title": title, "link": link})
                keyboard.append([InlineKeyboardButton(title, callback_data=f"series_{idx}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(" اختر المسلسل المناسب للتحميل لو ملقتوش في التحميل شوفة من هنا /start:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن المسلسلات للتحميل (User-Agent: {user_agent}): {e}")
        await update.message.reply_text("حدث خطأ أثناء البحث. حاول مرة أخرى.")

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_page(url, scraper=None, user_agent=None):
    decoded_url = urllib.parse.unquote(url)
    headers = {**HEADERS, "User-Agent": user_agent or get_random_user_agent()}
    logger.info(f"جلب الصفحة: {decoded_url} بـ User-Agent: {headers['User-Agent']}")
    if scraper:
        response = scraper.get(decoded_url, headers=headers, timeout=10)
    else:
        response = requests.get(decoded_url, headers=headers, timeout=10)
    response.raise_for_status()
    return response

def get_final_download_link(url, quality_id=None, is_episode=False, user_agent=None):
    try:
        response = fetch_page(url, user_agent=user_agent)
        soup = BeautifulSoup(response.text, 'html.parser')
        if is_episode:
            quality_selector = 'a[href="#tab-4"]'
            quality_button = soup.select_one(quality_selector)
            if not quality_button:
                logger.error(f"لم يتم العثور على زر الجودة في {url}")
                return None
            tab_id = quality_button["href"].replace("#", "")
        else:
            if not quality_id:
                logger.error(f"لم يتم تحديد معرف الجودة للفيلم في {url}")
                return None
            tab_id = quality_id
        tab_content = soup.select_one(f'div[id="{tab_id}"]')
        if not tab_content:
            logger.error(f"لم يتم العثور على تبويب الجودة {tab_id} في {url}")
            return None
        download_button = tab_content.select_one('.link-btn.link-download')
        if not download_button:
            logger.error(f"لم يتم العثور على زر التحميل في {url}")
            return None
        intermediate_link = download_button['href']
        scraper = cloudscraper.create_scraper(browser={
            'browser': 'chrome',
            'platform': 'windows',
            'mobile': False
        })
        response = fetch_page(intermediate_link, scraper, user_agent=user_agent)
        tree = HTMLParser(response.text)
        click_here_button = tree.css_first('a.download-link[href^="https://"]')
        if not click_here_button:
            logger.error(f"لم يتم العثور على رابط 'Click here' في {intermediate_link}")
            return None
        direct_link_page = click_here_button.attributes.get('href')
        response = fetch_page(direct_link_page, scraper, user_agent=user_agent)
        soup = BeautifulSoup(response.text, 'html.parser')
        final_download_button = soup.select_one('a[href][download], a.btn[href*="download"], a[href*=".mp4"]')
        if not final_download_button:
            logger.error(f"لم يتم العثور على الرابط النهائي في {direct_link_page}. HTML: {soup.prettify()[:500]}")
            return None
        final_link = urllib.parse.unquote(final_download_button['href'])
        if not is_valid_download_link(final_link):
            logger.error(f"الرابط النهائي غير صالح: {final_link}")
            return None
        return final_link
    except Exception as e:
        logger.error(f"خطأ أثناء استخراج الرابط من {url} (User-Agent: {user_agent}): {e}")
        return None

async def handle_movie_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    movie_index = int(query.data.split("_")[1])
    movie_results = context.user_data.get("movie_results")
    if not movie_results or movie_index >= len(movie_results):
        await query.edit_message_text("لم يتم العثور على رابط الفيلم. حاول مرة أخرى.")
        return
    movie_url = movie_results[movie_index]["link"]
    context.user_data["movie_url"] = movie_url
    try:
        user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
        response = fetch_page(movie_url, user_agent=user_agent)
        soup = BeautifulSoup(response.text, 'html.parser')
        quality_options = soup.select(".header-tabs.tabs li a")
        if not quality_options:
            await query.edit_message_text("لم يتم العثور على جودات متاحة لهذا الفيلم.")
            return
        keyboard = []
        context.user_data["qualities"] = []
        for quality in quality_options:
            quality_text = quality.text.strip()
            quality_id = quality["href"].replace("#", "")
            context.user_data["qualities"].append({"text": quality_text, "id": quality_id})
            keyboard.append([InlineKeyboardButton(quality_text, callback_data=f"quality_{quality_text}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر الجودة المطلوبة للتحميل:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في جلب الجودات من {movie_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب الجودات. حاول مرة أخرى لاحقًا.")

async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    try:
        sticker_message = await query.message.reply_sticker(sticker=LOADING_STICKER)
        context.user_data["sticker_message_id"] = sticker_message.message_id
        context.user_data["sticker_chat_id"] = sticker_message.chat_id
    except BadRequest as e:
        logger.error(f"خطأ أثناء إرسال الستيكر: {e}")
        await query.message.reply_text("⏳ جاري استخراج رابط التحميل...")
    await query.edit_message_text("⏳ جاري استخراج رابط التحميل...")
    quality_selected = query.data.split("_")[1]
    qualities = context.user_data.get("qualities")
    movie_url = context.user_data.get("movie_url")
    if not qualities or not movie_url:
        try:
            if "sticker_message_id" in context.user_data:
                await context.bot.delete_message(
                    chat_id=context.user_data["sticker_chat_id"],
                    message_id=context.user_data["sticker_message_id"]
                )
                del context.user_data["sticker_message_id"]
                del context.user_data["sticker_chat_id"]
        except BadRequest as e:
            logger.error(f"خطأ أثناء حذف رسالة الستيكر: {e}")
        await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى.")
        return
    quality_id = None
    for q in qualities:
        if q["text"] == quality_selected:
            quality_id = q["id"]
            break
    if not quality_id:
        try:
            if "sticker_message_id" in context.user_data:
                await context.bot.delete_message(
                    chat_id=context.user_data["sticker_chat_id"],
                    message_id=context.user_data["sticker_message_id"]
                )
                del context.user_data["sticker_message_id"]
                del context.user_data["sticker_chat_id"]
        except BadRequest as e:
            logger.error(f"خطأ أثناء حذف رسالة الستيكر: {e}")
        await query.edit_message_text("الجودة المختارة غير متوفرة. حاول مرة أخرى.")
        return
    user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
    final_link = get_final_download_link(movie_url, quality_id=quality_id, is_episode=False, user_agent=user_agent)
    try:
        if "sticker_message_id" in context.user_data:
            await context.bot.delete_message(
                chat_id=context.user_data["sticker_chat_id"],
                message_id=context.user_data["sticker_message_id"]
            )
            del context.user_data["sticker_message_id"]
            del context.user_data["sticker_chat_id"]
    except BadRequest as e:
        logger.error(f"خطأ أثناء حذف رسالة الستيكر: {e}")
    if not final_link or ".mp4" not in final_link:
        message = (
            "أسفين، دي مشكلة مؤقتة في الفيلم دا 😔\n"
            "يمكنك اختيار مشاهدة الفيلم بدون تحميل باستخدام الأمر:\n"
            " /cancel"
        )
        await query.edit_message_text(message)
        return
    message = (
        "رابط تحميل الفيلم جاهز! 😊\n"
        "اضغط على الزر للتحميل:\n"
        f"<a href='{final_link}'>📥 تحميل الفيلم</a>\n"
        "لبحث جديد اختر:\n"
        "🎬 /download_movie\n"
        "📺 /download_series\n"
        "👀 /watch_movie\n"
        "📽 /watch_series"
    )
    await query.edit_message_text(message, parse_mode="HTML")

async def series_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    selected_index = int(query.data.split("_")[1])
    series_results = context.user_data.get("search_results")
    if not series_results or selected_index >= len(series_results):
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    series_url = series_results[selected_index]["link"]
    try:
        user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
        response = fetch_page(series_url, user_agent=user_agent)
        soup = BeautifulSoup(response.content, "html.parser")
        episodes = soup.select(".bg-primary2")
        if not episodes:
            await query.edit_message_text("لم يتم العثور على حلقات لهذا المسلسل.")
            return
        context.user_data["episodes"] = []
        keyboard = []
        for idx, episode in enumerate(episodes):
            title_element = episode.select_one("h2 a")
            if title_element:
                title = title_element.text.strip()
                cleaned_title = f"الحلقة {title}"
                link = title_element["href"]
                context.user_data["episodes"].append({"title": cleaned_title, "link": link})
                keyboard.append([InlineKeyboardButton(cleaned_title, callback_data=f"episode_{idx}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر الحلقة المناسبة للتحميل:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في جلب الحلقات من {series_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب الحلقات. حاول مرة أخرى لاحقًا.")

async def episode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    try:
        sticker_message = await query.message.reply_sticker(sticker=LOADING_STICKER)
        context.user_data["sticker_message_id"] = sticker_message.message_id
        context.user_data["sticker_chat_id"] = sticker_message.chat_id
    except BadRequest as e:
        logger.error(f"خطأ أثناء إرسال الستيكر: {e}")
        await query.message.reply_text("⏳ جاري استخراج رابط التحميل...")
    await query.edit_message_text("⏳ جاري استخراج رابط التحميل...")
    selected_index = int(query.data.split("_")[1])
    episodes_list = context.user_data.get("episodes")
    if not episodes_list or selected_index >= len(episodes_list):
        try:
            if "sticker_message_id" in context.user_data:
                await context.bot.delete_message(
                    chat_id=context.user_data["sticker_chat_id"],
                    message_id=context.user_data["sticker_message_id"]
                )
                del context.user_data["sticker_message_id"]
                del context.user_data["sticker_chat_id"]
        except BadRequest as e:
            logger.error(f"خطأ أثناء حذف رسالة الستيكر: {e}")
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    episode_url = episodes_list[selected_index]["link"]
    user_agent = context.user_data.get("current_user_agent", get_random_user_agent())
    final_link = get_final_download_link(episode_url, is_episode=True, user_agent=user_agent)
    try:
        if "sticker_message_id" in context.user_data:
            await context.bot.delete_message(
                chat_id=context.user_data["sticker_chat_id"],
                message_id=context.user_data["sticker_message_id"]
            )
            del context.user_data["sticker_message_id"]
            del context.user_data["sticker_chat_id"]
    except BadRequest as e:
        logger.error(f"خطأ أثناء حذف رسالة الستيكر: {e}")
    if not final_link or ".mp4" not in final_link:
        message = (
            "أسفين، دي مشكلة مؤقتة في الحلقة دي 😔\n"
            "يمكنك اختيار مشاهدة الحلقة بدون تحميل باستخدام الأمر:\n"
            "📽 /cancel"
        )
        await query.edit_message_text(message)
        return
    message = (
        "رابط تحميل الحلقة جاهز! 😊\n"
        "اضغط على الزر للتحميل:\n"
        f"<a href='{final_link}'>📥 تحميل الحلقة</a>\n"
        "لبحث جديد اختر:\n"
        "🎬 /download_movie\n"
        "📺 /download_series\n"
        "👀 /watch_movie\n"
        "📽 /watch_series"
    )
    await query.edit_message_text(message, parse_mode="HTML")

# دوال المشاهدة
async def start_watch_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    # مسح الحالات الأخرى
    context.user_data.pop("download_movie_mode", None)
    context.user_data.pop("download_series_mode", None)
    context.user_data.pop("watch_series_mode", None)
    context.user_data["watch_movie_mode"] = True
    await update.message.reply_text("اكتب اسم الفيلم الذي تريد مشاهدته 👇")
    return WATCH_MOVIE_QUERY

async def watch_movie_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    if not context.user_data.get("watch_movie_mode"):
        await update.message.reply_text("يرجى بدء عملية مشاهدة فيلم باستخدام /watch_movie.")
        return ConversationHandler.END
    query = update.message.text.strip()
    add_search_history(user_id, query, "watch_movie")
    user_agent = get_random_user_agent()
    context.user_data["wecima_user_agent"] = user_agent
    logger.info(f"بدء عملية بحث لمشاهدة فيلم: '{query}' بـ User-Agent: {user_agent}")
    await search_wecima_films(update, context, query)
    return ConversationHandler.END

async def start_watch_series(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    # مسح الحالات الأخرى
    context.user_data.pop("download_movie_mode", None)
    context.user_data.pop("download_series_mode", None)
    context.user_data.pop("watch_movie_mode", None)
    context.user_data["watch_series_mode"] = True
    await update.message.reply_text("اكتب اسم المسلسل الذي تريد مشاهدته 👇")
    return WATCH_SERIES_QUERY

async def watch_series_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return ConversationHandler.END
    if not context.user_data.get("watch_series_mode"):
        await update.message.reply_text("يرجى بدء عملية مشاهدة مسلسل باستخدام /watch_series.")
        return ConversationHandler.END
    query = update.message.text.strip()
    add_search_history(user_id, query, "watch_series")
    user_agent = get_random_user_agent()
    context.user_data["wecima_user_agent"] = user_agent
    logger.info(f"بدء عملية بحث لمشاهدة مسلسل: '{query}' بـ User-Agent: {user_agent}")
    await search_wecima_series(update, context, query)
    return ConversationHandler.END

async def search_wecima_films(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        encoded_query = urllib.parse.quote(query)
        search_url = f"{WECIMA_SEARCH_URL}{encoded_query}/"
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select(".Grid--WecimaPosts .GridItem")
        if not results:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
                "جرب كتابة اسم الفيلم بشكل مختلف."
            )
            return
        context.user_data["wecima_film_results"] = []
        keyboard = []
        for idx, item in enumerate(results[:10]):
            title_element = item.select_one(".Thumb--GridItem a strong")
            link_element = item.select_one(".Thumb--GridItem a")
            if title_element and link_element:
                title = title_element.text.strip()
                link = link_element['href']
                if "/watch/" not in link:
                    continue
                context.user_data["wecima_film_results"].append({"title": title, "link": link})
                keyboard.append([InlineKeyboardButton(title, callback_data=f"wecima_film_{idx}")])
        if not keyboard:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
                "جرب كتابة اسم الفيلم بشكل مختلف."
            )
            return
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر الفيلم المناسب للمشاهدة:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن الأفلام في wecima (User-Agent: {user_agent}): {e}")
        await update.message.reply_text(
            "🤷🏻‍♂️ حدث خطأ أثناء البحث. حاول مرة أخرى."
        )

async def search_wecima_series(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        encoded_query = urllib.parse.quote(query)
        search_url = f"{WECIMA_SEARCH_URL}{encoded_query}/"
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select(".Grid--WecimaPosts .GridItem")
        if not results:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على مسلسلات بهذا الاسم.\n"
                "جرب كتابة اسم المسلسل بشكل مختلف."
            )
            return
        context.user_data["wecima_series_results"] = []
        keyboard = []
        for idx, item in enumerate(results[:10]):
            title_element = item.select_one(".Thumb--GridItem a strong")
            link_element = item.select_one(".Thumb--GridItem a")
            if title_element and link_element:
                title = title_element.text.strip()
                link = link_element['href']
                if "/series/" not in link:
                    continue
                context.user_data["wecima_series_results"].append({"title": title, "link": link})
                keyboard.append([InlineKeyboardButton(title, callback_data=f"wecima_series_{idx}")])
        if not keyboard:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على مسلسلات بهذا الاسم.\n"
                "جرب كتابة اسم المسلسل بشكل مختلف."
            )
            return
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر المسلسل المناسب للمشاهدة:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن المسلسلات في wecima (User-Agent: {user_agent}): {e}")
        await update.message.reply_text(
            "🤷🏻‍♂️ حدث خطأ أثناء البحث. حاول مرة أخرى."
        )

async def handle_wecima_film_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    film_index = int(query.data.split("_")[2])
    film_results = context.user_data.get("wecima_film_results")
    if not film_results or film_index >= len(film_results):
        await query.edit_message_text("لم يتم العثور على رابط الفيلم. حاول مرة أخرى.")
        return
    film_url = film_results[film_index]["link"]
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        response = requests.get(film_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        server_button = soup.select_one(".MyCimaServer btn")
        if not server_button:
            await query.edit_message_text("لم يتم العثور على رابط مشاهدة لهذا الفيلم.")
            return
        stream_url = server_button.get("data-url")
        if not stream_url:
            await query.edit_message_text("لم يتم العثور على رابط مشاهدة لهذا الفيلم.")
            return
        message = (
            "استمتع وشاهد الفيلم بدون تحميل! 😊\n"
            f"<a href='{stream_url}'>📺 شاهد من هنا</a>\n"
            "لبحث جديد اختر:\n"
            "🎬 /download_movie\n"
            "📺 /download_series\n"
            "👀 /watch_movie\n"
            "📽 /watch_series"
        )
        await query.edit_message_text(message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"خطأ في جلب رابط المشاهدة من {film_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب رابط المشاهدة. حاول مرة أخرى لاحقًا.")

# دالة مساعدة لاستخراج الحلقات من صفحة
async def extract_episodes(soup, context, query, series_url, user_agent):
    episodes = soup.select(".Episodes--Seasons--Episodes a")
    if not episodes:
        await query.edit_message_text("لم يتم العثور على حلقات لهذا المسلسل.")
        return False
    context.user_data["wecima_episodes"] = []
    keyboard = []
    for idx, episode in enumerate(episodes):
        title_element = episode.select_one("episodetitle")
        link = episode['href']
        if title_element:
            title = title_element.text.strip()
            context.user_data["wecima_episodes"].append({"title": title, "link": link})
            keyboard.append([InlineKeyboardButton(title, callback_data=f"wecima_episode_{idx}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر الحلقة المناسبة للمشاهدة:", reply_markup=reply_markup)
    return True

async def handle_wecima_series_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    series_index = int(query.data.split("_")[2])
    series_results = context.user_data.get("wecima_series_results")
    if not series_results or series_index >= len(series_results):
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    series_url = series_results[series_index]["link"]
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        response = requests.get(series_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # التحقق من وجود مواسم
        seasons = soup.select(".List--Seasons--Episodes a")
        if seasons:
            # إذا وجدت مواسم، اعرض قائمة المواسم
            context.user_data["wecima_seasons"] = []
            keyboard = []
            for idx, season in enumerate(seasons):
                season_title = season.text.strip()
                season_link = season['href']
                context.user_data["wecima_seasons"].append({"title": season_title, "link": season_link})
                keyboard.append([InlineKeyboardButton(season_title, callback_data=f"wecima_season_{idx}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("اختر الموسم المناسب للمشاهدة:", reply_markup=reply_markup)
        else:
            # إذا لم توجد مواسم، استخرج الحلقات مباشرة
            if not await extract_episodes(soup, context, query, series_url, user_agent):
                await query.edit_message_text("لم يتم العثور على حلقات لهذا المسلسل.")
    except Exception as e:
        logger.error(f"خطأ في جلب المواسم أو الحلقات من {series_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب المواسم أو الحلقات. حاول مرة أخرى لاحقًا.")

async def handle_wecima_season_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    season_index = int(query.data.split("_")[2])
    seasons = context.user_data.get("wecima_seasons")
    if not seasons or season_index >= len(seasons):
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    season_url = seasons[season_index]["link"]
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        response = requests.get(season_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        if not await extract_episodes(soup, context, query, season_url, user_agent):
            await query.edit_message_text("لم يتم العثور على حلقات لهذا الموسم.")
    except Exception as e:
        logger.error(f"خطأ في جلب الحلقات من {season_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب الحلقات. حاول مرة أخرى لاحقًا.")

async def handle_wecima_episode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    episode_index = int(query.data.split("_")[2])
    episodes = context.user_data.get("wecima_episodes")
    if not episodes or episode_index >= len(episodes):
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    episode_url = episodes[episode_index]["link"]
    try:
        user_agent = context.user_data.get("wecima_user_agent", get_random_user_agent())
        headers = {**WECIMA_HEADERS, "User-Agent": user_agent}
        response = requests.get(episode_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        server_button = soup.select_one(".MyCimaServer btn")
        if not server_button:
            await query.edit_message_text("لم يتم العثور على رابط مشاهدة لهذه الحلقة.")
            return
        stream_url = server_button.get("data-url")
        if not stream_url:
            await query.edit_message_text("لم يتم العثور على رابط مشاهدة لهذه الحلقة.")
            return
        message = (
            "استمتع وشاهد الحلقة بدون تحميل! 😊\n"
            f"<a href='{stream_url}'>📺 شاهد من هنا</a>\n"
            "لبحث جديد اختر:\n"
            "🎬 /download_movie\n"
            "📺 /download_series\n"
            "👀 /watch_movie\n"
            "📽 /watch_series"
        )
        await query.edit_message_text(message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"خطأ في جلب رابط المشاهدة من {episode_url} (User-Agent: {user_agent}): {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب رابط المشاهدة. حاول مرة أخرى لاحقًا.")

# دالة الإلغاء
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم إلغاء العملية. اختر أمرًا جديدًا:\n"
                                    "🎬 /download_movie\n"
                                    "📺 /download_series\n"
                                    "👀 /watch_movie\n"
                                    "📽 /watch_series")
    context.user_data.clear()
    return ConversationHandler.END

# إعداد البوت
def main():
    logger.info("🤖 Aflamia bot is running...")
    init_db()
    application = Application.builder().token(TOKEN).build()

    # ConversationHandler لتحميل الأفلام
    download_movie_conv = ConversationHandler(
        entry_points=[CommandHandler("download_movie", start_download_movie)],
        states={
            DOWNLOAD_MOVIE_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, download_movie_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ConversationHandler لتحميل المسلسلات
    download_series_conv = ConversationHandler(
        entry_points=[CommandHandler("download_series", start_download_series)],
        states={
            DOWNLOAD_SERIES_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, download_series_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ConversationHandler لمشاهدة الأفلام
    watch_movie_conv = ConversationHandler(
        entry_points=[CommandHandler("watch_movie", start_watch_movie)],
        states={
            WATCH_MOVIE_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_movie_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ConversationHandler لمشاهدة المسلسلات
    watch_series_conv = ConversationHandler(
        entry_points=[CommandHandler("watch_series", start_watch_series)],
        states={
            WATCH_SERIES_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, watch_series_query)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(download_movie_conv)
    application.add_handler(download_series_conv)
    application.add_handler(watch_movie_conv)
    application.add_handler(watch_series_conv)
    application.add_handler(CallbackQueryHandler(handle_movie_selection, pattern=r"^movie_\d+$"))
    application.add_handler(CallbackQueryHandler(series_callback, pattern=r"^series_\d+$"))
    application.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_quality_selection, pattern=r"^quality_.+$"))
    application.add_handler(CallbackQueryHandler(check_subscription_button, pattern=r"^check_subscription$"))
    application.add_handler(CallbackQueryHandler(handle_wecima_film_selection, pattern=r"^wecima_film_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_wecima_series_selection, pattern=r"^wecima_series_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_wecima_season_selection, pattern=r"^wecima_season_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_wecima_episode_selection, pattern=r"^wecima_episode_\d+$"))

    application.run_polling()

if __name__ == "__main__":
    main()
