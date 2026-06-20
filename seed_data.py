"""
Boshlang'ich ma'lumotlarni bazaga yuklaydi: Sotuvchi roli uchun
32 bandlik cheklist (yuklangan Excel fayl asosida).

Ishga tushirish: python seed_data.py
"""

from database import init_db, add_checklist_item

init_db()

ROLE_SOTUVCHI = "sotuvchi"

# ---------- OCHILISH bo'limi ----------
ochilish_items = [
    ("1", "Do'kon kirish eshigi va vitrinasini tozaladim"),
    ("2", "Do'kon polini artib chiqdim"),
    ("3", "Oynalarni tozaladim"),
    ("4", "Hojatxonani tozaladim"),
    ("5", "09:00da do'konni to'liq tozalab chiqdim"),
    ("6", "Ombor ostonasini tozaladim va kirish yo'lakni bloklamadim"),
    ("7", "POS terminalni yoqdim va lenta yetarliligini tekshirdim"),
    ("8", "Kassa sahtasini sanab, boshlang'ich pul qolipini tayyorladim"),
    ("9", "MoySklad dasturiga kirib, kassa kunini ochdim"),
    ("10", "Epos programmasida ham kunni ochib qo'ydim"),
    ("11", "Ertalab vitrinada bo'sh joylarni tezda to'ldirdim"),
    ("12", "Narx yorliqlari 100% to'g'ri va toza ekanini tekshirdim"),
    ("13", "Aksiya bannerlarini ko'rinadigan joyga joyladim"),
    ("14", "QR-so'rov plakatini kassaga yaqin joylashtirdim"),
    ("16", "Suv dispenserini to'ldirdim, bokalni tozaladim, mijozlarga suv tayyor"),
    ("17", "Telefon zaryadini tekshirdim va zaryadladim"),
    ("18", "Bo'sh plastik va salafan paketlar zaxirasini tekshirdim"),
    ("19", "100talik list tayyorlandi"),
    ("19.1", "Pul rezinka tayyorlandi"),
    ("19.2", "Mijozlar nakladnoyi taxlandi"),
]

# Band 15 - haftalik, faqat dushanba (mon) va payshanba (thu)
haftalik_items = [
    ("15", "Kassa stolini dezinfeksiya salfetkasi bilan artdim"),
    ("15.1", "Svetokopiya qog'ozi ostatka olindi"),
    ("15.2", "Registr papka ostatka olindi"),
    ("15.3", "Ramka A4 ostatka olindi"),
]

# ---------- YOPILISH bo'limi ----------
yopilish_items = [
    ("20", "Obed vaqtidan so'ng vitrinalarni tekshirib, bo'sh joylarni tartibga keltirdim"),
    ("21", "Mahsulotlar shtrix kodlarini tekshirdim"),
    ("22", "Naqd pulni sanab, seyfga oldim va mas'ul shaxsga topshirdim"),
    ("23", "Kun yopilishi screenshotini Telegram guruhga tashladim"),
    ("24", "Terminallar bo'yicha Z-otchetni chop etdim"),
    ("25", "Terminalga urilgan summa bilan MoySkladda urilgan summani solishtirdim"),
    ("26", "Eposda kunni yopdim"),
    ("27", "MoySklad kassa kunini yopdim"),
    ("28", "POS terminalni o'chirib, zaryadga qo'ydim"),
    ("29", "Elektr jihozlarini tekshirdim, xavfsiz o'chirdim"),
    ("30", "Do'kon va sklad eshigini qulfladim"),
    ("31", "Kuniga kamida 5 ta yangi mijoz kontaktini F-loyalga kiritdim"),
    ("32", "Kuniga kamida 3 ta yangi mijoz kontaktini Telegram kanalga qo'shdim"),
]

for i, (num, text) in enumerate(ochilish_items):
    add_checklist_item(ROLE_SOTUVCHI, "ochilish", num, text, sort_order=i)

for i, (num, text) in enumerate(haftalik_items):
    add_checklist_item(
        ROLE_SOTUVCHI, "ochilish", num, text,
        weekly_days="mon,thu", sort_order=100 + i,
    )

for i, (num, text) in enumerate(yopilish_items):
    add_checklist_item(ROLE_SOTUVCHI, "yopilish", num, text, sort_order=i)

print(f"Yuklandi: {len(ochilish_items)} ochilish band, "
      f"{len(haftalik_items)} haftalik band, "
      f"{len(yopilish_items)} yopilish band — rol: {ROLE_SOTUVCHI}")

# =====================================================================
# BROKER ROLI
# =====================================================================
ROLE_BROKER = "broker"

# ---------- OCHILISH bo'limi (sariq) ----------
# Hujjatdagi 6ta "Muddati o'tgan lotlar" bandi BITTA umumiy bandga
# birlashtirilgan — matn so'zma-so'z saqlangan, faqat bitta band sifatida
broker_ochilish_items = [
    ("1",
     "Muddati o'tgan lotlar aktiv qilish kerak:\n\n"
     "- Jizzax maxsus taminot — Xarid.uzex.uz elektron va milliy do'kon, "
     "xt-xarid.uz elektron va milliy do'kon, "
     "new.coorparation.uz elektron va milliy do'kon, "
     "e-birja elektron va milliy do'kon\n\n"
     "- Yatt Islomov P — Xarid.uzex.uz elektron va milliy do'kon, "
     "xt-xarid.uz elektron va milliy do'kon\n\n"
     "- Po'lat va Lola OK — Xarid.uzex.uz milliy do'kon, "
     "xt-xarid.uz milliy do'kon\n\n"
     "- Yatt Temirov Davidjon — Xarid.uzex.uz milliy do'kon, "
     "xt-xarid.uz milliy do'kon\n\n"
     "- Yatt Abduvaliyev (2ta birja) — Xarid.uzex.uz elektron va milliy "
     "do'kon, xt-xarid.uz elektron va milliy do'kon\n\n"
     "- Yatt Islomova Ozoda (2ta birja) — Xarid.uzex.uz milliy do'kon, "
     "xt-xarid.uz milliy do'kon"),
    ("2",
     "Bizdan tanlangan lotlarga narx berib chiqildi:\n\n"
     "- Jizzax maxsus taminot\n"
     "- Yatt Islomov P\n"
     "- Po'lat va Lola OK\n"
     "- Yatt Temirov Davidjon\n"
     "- Yatt Abduvaliyev\n"
     "- Yatt Islomova Ozoda"),
    ("3",
     "Elektron do'konga qo'yilgan lotlar bo'yicha narxlar berildi:\n\n"
     "- Jizzax maxsus taminot — xarid.uzex.uz va xt-xarid.uz\n"
     "- Yatt Islomov P — xarid.uzex.uz va xt-xarid.uz\n"
     "- Yatt Abduvaliyev — xarid.uzex.uz va xt-xarid.uz"),
]

# ---------- YOPILISH bo'limi (qizil) ----------
broker_yopilish_items = [
    ("4", "Moy skladdagi kunlik zadachalar tugatildi"),
    ("5", "Kun yopilgach kassa hisob-kitobi to'liq tekshirildi"),
    ("6", "Oprixodavaniya hamda spisaniyadagi tovarlar tekshirildi"),  # allow_comment=1
    ("7", "CHOK to'liq tugatildi va skrenshot gruppaga tashlandi"),
]

# Faqat dushanba kuni chiqadigan qizil band
broker_yopilish_weekly_items = [
    ("5.1", "Har dushanba kunida toshkentga ishlatilgan pullar hisob "
            "kitobi to'g'ri nazorat qilindi"),
]

# ---------- OY OXIRI bo'limi (yashil) ----------
broker_oyoxiri_items = [
    ("8",
     "Har oy oxirida oy hisoboti yopildi.\n\n"
     "Oy yopishda etibor beriladigan jihatlar:\n"
     "1. Yetkazib beruvchilar bilan hisob kitoblar tekshiriladi.\n"
     "2. Birja qoldiqlari tekshiriladi\n"
     "3. Ish haqi hisoblanadi\n"
     "4. Soliqlar hisoblanadi"),
    ("9", "Har oyning ohirida xarajatlar nazorati jadvali to'ldirildi"),
]

for i, (num, text) in enumerate(broker_ochilish_items):
    add_checklist_item(ROLE_BROKER, "ochilish", num, text, sort_order=i)

for i, (num, text) in enumerate(broker_yopilish_items):
    allow_comment = 1 if num == "6" else 0
    add_checklist_item(ROLE_BROKER, "yopilish", num, text, sort_order=i,
                        allow_comment=allow_comment)

for i, (num, text) in enumerate(broker_yopilish_weekly_items):
    add_checklist_item(ROLE_BROKER, "yopilish", num, text,
                        weekly_days="mon", sort_order=50 + i)

for i, (num, text) in enumerate(broker_oyoxiri_items):
    add_checklist_item(ROLE_BROKER, "oyoxiri", num, text, sort_order=i)

print(f"Yuklandi: {len(broker_ochilish_items)} ochilish band, "
      f"{len(broker_yopilish_items)} yopilish band, "
      f"{len(broker_yopilish_weekly_items)} haftalik (dushanba) band, "
      f"{len(broker_oyoxiri_items)} oy oxiri band — rol: {ROLE_BROKER}")

print("Eslatma: Do'kon boshqaruvchisi va B2B menejer rollari uchun "
      "bandlarni shu fayl ichiga xuddi shu uslubda qo'shing.")
