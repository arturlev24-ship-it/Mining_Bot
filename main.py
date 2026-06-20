import asyncio
import random
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # 🔴 ЗАМЕНИТЕ НА ТОКЕН ВАШЕГО БОТА
ADMIN_ID = 123456789  # 🔴 ЗАМЕНИТЕ НА ВАШ TELEGRAM ID
OTHER_BOT_USERNAME = "@your_other_bot"  # 🔴 ЗАМЕНИТЕ НА USERNAME ВАШЕГО ДРУГОГО БОТА

MINING_RATE = 0.5  # Базовый заработок звезд в час
REFERRAL_BONUS = 0.1  # Бонус за каждого активного реферала в час
MIN_WITHDRAWAL = 100  # Минимальная сумма вывода
MINING_COOLDOWN = 3 * 3600  # Кулдаун майнинга (3 часа в секундах)
AD_INTERVAL = 8 * 3600  # Интервал рекламы (8 часов)
AUTO_SAVE_INTERVAL = 300  # Автосохранение данных каждые 5 минут
BALANCE_UPDATE_INTERVAL = 60  # Обновление баланса каждую минуту

# ===================== НАСТРОЙКА ЛОГИРОВАНИЯ =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================== ХРАНИЛИЩЕ ДАННЫХ =====================
class Storage:
    def __init__(self, filename: str = "users_data.json"):
        self.filename = filename
        self.data: Dict[str, Dict] = {}
        self.lock = asyncio.Lock()
        self.load()

    def load(self):
        """Загрузка данных из файла"""
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"Загружено {len(self.data)} пользователей")
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")
            self.data = {}

    async def save(self):
        """Асинхронное сохранение данных"""
        async with self.lock:
            try:
                with open(self.filename, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Ошибка сохранения данных: {e}")

    def get_user(self, user_id: int) -> Dict:
        """Получение данных пользователя"""
        user_id = str(user_id)
        if user_id not in self.data:
            self.data[user_id] = self._create_default_user()
        return self.data[user_id]

    def _create_default_user(self) -> Dict:
        """Создание дефолтных данных пользователя"""
        return {
            'balance': 0.0,
            'total_earned': 0.0,
            'last_mining_start': None,
            'last_mining_stop': None,
            'mining_active': False,
            'mining_disabled_until': None,
            'referrals': [],
            'referral_code': None,
            'referred_by': None,
            'language': 'ru',
            'username': None,
            'last_ad_time': None,
            'first_name': None
        }

    async def update_user(self, user_id: int, data: Dict):
        """Обновление данных пользователя"""
        self.data[str(user_id)] = data

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
storage = Storage()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# ===================== ПЕРЕВОДЫ =====================
TRANSLATIONS = {
    'ru': {
        'welcome': (
            "🌟 <b>Добро пожаловать в Майнинг Бот!</b>\n\n"
            "💎 Майньте звезды Telegram\n"
            "👥 Приглашайте друзей\n"
            "💰 Выводите от 100 звезд\n\n"
            "🌍 Выберите язык:"
        ),
        'menu': (
            "⚡ <b>Майнинг Панель</b>\n\n"
            "👤 <b>Профиль:</b> {username}\n"
            "💎 <b>Баланс:</b> <code>{balance}</code> ⭐\n"
            "⚙ <b>Скорость:</b> <code>{rate}</code> ⭐/час\n"
            "👥 <b>Рефералы:</b> {total_refs} (активных: {active_refs})\n"
            "📊 <b>Статус:</b> {mining_status}\n\n"
            "🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>"
        ),
        'mining_active_text': "🟢 Активен",
        'mining_inactive_text': "🔴 Остановлен",
        'mining_blocked_text': "⛔ Заблокирован",
        'mining_started': (
            "✅ <b>Майнинг запущен!</b>\n\n"
            "⚙ Скорость: <code>{rate}</code> ⭐/час\n"
            "👥 Активных рефералов: {active_refs}\n\n"
            "⚠ Майнинг автоматически отключится через 3 часа"
        ),
        'mining_stopped': (
            "⏸ <b>Майнинг остановлен</b>\n\n"
            "💎 Заработано за сессию: <code>{earned}</code> ⭐\n"
            "💰 Общий баланс: <code>{balance}</code> ⭐\n\n"
            "🔄 Можете включить снова в любое время"
        ),
        'mining_auto_stopped': (
            "⏰ <b>Автоматическая остановка майнинга</b>\n\n"
            "💎 Заработано: <code>{earned}</code> ⭐\n"
            "💰 Баланс: <code>{balance}</code> ⭐\n\n"
            "🔄 Запустите майнинг снова"
        ),
        'mining_cooldown': "⏳ Майнинг будет доступен через: {time}",
        'balance_updated': (
            "💰 <b>Баланс обновлен</b>\n\n"
            "💎 Текущий баланс: <code>{balance}</code> ⭐\n"
            "⚡ Намайнено: <code>{earned}</code> ⭐"
        ),
        'withdraw_min': f"❌ Минимальная сумма вывода: <b>{MIN_WITHDRAWAL}</b> ⭐",
        'withdraw_no_balance': "❌ Недостаточно средств\n\n💰 Ваш баланс: <code>{balance}</code> ⭐",
        'withdraw_no_username': "❌ Для вывода нужен @username в Telegram\n\nУстановите его в настройках профиля",
        'withdraw_prompt': (
            "📤 <b>Вывод средств</b>\n\n"
            "Введите команду:\n"
            "<code>/withdraw СУММА</code>\n\n"
            "Пример: <code>/withdraw 100</code>\n\n"
            f"⚠ Минимум: {MIN_WITHDRAWAL} ⭐\n"
            "👤 Ваш username: @{username}"
        ),
        'withdraw_success': (
            "✅ <b>Заявка отправлена!</b>\n\n"
            "💰 Сумма: <code>{amount}</code> ⭐\n"
            "👤 @{username}\n\n"
            "Ожидайте обработки администратором"
        ),
        'withdraw_error': "❌ Ошибка отправки заявки. Попробуйте позже",
        'invite_text': (
            "🎁 <b>Реферальная программа</b>\n\n"
            "👥 Приглашайте друзей и получайте:\n"
            "• +{bonus} ⭐/час за каждого активного реферала\n"
            f"• Вывод от {MIN_WITHDRAWAL} ⭐\n\n"
            "📊 <b>Ваша статистика:</b>\n"
            "👥 Всего рефералов: {total_refs}\n"
            "⚡ Активных: {active_refs}\n\n"
            "🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>"
        ),
        'stats': (
            "📊 <b>Статистика</b>\n\n"
            "👤 Профиль: {username}\n"
            "💎 Баланс: <code>{balance}</code> ⭐\n"
            "📈 Всего заработано: <code>{total_earned}</code> ⭐\n"
            "👥 Рефералов: {total_refs}\n"
            "⚡ Активных: {active_refs}\n"
            "⚙ Скорость майнинга: <code>{rate}</code> ⭐/час"
        ),
        'ad_gift': (
            "🎁 <b>Специальное предложение!</b>\n\n"
            "Вам доступен подарок! 🎉\n"
            "Заберите его прямо сейчас!\n\n"
            "👇 Нажмите на кнопку ниже:"
        ),
        'ad_button': "🎁 Забрать подарок",
        'language_selected': "✅ Язык: <b>Русский</b>",
        'back_button': "🔙 В меню",
        'start_mining_btn': "▶️ Запустить майнинг",
        'stop_mining_btn': "⏸ Остановить майнинг",
        'update_balance_btn': "💰 Обновить баланс",
        'withdraw_btn': "📤 Вывести",
        'invite_btn': "👥 Пригласить друга",
        'stats_btn': "📊 Статистика",
        'cooldown_btn': "⏳ Доступно через {time}",
        'hourly_update': (
            "⚡ <b>Автоматическое обновление</b>\n\n"
            "💎 Намайнено: <code>{earned}</code> ⭐\n"
            "💰 Баланс: <code>{balance}</code> ⭐"
        ),
        'no_username': "не установлен",
    },
    'en': {
        'welcome': (
            "🌟 <b>Welcome to Mining Bot!</b>\n\n"
            "💎 Mine Telegram Stars\n"
            "👥 Invite friends\n"
            "💰 Withdraw from 100 stars\n\n"
            "🌍 Choose language:"
        ),
        'menu': (
            "⚡ <b>Mining Panel</b>\n\n"
            "👤 <b>Profile:</b> {username}\n"
            "💎 <b>Balance:</b> <code>{balance}</code> ⭐\n"
            "⚙ <b>Speed:</b> <code>{rate}</code> ⭐/hour\n"
            "👥 <b>Referrals:</b> {total_refs} (active: {active_refs})\n"
            "📊 <b>Status:</b> {mining_status}\n\n"
            "🔗 <b>Your link:</b>\n<code>{ref_link}</code>"
        ),
        'mining_active_text': "🟢 Active",
        'mining_inactive_text': "🔴 Stopped",
        'mining_blocked_text': "⛔ Blocked",
        'mining_started': (
            "✅ <b>Mining started!</b>\n\n"
            "⚙ Speed: <code>{rate}</code> ⭐/hour\n"
            "👥 Active referrals: {active_refs}\n\n"
            "⚠ Mining will auto-stop after 3 hours"
        ),
        'mining_stopped': (
            "⏸ <b>Mining stopped</b>\n\n"
            "💎 Earned this session: <code>{earned}</code> ⭐\n"
            "💰 Total balance: <code>{balance}</code> ⭐\n\n"
            "🔄 You can start again anytime"
        ),
        'mining_auto_stopped': (
            "⏰ <b>Mining auto-stopped</b>\n\n"
            "💎 Earned: <code>{earned}</code> ⭐\n"
            "💰 Balance: <code>{balance}</code> ⭐\n\n"
            "🔄 Start mining again"
        ),
        'mining_cooldown': "⏳ Mining available in: {time}",
        'balance_updated': (
            "💰 <b>Balance updated</b>\n\n"
            "💎 Current balance: <code>{balance}</code> ⭐\n"
            "⚡ Mined: <code>{earned}</code> ⭐"
        ),
        'withdraw_min': f"❌ Minimum withdrawal: <b>{MIN_WITHDRAWAL}</b> ⭐",
        'withdraw_no_balance': "❌ Insufficient funds\n\n💰 Your balance: <code>{balance}</code> ⭐",
        'withdraw_no_username': "❌ @username required for withdrawal\n\nSet it in Telegram profile settings",
        'withdraw_prompt': (
            "📤 <b>Withdrawal</b>\n\n"
            "Enter command:\n"
            "<code>/withdraw AMOUNT</code>\n\n"
            "Example: <code>/withdraw 100</code>\n\n"
            f"⚠ Minimum: {MIN_WITHDRAWAL} ⭐\n"
            "👤 Your username: @{username}"
        ),
        'withdraw_success': (
            "✅ <b>Request sent!</b>\n\n"
            "💰 Amount: <code>{amount}</code> ⭐\n"
            "👤 @{username}\n\n"
            "Wait for processing"
        ),
        'withdraw_error': "❌ Error sending request. Try later",
        'invite_text': (
            "🎁 <b>Referral Program</b>\n\n"
            "👥 Invite friends and earn:\n"
            "• +{bonus} ⭐/hour per active referral\n"
            f"• Withdraw from {MIN_WITHDRAWAL} ⭐\n\n"
            "📊 <b>Your stats:</b>\n"
            "👥 Total referrals: {total_refs}\n"
            "⚡ Active: {active_refs}\n\n"
            "🔗 <b>Your link:</b>\n<code>{ref_link}</code>"
        ),
        'stats': (
            "📊 <b>Statistics</b>\n\n"
            "👤 Profile: {username}\n"
            "💎 Balance: <code>{balance}</code> ⭐\n"
            "📈 Total earned: <code>{total_earned}</code> ⭐\n"
            "👥 Referrals: {total_refs}\n"
            "⚡ Active: {active_refs}\n"
            "⚙ Mining speed: <code>{rate}</code> ⭐/hour"
        ),
        'ad_gift': (
            "🎁 <b>Special Offer!</b>\n\n"
            "A gift is available! 🎉\n"
            "Claim it now!\n\n"
            "👇 Click button below:"
        ),
        'ad_button': "🎁 Claim Gift",
        'language_selected': "✅ Language: <b>English</b>",
        'back_button': "🔙 Back to menu",
        'start_mining_btn': "▶️ Start Mining",
        'stop_mining_btn': "⏸ Stop Mining",
        'update_balance_btn': "💰 Update Balance",
        'withdraw_btn': "📤 Withdraw",
        'invite_btn': "👥 Invite Friend",
        'stats_btn': "📊 Statistics",
        'cooldown_btn': "⏳ Available in {time}",
        'hourly_update': (
            "⚡ <b>Auto update</b>\n\n"
            "💎 Mined: <code>{earned}</code> ⭐\n"
            "💰 Balance: <code>{balance}</code> ⭐"
        ),
        'no_username': "not set",
    }
}

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def get_text(user_id: int, key: str, **kwargs) -> str:
    """Получение переведенного текста"""
    user = storage.get_user(user_id)
    lang = user.get('language', 'ru')
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ru']).get(key, key)
    return text.format(**kwargs) if kwargs else text

def format_balance(balance: float) -> str:
    """Форматирование баланса"""
    return f"{balance:.3f}"

def get_mining_rate(user: Dict) -> float:
    """Расчет скорости майнинга с учетом рефералов"""
    rate = MINING_RATE
    if user.get('referrals'):
        for ref_id in user['referrals']:
            ref = storage.get_user(int(ref_id))
            if ref.get('mining_active'):
                rate += REFERRAL_BONUS
    return rate

def count_active_referrals(user: Dict) -> int:
    """Подсчет активных рефералов"""
    active = 0
    if user.get('referrals'):
        for ref_id in user['referrals']:
            ref = storage.get_user(int(ref_id))
            if ref.get('mining_active'):
                active += 1
    return active

async def calculate_earnings(user: Dict) -> float:
    """Расчет заработка с последнего старта майнинга"""
    if not user.get('mining_active') or not user.get('last_mining_start'):
        return 0.0

    try:
        last_start = datetime.fromisoformat(user['last_mining_start'])
        hours_passed = (datetime.now() - last_start).total_seconds() / 3600

        if hours_passed <= 0:
            return 0.0

        rate = get_mining_rate(user)
        return hours_passed * rate
    except Exception as e:
        logger.error(f"Ошибка расчета заработка: {e}")
        return 0.0

async def update_user_balance(user_id: int) -> float:
    """Обновление баланса пользователя"""
    user = storage.get_user(user_id)
    earnings = await calculate_earnings(user)

    if earnings > 0:
        user['balance'] += earnings
        user['total_earned'] += earnings
        user['last_mining_start'] = datetime.now().isoformat()
        await storage.update_user(user_id, user)
        await storage.save()

    return earnings

def can_start_mining(user: Dict) -> bool:
    """Проверка, может ли пользователь запустить майнинг"""
    if user.get('mining_disabled_until'):
        try:
            disabled_until = datetime.fromisoformat(user['mining_disabled_until'])
            if datetime.now() < disabled_until:
                return False
        except:
            pass
    return True

def get_cooldown_time(user: Dict) -> Optional[str]:
    """Получение оставшегося времени кулдауна"""
    if not user.get('mining_disabled_until'):
        return None

    try:
        disabled_until = datetime.fromisoformat(user['mining_disabled_until'])
        remaining = (disabled_until - datetime.now()).total_seconds()

        if remaining <= 0:
            return None

        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except:
        return None

def get_ref_link(user_id: int) -> str:
    """Генерация реферальной ссылки"""
    user = storage.get_user(user_id)
    ref_code = user.get('referral_code', str(user_id))
    bot_username = "YourBot"  # 🔴 ЗАМЕНИТЕ на username вашего бота
    return f"https://t.me/{bot_username}?start={ref_code}"

# ===================== ОБРАБОТЧИКИ КОМАНД =====================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandStart = None):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    user = storage.get_user(user_id)

    # Обновляем данные пользователя
    user['username'] = message.from_user.username
    user['first_name'] = message.from_user.first_name

    # Обработка реферальной ссылки
    if command and command.args:
        ref_code = command.args
        if ref_code != str(user_id):
            try:
                ref_user_id = int(ref_code)
                ref_user = storage.get_user(ref_user_id)
                if ref_user and str(user_id) not in ref_user.get('referrals', []):
                    ref_user.setdefault('referrals', []).append(str(user_id))
                    user['referred_by'] = ref_code
                    await storage.update_user(ref_user_id, ref_user)

                    # Уведомляем реферера
                    try:
                        await bot.send_message(
                            chat_id=ref_user_id,
                            text=f"🎉 Новый реферал присоединился!\n👤 {message.from_user.full_name}"
                        )
                    except:
                        pass
            except:
                pass

    # Создаем реферальный код если нет
    if not user.get('referral_code'):
        user['referral_code'] = str(user_id)

    # Устанавливаем язык по умолчанию если не выбран
    if not user.get('language'):
        user['language'] = 'ru'

    await storage.update_user(user_id, user)
    await storage.save()

    # Клавиатура выбора языка
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")
    )

    await message.answer(
        TRANSLATIONS['ru']['welcome'],
        reply_markup=builder.as_markup()
    )

@dp.message(Command("withdraw"))
async def cmd_withdraw(message: Message):
    """Обработчик команды вывода"""
    user_id = message.from_user.id
    user = storage.get_user(user_id)

    if not message.from_user.username:
        await message.answer(get_text(user_id, 'withdraw_no_username'))
        return

    try:
        # Парсим сумму из команды
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                get_text(user_id, 'withdraw_prompt', username=message.from_user.username)
            )
            return

        # Очищаем сумму от запятых и пробелов
        amount_str = parts[1].replace(',', '.').replace(' ', '')
        amount = float(amount_str)

        if amount < MIN_WITHDRAWAL:
            await message.answer(get_text(user_id, 'withdraw_min'))
            return

        if amount > user['balance']:
            await message.answer(
                get_text(user_id, 'withdraw_no_balance',
                        balance=format_balance(user['balance']))
            )
            return

        # Отправляем заявку админу
        admin_msg = (
            f"📤 <b>Заявка на вывод #{datetime.now().strftime('%Y%m%d%H%M%S')}</b>\n\n"
            f"👤 Пользователь: @{message.from_user.username}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💰 Сумма: <b>{format_balance(amount)}</b> ⭐\n"
            f"💎 Баланс: <b>{format_balance(user['balance'])}</b> ⭐\n"
            f"📈 Всего заработано: <b>{format_balance(user['total_earned'])}</b> ⭐"
        )

        try:
            await bot.send_message(ADMIN_ID, admin_msg)

            # Списываем средства
            user['balance'] -= amount
            await storage.update_user(user_id, user)
            await storage.save()

            await message.answer(
                get_text(user_id, 'withdraw_success',
                        amount=format_balance(amount),
                        username=message.from_user.username)
            )
        except Exception as e:
            logger.error(f"Ошибка отправки админу: {e}")
            await message.answer(get_text(user_id, 'withdraw_error'))

    except (ValueError, IndexError):
        await message.answer(
            get_text(user_id, 'withdraw_prompt', username=message.from_user.username)
        )
    except Exception as e:
        logger.error(f"Ошибка вывода: {e}")
        await message.answer(get_text(user_id, 'withdraw_error'))

# ===================== ОБРАБОТЧИКИ CALLBACK =====================
@dp.callback_query(F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery):
    """Выбор языка"""
    user_id = callback.from_user.id
    lang = callback.data.split("_")[1]
    user = storage.get_user(user_id)
    user['language'] = lang
    await storage.update_user(user_id, user)
    await storage.save()

    await callback.answer()
    await callback.message.edit_text(get_text(user_id, 'language_selected'))

    # Показываем главное меню через секунду
    await asyncio.sleep(1)
    try:
        await callback.message.delete()
    except:
        pass
    await show_main_menu(callback.message.chat.id, user_id)

async def show_main_menu(chat_id: int, user_id: int, edit_message: Message = None):
    """Показать главное меню с username пользователя"""
    user = storage.get_user(user_id)
    await update_user_balance(user_id)
    user = storage.get_user(user_id)  # Обновляем данные после начисления

    rate = get_mining_rate(user)
    active_refs = count_active_referrals(user)
    total_refs = len(user.get('referrals', []))

    # Получаем и форматируем username
    username = user.get('username')
    if username:
        username_display = f"@{username}"
    else:
        username_display = get_text(user_id, 'no_username')

    # Определяем статус майнинга
    if user.get('mining_active'):
        mining_status = get_text(user_id, 'mining_active_text')
    elif not can_start_mining(user):
        mining_status = get_text(user_id, 'mining_blocked_text')
    else:
        mining_status = get_text(user_id, 'mining_inactive_text')

    ref_link = get_ref_link(user_id)

    # Формируем текст меню с username
    text = get_text(user_id, 'menu',
        username=username_display,
        balance=format_balance(user['balance']),
        rate=format_balance(rate),
        total_refs=total_refs,
        active_refs=active_refs,
        mining_status=mining_status,
        ref_link=ref_link
    )

    builder = InlineKeyboardBuilder()

    # Кнопка майнинга
    if user.get('mining_active'):
        builder.row(InlineKeyboardButton(
            text=get_text(user_id, 'stop_mining_btn'),
            callback_data="stop_mining"
        ))
    elif can_start_mining(user):
        builder.row(InlineKeyboardButton(
            text=get_text(user_id, 'start_mining_btn'),
            callback_data="start_mining"
        ))
    else:
        cooldown_time = get_cooldown_time(user)
        if cooldown_time:
            builder.row(InlineKeyboardButton(
                text=get_text(user_id, 'cooldown_btn', time=cooldown_time),
                callback_data="cooldown_info"
            ))

    # Основные кнопки
    builder.row(
        InlineKeyboardButton(
            text=get_text(user_id, 'update_balance_btn'),
            callback_data="update_balance"
        ),
        InlineKeyboardButton(
            text=get_text(user_id, 'withdraw_btn'),
            callback_data="withdraw_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=get_text(user_id, 'invite_btn'),
            callback_data="invite_friend"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=get_text(user_id, 'stats_btn'),
            callback_data="stats"
        )
    )

    # Кнопка установки username, если его нет
    if not username:
        builder.row(InlineKeyboardButton(
            text="⚙ Установить username",
            url="tg://settings"
        ))

    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=builder.as_markup())
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                await bot.send_message(chat_id, text, reply_markup=builder.as_markup())
    else:
        await bot.send_message(chat_id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "start_mining")
async def start_mining(callback: CallbackQuery):
    """Запуск майнинга"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)

    if not can_start_mining(user):
        cooldown_time = get_cooldown_time(user)
        if cooldown_time:
            await callback.answer(
                get_text(user_id, 'mining_cooldown', time=cooldown_time),
                show_alert=True
            )
        return

    # Начисляем предыдущий заработок если был активен
    if user.get('mining_active'):
        await update_user_balance(user_id)
        user = storage.get_user(user_id)

    # Запускаем майнинг
    user['mining_active'] = True
    user['last_mining_start'] = datetime.now().isoformat()
    user['mining_disabled_until'] = None
    await storage.update_user(user_id, user)
    await storage.save()

    rate = get_mining_rate(user)
    active_refs = count_active_referrals(user)

    await callback.answer("✅ Майнинг запущен!", show_alert=True)

    await callback.message.answer(
        get_text(user_id, 'mining_started',
                rate=format_balance(rate),
                active_refs=active_refs)
    )

    await asyncio.sleep(1)
    await show_main_menu(callback.message.chat.id, user_id, callback.message)

@dp.callback_query(F.data == "stop_mining")
async def stop_mining(callback: CallbackQuery):
    """Остановка майнинга"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)

    if not user.get('mining_active'):
        await callback.answer("Майнинг не запущен", show_alert=True)
        return

    # Начисляем заработок
    earned = await update_user_balance(user_id)
    user = storage.get_user(user_id)

    # Останавливаем майнинг без блокировки
    user['mining_active'] = False
    user['last_mining_stop'] = datetime.now().isoformat()
    await storage.update_user(user_id, user)
    await storage.save()

    await callback.answer("⏸ Майнинг остановлен", show_alert=True)

    await callback.message.answer(
        get_text(user_id, 'mining_stopped',
                earned=format_balance(earned),
                balance=format_balance(user['balance']))
    )

    await asyncio.sleep(1)
    await show_main_menu(callback.message.chat.id, user_id, callback.message)

@dp.callback_query(F.data == "update_balance")
async def update_balance(callback: CallbackQuery):
    """Обновление баланса"""
    user_id = callback.from_user.id
    earned = await update_user_balance(user_id)
    user = storage.get_user(user_id)

    await callback.answer(
        f"💰 Баланс: {format_balance(user['balance'])} ⭐",
        show_alert=True
    )

    await show_main_menu(callback.message.chat.id, user_id, callback.message)

@dp.callback_query(F.data == "withdraw_menu")
async def withdraw_menu(callback: CallbackQuery):
    """Меню вывода"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)

    if not callback.from_user.username:
        await callback.answer(get_text(user_id, 'withdraw_no_username'), show_alert=True)
        return

    if user['balance'] < MIN_WITHDRAWAL:
        await callback.answer(
            get_text(user_id, 'withdraw_min'),
            show_alert=True
        )
        return

    await callback.message.answer(
        get_text(user_id, 'withdraw_prompt', username=callback.from_user.username)
    )
    await callback.answer()

@dp.callback_query(F.data == "invite_friend")
async def invite_friend(callback: CallbackQuery):
    """Приглашение друга"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)

    ref_link = get_ref_link(user_id)
    total_refs = len(user.get('referrals', []))
    active_refs = count_active_referrals(user)

    text = get_text(user_id, 'invite_text',
        bonus=str(REFERRAL_BONUS),
        total_refs=total_refs,
        active_refs=active_refs,
        ref_link=ref_link
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=get_text(user_id, 'back_button'),
        callback_data="back_to_menu"
    ))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except:
        await callback.message.answer(text, reply_markup=builder.as_markup())

    await callback.answer()

@dp.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    """Показ статистики с username"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)
    await update_user_balance(user_id)
    user = storage.get_user(user_id)

    rate = get_mining_rate(user)
    active_refs = count_active_referrals(user)
    total_refs = len(user.get('referrals', []))

    # Получаем username для статистики
    username = user.get('username')
    username_display = f"@{username}" if username else get_text(user_id, 'no_username')

    text = get_text(user_id, 'stats',
        username=username_display,
        balance=format_balance(user['balance']),
        total_earned=format_balance(user['total_earned']),
        total_refs=total_refs,
        active_refs=active_refs,
        rate=format_balance(rate)
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=get_text(user_id, 'back_button'),
        callback_data="back_to_menu"
    ))

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except:
        await callback.message.answer(text, reply_markup=builder.as_markup())

    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    await show_main_menu(callback.message.chat.id, user_id, callback.message)
    await callback.answer()

@dp.callback_query(F.data == "cooldown_info")
async def cooldown_info(callback: CallbackQuery):
    """Информация о кулдауне"""
    user_id = callback.from_user.id
    user = storage.get_user(user_id)

    cooldown_time = get_cooldown_time(user)
    if cooldown_time:
        await callback.answer(
            get_text(user_id, 'mining_cooldown', time=cooldown_time),
            show_alert=True
        )
    else:
        await callback.answer("Можно запускать майнинг!", show_alert=True)

@dp.callback_query(F.data == "ad_gift")
async def ad_gift(callback: CallbackQuery):
    """Обработка рекламного подарка"""
    await callback.answer("🎁 Переходите в бота за подарком!", show_alert=True)

# ===================== ФОНОВЫЕ ЗАДАЧИ =====================
async def show_advertisements():
    """Показ рекламы"""
    while True:
        try:
            await asyncio.sleep(random.randint(14400, AD_INTERVAL))

            if not storage.data:
                continue

            users = list(storage.data.keys())
            random.shuffle(users)
            selected_users = users[:max(1, len(users) // 4)]

            for user_id in selected_users:
                try:
                    user_id_int = int(user_id)
                    user = storage.get_user(user_id_int)

                    if user.get('last_ad_time'):
                        last_ad = datetime.fromisoformat(user['last_ad_time'])
                        if (datetime.now() - last_ad).total_seconds() < AD_INTERVAL:
                            continue

                    builder = InlineKeyboardBuilder()
                    builder.row(InlineKeyboardButton(
                        text=get_text(user_id_int, 'ad_button'),
                        url=f"https://t.me/{OTHER_BOT_USERNAME.replace('@', '')}"
                    ))
                    builder.row(InlineKeyboardButton(
                        text="🎁 Забрать подарок",
                        callback_data="ad_gift"
                    ))

                    try:
                        await bot.send_message(
                            chat_id=user_id_int,
                            text=get_text(user_id_int, 'ad_gift'),
                            reply_markup=builder.as_markup()
                        )

                        user['last_ad_time'] = datetime.now().isoformat()
                        await storage.update_user(user_id_int, user)
                        await storage.save()

                        await asyncio.sleep(random.uniform(1, 5))
                    except TelegramForbiddenError:
                        logger.info(f"Пользователь {user_id} заблокировал бота")
                        continue
                    except Exception as e:
                        logger.error(f"Ошибка отправки рекламы {user_id}: {e}")
                        continue

                except Exception as e:
                    logger.error(f"Ошибка обработки пользователя {user_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Ошибка в рекламной задаче: {e}")
            await asyncio.sleep(60)

async def auto_disable_mining():
    """Автоматическое отключение майнинга каждые 3 часа"""
    while True:
        try:
            await asyncio.sleep(60)

            for user_id in list(storage.data.keys()):
                try:
                    user_id_int = int(user_id)
                    user = storage.get_user(user_id_int)

                    if not user.get('mining_active') or not user.get('last_mining_start'):
                        continue

                    last_start = datetime.fromisoformat(user['last_mining_start'])
                    elapsed = (datetime.now() - last_start).total_seconds()

                    if elapsed >= MINING_COOLDOWN:
                        earned = await calculate_earnings(user)
                        if earned > 0:
                            user['balance'] += earned
                            user['total_earned'] += earned

                        user['mining_active'] = False
                        user['last_mining_stop'] = datetime.now().isoformat()
                        user['mining_disabled_until'] = (
                            datetime.now() + timedelta(seconds=MINING_COOLDOWN)
                        ).isoformat()

                        await storage.update_user(user_id_int, user)
                        await storage.save()

                        try:
                            await bot.send_message(
                                chat_id=user_id_int,
                                text=get_text(user_id_int, 'mining_auto_stopped',
                                            earned=format_balance(earned),
                                            balance=format_balance(user['balance']))
                            )
                        except:
                            pass

                        logger.info(f"Майнинг автоотключен для {user_id}")

                except Exception as e:
                    logger.error(f"Ошибка автоотключения для {user_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Ошибка в автоотключении: {e}")
            await asyncio.sleep(60)

async def periodic_balance_update():
    """Периодическое обновление баланса"""
    while True:
        try:
            await asyncio.sleep(BALANCE_UPDATE_INTERVAL)

            for user_id in list(storage.data.keys()):
                try:
                    user_id_int = int(user_id)
                    user = storage.get_user(user_id_int)

                    if user.get('mining_active'):
                        earned = await update_user_balance(user_id_int)
                        user = storage.get_user(user_id_int)

                        if earned > 0.01:
                            try:
                                await bot.send_message(
                                    chat_id=user_id_int,
                                    text=get_text(user_id_int, 'hourly_update',
                                                earned=format_balance(earned),
                                                balance=format_balance(user['balance']))
                                )
                            except:
                                pass

                except Exception as e:
                    continue

        except Exception as e:
            logger.error(f"Ошибка периодического обновления: {e}")
            await asyncio.sleep(60)

async def auto_save():
    """Автосохранение данных"""
    while True:
        await asyncio.sleep(AUTO_SAVE_INTERVAL)
        await storage.save()
        logger.info(f"Автосохранение: {len(storage.data)} пользователей")

# ===================== ЗАПУСК БОТА =====================
async def on_startup():
    """Действия при запуске"""
    logger.info("🚀 Бот запускается...")

    asyncio.create_task(show_advertisements())
    asyncio.create_task(auto_disable_mining())
    asyncio.create_task(periodic_balance_update())
    asyncio.create_task(auto_save())

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} успешно запущен!")
    except Exception as e:
        logger.error(f"Ошибка получения информации о боте: {e}")
        logger.info("✅ Бот запущен!")

async def main():
    """Главная функция"""
    await on_startup()

    try:
        await dp.start_polling(bot)
    finally:
        await storage.save()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")