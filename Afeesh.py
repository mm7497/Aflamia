import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

BOT_TOKEN = "7514489443:AAEXW3fXRNNGdJwKOD6vXyK-jxx5ZrRTPIw"

movie_links = {}

def search_movies(query):
    url = "https://ak.sv/search"
    params = {"q": query}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://ak.sv/"}
    response = requests.get(url, params=params, headers=headers)
    
    if response.status_code != 200:
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    results = []
    for item in soup.select('.entry-box.entry-box-1'):
        title_element = item.select_one('.entry-title a')
        if not title_element:
            continue
        
        title = title_element.text.strip()
        link = title_element['href']
        movie_id = link.split("/")[-1]
        movie_links[movie_id] = link
        
        results.append({"title": title, "id": movie_id})
    
    return results

async def start_search(update: Update, context):
    query = update.message.text
    results = search_movies(query)
    
    if not results:
        await update.message.reply_text(
            "🤷🏻‍♂️ شكل الفيلم دا مش عندي\n\n"
            "جرب كدا تكتب اسم الفيلم بشكل تاني "
            "ولو حصلت مشكلة اكتب اسم الممثل 👌"
        )
        return
    
    keyboard = [[InlineKeyboardButton(result["title"], callback_data=result["id"])] for result in results]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("دوّر هنا كدا :", reply_markup=reply_markup)

async def handle_movie_selection(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    movie_id = query.data
    movie_url = movie_links.get(movie_id)
    
    if not movie_url:
        await query.edit_message_text(" 🤷🏻‍♂️لم يتم العثور على الفيلم.")
        return
    
    final_link = get_final_download_link(movie_url)
    
    if not final_link:
        await query.edit_message_text("بقولك ايه؟ جرب تاني 😅")
        return
    
    await query.edit_message_text(f'طب استلم مني وحمّل يا باشا ♥: <a href="{final_link}">اضغط هنا</a>', parse_mode="HTML")

def get_final_download_link(movie_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(movie_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        quality_section = soup.select_one('#tab-3')
        if not quality_section:
            return None
        
        download_button = quality_section.select_one('.link-download')
        if not download_button:
            return None
        
        intermediate_link = download_button['href']
        response = requests.get(intermediate_link, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        click_here_button = soup.find("a", class_="download-link")
        if not click_here_button:
            return None
        
        direct_link_page = click_here_button['href']
        response = requests.get(direct_link_page, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        final_download_button = soup.select_one(".btn.btn-light")
        if not final_download_button:
            return None
        
        return final_download_button['href']
    except Exception as e:
        print(f"خطأ أثناء استخراج الرابط: {e}")
        return None

async def start_command(update: Update, context):
    welcome_message = (
        "مرحبا بك في بوت أفلاميا - السينما بين ايديك - 🎬\n\n"
        "https://t.me/+7JRCObwnBRVhODU0\n\n"
        "انضم لقناة البوت عشان لو حصل مشكلة نقدر نوصلك ❤️\n\n"
        "وبعدها خش البوت تاني ابعت اسم الفيلم هنا ✅"
    )
    await update.message.reply_text(welcome_message)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start_search))
    application.add_handler(CallbackQueryHandler(handle_movie_selection, pattern=r"^[\w-]+$"))
    
    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
