import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import logging
import sqlite3
from datetime import datetime, timedelta

# إعداد التسجيل لتتبع الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# المتغيرات الأساسية
BASE_URL = "https://ak.sv"
SEARCH_URL = BASE_URL + "/search"
TOKEN = "7514489443:AAEXW3fXRNNGdJwKOD6vXyK-jxx5ZrRTPIw"
ADMIN_ID = 7234864373
CHANNEL_ID = "-1002253732336"  # معرّف القناة الخاصة
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": BASE_URL,
    "Accept-Language": "ar",
    "Accept-Encoding": "gzip, deflate"
}

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
        f"🕒 الوقت: {datetime.now().strftime('%H:%M:%S')}"  # إضافة علامة زمنية لتجنب "Message is not modified"
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
            "أنا هنا لمساعدتك في البحث عن الأفلام والمسلسلات وإيجاد روابط التحميل بسهولة.\n"
            "اختر ما تريد البحث عنه:\n"
            "🎬 /movies - للأفلام\n"
            "📺 /series - للمسلسلات\n"
            "📜 /history - لعرض سجل البحث الخاص بك"
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
        "أنا هنا لمساعدتك في البحث عن الأفلام والمسلسلات وإيجاد روابط التحميل بسهولة.\n"
        "اختر ما تريد البحث عنه:\n"
        "🎬 /movies - للأفلام\n"
        "📺 /series - للمسلسلات\n"
        "📜 /history - لعرض سجل البحث الخاص بك"
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
        await update.message.reply_text("لم تقم بأي عمليات بحث بعد! ابدأ بالبحث باستخدام /movies أو /series.")
        return
    message = "📜 سجل البحث الأخير (آخر 5 عمليات):\n"
    for query, mode, timestamp in history:
        mode_text = "فيلم" if mode == "movies" else "مسلسل"
        message += f"🔍 البحث: {query}\nنوع: {mode_text}\nوقت البحث: {timestamp}\n"
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

# دالة معالجة اختيار الأفلام
async def start_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    context.user_data["mode"] = "movies"
    await update.message.reply_text("اكتب اسم الفيلم الذي تريد البحث عنه 👇")

# دالة معالجة اختيار المسلسلات
async def start_series(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    context.user_data["mode"] = "series"
    await update.message.reply_text("اكتب اسم المسلسل الذي تريد البحث عنه 👇")

# دالة البحث العام
async def search_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("يرجى تحديد ما تريد البحث عنه باستخدام /movies أو /series.")
        return
    query = update.message.text.strip()
    add_search_history(user_id, query, mode)
    if mode == "movies":
        await search_movies_handler(update, context, query)
    elif mode == "series":
        await search_series_handler(update, context, query)

# دالة البحث عن الأفلام
async def search_movies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        params = {"q": query}
        response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select('.entry-box.entry-box-1')
        if not results:
            await update.message.reply_text(
                "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
                "جرب كتابة اسم الفيلم بشكل مختلف أو ابحث عن ممثل."
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
        await update.message.reply_text("اختر الفيلم المناسب من القائمة أدناه:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن الأفلام: {e}")
        await update.message.reply_text(
            "🤷🏻‍♂️ لم يتم العثور على أفلام بهذا الاسم.\n"
            "جرب كتابة اسم الفيلم بشكل مختلف أو ابحث عن ممثل."
        )

# دالة البحث عن المسلسلات
async def search_series_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    try:
        params = {"q": query}
        response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        results = soup.select(".widget .entry-box")
        if not results:
            await update.message.reply_text("لم يتم العثور على نتائج. حاول البحث باسم آخر.")
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
        await update.message.reply_text("اختر المسلسل المناسب من القائمة أدناه:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في البحث عن المسلسلات: {e}")
        await update.message.reply_text("حدث خطأ أثناء البحث. حاول مرة أخرى.")

# دالة استخراج الرابط النهائي
def get_final_download_link(url, quality_id=None, is_episode=False):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
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
        response = requests.get(intermediate_link, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        click_here_button = soup.select_one('a.download-link[href^="https://"]')
        if not click_here_button:
            logger.error(f"لم يتم العثور على رابط 'Click here' في {intermediate_link}")
            return None
        direct_link_page = click_here_button['href']
        response = requests.get(direct_link_page, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        final_download_button = soup.select_one('a.link.btn.btn-light[download]')
        if not final_download_button:
            logger.error(f"لم يتم العثور على الرابط النهائي في {direct_link_page}")
            return None
        return final_download_button['href']
    except Exception as e:
        logger.error(f"خطأ أثناء استخراج الرابط من {url}: {e}")
        return None

# دالة معالجة اختيار الفيلم
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
        response = requests.get(movie_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        quality_options = soup.select(".header-tabs.tabs li a")
        if not quality_options:
            await query.edit_message_text("ما لقيتش جودات متاحة للفيلم ده.")
            return
        keyboard = []
        context.user_data["qualities"] = []
        for quality in quality_options:
            quality_text = quality.text.strip()
            quality_id = quality["href"].replace("#", "")
            context.user_data["qualities"].append({"text": quality_text, "id": quality_id})
            keyboard.append([InlineKeyboardButton(quality_text, callback_data=f"quality_{quality_text}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر الجودة اللي عايزها:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في جلب الجودات من {movie_url}: {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب الجودات. حاول مرة أخرى.")

# دالة معالجة اختيار الجودة
async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    await query.edit_message_text("⏳ جاري تجهيز رابط التحميل...")
    quality_selected = query.data.split("_")[1]
    qualities = context.user_data.get("qualities")
    movie_url = context.user_data.get("movie_url")
    if not qualities or not movie_url:
        await query.edit_message_text("حصل خطأ. جرب تاني.")
        return
    quality_id = None
    for q in qualities:
        if q["text"] == quality_selected:
            quality_id = q["id"]
            break
    if not quality_id:
        await query.edit_message_text("الجودة مش موجودة. جرب تاني.")
        return
    final_link = get_final_download_link(movie_url, quality_id=quality_id, is_episode=False)
    if not final_link:
        await query.edit_message_text("حدث خطأ أثناء استخراج رابط التحميل. جرب مرة أخرى.")
        return
    message = (
        "رابط تحميل الفيلم جاهز! 😊\n"
        "اضغط هنا للتحميل:\n"
        f"<a href='{final_link}'>📥 تحميل الفيلم</a>\n"
        "لبحث جديد اختار القسم أولاً:\n"
        "🎬 /movies - للأفلام\n"
        "📺 /series - للمسلسلات"
    )
    await query.edit_message_text(message, parse_mode="HTML")

# دالة معالجة اختيار المسلسل
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
        response = requests.get(series_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
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
        await query.edit_message_text("اختر الحلقة المناسبة من القائمة أدناه:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في جلب الحلقات من {series_url}: {e}")
        await query.edit_message_text("حدث خطأ أثناء جلب الحلقات. حاول مرة أخرى.")

# دالة معالجة اختيار الحلقة
async def episode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await prompt_subscription(update, context)
        return
    await query.edit_message_text("⏳ جاري تجهيز رابط التحميل...")
    selected_index = int(query.data.split("_")[1])
    episodes_list = context.user_data.get("episodes")
    if not episodes_list or selected_index >= len(episodes_list):
        await query.edit_message_text("اختيار غير صحيح. يرجى المحاولة مرة أخرى.")
        return
    episode_url = episodes_list[selected_index]["link"]
    final_link = get_final_download_link(episode_url, is_episode=True)
    if not final_link:
        await query.edit_message_text("حدث خطأ أثناء استخراج رابط التحميل. جرب مرة أخرى.")
        return
    message = (
        "رابط تحميل الحلقة جاهز! 😊\n"
        "اضغط هنا للتحميل:\n"
        f"<a href='{final_link}'>📥 تحميل الحلقة</a>\n"
        "لبحث جديد اختار القسم أولاً:\n"
        "🎬 /movies - للأفلام\n"
        "📺 /series - للمسلسلات"
    )
    await query.edit_message_text(message, parse_mode="HTML")

# إعداد البوت
def main():
    logger.info("🤖 Aflamia bot is running...")
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("movies", start_movies))
    application.add_handler(CommandHandler("series", start_series))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_content))
    application.add_handler(CallbackQueryHandler(handle_movie_selection, pattern=r"^movie_\d+$"))
    application.add_handler(CallbackQueryHandler(series_callback, pattern=r"^series_\d+$"))
    application.add_handler(CallbackQueryHandler(episode_callback, pattern=r"^episode_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_quality_selection, pattern=r"^quality_.+$"))
    application.add_handler(CallbackQueryHandler(check_subscription_button, pattern=r"^check_subscription$"))
    application.run_polling()

if __name__ == "__main__":
    main()
