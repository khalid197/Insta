# -*- coding: utf-8 -*-
import telebot
from telebot import types
from telebot.types import Update
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, ClientError, TwoFactorRequired, RateLimitError,
    ChallengeRequired, # SelectChallengeRequired, <-- تأكد من أن هذا معلق أو محذوف
    FeedbackRequired
)
# import threading # علقنا هذا مؤقتًا إذا لم نكن نستخدمه حاليًا
import time
import uuid
import json
import flask
from flask import Flask, request, abort
import logging
import logging.handlers
import sys

# --- TEST IMPORTS ---
# سنستخدم print هنا لأنه يتم تنفيذه عند بدء تشغيل العامل (worker)
# قبل أن يتم تكوين الـ logger بالكامل أحيانًا.
print("--- STARTING DEPENDENCY IMPORT TEST ---")
try:
    import numpy
    print("[IMPORT TEST] Successfully imported numpy")
    import decorator
    print("[IMPORT TEST] Successfully imported decorator")
    import imageio
    print("[IMPORT TEST] Successfully imported imageio")
    import PIL # Pillow يتم استيرادها كـ PIL
    print("[IMPORT TEST] Successfully imported PIL (Pillow)")
    import proglog
    print("[IMPORT TEST] Successfully imported proglog")
    import imageio_ffmpeg
    print("[IMPORT TEST] Successfully imported imageio_ffmpeg")
    print("--- ALL CORE MOVIEPY DEPENDENCIES IMPORTED OK ---")
except ImportError as test_imp_err:
    print(f"!!!!!!!! FAILED TO IMPORT A MOVIEPY DEPENDENCY: {test_imp_err} !!!!!!!!!!")
except Exception as test_other_err:
    # التقاط أي أخطاء أخرى قد تحدث أثناء الاستيراد
    print(f"!!!!!!!! UNEXPECTED ERROR DURING DEPENDENCY IMPORT TEST: {test_other_err} !!!!!!!!!!")
print("--- FINISHED DEPENDENCY IMPORT TEST ---")
# --- END TEST IMPORTS ---


import os  # <-- الاستيراد الرئيسي لـ os

# --- Constants ---
SESSIONS_DIR = 'sessions'
TEMP_MEDIA_DIR = 'temp_media'

# --- Flask App Setup ---
app = Flask(__name__)
last_processed_update_id = 0

# --- Logging Setup ---
# ... (بقية الكود كما هو: setup_logger, Hardcoded Settings, إنشاء المجلدات, user_data, دوال instagrapi المساعدة, معالجات الأوامر والرسائل, upload_media_to_instagram, webhook, index, __main__) ...

# --- Logging Setup ---
def setup_logger():
    try:
        log_dir = 'logs'
        if not os.path.exists(log_dir): os.makedirs(log_dir)
        log_file = os.path.join(log_dir, 'insta_poster_bot.log')
        logger_instance = logging.getLogger('InstaPosterBotLogger')
        logger_instance.setLevel(logging.DEBUG) # مستوى DEBUG لرؤية كل شيء
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger_instance.addHandler(file_handler)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger_instance.addHandler(console_handler)
        # لا تطبع رسالة البدء هنا، دع كتلة الاختبار تطبع أولاً
        # logger_instance.info("----- Insta Poster Bot Starting -----")
        return logger_instance
    except Exception as e:
        print(f"❌ Error setting up logger: {e}")
        raise
logger = setup_logger() # نهيئ الـ logger بعد الاختبار

# --- Hardcoded Settings (للاختبار فقط - استبدل بمتغيرات البيئة للإنتاج!) ---
# ... (الكود المتبقي) ...

# --- Hardcoded Settings (للاختبار فقط - استبدل بمتغيرات البيئة للإنتاج!) ---
try:
    BOT_TOKEN = "8123567301:AAHyFMqPNgbS4Es5LUfZoHf017IBfZf36Oo" # <-- استخدم التوكن الحقيقي الجديد
    WEBHOOK_URL_BASE = "https://afsdfart34343.pythonanywhere.com" # <-- تأكد من اسم المستخدم
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is missing")
    if not WEBHOOK_URL_BASE: raise ValueError("WEBHOOK_URL_BASE is missing")

    bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
    logger.info("Bot initialized successfully.")
    WEBHOOK_URL_PATH = f"/webhook/"

except Exception as e:
    logger.critical(f"FATAL ERROR during initialization: {e}", exc_info=True)
    sys.exit(1)

# --- إنشاء المجلدات ---
try:
    if not os.path.exists(SESSIONS_DIR): os.makedirs(SESSIONS_DIR); logger.info(f"Created directory: {SESSIONS_DIR}")
    if not os.path.exists(TEMP_MEDIA_DIR): os.makedirs(TEMP_MEDIA_DIR); logger.info(f"Created directory: {TEMP_MEDIA_DIR}")
except OSError as e:
    logger.critical(f"Error creating directories: {e}", exc_info=True)
    sys.exit(1)

# --- قاموس بيانات المستخدمين (في الذاكرة) ---
user_data = {}

# --- دوال مساعدة للانستجرام ---
def get_session_path(chat_id):
    return os.path.join(SESSIONS_DIR, f"session_{chat_id}.json")

def save_session(client, chat_id):
    session_path = get_session_path(chat_id)
    try:
        settings = client.get_settings()
        with open(session_path, 'w') as outfile: json.dump(settings, outfile, indent=4)
        logger.info(f"Session saved for chat {chat_id} to {session_path}")
        if chat_id in user_data: user_data[chat_id]['username'] = client.username
    except Exception as e: logger.error(f"Error saving session for chat {chat_id}: {e}", exc_info=True)

def load_session(chat_id):
    session_path = get_session_path(chat_id)
    logger.debug(f"Attempting to load session from: {session_path} for chat {chat_id}")
    if os.path.exists(session_path):
        try:
            client = Client()
            with open(session_path, 'r') as infile: settings = json.load(infile)
            client.set_settings(settings)
            logger.debug(f"Attempting get_timeline_feed() for verification for chat {chat_id}...")
            client.get_timeline_feed()
            logger.info(f"Session loaded and verified successfully for chat {chat_id}. Username: {client.username}")
            user_data[chat_id] = {**user_data.get(chat_id, {}),'client': client, 'username': client.username, 'state': 'logged_in'}
            logger.info(f"[load_session] State set to 'logged_in' for chat {chat_id}")
            return client
        except (LoginRequired, ChallengeRequired) as auth_err:
             logger.warning(f"{type(auth_err).__name__} during session verification for chat {chat_id}. Session invalid/requires re-challenge.")
             try: os.remove(session_path)
             except Exception as e: logger.error(f"Error deleting invalid/challenged session file {session_path}: {e}")
        except Exception as e:
            logger.error(f"Exception loading/verifying session from {session_path} for chat {chat_id}: {e}", exc_info=True)
            try: os.remove(session_path)
            except Exception as re: logger.error(f"Error deleting potentially corrupt session file {session_path}: {re}")
        if chat_id in user_data:
            user_data[chat_id].pop('client', None); user_data[chat_id].pop('username', None)
        return None
    else:
        logger.debug(f"No session file found for chat {chat_id} at {session_path}")
        return None

def get_instagram_client(chat_id):
    logger.debug(f"get_instagram_client called for chat {chat_id}. Checking memory first.")
    if chat_id in user_data and 'client' in user_data[chat_id] and user_data.get(chat_id, {}).get('state') == 'logged_in':
        client = user_data[chat_id]['client']
        logger.debug(f"Found client object in memory for chat {chat_id}. Verifying...")
        try:
            client.get_timeline_feed()
            logger.debug(f"Memory client verified successfully for chat {chat_id}.")
            return client
        except (LoginRequired, ChallengeRequired) as auth_err:
             logger.warning(f"{type(auth_err).__name__} for memory client (chat {chat_id}). Removing and trying to load session.")
             user_data[chat_id].pop('client', None)
        except Exception as e:
            logger.error(f"Exception checking memory client for chat {chat_id}: {e}", exc_info=True)
            user_data[chat_id].pop('client', None)

    logger.debug(f"Client not valid in memory or state not logged_in for chat {chat_id}. Calling load_session.")
    loaded_client = load_session(chat_id)
    if loaded_client:
        logger.debug(f"load_session returned a valid client for chat {chat_id}.")
        return loaded_client

    logger.debug(f"No valid session or client found after all checks for chat {chat_id}.")
    if chat_id not in user_data or user_data.get(chat_id, {}).get('state') not in ['awaiting_username', 'awaiting_password', 'awaiting_challenge_code']:
         user_data[chat_id] = {**user_data.get(chat_id, {}), 'state': 'awaiting_login_command'}
         logger.debug(f"[get_instagram_client] State reset to 'awaiting_login_command' for chat {chat_id}")
    return None

# --- دالة تسجيل الدخول المعدلة ---
def login_to_instagram(chat_id, username, password):
    """تسجيل الدخول، مع محاولة التعامل مع ChallengeRequired (وتجاهل SelectChallengeRequired)."""
    client = Client()
    try:
        logger.info(f"Attempting Instagram login for {username} (Chat ID: {chat_id})...")
        user_data[chat_id]['temp_login_username'] = username
        user_data[chat_id]['temp_login_password'] = password
        client.login(username, password)
        logger.info(f"Instagram login successful for {username} without challenge.")
        user_data[chat_id]['client'] = client
        user_data[chat_id]['username'] = client.username
        user_data[chat_id]['state'] = 'logged_in'
        logger.info(f"[login_to_instagram] State set to 'logged_in' for chat {chat_id} after direct login.")
        save_session(client, chat_id)
        user_data[chat_id].pop('temp_login_username', None)
        user_data[chat_id].pop('temp_login_password', None)
        return client

    except ChallengeRequired as e:
        challenge_url = client.last_json.get('challenge', {}).get('url')
        logger.warning(f"ChallengeRequired for {username} (chat {chat_id}). Challenge URL: {challenge_url}")
        logger.debug(f"ChallengeRequired last_json: {client.last_json}")
        user_data[chat_id]['client'] = client
        user_data[chat_id]['challenge_url'] = challenge_url
        try:
            logger.info(f"Attempting to send challenge code request via EMAIL for chat {chat_id}")
            challenge_response = client.challenge_select_verify_method(challenge_url, 1, True)
            logger.info(f"Challenge select verify method response: {challenge_response}")
            user_data[chat_id]['state'] = 'awaiting_challenge_code'
            logger.info(f"[login_to_instagram] State set to 'awaiting_challenge_code' for chat {chat_id}")
            bot.send_message(chat_id,"🔒 يتطلب انستجرام تحققًا أمنيًا.\nتم (محاولة) إرسال رمز مكون من 6 أرقام إلى بريدك الإلكتروني.\n**من فضلك أرسل الرمز هنا للمتابعة.** أو استخدم /cancel.")
            return None
        except Exception as e_challenge:
            logger.error(f"Failed to initiate challenge verification for {username} (chat {chat_id}): {e_challenge}", exc_info=True)
            bot.send_message(chat_id, f"❌ فشل في بدء عملية التحقق الأمني.\nالخطأ: {e_challenge}\nيرجى المحاولة مرة أخرى لاحقًا أو /cancel.")
            user_data[chat_id].pop('client', None); user_data[chat_id].pop('challenge_url', None)
            user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
            user_data[chat_id]['state'] = 'awaiting_login_command'
            logger.info(f"[login_to_instagram] State reset to 'awaiting_login_command' after challenge initiation failure for chat {chat_id}")
            return None

    except TwoFactorRequired:
         logger.warning(f"Two Factor Authentication required for {username} (chat {chat_id}). Not supported.")
         bot.send_message(chat_id, "يتطلب حساب انستجرام الخاص بك المصادقة الثنائية (2FA). البوت لا يدعمها حاليًا.")
         if chat_id in user_data:
             user_data[chat_id].pop('client', None); user_data[chat_id].pop('username', None)
             user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
             user_data[chat_id].pop('challenge_url', None)
             user_data[chat_id]['state'] = 'awaiting_login_command'
             logger.info(f"[login_to_instagram] State reset to 'awaiting_login_command' due to 2FA for chat {chat_id}")
         return None
    except ClientError as e:
        logger.error(f"Instagram login failed for {username} (chat {chat_id}): {e}")
        bot.send_message(chat_id, f"❌ فشل تسجيل الدخول إلى انستجرام.\nالسبب: {e}")
        if chat_id in user_data:
             user_data[chat_id].pop('client', None); user_data[chat_id].pop('username', None)
             user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
             user_data[chat_id].pop('challenge_url', None)
             user_data[chat_id]['state'] = 'awaiting_login_command'
             logger.info(f"[login_to_instagram] State reset to 'awaiting_login_command' due to ClientError for chat {chat_id}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during Instagram login for {username} (chat {chat_id}): {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ حدث خطأ غير متوقع أثناء محاولة تسجيل الدخول: {e}")
        if chat_id in user_data:
             user_data[chat_id].pop('client', None); user_data[chat_id].pop('username', None)
             user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
             user_data[chat_id].pop('challenge_url', None)
             user_data[chat_id]['state'] = 'awaiting_login_command'
             logger.info(f"[login_to_instagram] State reset to 'awaiting_login_command' due to unexpected error for chat {chat_id}")
        return None

# --- معالجات الأوامر والرسائل ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    logger.info(f"Received /start or /help from chat {chat_id}")
    client = get_instagram_client(chat_id)
    current_state = user_data.get(chat_id, {}).get('state')
    logger.info(f"State after get_instagram_client in /start: {current_state} for chat {chat_id}")
    if client:
        username = user_data.get(chat_id, {}).get('username', 'N/A')
        bot.reply_to(message, f"أهلاً بك مجددًا!\nالجلسة محملة للحساب: `{username}`\nأرسل صورة/فيديو.", parse_mode="Markdown")
    else:
        user_data[chat_id]['state'] = 'awaiting_login_command'
        logger.info(f"[send_welcome] State reset to 'awaiting_login_command' for chat {chat_id}")
        bot.reply_to(message,"أهلاً بك!\nبوت نشر انستجرام.\n1. /login للدخول.\n2. أرسل صورة/فيديو.\n3. أرسل الكابشن.")

@bot.message_handler(commands=['login'])
def handle_login(message):
    chat_id = message.chat.id
    logger.info(f"Received /login from chat {chat_id}")
    client = get_instagram_client(chat_id)
    current_state = user_data.get(chat_id, {}).get('state')
    logger.info(f"State in /login after get_instagram_client: {current_state} for chat {chat_id}")
    if client:
        username = user_data.get(chat_id, {}).get('username', 'N/A')
        bot.send_message(chat_id, f"✅ أنت مسجل الدخول بالفعل كـ `{username}`.\nاستخدم /logout أولاً.", parse_mode="Markdown")
        return
    user_data[chat_id]['state'] = 'awaiting_username'
    logger.info(f"[handle_login] State set to 'awaiting_username' for chat {chat_id}")
    bot.send_message(chat_id, "🔑 يرجى إرسال اسم مستخدم انستجرام:")

@bot.message_handler(commands=['logout'])
def handle_logout(message):
    chat_id = message.chat.id
    logger.info(f"Received /logout from chat {chat_id}")
    session_path = get_session_path(chat_id)
    logged_out = False
    if os.path.exists(session_path):
        try: os.remove(session_path); logger.info(f"Deleted session file: {session_path}"); logged_out = True
        except Exception as e: logger.error(f"Error deleting session file {session_path}: {e}", exc_info=True)
    if chat_id in user_data: user_data.pop(chat_id, None); logged_out = True
    if logged_out: bot.send_message(chat_id, "🔒 تم تسجيل الخروج وحذف الجلسة.")
    else: bot.send_message(chat_id, "أنت لم تكن مسجلاً للدخول.")
    user_data[chat_id] = {'state': 'awaiting_login_command'}
    logger.info(f"[handle_logout] State set to 'awaiting_login_command' for chat {chat_id}")

@bot.message_handler(commands=['account'])
def handle_account(message):
    chat_id = message.chat.id
    logger.info(f"Received /account from chat {chat_id}")
    client = get_instagram_client(chat_id)
    current_state = user_data.get(chat_id, {}).get('state')
    logger.info(f"State in /account after get_instagram_client: {current_state} for chat {chat_id}")
    if client and 'username' in user_data.get(chat_id, {}):
        username = user_data[chat_id]['username']
        bot.send_message(chat_id, f"👤 الحساب الحالي:\n**المستخدم:** `{username}`", parse_mode="Markdown")
    else: bot.send_message(chat_id, "❌ أنت غير مسجل الدخول.")

@bot.message_handler(commands=['cancel'])
def handle_cancel(message):
    chat_id = message.chat.id
    logger.info(f"Received /cancel from chat {chat_id}")
    current_state = user_data.get(chat_id, {}).get('state')
    logger.info(f"Cancelling operation in state: {current_state}")
    media_path = user_data.get(chat_id, {}).get('media_path')
    if media_path and os.path.exists(media_path):
        try: os.remove(media_path); logger.info(f"Deleted temp media on cancel: {media_path}")
        except Exception as e: logger.error(f"Error deleting temp media {media_path} on cancel: {e}", exc_info=True)
    if chat_id in user_data:
        keys_to_pop = ['media_path', 'media_type', 'caption', 'challenge_url', 'temp_login_username', 'temp_login_password']
        for key in keys_to_pop: user_data[chat_id].pop(key, None)
        if current_state in ['awaiting_challenge_choice', 'awaiting_challenge_code']:
            user_data[chat_id].pop('client', None); logger.debug(f"Removed temp challenge client for chat {chat_id}")
    final_client = get_instagram_client(chat_id)
    final_state = user_data.get(chat_id, {}).get('state')
    logger.info(f"State after cancel and get_client: {final_state} for chat {chat_id}")
    if final_client:
        bot.send_message(chat_id, "تم إلغاء العملية. لا تزال مسجلاً للدخول.")
    else:
        bot.send_message(chat_id, "تم إلغاء العملية. أنت غير مسجل الدخول الآن.")

@bot.message_handler(func=lambda message: user_data.get(message.chat.id, {}).get('state') == 'awaiting_username')
def handle_username(message):
    chat_id = message.chat.id
    username = message.text.strip()
    if not username: bot.send_message(chat_id, "اسم المستخدم فارغ."); return
    user_data[chat_id]['_temp_username'] = username
    user_data[chat_id]['state'] = 'awaiting_password'
    logger.info(f"[handle_username] State set to 'awaiting_password' for chat {chat_id}")
    bot.send_message(chat_id,"🔒 الآن أرسل كلمة مرور انستجرام:")

@bot.message_handler(func=lambda message: user_data.get(message.chat.id, {}).get('state') == 'awaiting_password')
def handle_password(message):
    chat_id = message.chat.id
    password = message.text
    try: bot.delete_message(chat_id, message.message_id)
    except Exception as e: logger.warning(f"Could not delete password message: {e}")
    username = user_data.get(chat_id, {}).get('_temp_username')
    if not username: logger.error(f"Temp username missing for chat {chat_id}"); bot.send_message(chat_id, "خطأ، ابدأ من /login."); user_data[chat_id]['state'] = 'awaiting_login_command'; return
    bot.send_message(chat_id, "⏳ جاري محاولة تسجيل الدخول...")
    client = login_to_instagram(chat_id, username, password)
    if chat_id in user_data: user_data[chat_id].pop('_temp_username', None)
    if client: bot.send_message(chat_id, f"✅ تم تسجيل الدخول كـ `{client.username}`.\nأرسل صورة أو فيديو.", parse_mode="Markdown")

# --- معالج جديد لرمز التحقق ---
@bot.message_handler(func=lambda message: user_data.get(message.chat.id, {}).get('state') == 'awaiting_challenge_code')
def handle_challenge_code(message):
    chat_id = message.chat.id
    challenge_code = message.text.strip()
    logger.info(f"Received potential challenge code from chat {chat_id}: {challenge_code}")

    if not challenge_code.isdigit() or len(challenge_code) != 6:
        bot.send_message(chat_id, "❌ الرمز غير صالح. يجب أن يكون 6 أرقام. أرسله مرة أخرى أو /cancel.")
        return

    if chat_id not in user_data or 'client' not in user_data[chat_id] or 'challenge_url' not in user_data[chat_id]:
        logger.error(f"Challenge state inconsistency for chat {chat_id}. Missing client or challenge_url.")
        bot.send_message(chat_id, "حدث خطأ في حالة التحقق. ابدأ من /login.")
        user_data[chat_id]['state'] = 'awaiting_login_command'
        return

    client = user_data[chat_id]['client']
    challenge_url = user_data[chat_id]['challenge_url']
    username = user_data.get(chat_id, {}).get('temp_login_username', 'N/A')

    bot.send_message(chat_id, "⏳ جاري إرسال رمز التحقق...")
    try:
        logger.info(f"Attempting to send challenge code {challenge_code} for chat {chat_id}")
        code_response = client.challenge_code(challenge_url, challenge_code)
        logger.info(f"Challenge code submission response for chat {chat_id}: {code_response}")

        if code_response and client.user_id:
            logger.info(f"Challenge resolved successfully for {username} (chat {chat_id}). User ID: {client.user_id}")
            user_data[chat_id]['client'] = client
            user_data[chat_id]['username'] = client.username
            user_data[chat_id]['state'] = 'logged_in'
            logger.info(f"[handle_challenge_code] State set to 'logged_in' for chat {chat_id} after challenge resolution.")
            save_session(client, chat_id)
            user_data[chat_id].pop('challenge_url', None)
            user_data[chat_id].pop('temp_login_username', None)
            user_data[chat_id].pop('temp_login_password', None)
            bot.send_message(chat_id, f"✅ تم التحقق بنجاح وتسجيل الدخول كـ `{client.username}`!\nأرسل صورة أو فيديو.", parse_mode="Markdown")
        else:
            logger.error(f"Challenge code submission failed or did not result in login for chat {chat_id}. Response: {code_response}")
            bot.send_message(chat_id, "❌ فشل التحقق من الرمز. حاول /login مرة أخرى.")
            user_data[chat_id].pop('client', None); user_data[chat_id].pop('challenge_url', None)
            user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
            user_data[chat_id]['state'] = 'awaiting_login_command'
            logger.info(f"[handle_challenge_code] State reset to 'awaiting_login_command' after failed code submission for chat {chat_id}")

    except FeedbackRequired as fr:
        logger.error(f"FeedbackRequired encountered after challenge code for chat {chat_id}: {fr}")
        bot.send_message(chat_id, f"❌ يتطلب انستجرام إجراءً إضافيًا.\nالرسالة: {fr.message}\nحاول تسجيل الدخول من التطبيق.")
        user_data[chat_id].pop('client', None); user_data[chat_id].pop('challenge_url', None)
        user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
        user_data[chat_id]['state'] = 'awaiting_login_command'
        logger.info(f"[handle_challenge_code] State reset to 'awaiting_login_command' due to FeedbackRequired for chat {chat_id}")
    except Exception as e:
        logger.error(f"Error submitting challenge code for chat {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ حدث خطأ أثناء إرسال رمز التحقق: {e}. حاول /login مرة أخرى.")
        user_data[chat_id].pop('client', None); user_data[chat_id].pop('challenge_url', None)
        user_data[chat_id].pop('temp_login_username', None); user_data[chat_id].pop('temp_login_password', None)
        user_data[chat_id]['state'] = 'awaiting_login_command'
        logger.info(f"[handle_challenge_code] State reset to 'awaiting_login_command' due to exception for chat {chat_id}")


@bot.message_handler(func=lambda message: user_data.get(message.chat.id, {}).get('state') == 'awaiting_caption')
def handle_caption(message):
    chat_id = message.chat.id
    if message.content_type != 'text': bot.send_message(chat_id, "أرسل الكابشن (نص)."); return
    caption = message.text
    logger.info(f"Received caption for chat {chat_id}: '{caption[:50]}...'")
    user_data[chat_id]['caption'] = caption
    user_data[chat_id]['state'] = 'ready_to_post'
    logger.info(f"[handle_caption] State set to 'ready_to_post' for chat {chat_id}")
    bot.send_message(chat_id, f"👍 تم استلام الكابشن. جاري النشر...")
    upload_media_to_instagram(chat_id)

# --- دالة مساعدة للتحقق من الحالة وتسجيل الدخول ---
def check_login_and_state(message):
    chat_id = message.chat.id
    current_state_at_entry = user_data.get(chat_id, {}).get('state')
    logger.debug(f"check_login_and_state called for chat {chat_id}. State at entry: {current_state_at_entry}")

    client = get_instagram_client(chat_id)
    if not client:
        logger.warning(f"check_login_and_state failed for chat {chat_id}: not logged in (get_instagram_client returned None).")
        bot.send_message(chat_id, "❌ يرجى تسجيل الدخول أولاً باستخدام /login.")
        return False

    current_state_after_get = user_data.get(chat_id, {}).get('state')
    logger.debug(f"State after get_instagram_client in check_login_and_state for chat {chat_id}: {current_state_after_get}")

    if current_state_after_get != 'logged_in':
        logger.warning(f"check_login_and_state failed for chat {chat_id}: state is '{current_state_after_get}', expected 'logged_in'.")
        if current_state_after_get == 'awaiting_caption': bot.send_message(chat_id, "أرسل الكابشن أو /cancel.")
        elif current_state_after_get == 'awaiting_challenge_code': bot.send_message(chat_id, "أرسل رمز التحقق أو /cancel.")
        else: bot.send_message(chat_id, "حالة غير متوقعة. استخدم /cancel.")
        return False

    logger.debug(f"check_login_and_state passed for chat {chat_id}. Cleaning up previous media data.")
    old_media_path = user_data.get(chat_id, {}).get('media_path')
    if old_media_path and os.path.exists(old_media_path):
        try: os.remove(old_media_path)
        except Exception as e: logger.error(f"Could not delete previous temp media {old_media_path}: {e}", exc_info=True)
    if chat_id in user_data:
        user_data[chat_id].pop('media_path', None); user_data[chat_id].pop('media_type', None); user_data[chat_id].pop('caption', None)
    return True

# --- معالجات الصور والفيديو ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    current_state_before_check = user_data.get(chat_id, {}).get('state')
    logger.info(f"Received photo from chat {chat_id}. State before check: {current_state_before_check}")
    if not check_login_and_state(message): return
    bot.send_message(chat_id, "⏳ جاري تحميل الصورة...")
    try:
        photo_info = message.photo[-1]; file_info = bot.get_file(photo_info.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path)[1] or '.jpg'
        path = os.path.join(TEMP_MEDIA_DIR, f'{chat_id}_{uuid.uuid4()}{ext}')
        with open(path, 'wb') as f: f.write(downloaded_file)
        logger.info(f"Photo downloaded to: {path} for chat {chat_id}")
        user_data[chat_id].update({'media_path': path, 'media_type': 'photo', 'state': 'awaiting_caption'})
        logger.info(f"[handle_photo] State set to 'awaiting_caption' for chat {chat_id}")
        bot.send_message(chat_id, "🖼️ تم استلام الصورة.\nأرسل الآن الكابشن أو /cancel.")
    except Exception as e:
        logger.error(f"Error downloading photo for chat {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ حدث خطأ أثناء تحميل الصورة: {e}")
        if chat_id in user_data: user_data[chat_id]['state'] = 'logged_in'

@bot.message_handler(content_types=['video'])
def handle_video(message):
    chat_id = message.chat.id
    current_state_before_check = user_data.get(chat_id, {}).get('state')
    logger.info(f"Received video from chat {chat_id}. State before check: {current_state_before_check}")
    if not check_login_and_state(message): return
    bot.send_message(chat_id, "⏳ جاري تحميل الفيديو...")
    try:
        video_info = message.video; file_info = bot.get_file(video_info.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path)[1] or '.mp4'
        path = os.path.join(TEMP_MEDIA_DIR, f'{chat_id}_{uuid.uuid4()}{ext}')
        with open(path, 'wb') as f: f.write(downloaded_file)
        logger.info(f"Video downloaded to: {path} for chat {chat_id}")
        user_data[chat_id].update({'media_path': path, 'media_type': 'video', 'state': 'awaiting_caption'})
        logger.info(f"[handle_video] State set to 'awaiting_caption' for chat {chat_id}")
        bot.send_message(chat_id, "🎬 تم استلام الفيديو.\nأرسل الآن الكابشن أو /cancel.")
    except Exception as e:
        logger.error(f"Error downloading video for chat {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ حدث خطأ أثناء تحميل الفيديو: {e}")
        if chat_id in user_data: user_data[chat_id]['state'] = 'logged_in'

# --- دالة النشر الفعلية ---
def upload_media_to_instagram(chat_id):
    logger.info(f"Attempting to upload media for chat {chat_id}")
    required_keys = ['media_path', 'media_type', 'caption']
    if not (chat_id in user_data and all(key in user_data[chat_id] for key in required_keys)):
        logger.error(f"Upload failed for chat {chat_id}: incomplete data. Data: {user_data.get(chat_id)}")
        bot.send_message(chat_id, "❌ خطأ: بيانات النشر غير مكتملة. حاول إرسال الوسائط مرة أخرى.")
        if chat_id in user_data: user_data[chat_id]['state'] = 'logged_in'
        return

    media_path = user_data[chat_id]['media_path']
    media_type = user_data[chat_id]['media_type']
    caption = user_data[chat_id]['caption']
    logger.info(f"Preparing to upload {media_type}: {media_path} with caption for chat {chat_id}")

    if not os.path.exists(media_path):
         logger.error(f"Upload failed for chat {chat_id}: media file not found at {media_path}")
         bot.send_message(chat_id, "❌ خطأ: لم يتم العثور على ملف الوسائط المؤقت.")
         if chat_id in user_data: user_data[chat_id]['state'] = 'logged_in'
         return

    client = get_instagram_client(chat_id)
    if not client:
        logger.error(f"Upload failed for chat {chat_id}: Instagram client not available.")
        bot.send_message(chat_id, "❌ فقد الاتصال بانستجرام. استخدم /login مرة أخرى.")
        if os.path.exists(media_path):
            try: os.remove(media_path); logger.info(f"Deleted temporary media file after client failure: {media_path}")
            except Exception as e: logger.error(f"Error deleting temp media {media_path} after client failure: {e}", exc_info=True)
        if chat_id in user_data:
            user_data[chat_id].pop('media_path', None); user_data[chat_id].pop('media_type', None)
            user_data[chat_id].pop('caption', None); user_data[chat_id]['state'] = 'awaiting_login_command'
        return

    upload_successful = False
    try:
        logger.info(f"Calling instagrapi to upload {media_type} for chat {chat_id}...")
        # إضافة التسجيل قبل وبعد استدعاء الرفع
        if media_type == 'photo':
            logger.debug(f"--> IMMEDIATELY BEFORE client.photo_upload for chat {chat_id}")
            client.photo_upload(path=media_path, caption=caption)
            logger.debug(f"<-- IMMEDIATELY AFTER client.photo_upload for chat {chat_id}")

        elif media_type == 'video':
            # --- تم تبسيط هذا الجزء ---
            # سنحاول تعيين مسار ffmpeg كإجراء احترازي أخير، لكن لن نحاول الاستيراد هنا
            try:
                ffmpeg_exe_path = "/usr/bin/ffmpeg"
                os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_exe_path
                logger.info(f"Ensured IMAGEIO_FFMPEG_EXE environment variable is set to: {os.environ.get('IMAGEIO_FFMPEG_EXE')}")
            except Exception as ffmpeg_env_err:
                 logger.error(f"Error setting IMAGEIO_FFMPEG_EXE: {ffmpeg_env_err}", exc_info=True)
                 # لا نوقف العملية هنا، فقط نسجل الخطأ ونترك instagrapi تحاول

            # استدعاء دالة الرفع مباشرة، ونعتمد على كتلة except الرئيسية لالتقاط أي خطأ
            logger.info("Proceeding with video upload attempt...")
            logger.debug(f"--> IMMEDIATELY BEFORE client.video_upload for chat {chat_id}")
            client.video_upload(path=media_path, caption=caption)
            logger.debug(f"<-- IMMEDIATELY AFTER client.video_upload for chat {chat_id}")
            # --- نهاية الجزء المبسط ---

        else:
            logger.error(f"Unknown media type '{media_type}'"); raise ValueError(f"Unknown media type: {media_type}")

        # إذا لم يحدث استثناء، فالرفع نجح (أو على الأقل لم يتم اكتشاف فشله)
        logger.info(f"Upload process seems completed for {media_type} from chat {chat_id}")
        bot.send_message(chat_id, f"✅ تم نشر {media_type} بنجاح!") # إرسال رسالة النجاح
        upload_successful = True # اعتبار العملية ناجحة

    except LoginRequired:
         # ... (نفس كود التعامل مع LoginRequired) ...
         logger.error(f"LoginRequired during upload for chat {chat_id}. Session expired.")
         bot.send_message(chat_id, "❌ انقطع الاتصال بانستجرام أثناء الرفع. الجلسة انتهت. استخدم /login.")
         session_path = get_session_path(chat_id)
         if os.path.exists(session_path):
             try: os.remove(session_path); logger.info(f"Deleted expired session file: {session_path}")
             except Exception as e: logger.error(f"Error deleting expired session file {session_path}: {e}", exc_info=True)
         if chat_id in user_data:
             user_data[chat_id].pop('client', None); user_data[chat_id].pop('username', None)
             user_data[chat_id]['state'] = 'awaiting_login_command'
             logger.info(f"[upload_media] State reset to 'awaiting_login_command' due to LoginRequired for chat {chat_id}")

    except ClientError as e:
        # ... (نفس كود التعامل مع ClientError) ...
        logger.error(f"Instagram ClientError during upload for chat {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ فشل نشر {media_type}.\nالسبب: {e}")
    except Exception as e:
        # ... (نفس كود التعامل مع Exception، مع التحقق من moviepy/ffmpeg) ...
        error_str = str(e)
        # التحقق من رسائل الخطأ الشائعة المتعلقة بالاعتماديات المفقودة أو مشاكل المعالجة
        if "moviepy" in error_str or "ffmpeg" in error_str or "Please install moviepy" in error_str \
           or "ImportError" in error_str or "Could not find" in error_str or "Cannot open" in error_str:
             logger.critical(f"Video processing/dependency issue during upload for chat {chat_id}: {e}", exc_info=True)
             # إعطاء رسالة واضحة للمستخدم تشير إلى مشكلة الفيديو
             bot.send_message(chat_id, f"❌ حدث خطأ أثناء معالجة الفيديو أو بسبب اعتماديات مفقودة. تأكد من تثبيت `moviepy` و `ffmpeg` بشكل كامل وصحيح على الخادم.\nالخطأ: {e}")
        else:
             # أخطاء أخرى غير متوقعة
             logger.error(f"Unexpected error during upload for chat {chat_id}: {e}", exc_info=True)
             bot.send_message(chat_id, f"❌ حدث خطأ غير متوقع أثناء نشر {media_type}: {e}")

    finally:
        # ... (نفس كود finally لتنظيف الملفات وإعادة الحالة) ...
        logger.debug(f"Entering 'finally' block for upload process, chat {chat_id}")
        if os.path.exists(media_path):
            try: os.remove(media_path); logger.info(f"Deleted temporary media file: {media_path}")
            except Exception as e: logger.error(f"Error deleting temp media {media_path} in finally block: {e}", exc_info=True)

        if chat_id in user_data:
            user_data[chat_id].pop('media_path', None); user_data[chat_id].pop('media_type', None)
            user_data[chat_id].pop('caption', None)
            if 'client' in user_data[chat_id] and user_data[chat_id]['state'] != 'awaiting_login_command':
                user_data[chat_id]['state'] = 'logged_in'
                # لا نطبع رسالة إعادة الحالة هنا إلا إذا كنا متأكدين من النجاح، أو نعتمد على السجلات الأخرى
            else:
                 current_final_state = user_data.get(chat_id, {}).get('state')
                 logger.info(f"[upload_media] State remains '{current_final_state}' for chat {chat_id} after upload attempt.")

# --- معالج لأي رسالة أخرى غير متوقعة ---
@bot.message_handler(func=lambda message: True, content_types=['audio', 'document', 'text', 'location', 'contact', 'sticker'])
def handle_other_messages(message):
     chat_id = message.chat.id
     current_state = user_data.get(chat_id, {}).get('state')
     if message.content_type == 'text' and current_state in ['awaiting_caption', 'awaiting_challenge_code', 'awaiting_password', 'awaiting_username']: pass
     else: logger.warning(f"Received unexpected message type {message.content_type} from chat {chat_id} in state {current_state}")
     if current_state == 'awaiting_username': bot.send_message(chat_id,"أرسل اسم المستخدم (نص) أو /cancel.")
     elif current_state == 'awaiting_password': bot.send_message(chat_id,"أرسل كلمة المرور (نص) أو /cancel.")
     elif current_state == 'awaiting_challenge_code': bot.send_message(chat_id,"أرسل رمز التحقق (6 أرقام) أو /cancel.")
     elif current_state == 'awaiting_caption':
          if message.content_type == 'text': pass
          else: bot.send_message(chat_id,"أرسل الكابشن (نص) أو /cancel.")
     elif current_state == 'logged_in': bot.send_message(chat_id,"أرسل صورة أو فيديو أو /cancel أو /logout.")
     else: bot.send_message(chat_id,"غير متأكد. استخدم /start.")


# --- مسار الـ Webhook لاستقبال التحديثات من تيليجرام ---
@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    global last_processed_update_id
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = Update.de_json(json_string)
            logger.debug(f"Webhook received update (JSON): {json_string[:500]}...")
            if update.update_id > last_processed_update_id:
                logger.info(f"Processing update ID: {update.update_id}")
                # تشغيل المعالجة في thread منفصل لتجنب تعليق الـ webhook (اختياري لكن قد يساعد)
                # threading.Thread(target=bot.process_new_updates, args=([update],)).start()
                bot.process_new_updates([update]) # المعالجة المباشرة
                last_processed_update_id = update.update_id
            else:
                logger.warning(f"Skipping duplicate update ID: {update.update_id} (last processed: {last_processed_update_id})")
            return '', 200
        else:
            logger.error(f"Invalid content type received on webhook: {request.headers.get('content-type')}")
            abort(403)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return '', 200 # Always return 200 OK

# --- مسار اختياري للتأكد أن الخادم يعمل ---
@app.route('/')
def index():
    logger.info("Root URL accessed - Health check OK.")
    return "Insta Poster Bot is running!", 200

# --- Main Execution Block (Webhook) ---
if __name__ == "__main__":
    if WEBHOOK_URL_BASE:
        logger.info(f"WEBHOOK_URL_BASE is set to: {WEBHOOK_URL_BASE}")
        logger.info("Attempting to remove previous webhook (if any)...")
        try: bot.remove_webhook()
        except Exception as e: logger.warning(f"Could not remove webhook: {e}")
        time.sleep(0.5)
        webhook_full_url = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_URL_PATH
        logger.info(f"Attempting to set webhook to: {webhook_full_url}")
        webhook_set = False
        try: webhook_set = bot.set_webhook(url=webhook_full_url)
        except Exception as e: logger.critical(f"Exception setting webhook: {e}", exc_info=True)
        if webhook_set: logger.info("Webhook set successfully!")
        else: logger.critical(f"!!! Failed to set webhook at {webhook_full_url} !!!")
    else:
        logger.error("WEBHOOK_URL_BASE not set. Cannot configure webhook.")
        sys.exit(1)

    logger.info("Starting Flask server...")
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Flask server will listen on host 0.0.0.0, port {port}")
    try:
        # استخدام خادم waitress للإنتاج (إذا تم تثبيته: pip install waitress)
        # from waitress import serve
        # logger.info("Running with Waitress production server.")
        # serve(app, host='0.0.0.0', port=port)

        # استخدام الخادم المدمج حاليًا
        logger.info("Running with Flask's built-in development server.")
        app.run(host='0.0.0.0', port=port, debug=False) # debug=False مهم للإنتاج
    except Exception as e:
         logger.critical(f"Failed to start Flask server: {e}", exc_info=True)
         sys.exit(1)
