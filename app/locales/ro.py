"""Romanian strings — full coverage."""
RO: dict[str, str] = {
    # menu
    "menu.book": "📅 Programează-te",
    "menu.my": "🗓 Programările mele",
    "menu.masters": "💇 Maeștri",
    "menu.services": "💰 Servicii și prețuri",
    "menu.contacts": "📍 Adresă și contacte",
    "menu.support": "✉️ Contactează administratorul",
    "menu.language": "🌐 Limbă",
    "menu.title": "Meniu principal",
    "admin.menu": "⚙️ Panou admin",
    # common
    "back": "⬅️ Înapoi",
    "cancel": "❌ Anulează",
    "confirm": "✅ Confirmă",
    "edit": "✏️ Modifică",
    "next": "Înainte ➡️",
    "prev": "⬅️ Înapoi",
    "yes": "Da",
    "no": "Nu",
    "done": "Gata",
    "error.generic": "A apărut o eroare. Reveniți la meniul principal.",
    "error.not_owner": "Aceasta nu este programarea dvs.",
    "start.greeting": "Bună ziua! Bine ați venit la „{salon}”.\nAlegeți o acțiune:",
    # booking flow
    "book.choose_service": "Alegeți serviciul:",
    "book.choose_master_mode": "Cum alegeți maestrul?",
    "book.pick_master_self": "Aleg singur maestrul",
    "book.pick_master_auto": "Găsiți un maestru liber",
    "book.auto_soonest": "Cel mai apropiat timp",
    "book.auto_best": "Cel mai bun rating",
    "book.no_masters": "Nu există maeștri disponibili pentru acest serviciu.",
    "book.choose_date": "Alegeți data:",
    "book.choose_time": "Alegeți ora:",
    "book.no_slots": "Nu există ore libere pentru această dată. Alegeți altă dată.",
    "book.share_contact": "Vă rugăm să partajați contactul sau introduceți telefonul:",
    "book.share_button": "📱 Partajează contactul",
    "book.ask_comment": "Adăugați un comentariu (sau apăsați «Omite»):",
    "book.skip": "Omite",
    "book.summary": (
        "Verificați programarea:\n\n"
        "Serviciu: {service}\nMaestru: {master}\nData: {date}\nOra: {time}\n"
        "Durata: {duration} min\nPreț: {price} {currency}\n"
        "Adresa: {address}\nNume: {name}\nTelefon: {phone}"
    ),
    "book.confirmed": "✅ Programare creată! Maestrul a fost notificat.",
    "book.slot_taken": "Din păcate, această oră tocmai a fost ocupată. Alegeți alta.",
    "book.hold_expired": "Timpul de rezervare a expirat. Începeți din nou.",
    # master card
    "master.card": (
        "💇 {name}\nSpecializare: {spec}\nExperiență: {exp} ani\n"
        "Rating: {rating} ⭐ ({reviews} recenzii)\nDe la {price} {currency}"
    ),
    "master.portfolio": "🖼 Portofoliu",
    "master.reviews": "⭐ Recenzii",
    "master.choose": "Alege maestrul",
    "master.book_to": "Programează-te la maestru",
    "master.no_portfolio": "Maestrul nu are încă lucrări în portofoliu.",
    "master.no_reviews": "Încă nu există recenzii.",
    # my appointments
    "my.empty": "Nu aveți programări viitoare.",
    "my.item": (
        "📌 {service} — {master}\n{date} la {time}\n"
        "Status: {status}\nPreț: {price} {currency}"
    ),
    "my.reschedule": "🔄 Reprogramează",
    "my.cancel": "❌ Anulează",
    "my.cancel_reason": "Indicați motivul anulării:",
    "my.cancel_too_late": (
        "Puteți anula cu cel puțin {hours} ore înainte. "
        "Contactați administratorul."
    ),
    "my.cancelled": "Programarea a fost anulată.",
    "my.rescheduled": "Programarea a fost reprogramată.",
    "my.repeat": "🔁 Repetă ultima programare",
    # notifications
    "notify.master.new": (
        "🔔 Programare nouă!\n\nClient: {client}\nTelefon: {phone}\n"
        "Serviciu: {service}\nData: {date}\nOra: {time}\n"
        "Durata: {duration} min\nPreț: {price} {currency}\n"
        "Comentariu: {comment}"
    ),
    "notify.master.confirm": "Confirmă",
    "notify.master.decline": "Refuză",
    "notify.master.contact": "Contactează clientul",
    "notify.master.schedule": "Deschide programul",
    "notify.master.decline_reason": "Indicați motivul refuzului:",
    "notify.client.confirmed": "✅ Maestrul a confirmat programarea pentru {date} la {time}.",
    "notify.client.declined": (
        "Din păcate, maestrul a refuzat programarea pentru {date} la {time}.\nMotiv: {reason}\n"
        "Alegeți alt maestru sau altă oră."
    ),
    "notify.client.reminder": (
        "⏰ Reamintire programare!\n\nServiciu: {service}\nMaestru: {master}\n"
        "Data: {date}\nOra: {time}\nAdresa: {address}"
    ),
    "notify.client.confirm_visit": "✅ Confirm vizita",
    "notify.master.daily": "🗓 Programările de azi:\n{items}",
    # reviews
    "review.ask": "Evaluați vizita la maestrul {master} (1–5 stele):",
    "review.ask_text": "Doriți să lăsați o recenzie? Scrieți textul sau apăsați «Omite».",
    "review.thanks": "Mulțumim pentru recenzie!",
    "review.already": "Ați lăsat deja o recenzie pentru această programare.",
    # statuses
    "status.pending": "în așteptare",
    "status.confirmed": "confirmată",
    "status.completed": "finalizată",
    "status.cancelled_by_client": "anulată de client",
    "status.cancelled_by_master": "anulată de maestru",
    "status.cancelled_by_admin": "anulată de administrator",
    "status.rescheduled": "reprogramată",
    "status.no_show": "clientul nu a venit",
    # contacts
    "contacts.card": "🏠 {name}\n📍 {address}\n📞 {phone}",
    # language
    "lang.choose": "Alegeți limba:",
    "lang.set": "Limba a fost schimbată în română.",
    # admin
    "admin.only": "Disponibil doar administratorului.",
    "admin.today": "📅 Programări azi",
    "admin.all": "📋 Toate programările",
    "admin.masters": "💇 Maeștri",
    "admin.services": "💰 Servicii",
    "admin.clients": "👥 Clienți",
    "admin.reviews": "⭐ Recenzii",
    "admin.stats": "📊 Statistici",
    "admin.broadcast": "📣 Mesaje în masă",
    "admin.settings": "⚙️ Setări",
    "admin.export": "⬇️ Export CSV",
    "admin.stats.body": (
        "📊 Statistici\n\nProgramări azi: {today}\nSăptămâna: {week}\n"
        "Finalizate: {completed}\nAnulări: {cancelled}\nNeprezentări: {no_show}\n"
        "Venit (finalizate): {revenue} {currency}"
    ),
    "admin.broadcast.ask": "Introduceți textul pentru toți clienții:",
    "admin.broadcast.confirm": "Trimiteți mesajul la {count} clienți?",
    "admin.broadcast.done": "Trimitere finalizată. Livrate: {ok}, erori: {fail}.",
    "support.text": "Scrieți administratorului direct: {contact}",
    # admin extras
    "admin.empty": "Nimic de afișat.",
    "admin.masters.today": "💇 Maeștri la lucru azi:\n{items}",
    "admin.masters.none_today": "Azi nimeni nu lucrează.",
    "admin.clients.list": "👥 Clienți ({count}):\n{items}",
    "admin.reviews.list": "⭐ Ultimele recenzii:\n\n{items}",
    "admin.all.header": "📋 Programări viitoare:",
    "admin.settings.body": (
        "⚙️ Setări salon\n\nNume: {name}\nAdresă: {address}\nTelefon: {phone}\n"
        "Fus orar: {tz}\nValută: {currency}"
    ),
    # onboarding
    "onboarding.choose_lang": "Выберите язык / Alegeți limba / Choose language:",
}
