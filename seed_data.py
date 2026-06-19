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
print("Eslatma: Do'kon boshqaruvchisi, B2B menejer, Broker rollari uchun "
      "bandlarni shu fayl ichiga xuddi shu uslubda qo'shing.")
