"""
Kunlik/davriy hisobotni PDF formatda yaratadi.
Admin /hisobot buyrug'i orqali chaqiriladi (bot.py ichida bog'lanadi).
"""

from datetime import date
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

import database as db

ROLE_LABELS = {
    "sotuvchi": "Sotuvchi",
    "boshqaruvchi": "Do'kon boshqaruvchisi",
    "b2b_menejer": "B2B menejer",
    "broker": "Broker",
}


def generate_daily_pdf(report_date: str, output_path: str = None):
    """report_date format: 'YYYY-MM-DD'. PDF faylga yo'lni qaytaradi."""
    if output_path is None:
        output_path = f"data/hisobot_{report_date}.pdf"

    rows = db.get_daily_report(report_date)

    doc = SimpleDocTemplate(
        output_path, pagesize=landscape(A4),
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleUz", parent=styles["Title"], fontSize=16, spaceAfter=10,
    )

    story = [Paragraph(f"Kunlik hisobot — {report_date}", title_style),
             Spacer(1, 8)]

    if not rows:
        story.append(Paragraph("Bu kun uchun ma'lumot topilmadi.", styles["Normal"]))
        doc.build(story)
        return output_path

    table_data = [["Xodim", "Rol", "Ochilish vaqti", "Yopilish vaqti",
                   "Bajarilgan", "Bajarilmagan"]]

    for r in rows:
        role_label = ROLE_LABELS.get(r["role"], r["role"])
        opening = r["opening_time"] or "—"
        closing = r["closing_time"] or "—"
        done = r["done_count"] or 0
        total = r["total_count"] or 0
        incomplete = max(total - done, 0)
        table_data.append([
            r["full_name"], role_label, opening, closing,
            f"{done}/{total}", str(incomplete),
        ])

    col_widths = [55 * mm, 50 * mm, 35 * mm, 35 * mm, 35 * mm, 35 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E5C3E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F4F4F4")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])

    # Bajarilmagan soni > 0 bo'lsa, qizil rangda belgilash
    for i, r in enumerate(rows, start=1):
        total = r["total_count"] or 0
        done = r["done_count"] or 0
        if total - done > 0:
            style.add("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#B00020"))
            style.add("FONTNAME", (5, i), (5, i), "Helvetica-Bold")

    table.setStyle(style)
    story.append(table)

    # Barcha xodimlarning bandlari tafsiloti (bajarilgan ✅ va bajarilmagan ❌)
    story.append(Spacer(1, 16))
    detail_style = ParagraphStyle(
        "Detail", parent=styles["Normal"], fontSize=10, leading=15,
    )

    story.append(Paragraph("Bandlar tafsiloti:", styles["Heading3"]))
    users = db.list_users_by_role()
    name_to_id = {u["full_name"]: u["id"] for u in users}

    for r in rows:
        uid = name_to_id.get(r["full_name"])
        if not uid:
            continue
        all_items = db.get_all_items_with_status(uid, report_date)
        if not all_items:
            continue
        lines = []
        for it in all_items:
            if it["done"]:
                lines.append(
                    f'<font color="#1A7F37">[✓]</font> {it["text"]}'
                )
            else:
                lines.append(
                    f'<font color="#B00020">[✗]</font> {it["text"]}'
                )
        items_block = "<br/>".join(lines)
        story.append(Paragraph(
            f"<b>{r['full_name']}</b> ({ROLE_LABELS.get(r['role'], r['role'])}):<br/>{items_block}",
            detail_style
        ))
        story.append(Spacer(1, 10))

    doc.build(story)
    return output_path


if __name__ == "__main__":
    path = generate_daily_pdf(date.today().isoformat())
    print(f"PDF yaratildi: {path}")


def generate_period_role_pdf(role: str, start_date: str, end_date: str,
                              output_path: str = None):
    """Berilgan rol uchun, sanalar oralig'ida, HAR XODIM ALOHIDA bo'limda
    band statistikasini (jami bajarilgan/bajarilmagan) ko'rsatadi.
    Xodimlar bir-biriga aralashmaydi — har biri o'z jadvaliga ega."""
    if output_path is None:
        output_path = f"data/hisobot_{role}_{start_date}_{end_date}.pdf"

    role_label = ROLE_LABELS.get(role, role)
    stats = db.get_period_item_stats(role, start_date, end_date)

    doc = SimpleDocTemplate(
        output_path, pagesize=landscape(A4),
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleUz", parent=styles["Title"], fontSize=16, spaceAfter=10,
    )
    name_style = ParagraphStyle(
        "NameUz", parent=styles["Heading2"], fontSize=13,
        spaceBefore=18, spaceAfter=6, textColor=colors.HexColor("#2E5C3E"),
    )

    story = [
        Paragraph(f"Davriy hisobot — {role_label}", title_style),
        Paragraph(f"{start_date} dan {end_date} gacha", styles["Normal"]),
        Spacer(1, 8),
    ]

    if not stats:
        story.append(Paragraph("Bu davr uchun ma'lumot topilmadi.", styles["Normal"]))
        doc.build(story)
        return output_path

    # Har xodim uchun ALOHIDA bo'lim va jadval — aralashtirilmaydi
    for uid, data in sorted(stats.items(), key=lambda kv: kv[1]["full_name"]):
        story.append(Paragraph(data["full_name"], name_style))

        table_data = [["№", "Band", "Bajarilgan", "Bajarilmagan"]]
        items = sorted(data["items"].values(),
                        key=lambda it: (it["item_number"]))
        for it in items:
            table_data.append([
                it["item_number"], it["text"],
                str(it["done"]), str(it["not_done"]),
            ])

        col_widths = [12 * mm, 140 * mm, 30 * mm, 35 * mm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E5C3E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F4F4F4")]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])

        # Bajarilmagan soni 0dan ko'p bo'lsa, qizil rangda belgilash
        for i, it in enumerate(items, start=1):
            if it["not_done"] > 0:
                style.add("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#B00020"))
                style.add("FONTNAME", (3, i), (3, i), "Helvetica-Bold")
            if it["done"] > 0:
                style.add("TEXTCOLOR", (2, i), (2, i), colors.HexColor("#1A7F37"))

        table.setStyle(style)
        story.append(table)

    doc.build(story)
    return output_path
