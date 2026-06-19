"""Minimal RU/EN localization. Use t(lang, key, **kwargs)."""

TEXTS = {
    'ru': {
        'start': (
            '👋 Привет, {name}!\n\n'
            'Это <b>Sevrax</b> — я сохраняю всё что тебе пишут, даже если потом удалят или изменят.\n\n'
            'Что умею:\n'
            '🔹 Показываю удалённые сообщения\n'
            '🔹 Показываю что изменили (было/стало)\n'
            '🔹 Сохраняю медиа с пометкой\n'
            '🔹 Веду историю по каждому собеседнику\n\n'
            'Чтобы начать — подключи меня через Telegram Business:\n'
            'Настройки → Telegram для бизнеса → Чат-боты → @твой_бот'
        ),
        'btn_connected': '✅ Я подключил',
        'btn_instruction': '📖 Подробная инструкция',
        'instruction': (
            '📖 <b>Как подключить</b>\n\n'
            '1. Открой <b>Настройки</b> Telegram\n'
            '2. Выбери <b>Telegram для бизнеса</b>\n'
            '   (доступно при активной Premium-подписке Telegram)\n'
            '3. Открой раздел <b>Чат-боты</b>\n'
            '4. Введи юзернейм этого бота и выбери его\n'
            '5. Разреши боту читать и управлять сообщениями\n'
            '6. Вернись сюда и нажми «✅ Я подключил»'
        ),
        'connected_ok': '🎉 Отлично, подключение активно! Вот главное меню:',
        'connected_fail': (
            '❌ Пока не вижу подключения.\n'
            'Убедись что добавил бота в Telegram Business и попробуй ещё раз.'
        ),
        'menu_title': 'Главное меню:',
        'menu_history': '📜 История изменений',
        'menu_contacts': '👥 Мои собеседники',
        'menu_stats': '📊 Статистика',
        'menu_settings': '⚙️ Настройки',
        'menu_subscription': '💎 Подписка',
        'menu_help': '❓ Помощь',
        'menu_support': '🆘 Поддержка',
        'btn_back': '⬅️ Назад',
        'btn_delete': '🗑 Удалить',
        'btn_subscribe': '💎 Оформить подписку',
        'btn_support': '💬 Написать в поддержку',
        'help': (
            '❓ <b>Помощь — Sevrax</b>\n\n'
            'Я сохраняю входящие сообщения и показываю, если их удалили или изменили.\n\n'
            '<b>Что умею:</b>\n'
            '🔹 Уведомления об удалённых и изменённых сообщениях\n'
            '🔹 История по каждому собеседнику (было/стало)\n'
            '🔹 Сохранение медиа\n'
            '🔹 Статистика, ключевые слова, тихий режим\n\n'
            '<b>Команды:</b>\n'
            '/start — главное меню\n'
            '/history — история по собеседникам\n'
            '/subscribe — оформить подписку\n'
            '/trial — пробный период на 7 дней\n'
            '/myref — реферальная ссылка\n'
            '/cancel_subscription — отключить автопродление\n'
            '/help — эта справка\n'
            '/support — связаться с поддержкой\n\n'
            'Подключение: Настройки Telegram → Telegram для бизнеса → Чат-боты.'
        ),
        'support': (
            '🆘 <b>Поддержка</b>\n\n'
            'Возник вопрос или что-то не работает? Напиши нам — поможем.\n'
            'Нажми кнопку ниже, чтобы открыть чат.'
        ),
        'no_connection': 'У вас нет активного бизнес-соединения. Подключите бота через Telegram Business.',
        'premium_only': (
            '💎 Эта функция доступна в <b>Premium</b>.\n\n'
            'В бесплатной версии — только уведомления «что-то удалили/изменили» '
            'и история за 7 дней.'
        ),
        'btn_buy': '💎 Купить подписку',
        'btn_activate': '🎁 Активировать бесплатно',
        'btn_share': '📤 Поделиться с друзьями',
        'sub_test_offer': (
            '💎 <b>Sevrax Premium</b>\n\n'
            '🎉 Хорошие новости: сейчас бот работает в <b>тестовом режиме</b>, '
            'поэтому Premium включается <b>бесплатно</b> — оплату мы пока не принимаем.\n\n'
            'Что откроется:\n'
            '• Полное содержимое сообщений и медиа\n'
            '• История без ограничений\n'
            '• Умные алерты по ключевым словам\n'
            '• Статистика, экспорт, транскрибация голосовых\n\n'
            'Нажми кнопку ниже, чтобы активировать 👇'
        ),
        'sub_active': (
            '💎 <b>Premium активен</b> (тестовый режим).\n\n'
            'Спасибо что пользуешься Sevrax! 🙌\n'
            'Помоги нам расти — поделись ботом с друзьями:'
        ),
        'sub_activated': (
            '🎉 <b>Готово! Premium активирован бесплатно.</b>\n\n'
            'Пока мы в тестовом режиме — все функции открыты.\n'
            'Если бот тебе зашёл, поделись им с друзьями 🙏'
        ),
    },
    'en': {
        'start': (
            '👋 Hi, {name}!\n\n'
            "This is <b>Sevrax</b> — I save everything people send you, even if they delete or edit it later.\n\n"
            'What I can do:\n'
            '🔹 Show deleted messages\n'
            '🔹 Show edits (before/after)\n'
            '🔹 Store media with a note\n'
            '🔹 Keep history per contact\n\n'
            'To start — connect me via Telegram Business:\n'
            'Settings → Telegram Business → Chatbots → @your_bot'
        ),
        'btn_connected': '✅ I connected',
        'btn_instruction': '📖 Detailed instructions',
        'instruction': (
            '📖 <b>How to connect</b>\n\n'
            '1. Open Telegram <b>Settings</b>\n'
            '2. Choose <b>Telegram Business</b>\n'
            '3. Open <b>Chatbots</b>\n'
            '4. Type this bot username and select it\n'
            '5. Allow the bot to read and manage messages\n'
            '6. Come back and tap “✅ I connected”'
        ),
        'connected_ok': '🎉 Great, connection is active! Here is the main menu:',
        'connected_fail': (
            "❌ I don't see a connection yet.\n"
            'Make sure you added the bot in Telegram Business and try again.'
        ),
        'menu_title': 'Main menu:',
        'menu_history': '📜 Edit history',
        'menu_contacts': '👥 My contacts',
        'menu_stats': '📊 Statistics',
        'menu_settings': '⚙️ Settings',
        'menu_subscription': '💎 Subscription',
        'menu_help': '❓ Help',
        'menu_support': '🆘 Support',
        'btn_back': '⬅️ Back',
        'btn_delete': '🗑 Delete',
        'btn_subscribe': '💎 Subscribe',
        'btn_support': '💬 Contact support',
        'help': (
            '❓ <b>Help — Sevrax</b>\n\n'
            'I store incoming messages and show you if they are deleted or edited.\n\n'
            '<b>What I can do:</b>\n'
            '🔹 Notify about deleted and edited messages\n'
            '🔹 Per-contact history (before/after)\n'
            '🔹 Store media\n'
            '🔹 Statistics, keywords, quiet mode\n\n'
            '<b>Commands:</b>\n'
            '/start — main menu\n'
            '/history — per-contact history\n'
            '/subscribe — buy a subscription\n'
            '/trial — 7-day free trial\n'
            '/myref — referral link\n'
            '/cancel_subscription — stop auto-renewal\n'
            '/help — this help\n'
            '/support — contact support\n\n'
            'Connect: Telegram Settings → Telegram Business → Chatbots.'
        ),
        'support': (
            '🆘 <b>Support</b>\n\n'
            'Got a question or something not working? Message us — we will help.\n'
            'Tap the button below to open the chat.'
        ),
        'no_connection': 'You have no active business connection. Connect the bot via Telegram Business.',
        'premium_only': (
            '💎 This feature is available in <b>Premium</b>.\n\n'
            'In the free version — only "something was deleted/edited" notifications '
            'and 7-day history.'
        ),
        'btn_buy': '💎 Buy subscription',
        'btn_activate': '🎁 Activate for free',
        'btn_share': '📤 Share with friends',
        'sub_test_offer': (
            '💎 <b>Sevrax Premium</b>\n\n'
            '🎉 Good news: the bot is in <b>test mode</b>, so Premium is enabled '
            'for <b>free</b> — we are not accepting payments yet.\n\n'
            'What you unlock:\n'
            '• Full message content and media\n'
            '• Unlimited history\n'
            '• Smart keyword alerts\n'
            '• Statistics, export, voice transcription\n\n'
            'Tap the button below to activate 👇'
        ),
        'sub_active': (
            '💎 <b>Premium is active</b> (test mode).\n\n'
            'Thanks for using Sevrax! 🙌\n'
            'Help us grow — share the bot with friends:'
        ),
        'sub_activated': (
            '🎉 <b>Done! Premium activated for free.</b>\n\n'
            "While we're in test mode all features are unlocked.\n"
            'If you like the bot, please share it with friends 🙏'
        ),
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXTS else 'ru'
    value = TEXTS[lang].get(key) or TEXTS['ru'].get(key, key)
    return value.format(**kwargs) if kwargs else value
