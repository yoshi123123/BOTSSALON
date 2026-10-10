"""Russian strings (default language)."""
RU: dict[str, str] = {
    # menu
    "menu.book": "📅 Записаться",
    "menu.my": "🗓 Мои записи",
    "menu.masters": "💇 Мастера",
    "menu.services": "💰 Услуги и цены",
    "menu.contacts": "📍 Адрес и контакты",
    "menu.support": "✉️ Связаться с администратором",
    "menu.language": "🌐 Язык",
    "menu.title": "Главное меню",
    "admin.menu": "⚙️ Админ-панель",
    # common
    "back": "⬅️ Назад",
    "cancel": "❌ Отмена",
    "confirm": "✅ Подтвердить",
    "edit": "✏️ Изменить",
    "next": "Вперёд ➡️",
    "prev": "⬅️ Назад",
    "yes": "Да",
    "no": "Нет",
    "done": "Готово",
    "error.generic": "Произошла ошибка. Попробуйте вернуться в главное меню.",
    "error.not_owner": "Это не ваша запись.",
    "start.greeting": "Здравствуйте! Добро пожаловать в «{salon}».\nВыберите действие:",
    # booking flow
    "book.choose_service": "Выберите услугу:",
    "book.choose_master_mode": "Как выбрать мастера?",
    "book.pick_master_self": "Выбрать мастера самому",
    "book.pick_master_auto": "Подобрать свободного мастера",
    "book.auto_soonest": "Ближайшее время",
    "book.auto_best": "Лучший рейтинг",
    "book.no_masters": "Нет доступных мастеров для этой услуги.",
    "book.choose_date": "Выберите дату:",
    "book.choose_time": "Выберите время:",
    "book.no_slots": "На эту дату нет свободного времени. Выберите другую дату.",
    "book.share_contact": "Пожалуйста, поделитесь контактом или введите телефон:",
    "book.share_button": "📱 Поделиться контактом",
    "book.ask_comment": "Добавьте комментарий (или нажмите «Пропустить»):",
    "book.skip": "Пропустить",
    "book.summary": (
        "Проверьте запись:\n\n"
        "Услуга: {service}\nМастер: {master}\nДата: {date}\nВремя: {time}\n"
        "Длительность: {duration} мин\nСтоимость: {price} {currency}\n"
        "Адрес: {address}\nИмя: {name}\nТелефон: {phone}"
    ),
    "book.confirmed": "✅ Запись создана! Мастер получил уведомление.",
    "book.slot_taken": "К сожалению, это время только что заняли. Выберите другое.",
    "book.hold_expired": "Время удержания слота истекло. Начните запись заново.",
    # master card
    "master.card": (
        "💇 {name}\nСпециализация: {spec}\nСтаж: {exp} лет\n"
        "Рейтинг: {rating} ⭐ ({reviews} отзывов)\nОт {price} {currency}"
    ),
    "master.portfolio": "🖼 Портфолио",
    "master.reviews": "⭐ Отзывы",
    "master.choose": "Выбрать мастера",
    "master.book_to": "Записаться к мастеру",
    "master.no_portfolio": "У мастера пока нет работ в портфолио.",
    "master.no_reviews": "Отзывов пока нет.",
    # my appointments
    "my.empty": "У вас нет предстоящих записей.",
    "my.item": (
        "📌 {service} — {master}\n{date} в {time}\n"
        "Статус: {status}\nСтоимость: {price} {currency}"
    ),
    "my.reschedule": "🔄 Перенести",
    "my.cancel": "❌ Отменить",
    "my.cancel_reason": "Укажите причину отмены:",
    "my.cancel_too_late": (
        "Отменить самостоятельно можно не позднее чем за {hours} ч. "
        "Свяжитесь с администратором."
    ),
    "my.cancelled": "Запись отменена.",
    "my.rescheduled": "Запись перенесена.",
    "my.repeat": "🔁 Повторить последнюю запись",
    # notifications
    "notify.master.new": (
        "🔔 Новая запись!\n\nКлиент: {client}\nТелефон: {phone}\n"
        "Услуга: {service}\nДата: {date}\nВремя: {time}\n"
        "Длительность: {duration} мин\nСтоимость: {price} {currency}\n"
        "Комментарий: {comment}"
    ),
    "notify.master.confirm": "Подтвердить",
    "notify.master.decline": "Отклонить",
    "notify.master.contact": "Связаться с клиентом",
    "notify.master.schedule": "Открыть расписание",
    "notify.master.decline_reason": "Укажите причину отклонения:",
    "notify.client.confirmed": "✅ Мастер подтвердил вашу запись на {date} в {time}.",
    "notify.client.declined": (
        "К сожалению, мастер отклонил запись на {date} в {time}.\nПричина: {reason}\n"
        "Выберите другого мастера или время."
    ),
    "notify.client.reminder": (
        "⏰ Напоминание о записи!\n\nУслуга: {service}\nМастер: {master}\n"
        "Дата: {date}\nВремя: {time}\nАдрес: {address}"
    ),
    "notify.client.confirm_visit": "✅ Подтвердить визит",
    "notify.master.daily": "🗓 Ваши записи на сегодня:\n{items}",
    # reviews
    "review.ask": "Оцените визит к мастеру {master} (1–5 звёзд):",
    "review.ask_text": "Хотите оставить отзыв? Напишите текст или нажмите «Пропустить».",
    "review.thanks": "Спасибо за отзыв!",
    "review.already": "Вы уже оставили отзыв по этой записи.",
    # statuses
    "status.pending": "ожидает подтверждения",
    "status.confirmed": "подтверждена",
    "status.completed": "выполнена",
    "status.cancelled_by_client": "отменена клиентом",
    "status.cancelled_by_master": "отменена мастером",
    "status.cancelled_by_admin": "отменена администратором",
    "status.rescheduled": "перенесена",
    "status.no_show": "клиент не пришёл",
    # contacts
    "contacts.card": "🏠 {name}\n📍 {address}\n📞 {phone}",
    # language
    "lang.choose": "Выберите язык:",
    "lang.set": "Язык изменён на русский.",
    # admin
    "admin.only": "Доступно только администратору.",
    "admin.today": "📅 Записи сегодня",
    "admin.all": "📋 Все записи",
    "admin.masters": "💇 Мастера",
    "admin.services": "💰 Услуги",
    "admin.clients": "👥 Клиенты",
    "admin.reviews": "⭐ Отзывы",
    "admin.stats": "📊 Статистика",
    "admin.broadcast": "📣 Рассылки",
    "admin.settings": "⚙️ Настройки",
    "admin.export": "⬇️ Экспорт CSV",
    "admin.stats.body": (
        "📊 Статистика\n\nЗаписей сегодня: {today}\nЗа неделю: {week}\n"
        "Выполнено: {completed}\nОтмен: {cancelled}\nНе пришли: {no_show}\n"
        "Выручка (завершённые): {revenue} {currency}"
    ),
    "admin.broadcast.ask": "Введите текст рассылки для всех клиентов:",
    "admin.broadcast.confirm": "Отправить сообщение {count} клиентам?",
    "admin.broadcast.done": "Рассылка завершена. Доставлено: {ok}, ошибок: {fail}.",
    "support.text": "Напишите администратору напрямую: {contact}",
    # admin extras
    "admin.empty": "Нечего показывать.",
    "admin.masters.today": "💇 Мастера на работе сегодня:\n{items}",
    "admin.masters.none_today": "Сегодня никто не работает.",
    "admin.clients.list": "👥 Клиенты ({count}):\n{items}",
    "admin.reviews.list": "⭐ Последние отзывы:\n\n{items}",
    "admin.all.header": "📋 Предстоящие записи:",
    "admin.settings.body": (
        "⚙️ Настройки салона\n\nНазвание: {name}\nАдрес: {address}\nТелефон: {phone}\n"
        "Часовой пояс: {tz}\nВалюта: {currency}"
    ),
    # onboarding
    "onboarding.choose_lang": "Выберите язык / Alegeți limba / Choose language:",
    # admin appointment editing
    "aedit.card": (
        "📌 Запись #{id}\n\nУслуга: {service}\nМастер: {master}\n"
        "Дата: {date} в {time}\nСтатус: {status}\nЦена: {price} {currency}\n\n"
        "Клиент: {client}\nТелефон: {phone}\nUsername: {username}\n"
        "Комментарий: {comment}"
    ),
    "aedit.reschedule": "🔄 Перенести",
    "aedit.master": "💇 Сменить мастера",
    "aedit.status": "🚦 Сменить статус",
    "aedit.cancel": "❌ Отменить запись",
    "aedit.pick_master": "Выберите нового мастера:",
    "aedit.pick_status": "Выберите новый статус:",
    "aedit.done": "✅ Запись обновлена.",
    "aedit.cancelled": "❌ Запись отменена администратором.",
    "aedit.master_cant": "Этот мастер не выполняет данную услугу.",
    "notify.admin.change": (
        "🛠 Изменение записи #{id} ({by})\n{what}\n\n"
        "Клиент: {client} {phone}\nУслуга: {service}\nМастер: {master}\n"
        "Когда: {date} {time}"
    ),
    "notify.client.admin_changed": (
        "ℹ️ Администратор изменил вашу запись:\n{what}\n\n"
        "Услуга: {service}\nМастер: {master}\nКогда: {date} в {time}"
    ),
}
