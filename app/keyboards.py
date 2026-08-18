from urllib.parse import quote

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.texts import t
from app.callbacks import DeleteMsg


def back_btn(lang: str = 'ru') -> InlineKeyboardButton:
    """Reusable «back» button: closes the current inline menu."""
    return InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data='nav:back')


def onboarding_kb(lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'btn_connected'), callback_data='check_conn')],
        [InlineKeyboardButton(text=t(lang, 'btn_instruction'), callback_data='instruction')],
    ])


def main_menu_kb(lang: str = 'ru') -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, 'menu_history')), KeyboardButton(text=t(lang, 'menu_contacts'))],
            [KeyboardButton(text=t(lang, 'menu_stats')), KeyboardButton(text=t(lang, 'menu_settings'))],
            [KeyboardButton(text=t(lang, 'menu_subscription'))],
            [KeyboardButton(text=t(lang, 'menu_help')), KeyboardButton(text=t(lang, 'menu_support'))],
        ],
        resize_keyboard=True,
    )


def del_item_kb(db_id: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    """Delete button shown under each history item."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'btn_delete'), callback_data=DeleteMsg(db_id=db_id).pack())],
    ])


def support_kb(username: str, lang: str = 'ru') -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t(lang, 'btn_support'), url=f'https://t.me/{username}')]]
    rows.append([back_btn(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buy_kb(lang: str = 'ru') -> InlineKeyboardMarkup:
    # Кнопка «Оформить подписку» — открывает тарифы (YooKassa 500 ₽/год + триал).
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'btn_subscribe'), callback_data='open_subscribe')],
        [back_btn(lang)],
    ])


def subscribe_kb(lang: str = 'ru') -> InlineKeyboardMarkup:
    """Inline button that opens the Stars subscription plans flow."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'btn_subscribe'), callback_data='open_subscribe')],
        [back_btn(lang)],
    ])


def share_kb(lang: str, bot_username: str) -> InlineKeyboardMarkup:
    url = f'https://t.me/{bot_username}'
    text = (
        'Лови Sevrax — бот показывает удалённые и изменённые сообщения 👀'
        if lang == 'ru' else
        'Check out Sevrax — it shows deleted and edited messages 👀'
    )
    # URL-encode both params so the text isn't mangled in the share dialog.
    share = f'https://t.me/share/url?url={quote(url, safe="")}&text={quote(text, safe="")}'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'btn_share'), url=share)],
    ])


def history_filter_kb(user_id: int) -> InlineKeyboardMarkup:
    """Filters for a contact's history: all / deleted / edited."""
    b = InlineKeyboardBuilder()
    b.button(text='Всё', callback_data=f'hist:all:{user_id}')
    b.button(text='🗑 Удалённые', callback_data=f'hist:deleted:{user_id}')
    b.button(text='✏️ Изменённые', callback_data=f'hist:edited:{user_id}')
    b.adjust(3)
    return b.as_markup()


def settings_kb(settings: dict) -> InlineKeyboardMarkup:
    quiet = 'вкл' if settings and settings.get('quiet_enabled') else 'выкл'
    lang = (settings or {}).get('language', 'ru')
    b = InlineKeyboardBuilder()
    b.button(text='🔑 Ключевые слова', callback_data='set:keywords')
    b.button(text=f'🔕 Тихий режим: {quiet}', callback_data='set:quiet')
    b.button(text='🕐 Часы тихого режима', callback_data='set:qhours')
    b.button(text=f'🌐 Язык: {lang.upper()}', callback_data='set:lang')
    b.button(text='🧹 Очистить чат', callback_data='set:clearchat')
    b.button(text='🗑 Удалить мою историю', callback_data='set:wipe')
    b.button(text=t(lang, 'btn_back'), callback_data='nav:back')
    b.adjust(1)
    return b.as_markup()


def confirm_wipe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='✅ Да, удалить всё', callback_data='wipe:yes'),
            InlineKeyboardButton(text='↩️ Отмена', callback_data='wipe:no'),
        ],
    ])
