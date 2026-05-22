import asyncio
import logging
import sys
import os
import json
import sqlite3
import random
import string
import hashlib
import re
import time
import shutil
import zipfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# ===================== AUTO INSTALL DEPENDENCIES =====================
def install_packages():
    packages = [
        "python-telegram-bot>=20.0",
        "aiofiles",
        "pillow",
    ]
    for package in packages:
        try:
            __import__(package.split(">=")[0].replace("-", "_"))
        except ImportError:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_packages()
# ======================================================================

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, ChatMember, Chat, User, InputMediaPhoto,
    InputMediaDocument, InputMediaVideo, ForceReply
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError
import aiofiles
from PIL import Image, ImageDraw, ImageFont

# ===================== CONFIGURATION =====================
TOKEN = "8715636351:AAFgE1X25ySy8gVwG-ly6wgcxVc21Am2Vuc"
ADMIN_ID = int(8263177760)
ADMIN_USERNAME = "@EEEEOXO"
BOT_USERNAME = "@oll_sbot"
BOT_NAME = "hotsalsfah"

DB_FILE = "codehost.db"
FILES_DIR = "user_files"
BACKUP_DIR = "backups"
LOGS_DIR = "logs"
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ===================== ALLOWED EXTENSIONS =====================
ALLOWED_EXTENSIONS = ['.php', '.py', '.html', '.css', '.js', '.txt', '.json', '.xml', '.sql', '.md']
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# ===================== VIP PLANS =====================
VIP_PLANS = {
    1: {"name": "VIP 🥉", "price": 500, "storage_gb": 1, "duration_days": 30, "color": "🥉"},
    2: {"name": "VIP 🥈", "price": 1500, "storage_gb": 5, "duration_days": 30, "color": "🥈"},
    3: {"name": "VIP 🥇", "price": 5000, "storage_gb": 20, "duration_days": 30, "color": "🥇"},
}

# ===================== DATABASE MANAGER =====================
class DatabaseManager:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_file)

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    join_date TEXT,
                    last_active TEXT,
                    points INTEGER DEFAULT 0,
                    total_uploaded INTEGER DEFAULT 0,
                    total_downloads INTEGER DEFAULT 0,
                    used_storage INTEGER DEFAULT 0,
                    max_storage INTEGER DEFAULT 209715200,
                    vip_level INTEGER DEFAULT 0,
                    vip_expiry TEXT,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    role TEXT DEFAULT "user"
                )
            ''')
            
            # Files table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_file_id TEXT,
                    file_name TEXT,
                    file_size INTEGER,
                    file_path TEXT,
                    file_type TEXT,
                    upload_date TEXT,
                    download_count INTEGER DEFAULT 0,
                    is_public INTEGER DEFAULT 0,
                    file_hash TEXT
                )
            ''')
            
            # Points transactions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS points_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    points_change INTEGER,
                    balance_before INTEGER,
                    balance_after INTEGER,
                    reason TEXT,
                    transaction_type TEXT,
                    date TEXT
                )
            ''')
            
            # Shopping history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS purchases (
                    purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_type TEXT,
                    item_id INTEGER,
                    price INTEGER,
                    purchase_date TEXT,
                    expiry_date TEXT,
                    status TEXT DEFAULT "active"
                )
            ''')
            
            # Settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Insert default settings
            default_settings = [
                ("default_storage_mb", "200"),
                ("points_per_upload", "5"),
                ("points_per_download", "1"),
                ("vip1_price", "500"),
                ("vip1_storage_gb", "1"),
                ("vip2_price", "1500"),
                ("vip2_storage_gb", "5"),
                ("vip3_price", "5000"),
                ("vip3_storage_gb", "20"),
                ("maintenance_mode", "false"),
                ("max_file_size_mb", "10"),
            ]
            for key, value in default_settings:
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
            
            # Insert main admin
            referral_code = self.generate_referral_code()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, first_name, username, join_date, role, points, referral_code, max_storage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ADMIN_ID, "Admin", ADMIN_USERNAME.replace("@", ""), 
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "admin", 10000, referral_code, 10737418240))
            
            conn.commit()

    def generate_referral_code(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    # ==================== USER METHODS ====================
    def add_user(self, user_id: int, first_name: str, username: str, referred_by: int = 0):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                return
            referral_code = self.generate_referral_code()
            join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            default_storage_mb = int(self.get_setting("default_storage_mb", "200"))
            default_storage_bytes = default_storage_mb * 1024 * 1024
            
            cursor.execute('''
                INSERT INTO users (user_id, first_name, username, join_date, last_active, referral_code, referred_by, max_storage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, first_name, username, join_date, join_date, referral_code, referred_by, default_storage_bytes))
            
            # Process referral
            if referred_by > 0 and referred_by != user_id:
                referral_points = 50
                cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (referral_points, referred_by))
                cursor.execute('''
                    INSERT INTO points_history (user_id, points_change, balance_before, balance_after, reason, transaction_type, date)
                    SELECT ?, ?, points, points + ?, ?, ?, ?
                    FROM users WHERE user_id = ?
                ''', (referred_by, referral_points, referral_points, f"إحالة المستخدم {user_id}", "referral", 
                      join_date, referred_by))
            conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                user = dict(zip(columns, row))
                # Check VIP expiry
                if user.get("vip_expiry") and user["vip_level"] > 0:
                    expiry = datetime.strptime(user["vip_expiry"], "%Y-%m-%d %H:%M:%S")
                    if expiry < datetime.now():
                        user["vip_level"] = 0
                        user["max_storage"] = int(self.get_setting("default_storage_mb", "200")) * 1024 * 1024
                        cursor.execute("UPDATE users SET vip_level = 0, max_storage = ? WHERE user_id = ?", 
                                      (user["max_storage"], user_id))
                        conn.commit()
                return user
        return None

    def get_all_users(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY points DESC")
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    def get_user_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]

    def update_user_activity(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_active = ? WHERE user_id = ?",
                          (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
            conn.commit()

    def add_points(self, user_id: int, points: int, reason: str = "", transaction_type: str = "admin_add") -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            balance_before = row[0]
            balance_after = balance_before + points
            cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
            cursor.execute('''
                INSERT INTO points_history (user_id, points_change, balance_before, balance_after, reason, transaction_type, date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, points, balance_before, balance_after, reason, transaction_type,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            return True

    def deduct_points(self, user_id: int, points: int, reason: str = "", transaction_type: str = "purchase") -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            balance_before = row[0]
            if balance_before < points:
                return False
            balance_after = balance_before - points
            cursor.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (points, user_id))
            cursor.execute('''
                INSERT INTO points_history (user_id, points_change, balance_before, balance_after, reason, transaction_type, date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, -points, balance_before, balance_after, reason, transaction_type,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            return True

    def update_storage(self, user_id: int, additional_bytes: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT used_storage, max_storage FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            used, max_storage = row
            if used + additional_bytes > max_storage:
                return False
            cursor.execute("UPDATE users SET used_storage = used_storage + ? WHERE user_id = ?", 
                          (additional_bytes, user_id))
            conn.commit()
            return True

    def reduce_storage(self, user_id: int, bytes_to_reduce: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET used_storage = used_storage - ? WHERE user_id = ? AND used_storage >= ?",
                          (bytes_to_reduce, user_id, bytes_to_reduce))
            conn.commit()

    def ban_user(self, user_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def unban_user(self, user_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def is_admin(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return user and user.get("role") in ["admin", "super_admin"]

    def get_remaining_storage(self, user_id: int) -> Tuple[int, int]:
        user = self.get_user(user_id)
        if not user:
            return 0, 0
        used = user.get("used_storage", 0)
        max_storage = user.get("max_storage", 200 * 1024 * 1024)
        remaining = max(0, max_storage - used)
        return remaining, max_storage

    # ==================== VIP METHODS ====================
    def buy_vip(self, user_id: int, vip_level: int) -> Tuple[bool, str]:
        if vip_level not in VIP_PLANS:
            return False, "❌ باقة غير موجودة!"
        
        plan = VIP_PLANS[vip_level]
        price = plan["price"]
        
        user = self.get_user(user_id)
        if not user:
            return False, "❌ المستخدم غير موجود!"
        
        if user["points"] < price:
            return False, f"❌ رصيدك غير كافٍ! تحتاج {price} نقطة"
        
        if self.deduct_points(user_id, price, f"شراء {plan['name']}", "vip_purchase"):
            expiry = (datetime.now() + timedelta(days=plan["duration_days"])).strftime("%Y-%m-%d %H:%M:%S")
            storage_bytes = plan["storage_gb"] * 1024 * 1024 * 1024
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET vip_level = ?, vip_expiry = ?, max_storage = ? WHERE user_id = ?",
                              (vip_level, expiry, storage_bytes, user_id))
                cursor.execute('''
                    INSERT INTO purchases (user_id, item_type, item_id, price, purchase_date, expiry_date)
                    VALUES (?, "vip", ?, ?, ?, ?)
                ''', (user_id, vip_level, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expiry))
                conn.commit()
            
            return True, f"✅ تم شراء {plan['name']} بنجاح!\n📦 مساحة {plan['storage_gb']} GB\n📅 تنتهي بعد {plan['duration_days']} يوم"
        
        return False, "❌ حدث خطأ أثناء الشراء!"

    # ==================== FILE METHODS ====================
    def save_file_info(self, user_id: int, telegram_file_id: str, file_name: str, 
                       file_size: int, file_path: str, file_type: str) -> int:
        file_hash = hashlib.md5(f"{telegram_file_id}{file_name}".encode()).hexdigest()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (user_id, telegram_file_id, file_name, file_size, file_path, file_type, upload_date, file_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, telegram_file_id, file_name, file_size, file_path, file_type,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), file_hash))
            conn.commit()
            return cursor.lastrowid

    def get_user_files(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE user_id = ? ORDER BY file_id DESC", (user_id,))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    def get_file(self, file_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None

    def delete_file(self, file_id: int, user_id: int) -> bool:
        file = self.get_file(file_id)
        if not file or file["user_id"] != user_id:
            if not self.is_admin(user_id):
                return False
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            conn.commit()
        
        # Delete physical file
        if file and os.path.exists(file["file_path"]):
            os.remove(file["file_path"])
            self.reduce_storage(file["user_id"], file["file_size"])
        
        return True

    def increment_download(self, file_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE files SET download_count = download_count + 1 WHERE file_id = ?", (file_id,))
            conn.commit()

    # ==================== SETTINGS ====================
    def get_setting(self, key: str, default: str = None) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

# ===================== KEYBOARDS =====================
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📁 رفع ملف", callback_data="upload_file")],
        [InlineKeyboardButton("📂 ملفاتي", callback_data="my_files")],
        [InlineKeyboardButton("🛒 المتجر", callback_data="shop")],
        [InlineKeyboardButton("💰 محفظتي", callback_data="my_wallet")],
        [InlineKeyboardButton("👤 حسابي", callback_data="my_account")],
        [InlineKeyboardButton("👑 باقات VIP", callback_data="vip_packages")],
        [InlineKeyboardButton("📖 التعليمات", callback_data="help")],
        [InlineKeyboardButton("📦 تثبيت مكتبة", callback_data="install_library")],
        [InlineKeyboardButton("👨‍💻 المطور", callback_data="developer")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 إذاعة", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("💰 إدارة النقاط", callback_data="admin_points")],
        [InlineKeyboardButton("📂 إدارة الملفات", callback_data="admin_files")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="admin_settings")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_files_keyboard(files: List[Dict], page: int = 0, per_page: int = 10):
    keyboard = []
    start = page * per_page
    end = min(start + per_page, len(files))
    for i in range(start, end):
        file = files[i]
        size_kb = file["file_size"] // 1024
        size_str = f"{size_kb}KB" if size_kb < 1024 else f"{size_kb//1024}MB"
        btn_text = f"📄 {file['file_name'][:20]} ({size_str})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_file_{file['file_id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"files_page_{page-1}"))
    if end < len(files):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"files_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def get_file_actions_keyboard(file_id: int):
    keyboard = [
        [InlineKeyboardButton("📥 تحميل", callback_data=f"download_file_{file_id}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_file_{file_id}")],
        [InlineKeyboardButton("🔗 مشاركة", callback_data=f"share_file_{file_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="my_files")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_vip_keyboard():
    keyboard = [
        [InlineKeyboardButton("🥉 VIP 1 - 1GB - 500 نقطة", callback_data="buy_vip_1")],
        [InlineKeyboardButton("🥈 VIP 2 - 5GB - 1500 نقطة", callback_data="buy_vip_2")],
        [InlineKeyboardButton("🥇 VIP 3 - 20GB - 5000 نقطة", callback_data="buy_vip_3")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_shop_keyboard():
    keyboard = [
        [InlineKeyboardButton("👑 باقات VIP", callback_data="vip_packages")],
        [InlineKeyboardButton("💾 مساحة إضافية 100MB - 100 نقطة", callback_data="buy_storage_100")],
        [InlineKeyboardButton("💾 مساحة إضافية 500MB - 400 نقطة", callback_data="buy_storage_500")],
        [InlineKeyboardButton("💾 مساحة إضافية 1GB - 700 نقطة", callback_data="buy_storage_1024")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ===================== BOT HANDLERS =====================
class CodeHostBot:
    def __init__(self):
        self.db = DatabaseManager(DB_FILE)
        self.application = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat = update.effective_chat
        
        # Check referral
        referred_by = 0
        if context.args and len(context.args) > 0:
            code = context.args[0]
            for u in self.db.get_all_users():
                if u.get("referral_code") == code and u["user_id"] != user.id:
                    referred_by = u["user_id"]
                    break
        
        self.db.add_user(user.id, user.first_name, user.username or "", referred_by)
        self.db.update_user_activity(user.id)
        user_data = self.db.get_user(user.id)
        
        if user_data and user_data.get("is_banned"):
            await update.message.reply_text(f"🚫 حسابك محظور. تواصل مع {ADMIN_USERNAME}")
            return
        
        points = user_data.get("points", 0) if user_data else 0
        remaining, max_storage = self.db.get_remaining_storage(user.id)
        used_mb = (user_data.get("used_storage", 0) // (1024 * 1024)) if user_data else 0
        max_mb = max_storage // (1024 * 1024)
        
        welcome_text = (
            f"✨ **{BOT_NAME}** ✨\n\n"
            f"👤 **الاسم:** {user.first_name}\n"
            f"🆔 **الإيدي:** `{user.id}`\n"
            f"👑 **الرتبة:** {'VIP' if user_data.get('vip_level', 0) > 0 else 'عادي'}\n"
            f"💰 **النقاط:** {points}\n\n"
            f"📊 **شاغلة:** {used_mb} / {max_mb} MB\n"
            f"📊 **واقفة:** {max_mb - used_mb} MB\n\n"
            f"🔪 *أهلا بك، استمتع بتجربة استضافة لا مثيل لها* 🔪"
        )
        
        # Get user profile photo
        try:
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][-1].file_id
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=file_id,
                    caption=welcome_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_main_keyboard()
                )
                return
        except:
            pass
        
        await context.bot.send_message(
            chat_id=chat.id,
            text=welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_keyboard()
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = query.data
        
        user = self.db.get_user(user_id)
        if not user:
            self.db.add_user(user_id, query.from_user.first_name, query.from_user.username or "", 0)
            user = self.db.get_user(user_id)
        
        if user and user.get("is_banned") and user_id != ADMIN_ID:
            await query.edit_message_text("🚫 حسابك محظور. تواصل مع الأدمن.")
            return
        
        self.db.update_user_activity(user_id)
        
        # Back to main
        if data == "back_to_main":
            points = user.get("points", 0)
            remaining, max_storage = self.db.get_remaining_storage(user_id)
            used_mb = (user.get("used_storage", 0) // (1024 * 1024))
            max_mb = max_storage // (1024 * 1024)
            
            welcome_text = (
                f"✨ **{BOT_NAME}** ✨\n\n"
                f"👤 **الاسم:** {query.from_user.first_name}\n"
                f"🆔 **الإيدي:** `{user_id}`\n"
                f"👑 **الرتبة:** {'VIP' if user.get('vip_level', 0) > 0 else 'عادي'}\n"
                f"💰 **النقاط:** {points}\n\n"
                f"📊 **شاغلة:** {used_mb} / {max_mb} MB\n"
                f"📊 **واقفة:** {max_mb - used_mb} MB\n\n"
                f"🔪 *أهلا بك، استمتع بتجربة استضافة لا مثيل لها* 🔪"
            )
            await query.edit_message_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard())
            return
        
        # ==================== ADMIN PANEL ====================
        if self.db.is_admin(user_id) or user_id == ADMIN_ID:
            if data == "admin_panel":
                await query.edit_message_text("🔧 *لوحة تحكم الأدمن* 🔧\n\nاختر الإجراء:", 
                                              parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())
                return
            
            if data == "admin_broadcast":
                context.user_data["broadcast_mode"] = True
                await query.edit_message_text("📢 *وضع الإذاعة*\nأرسل الرسالة لإذاعتها لجميع المستخدمين.\nلإلغاء: /cancel", 
                                              parse_mode=ParseMode.MARKDOWN)
                return
            
            if data == "admin_stats":
                total_users = self.db.get_user_count()
                total_files = len(self.db.get_user_files(user_id))
                total_points = sum(u.get("points", 0) for u in self.db.get_all_users())
                vip_count = sum(1 for u in self.db.get_all_users() if u.get("vip_level", 0) > 0)
                total_storage = sum(u.get("used_storage", 0) for u in self.db.get_all_users()) // (1024 * 1024)
                
                stats_text = (
                    f"📊 *إحصائيات {BOT_NAME}* 📊\n\n"
                    f"👥 **إجمالي المستخدمين:** {total_users}\n"
                    f"👑 **مشتركي VIP:** {vip_count}\n"
                    f"📁 **إجمالي الملفات:** {total_files}\n"
                    f"💰 **إجمالي النقاط:** {total_points}\n"
                    f"💾 **المساحة المستخدمة:** {total_storage} MB\n"
                )
                await query.edit_message_text(stats_text, parse_mode=ParseMode.MARKDOWN, 
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]))
                return
            
            if data == "admin_users":
                await query.edit_message_text(
                    "👥 *إدارة المستخدمين* 👥\n\n"
                    "📌 **الأوامر:**\n"
                    "/ban <ايدي> - حظر مستخدم\n"
                    "/unban <ايدي> - إلغاء حظر\n"
                    "/addpoints <ايدي> <نقاط> - إضافة نقاط\n"
                    "/userinfo <ايدي> - معلومات مستخدم\n"
                    "/listusers - قائمة المستخدمين\n\n"
                    "📊 استخدم الأزرار أدناه:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
                    ])
                )
                return
            
            if data == "admin_points":
                await query.edit_message_text(
                    "💰 *إدارة النقاط* 💰\n\n"
                    "📌 **الأوامر:**\n"
                    "/addpoints <ايدي> <نقاط> - إضافة نقاط\n"
                    "/removepoints <ايدي> <نقاط> - خصم نقاط\n"
                    "/setpoints <ايدي> <نقاط> - تعيين نقاط\n\n"
                    "📊 **الإعدادات الحالية:**\n"
                    f"• نقاط الرفع: {self.db.get_setting('points_per_upload', '5')}\n"
                    f"• نقاط التحميل: {self.db.get_setting('points_per_download', '1')}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
                    ])
                )
                return
            
            if data == "admin_files":
                await query.edit_message_text(
                    "📂 *إدارة الملفات* 📂\n\n"
                    "📌 **الأوامر:**\n"
                    "/listfiles - عرض جميع الملفات\n"
                    "/delfile <id> - حذف ملف\n\n"
                    "📊 لعرض ملفات المستخدمين:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
                    ])
                )
                return
            
            if data == "admin_settings":
                settings_text = (
                    f"⚙️ *إعدادات البوت* ⚙️\n\n"
                    f"📁 **المساحة الافتراضية:** {self.db.get_setting('default_storage_mb', '200')} MB\n"
                    f"💰 **نقاط الرفع:** {self.db.get_setting('points_per_upload', '5')}\n"
                    f"💰 **نقاط التحميل:** {self.db.get_setting('points_per_download', '1')}\n"
                    f"📦 **الحد الأقصى للملف:** {self.db.get_setting('max_file_size_mb', '10')} MB\n\n"
                    f"🛠 **وضع الصيانة:** {'مفعل' if self.db.get_setting('maintenance_mode') == 'true' else 'معطل'}\n\n"
                    f"📌 **لتغيير إعداد:** /set <الإعداد> <القيمة>"
                )
                await query.edit_message_text(settings_text, parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup([
                                                  [InlineKeyboardButton("🛠 تبديل وضع الصيانة", callback_data="admin_toggle_maintenance")],
                                                  [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
                                              ]))
                return
            
            if data == "admin_toggle_maintenance":
                current = self.db.get_setting("maintenance_mode", "false")
                new_value = "false" if current == "true" else "true"
                self.db.set_setting("maintenance_mode", new_value)
                status = "مفعل" if new_value == "true" else "معطل"
                await query.edit_message_text(f"🛠 تم {status} وضع الصيانة.",
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_settings")]]))
                return
        
        # ==================== USER HANDLERS ====================
        if data == "upload_file":
            if self.db.get_setting("maintenance_mode", "false") == "true":
                await query.edit_message_text("🛠 البوت في وضع الصيانة حالياً. عودة قريباً.")
                return
            
            await query.edit_message_text(
                "📁 *رفع ملف* 📁\n\n"
                f"📌 **الملفات المسموحة:** {', '.join(['.php', '.py', '.html', '.css', '.js', '.txt', '.json', '.xml', '.sql', '.md'])}\n"
                f"📦 **الحد الأقصى:** {self.db.get_setting('max_file_size_mb', '10')} MB\n"
                f"💰 **نقاط الرفع:** +{self.db.get_setting('points_per_upload', '5')}\n\n"
                f"🔗 *أرسل الملف الآن:*",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data["waiting_for_upload"] = True
            return
        
        if data == "my_files":
            files = self.db.get_user_files(user_id)
            if not files:
                await query.edit_message_text("📂 لا توجد ملفات مرفوعة.",
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))
            else:
                await query.edit_message_text("📂 *ملفاتي* 📂\n\nاختر ملفاً:", 
                                              parse_mode=ParseMode.MARKDOWN, 
                                              reply_markup=get_files_keyboard(files))
            return
        
        if data.startswith("files_page_"):
            page = int(data.split("_")[-1])
            files = self.db.get_user_files(user_id)
            await query.edit_message_text("📂 *ملفاتي* 📂\n\nاختر ملفاً:", 
                                          parse_mode=ParseMode.MARKDOWN, 
                                          reply_markup=get_files_keyboard(files, page))
            return
        
        if data.startswith("view_file_"):
            file_id = int(data.split("_")[-1])
            file = self.db.get_file(file_id)
            if file and file["user_id"] == user_id:
                size_kb = file["file_size"] // 1024
                size_str = f"{size_kb}KB" if size_kb < 1024 else f"{size_kb//1024}MB"
                text = (
                    f"📄 *{file['file_name']}*\n\n"
                    f"📦 **الحجم:** {size_str}\n"
                    f"📅 **تاريخ الرفع:** {file['upload_date'][:16]}\n"
                    f"📥 **عدد التحميلات:** {file['download_count']}\n"
                    f"🔧 **النوع:** {file['file_type']}"
                )
                await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, 
                                              reply_markup=get_file_actions_keyboard(file_id))
            return
        
        if data.startswith("download_file_"):
            file_id = int(data.split("_")[-1])
            file = self.db.get_file(file_id)
            if file and file["user_id"] == user_id:
                self.db.increment_download(file_id)
                points_per_download = int(self.db.get_setting("points_per_download", "1"))
                self.db.add_points(user_id, points_per_download, f"تحميل ملف {file['file_name']}", "download")
                
                try:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=file["telegram_file_id"],
                        caption=f"📄 {file['file_name']}\n📥 تم التحميل بنجاح!\n💰 ربحت +{points_per_download} نقطة!"
                    )
                    await query.edit_message_reply_markup(reply_markup=get_files_keyboard(self.db.get_user_files(user_id)))
                except Exception as e:
                    await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
            return
        
        if data.startswith("delete_file_"):
            file_id = int(data.split("_")[-1])
            if self.db.delete_file(file_id, user_id):
                await query.answer("✅ تم حذف الملف", show_alert=True)
                files = self.db.get_user_files(user_id)
                if files:
                    await query.edit_message_text("📂 *ملفاتي* 📂\n\nاختر ملفاً:", 
                                                  parse_mode=ParseMode.MARKDOWN, 
                                                  reply_markup=get_files_keyboard(files))
                else:
                    await query.edit_message_text("📂 لا توجد ملفات مرفوعة.",
                                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))
            else:
                await query.answer("❌ فشل الحذف", show_alert=True)
            return
        
        if data.startswith("share_file_"):
            file_id = int(data.split("_")[-1])
            file = self.db.get_file(file_id)
            if file:
                share_link = f"https://t.me/{BOT_USERNAME}?start=file_{file_id}"
                await query.edit_message_text(
                    f"🔗 *مشاركة الملف*\n\n"
                    f"📄 **الملف:** {file['file_name']}\n"
                    f"🔗 **الرابط:** `{share_link}`\n\n"
                    f"📤 شارك الرابط مع أصدقائك!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data=f"view_file_{file_id}")]
                    ])
                )
            return
        
        if data == "shop":
            await query.edit_message_text("🛒 *المتجر* 🛒\n\nاختر المنتج:", 
                                          parse_mode=ParseMode.MARKDOWN, 
                                          reply_markup=get_shop_keyboard())
            return
        
        if data.startswith("buy_storage_"):
            mb = int(data.split("_")[-1])
            price_map = {100: 100, 500: 400, 1024: 700}
            price = price_map.get(mb, 100)
            bytes_to_add = mb * 1024 * 1024
            
            if user["points"] < price:
                await query.answer(f"❌ رصيدك غير كافٍ! تحتاج {price} نقطة", show_alert=True)
                return
            
            remaining, max_storage = self.db.get_remaining_storage(user_id)
            new_max = max_storage + bytes_to_add
            
            if self.db.deduct_points(user_id, price, f"شراء {mb}MB مساحة", "storage_purchase"):
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET max_storage = ? WHERE user_id = ?", (new_max, user_id))
                    conn.commit()
                await query.answer(f"✅ تم شراء {mb}MB مساحة!", show_alert=True)
                await query.edit_message_text(f"✅ *تم شراء {mb}MB مساحة إضافية!*\n\n💰 تم خصم {price} نقطة\n📦 المساحة الإجمالية: {new_max // (1024*1024)} MB",
                                              parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="shop")]]))
            return
        
        if data == "vip_packages":
            await query.edit_message_text(
                "👑 *باقات VIP* 👑\n\n"
                "🥉 **VIP 1** - 1GB مساحة - 500 نقطة - 30 يوم\n"
                "🥈 **VIP 2** - 5GB مساحة - 1500 نقطة - 30 يوم\n"
                "🥇 **VIP 3** - 20GB مساحة - 5000 نقطة - 30 يوم\n\n"
                "✨ **مميزات VIP:**\n"
                "• مساحة تخزين أكبر\n"
                "• رفع ملفات أكبر حجماً\n"
                "• دعم أولوية\n\n"
                "اختر الباقة المناسبة لك:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_vip_keyboard()
            )
            return
        
        if data.startswith("buy_vip_"):
            vip_level = int(data.split("_")[-1])
            success, msg = self.db.buy_vip(user_id, vip_level)
            await query.answer(msg[:200] if len(msg) > 200 else msg, show_alert=True)
            if success:
                await query.edit_message_text(msg + "\n\n🔙 يمكنك العودة للقائمة الرئيسية.",
                                              parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))
            return
        
        if data == "my_wallet":
            points = user.get("points", 0)
            remaining, max_storage = self.db.get_remaining_storage(user_id)
            used_mb = (user.get("used_storage", 0) // (1024 * 1024))
            max_mb = max_storage // (1024 * 1024)
            
            text = (
                f"💰 *محفظتي* 💰\n\n"
                f"⭐ **رصيد النقاط:** {points} نقطة\n"
                f"📦 **المساحة المستخدمة:** {used_mb} / {max_mb} MB\n"
                f"📊 **المساحة المتبقية:** {max_mb - used_mb} MB\n\n"
                f"📌 **كيفية كسب النقاط:**\n"
                f"• رفع ملف: +{self.db.get_setting('points_per_upload', '5')} نقطة\n"
                f"• تحميل ملف: +{self.db.get_setting('points_per_download', '1')} نقطة\n"
                f"• إحالة الأصدقاء: +50 نقطة لكل صديق\n\n"
                f"🔗 **رابط الإحالة:**\n"
                f"`https://t.me/{BOT_USERNAME}?start={user.get('referral_code', '')}`"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))
            return
        
        if data == "my_account":
            vip_level = user.get("vip_level", 0)
            vip_expiry = user.get("vip_expiry", "غير مشترك")
            remaining, max_storage = self.db.get_remaining_storage(user_id)
            used_mb = (user.get("used_storage", 0) // (1024 * 1024))
            max_mb = max_storage // (1024 * 1024)
            
            text = (
                f"👤 *حسابي* 👤\n\n"
                f"🆔 **الايدي:** `{user_id}`\n"
                f"👤 **الاسم:** {user.get('first_name', '')}\n"
                f"🔖 **يوزر:** @{user.get('username', 'لا يوجد')}\n"
                f"📅 **تاريخ الانضمام:** {user.get('join_date', '')[:16]}\n"
                f"👑 **VIP:** {'المستوى ' + str(vip_level) if vip_level > 0 else 'لا'}\n"
                f"⏳ **انتهاء VIP:** {vip_expiry[:16] if vip_expiry != 'غير مشترك' else 'لا يوجد'}\n"
                f"💰 **النقاط:** {user.get('points', 0)}\n"
                f"📁 **عدد الملفات:** {len(self.db.get_user_files(user_id))}\n"
                f"📦 **المساحة:** {used_mb} / {max_mb} MB\n"
                f"🔗 **كود الإحالة:** `{user.get('referral_code', '')}`"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup([
                                              [InlineKeyboardButton("🔗 مشاركة الرابط", callback_data="share_referral")],
                                              [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
                                          ]))
            return
        
        if data == "share_referral":
            text = f"🔗 *رابط الإحالة الخاص بك*\n\n`https://t.me/{BOT_USERNAME}?start={user.get('referral_code', '')}`\n\nشارك الرابط مع أصدقائك لكسب 50 نقطة لكل مستخدم جديد!"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="my_account")]]))
            return
        
        if data == "help":
            text = (
                "📖 *التعليمات* 📖\n\n"
                "📌 **كيفية رفع ملف:**\n"
                "1. اضغط على زر 'رفع ملف'\n"
                "2. أرسل الملف (PHP, PY, HTML, CSS, JS, TXT, JSON, XML, SQL, MD)\n"
                "3. سيتم حفظ الملف وسيتم إضافة نقاط\n\n"
                "📌 **تحميل الملفات:**\n"
                "• من قائمة 'ملفاتي' اختر الملف\n"
                "• اضغط تحميل\n\n"
                "📌 **كسب النقاط:**\n"
                "• رفع ملف: +5 نقاط\n"
                "• تحميل ملف: +1 نقطة\n"
                "• إحالة الأصدقاء: +50 نقطة\n\n"
                "📌 **شراء مساحة أو VIP:**\n"
                "• من المتجر أو باقات VIP\n\n"
                "📞 **للاستفسارات:** {ADMIN_USERNAME}"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))
            return
        
        if data == "install_library":
            await query.edit_message_text(
                "📦 *تثبيت مكتبة بايثون* 📦\n\n"
                "📌 أرسل الأمر:\n"
                "`/pip install <اسم_المكتبة>`\n\n"
                "مثال: `/pip install requests`\n\n"
                "⚠️ ملاحظة: هذه الميزة متاحة فقط للأدمن والمشتركين VIP",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]])
            )
            return
        
        if data == "developer":
            text = (
                "👨‍💻 *المطور* 👨‍💻\n\n"
                f"👤 **الاسم:** {ADMIN_USERNAME}\n"
                f"🆔 **الايدي:** `{ADMIN_ID}`\n"
                f"🤖 **البوت:** @{BOT_USERNAME}\n"
                f"📅 **الإصدار:** 1.0.0\n\n"
                f"📞 **للتواصل:** {ADMIN_USERNAME}"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]]))

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        message = update.message
        
        user = self.db.get_user(user_id)
        if not user:
            self.db.add_user(user_id, message.from_user.first_name, message.from_user.username or "", 0)
            user = self.db.get_user(user_id)
        
        if user and user.get("is_banned") and user_id != ADMIN_ID:
            await message.reply_text("🚫 حسابك محظور. تواصل مع الأدمن.")
            return
        
        # Handle file upload
        if context.user_data.get("waiting_for_upload"):
            context.user_data["waiting_for_upload"] = False
            
            if not message.document:
                await message.reply_text("❌ يرجى إرسال ملف صالح.")
                return
            
            document = message.document
            file_name = document.file_name or "unknown"
            file_size = document.file_size
            max_size_mb = int(self.db.get_setting("max_file_size_mb", "10"))
            max_size_bytes = max_size_mb * 1024 * 1024
            
            # Check file extension
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                await message.reply_text(f"❌ نوع الملف غير مسموح! الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}")
                return
            
            # Check file size
            if file_size > max_size_bytes:
                await message.reply_text(f"❌ حجم الملف كبير جداً! الحد الأقصى {max_size_mb} MB")
                return
            
            # Check storage space
            remaining, max_storage = self.db.get_remaining_storage(user_id)
            if file_size > remaining:
                await message.reply_text(f"❌ لا توجد مساحة كافية! المساحة المتبقية: {remaining // (1024*1024)} MB\n💡 يمكنك شراء مساحة إضافية من المتجر")
                return
            
            # Save file
            user_dir = os.path.join(FILES_DIR, str(user_id))
            os.makedirs(user_dir, exist_ok=True)
            file_path = os.path.join(user_dir, file_name)
            
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive(file_path)
            
            # Save to database
            self.db.save_file_info(user_id, document.file_id, file_name, file_size, file_path, ext[1:])
            self.db.update_storage(user_id, file_size)
            points_per_upload = int(self.db.get_setting("points_per_upload", "5"))
            self.db.add_points(user_id, points_per_upload, f"رفع ملف {file_name}", "upload")
            
            await message.reply_text(
                f"✅ *تم رفع الملف بنجاح!*\n\n"
                f"📄 **الاسم:** {file_name}\n"
                f"📦 **الحجم:** {file_size // 1024}KB\n"
                f"💰 **الربح:** +{points_per_upload} نقطة\n\n"
                f"📂 يمكنك عرض ملفاتك من قائمة 'ملفاتي'",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 ملفاتي", callback_data="my_files")]])
            )
            return
        
        # Handle broadcast
        if context.user_data.get("broadcast_mode"):
            context.user_data["broadcast_mode"] = False
            users = self.db.get_all_users()
            success = 0
            fail = 0
            
            status_msg = await message.reply_text(f"📢 بدء الإذاعة لـ {len(users)} مستخدم...")
            
            for u in users:
                try:
                    if message.text:
                        await context.bot.send_message(u["user_id"], message.text, parse_mode=ParseMode.MARKDOWN)
                    elif message.photo:
                        await context.bot.send_photo(u["user_id"], message.photo[-1].file_id, caption=message.caption)
                    elif message.document:
                        await context.bot.send_document(u["user_id"], message.document.file_id, caption=message.caption)
                    else:
                        await context.bot.send_message(u["user_id"], "📢 رسالة من الإدارة")
                    success += 1
                except:
                    fail += 1
                await asyncio.sleep(0.05)
            
            await status_msg.edit_text(f"✅ *انتهت الإذاعة*\n\n✅ نجاح: {success}\n❌ فشل: {fail}", parse_mode=ParseMode.MARKDOWN)
            return

    async def handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        args = context.args
        
        user = self.db.get_user(user_id)
        
        # Cancel command
        if text.startswith("/cancel"):
            context.user_data.clear()
            await update.message.reply_text("✅ تم إلغاء جميع العمليات.")
            return
        
        # Pip install command (admin or VIP only)
        if text.startswith("/pip"):
            if not (user_id == ADMIN_ID or self.db.is_admin(user_id) or (user and user.get("vip_level", 0) > 0)):
                await update.message.reply_text("⚠️ هذه الميزة متاحة فقط للأدمن ومشتركي VIP.")
                return
            
            if len(args) < 2 or args[0] != "install":
                await update.message.reply_text("❌ استخدم: /pip install <اسم_المكتبة>\nمثال: /pip install requests")
                return
            
            library = args[1]
            msg = await update.message.reply_text(f"📦 جاري تثبيت مكتبة {library}...")
            
            try:
                import subprocess
                result = subprocess.run([sys.executable, "-m", "pip", "install", library], 
                                        capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    await msg.edit_text(f"✅ *تم تثبيت المكتبة بنجاح!*\n\n📦 **المكتبة:** {library}\n💡 يمكنك الآن استخدامها.", 
                                        parse_mode=ParseMode.MARKDOWN)
                else:
                    await msg.edit_text(f"❌ *فشل التثبيت*\n\n📦 **المكتبة:** {library}\n⚠️ {result.stderr[:200]}", 
                                        parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await msg.edit_text(f"❌ خطأ: {str(e)[:100]}", parse_mode=ParseMode.MARKDOWN)
            return
        
        # Admin commands
        if user_id == ADMIN_ID or (user and self.db.is_admin(user_id)):
            if text.startswith("/ban"):
                if len(args) < 1:
                    await update.message.reply_text("❌ استخدم: /ban <ايدي>")
                    return
                target_id = int(args[0])
                if self.db.ban_user(target_id):
                    await update.message.reply_text(f"✅ تم حظر المستخدم `{target_id}`", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            if text.startswith("/unban"):
                if len(args) < 1:
                    await update.message.reply_text("❌ استخدم: /unban <ايدي>")
                    return
                target_id = int(args[0])
                if self.db.unban_user(target_id):
                    await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم `{target_id}`", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            if text.startswith("/addpoints"):
                if len(args) < 2:
                    await update.message.reply_text("❌ استخدم: /addpoints <ايدي> <نقاط>")
                    return
                target_id = int(args[0])
                points = int(args[1])
                if self.db.add_points(target_id, points, "إضافة من الأدمن", "admin_add"):
                    await update.message.reply_text(f"✅ تم إضافة {points} نقطة للمستخدم `{target_id}`", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            if text.startswith("/removepoints"):
                if len(args) < 2:
                    await update.message.reply_text("❌ استخدم: /removepoints <ايدي> <نقاط>")
                    return
                target_id = int(args[0])
                points = int(args[1])
                if self.db.deduct_points(target_id, points, "خصم من الأدمن", "admin_remove"):
                    await update.message.reply_text(f"✅ تم خصم {points} نقطة من المستخدم `{target_id}`", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ لم يتم العثور على المستخدم أو رصيده غير كافٍ")
                return
            
            if text.startswith("/userinfo"):
                if len(args) < 1:
                    await update.message.reply_text("❌ استخدم: /userinfo <ايدي>")
                    return
                target_id = int(args[0])
                target = self.db.get_user(target_id)
                if target:
                    used_mb = target.get("used_storage", 0) // (1024 * 1024)
                    max_mb = target.get("max_storage", 200 * 1024 * 1024) // (1024 * 1024)
                    text_msg = (
                        f"👤 *معلومات المستخدم*\n\n"
                        f"🆔 **الايدي:** `{target['user_id']}`\n"
                        f"👤 **الاسم:** {target['first_name']}\n"
                        f"🔖 **يوزر:** @{target.get('username', 'لا يوجد')}\n"
                        f"💰 **النقاط:** {target['points']}\n"
                        f"👑 **VIP:** {target.get('vip_level', 0)}\n"
                        f"📦 **المساحة:** {used_mb} / {max_mb} MB\n"
                        f"🚫 **محظور:** {'نعم' if target.get('is_banned') else 'لا'}\n"
                        f"📅 **الانضمام:** {target.get('join_date', '')[:16]}"
                    )
                    await update.message.reply_text(text_msg, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ لم يتم العثور على المستخدم")
                return
            
            if text.startswith("/listusers"):
                users = self.db.get_all_users()
                text_msg = "👥 *قائمة المستخدمين*\n\n"
                for u in users[:30]:
                    role_icon = "👑" if u.get("role") == "admin" else "⭐" if u.get("vip_level", 0) > 0 else "👤"
                    text_msg += f"{role_icon} {u['first_name'][:15]} - `{u['user_id']}` - {u['points']} نقطة\n"
                if len(users) > 30:
                    text_msg += f"\n... و {len(users) - 30} مستخدم آخر"
                await update.message.reply_text(text_msg, parse_mode=ParseMode.MARKDOWN)
                return
            
            if text.startswith("/set"):
                if len(args) < 2:
                    await update.message.reply_text("❌ استخدم: /set <الإعداد> <القيمة>\nالإعدادات: default_storage_mb, points_per_upload, points_per_download, max_file_size_mb")
                    return
                setting = args[0]
                value = args[1]
                self.db.set_setting(setting, value)
                await update.message.reply_text(f"✅ تم تعيين {setting} = {value}")
                return
            
            if text.startswith("/listfiles"):
                all_files = []
                for u in self.db.get_all_users():
                    files = self.db.get_user_files(u["user_id"])
                    all_files.extend(files)
                if not all_files:
                    await update.message.reply_text("📂 لا توجد ملفات")
                    return
                text_msg = "📂 *جميع الملفات*\n\n"
                for f in all_files[:50]:
                    text_msg += f"• {f['file_name']} - مستخدم {f['user_id']} - {f['download_count']} تحميل\n"
                if len(all_files) > 50:
                    text_msg += f"\n... و {len(all_files) - 50} ملف آخر"
                await update.message.reply_text(text_msg, parse_mode=ParseMode.MARKDOWN)
                return
            
            if text.startswith("/delfile"):
                if len(args) < 1:
                    await update.message.reply_text("❌ استخدم: /delfile <id>")
                    return
                file_id = int(args[0])
                if self.db.delete_file(file_id, user_id):
                    await update.message.reply_text(f"✅ تم حذف الملف {file_id}")
                else:
                    await update.message.reply_text("❌ فشل الحذف")
                return

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception: {context.error}")
        try:
            await update.message.reply_text("⚠️ حدث خطأ. تم إبلاغ المطور.")
        except:
            pass

    async def post_init(self, application: Application):
        global BOT_USERNAME
        bot_info = await application.bot.get_me()
        BOT_USERNAME = bot_info.username
        await application.bot.set_my_commands([
            BotCommand("start", "بدء البوت"),
            BotCommand("cancel", "إلغاء العملية"),
        ])
        print("=" * 50)
        print(f"📁 {BOT_NAME} يعمل الآن!")
        print(f"👑 الأدمن: {ADMIN_USERNAME}")
        print(f"📊 المستخدمين: {self.db.get_user_count()}")
        print("=" * 50)

    def run(self):
        self.application = Application.builder().token(TOKEN).post_init(self.post_init).build()
        
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("cancel", self.handle_command))
        self.application.add_handler(CommandHandler("pip", self.handle_command))
        
        # Admin commands
        self.application.add_handler(CommandHandler("ban", self.handle_command))
        self.application.add_handler(CommandHandler("unban", self.handle_command))
        self.application.add_handler(CommandHandler("addpoints", self.handle_command))
        self.application.add_handler(CommandHandler("removepoints", self.handle_command))
        self.application.add_handler(CommandHandler("userinfo", self.handle_command))
        self.application.add_handler(CommandHandler("listusers", self.handle_command))
        self.application.add_handler(CommandHandler("set", self.handle_command))
        self.application.add_handler(CommandHandler("listfiles", self.handle_command))
        self.application.add_handler(CommandHandler("delfile", self.handle_command))
        
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_error_handler(self.error_handler)
        
        self.application.run_polling()

# ===================== MAIN =====================
if __name__ == "__main__":
    bot = CodeHostBot()
    bot.run()