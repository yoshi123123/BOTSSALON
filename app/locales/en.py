"""English strings — full coverage."""
EN: dict[str, str] = {
    # menu
    "menu.book": "📅 Book",
    "menu.my": "🗓 My appointments",
    "menu.masters": "💇 Masters",
    "menu.services": "💰 Services & prices",
    "menu.contacts": "📍 Address & contacts",
    "menu.support": "✉️ Contact admin",
    "menu.language": "🌐 Language",
    "menu.title": "Main menu",
    "admin.menu": "⚙️ Admin panel",
    # common
    "back": "⬅️ Back",
    "cancel": "❌ Cancel",
    "confirm": "✅ Confirm",
    "edit": "✏️ Edit",
    "next": "Next ➡️",
    "prev": "⬅️ Back",
    "yes": "Yes",
    "no": "No",
    "done": "Done",
    "error.generic": "An error occurred. Please return to the main menu.",
    "error.not_owner": "This is not your appointment.",
    "start.greeting": "Hello! Welcome to \"{salon}\".\nChoose an action:",
    # booking flow
    "book.choose_service": "Choose a service:",
    "book.choose_master_mode": "How to pick a master?",
    "book.pick_master_self": "Pick a master myself",
    "book.pick_master_auto": "Find an available master",
    "book.auto_soonest": "Soonest time",
    "book.auto_best": "Best rating",
    "book.no_masters": "No masters available for this service.",
    "book.choose_date": "Choose a date:",
    "book.choose_time": "Choose a time:",
    "book.no_slots": "No free slots for this date. Choose another one.",
    "book.share_contact": "Please share your contact or type your phone:",
    "book.share_button": "📱 Share contact",
    "book.ask_comment": "Add a comment (or press “Skip”):",
    "book.skip": "Skip",
    "book.summary": (
        "Review your booking:\n\n"
        "Service: {service}\nMaster: {master}\nDate: {date}\nTime: {time}\n"
        "Duration: {duration} min\nPrice: {price} {currency}\n"
        "Address: {address}\nName: {name}\nPhone: {phone}"
    ),
    "book.confirmed": "✅ Booking created! The master has been notified.",
    "book.slot_taken": "Sorry, this slot was just taken. Pick another one.",
    "book.hold_expired": "Slot hold expired. Please start the booking again.",
    # master card
    "master.card": (
        "💇 {name}\nSpecialty: {spec}\nExperience: {exp} yrs\n"
        "Rating: {rating} ⭐ ({reviews} reviews)\nFrom {price} {currency}"
    ),
    "master.portfolio": "🖼 Portfolio",
    "master.reviews": "⭐ Reviews",
    "master.choose": "Choose master",
    "master.book_to": "Book this master",
    "master.no_portfolio": "This master has no portfolio items yet.",
    "master.no_reviews": "No reviews yet.",
    # my appointments
    "my.empty": "You have no upcoming appointments.",
    "my.item": (
        "📌 {service} — {master}\n{date} at {time}\n"
        "Status: {status}\nPrice: {price} {currency}"
    ),
    "my.reschedule": "🔄 Reschedule",
    "my.cancel": "❌ Cancel",
    "my.cancel_reason": "Please state the cancellation reason:",
    "my.cancel_too_late": (
        "Self-cancellation is allowed no later than {hours} h before. "
        "Please contact the administrator."
    ),
    "my.cancelled": "The appointment has been cancelled.",
    "my.rescheduled": "The appointment has been rescheduled.",
    "my.repeat": "🔁 Repeat last booking",
    # notifications
    "notify.master.new": (
        "🔔 New booking!\n\nClient: {client}\nPhone: {phone}\n"
        "Service: {service}\nDate: {date}\nTime: {time}\n"
        "Duration: {duration} min\nPrice: {price} {currency}\n"
        "Comment: {comment}"
    ),
    "notify.master.confirm": "Confirm",
    "notify.master.decline": "Decline",
    "notify.master.contact": "Contact client",
    "notify.master.schedule": "Open schedule",
    "notify.master.decline_reason": "State the decline reason:",
    "notify.client.confirmed": "✅ The master confirmed your booking for {date} at {time}.",
    "notify.client.declined": (
        "Unfortunately, the master declined the booking for {date} at {time}.\nReason: {reason}\n"
        "Choose another master or time."
    ),
    "notify.client.reminder": (
        "⏰ Appointment reminder!\n\nService: {service}\nMaster: {master}\n"
        "Date: {date}\nTime: {time}\nAddress: {address}"
    ),
    "notify.client.confirm_visit": "✅ Confirm visit",
    "notify.master.daily": "🗓 Your appointments today:\n{items}",
    # reviews
    "review.ask": "Rate your visit to {master} (1–5 stars):",
    "review.ask_text": "Want to leave a review? Type it or press “Skip”.",
    "review.thanks": "Thanks for your review!",
    "review.already": "You already reviewed this appointment.",
    # statuses
    "status.pending": "pending",
    "status.confirmed": "confirmed",
    "status.completed": "completed",
    "status.cancelled_by_client": "cancelled by client",
    "status.cancelled_by_master": "cancelled by master",
    "status.cancelled_by_admin": "cancelled by admin",
    "status.rescheduled": "rescheduled",
    "status.no_show": "no-show",
    # contacts
    "contacts.card": "🏠 {name}\n📍 {address}\n📞 {phone}",
    # language
    "lang.choose": "Choose a language:",
    "lang.set": "Language switched to English.",
    # admin
    "admin.only": "Admins only.",
    "admin.today": "📅 Today's bookings",
    "admin.all": "📋 All bookings",
    "admin.masters": "💇 Masters",
    "admin.services": "💰 Services",
    "admin.clients": "👥 Clients",
    "admin.reviews": "⭐ Reviews",
    "admin.stats": "📊 Statistics",
    "admin.broadcast": "📣 Broadcasts",
    "admin.settings": "⚙️ Settings",
    "admin.export": "⬇️ Export CSV",
    "admin.stats.body": (
        "📊 Statistics\n\nBookings today: {today}\nThis week: {week}\n"
        "Completed: {completed}\nCancelled: {cancelled}\nNo-shows: {no_show}\n"
        "Revenue (completed): {revenue} {currency}"
    ),
    "admin.broadcast.ask": "Enter the broadcast text for all clients:",
    "admin.broadcast.confirm": "Send the message to {count} clients?",
    "admin.broadcast.done": "Broadcast finished. Delivered: {ok}, failed: {fail}.",
    "support.text": "Write to the administrator directly: {contact}",
    # admin extras
    "admin.empty": "Nothing to show.",
    "admin.masters.today": "💇 Masters working today:\n{items}",
    "admin.masters.none_today": "Nobody works today.",
    "admin.clients.list": "👥 Clients ({count}):\n{items}",
    "admin.reviews.list": "⭐ Latest reviews:\n\n{items}",
    "admin.all.header": "📋 Upcoming bookings:",
    "admin.settings.body": (
        "⚙️ Salon settings\n\nName: {name}\nAddress: {address}\nPhone: {phone}\n"
        "Timezone: {tz}\nCurrency: {currency}"
    ),
    # onboarding
    "onboarding.choose_lang": "Выберите язык / Alegeți limba / Choose language:",
}
