"""
Tijorat Taklifi Moduli
Broker Excel yuboradi → bot PDF tayyorlaydi (UZ + RU)
5 ta shablon: ko'k (1), yashil-ADM (2), qizil-qora (3), klassik (4), yashil-ADM2 (5)
"""
import os, io, random, tempfile
from datetime import date

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

import database as db

# ── Shrift ──
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
if os.path.exists(FONT_DIR):
    try:
        pdfmetrics.registerFont(TTFont("DJ",  f"{FONT_DIR}/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DJB", f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
        pdfmetrics.registerFont(TTFont("DJI", f"{FONT_DIR}/DejaVuSans-Oblique.ttf"))
    except Exception:
        pass
    F, FB, FI = "DJ", "DJB", "DJI"
else:
    F, FB, FI = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

# ── Conversation holatlari ──
(TJ_FIRMA, TJ_EXCEL, TJ_SHABLON, TJ_TIL, TJ_FOIZ,
 FIRMA_NOMI, FIRMA_MANZIL, FIRMA_STIR, FIRMA_HISOB,
 FIRMA_BANK, FIRMA_MFO, FIRMA_TEL, FIRMA_DIR) = range(50, 63)


def fmt(n):
    try:
        return f"{int(round(float(n))):,}".replace(",", " ")
    except Exception:
        return str(n)


def apply_foiz(rows, foiz):
    if not foiz:
        return rows
    return [{**r, "narxi": r["narxi"] * (1 + foiz / 100)} for r in rows]


# ══════════════════════════════════════════════════════════
# EXCEL PARSE
# ══════════════════════════════════════════════════════════

def parse_excel(file_bytes: bytes) -> list:
    """
    Excel fayldan tovar qatorlarini o'qiydi.
    Ustunlar: nomi, olchov, miqdor, narxi (istalgan tartibda, bot topadi)
    """
    df = pd.read_excel(io.BytesIO(file_bytes), header=None)

    # Sarlavha qatorini topamiz
    header_row = None
    for i, row in df.iterrows():
        vals = [str(v).lower().strip() for v in row.values]
        hits = sum(1 for v in vals if any(
            kw in v for kw in ["nomi", "naim", "tovar", "mahsulot",
                                "olchov", "birlik", "ed.", "ед", "unit",
                                "miqdor", "kol", "кол", "qty",
                                "narx", "sum", "цен", "price"]
        ))
        if hits >= 2:
            header_row = i
            break

    if header_row is None:
        header_row = 0

    df.columns = df.iloc[header_row].values
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    # Ustun nomlarini lotin/kirill dan standartlashtirish
    col_map = {}
    for col in df.columns:
        s = str(col).lower().strip()
        if any(k in s for k in ["nomi", "naim", "tovar", "mahsulot", "product", "наим"]):
            col_map["nomi"] = col
        elif any(k in s for k in ["olchov", "birlik", "ed.", "ед", "unit", "мер"]):
            col_map["olchov"] = col
        elif any(k in s for k in ["miqdor", "kol", "кол", "qty", "количест"]):
            col_map["miqdor"] = col
        elif any(k in s for k in ["narx", "цен", "price", "сумм", "summa"]):
            if "narxi" not in col_map and "jami" not in col_map:
                col_map["narxi"] = col
        elif any(k in s for k in ["jami", "итог", "total", "итог"]):
            col_map["jami"] = col

    rows = []
    for _, row in df.iterrows():
        nomi = str(row.get(col_map.get("nomi",""), "")).strip()
        if not nomi or nomi.lower() in ("nan", "", "none", "итого", "jami", "total"):
            continue
        try:
            miqdor = float(str(row.get(col_map.get("miqdor",""), 1)).replace(" ","").replace(",","."))
        except Exception:
            miqdor = 1
        try:
            narxi = float(str(row.get(col_map.get("narxi",""), 0)).replace(" ","").replace(",","."))
        except Exception:
            narxi = 0
        olchov = str(row.get(col_map.get("olchov",""), "dona")).strip()
        if olchov.lower() in ("nan", "none", ""):
            olchov = "dona"
        if narxi > 0:
            rows.append({"nomi": nomi, "olchov": olchov, "miqdor": miqdor, "narxi": narxi})

    return rows


# ══════════════════════════════════════════════════════════
# PDF GENERATORLAR — 5 SHABLON
# ══════════════════════════════════════════════════════════

def _doc(out, margin=15):
    return SimpleDocTemplate(out, pagesize=A4,
        topMargin=margin*mm, bottomMargin=12*mm,
        leftMargin=margin*mm, rightMargin=margin*mm)


def _tbl(data, cw, style_extra=None):
    t = Table(data, colWidths=cw, repeatRows=1)
    base = [
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]
    if style_extra:
        base += style_extra
    t.setStyle(TableStyle(base))
    return t


def _rows_to_table(rows, foiz, C1, C2, CLT, lang):
    rows = apply_foiz(rows, foiz)
    if lang == "uz":
        cols = ["No", "Tovar nomi", "O'lchov", "Miqdor", "Narxi", "Jami"]
        itogo = "JAMI:"
    else:
        cols = ["No", "Nomi (Naim.)", "Birlik", "Miqdor", "Narxi", "Jami"]
        itogo = "JAMI:"

    cw = [10*mm, 72*mm, 14*mm, 14*mm, 24*mm, 24*mm]
    th  = ParagraphStyle("th", fontName=FB, fontSize=8.5, textColor=colors.white, alignment=TA_CENTER, leading=11)
    td  = ParagraphStyle("td", fontName=F,  fontSize=8.5, leading=11)
    tdc = ParagraphStyle("tc", fontName=F,  fontSize=8.5, alignment=TA_CENTER, leading=11)
    tdr = ParagraphStyle("tr", fontName=F,  fontSize=8.5, alignment=TA_RIGHT,  leading=11)
    tdb = ParagraphStyle("tb", fontName=FB, fontSize=9.5, alignment=TA_RIGHT,  leading=11, textColor=C1)

    data = [[Paragraph(c, th) for c in cols]]
    total = 0
    for i, r in enumerate(rows):
        j = r["miqdor"] * r["narxi"]
        total += j
        data.append([Paragraph(str(i+1), tdc), Paragraph(r["nomi"], td),
                     Paragraph(r.get("olchov","dona"), tdc),
                     Paragraph(fmt(r["miqdor"]), tdc),
                     Paragraph(fmt(r["narxi"]), tdr),
                     Paragraph(fmt(j), tdr)])

    tl = ParagraphStyle("tl", fontName=FB, fontSize=10, alignment=TA_RIGHT, textColor=C1)
    data.append(["","","","", Paragraph(itogo, tl), Paragraph(fmt(total), tdb)])

    n = len(data)
    tbl = Table(data, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), C2),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),4),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
        *[("BACKGROUND",(0,i),(-1,i),CLT) for i in range(2,n-1,2)],
        ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#E8F0FF")),
        ("GRID",(0,0),(-1,-2),0.4,colors.HexColor("#BBBBCC")),
        ("LINEABOVE",(0,-1),(-1,-1),1.5,C1),
        ("LINEBELOW",(0,-1),(-1,-1),1.5,C1),
        ("BOX",(0,0),(-1,-2),1,C2),
        ("SPAN",(0,-1),(3,-1)),
    ]))
    return tbl


# --- Shablon 1: Ko'k gradient ---
def gen_1(firma, rows, raqam, sana, lang, foiz, out):
    C1=colors.HexColor("#1A3A6B"); C2=colors.HexColor("#2E6DB4"); CLT=colors.HexColor("#E8F0FB")
    fn = f" (+{foiz}%)" if foiz else ""
    title = "TIJORAT TAKLIFI" if lang=="uz" else "TIJORAT TAKLIFI (RU)"
    doc = _doc(out)
    story = []
    hf = ParagraphStyle("hf",fontName=FB,fontSize=18,textColor=colors.white,leading=22)
    hd = ParagraphStyle("hd",fontName=F, fontSize=8, textColor=colors.white,leading=12)
    det = "<br/>".join([f"STIR: {firma.get('stir','')}   MFO: {firma.get('mfo','')}",
                        f"H/r: {firma.get('hisob','')}",
                        f"Bank: {firma.get('bank','')}",
                        f"Manzil: {firma.get('manzil','')}",
                        f"Tel: {firma.get('telefon','')}"])
    ht = Table([[Paragraph(f"«{firma['nomi']}»",hf), Paragraph(det,hd)]],colWidths=[75*mm,105*mm])
    ht.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C1),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(0,-1),12),("LEFTPADDING",(1,0),(1,-1),8)]))
    story += [ht, Spacer(1,5*mm)]
    story.append(Paragraph(f"No{raqam}{fn}   {sana}",
        ParagraphStyle("ns",fontName=FB,fontSize=10,textColor=C1)))
    story.append(Spacer(1,3*mm))
    story.append(Paragraph(title,ParagraphStyle("tt",fontName=FB,fontSize=14,alignment=TA_CENTER,textColor=C1,spaceAfter=3*mm)))
    story.append(Paragraph(f"«{firma['nomi']}» sizga ushbu tijorat taklifini taqdim etadi.",
        ParagraphStyle("in",fontName=F,fontSize=9.5,alignment=TA_JUSTIFY,leading=14,spaceAfter=4*mm)))
    story.append(_rows_to_table(rows,foiz,C1,C2,CLT,lang))
    story.append(Spacer(1,6*mm))
    story.append(Table([[Paragraph("Hurmat bilan,",ParagraphStyle("s",fontName=F,fontSize=9.5)),""],
        [Paragraph("Direktor:",ParagraphStyle("s2",fontName=F,fontSize=9.5)),
         Paragraph(firma.get("direktor",""),ParagraphStyle("sb",fontName=FB,fontSize=9.5))]],
        colWidths=[45*mm,100*mm]))
    doc.build(story); return out


# --- Shablon 2: Qizil-qora ---
def gen_2(firma, rows, raqam, sana, lang, foiz, out):
    C1=colors.HexColor("#C0392B"); C2=colors.HexColor("#1A1A1A"); CLT=colors.HexColor("#FDECEA")
    fn = f" (+{foiz}%)" if foiz else ""
    title = "TIJORAT TAKLIFI" if lang=="uz" else "TIJORAT TAKLIFI"
    doc = _doc(out)
    story = []
    hf = ParagraphStyle("hf2",fontName=FB,fontSize=18,textColor=colors.white,leading=22)
    hd = ParagraphStyle("hd2",fontName=F, fontSize=8, textColor=colors.HexColor("#CCCCCC"),leading=12)
    det = "<br/>".join([f"STIR: {firma.get('stir','')}   MFO: {firma.get('mfo','')}",
                        f"H/r: {firma.get('hisob','')}",
                        f"Bank: {firma.get('bank','')}",
                        f"Tel: {firma.get('telefon','')}"])
    ht = Table([[Paragraph(f"«{firma['nomi']}»",hf), Paragraph(det,hd)]],colWidths=[80*mm,100*mm])
    ht.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C2),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(0,-1),12),("LEFTPADDING",(1,0),(1,-1),8)]))
    story.append(ht)
    story.append(Table([[""]], colWidths=[180*mm],
        style=[("BACKGROUND",(0,0),(-1,-1),C1),("ROWHEIGHT",(0,0),(-1,-1),4)]))
    story.append(Spacer(1,4*mm))
    story.append(Paragraph(title,ParagraphStyle("tt2",fontName=FB,fontSize=15,alignment=TA_CENTER,textColor=C2,spaceAfter=2*mm)))
    story.append(Paragraph(f"No{raqam}{fn}   Sana: {sana}",
        ParagraphStyle("sn2",fontName=F,fontSize=9.5,textColor=C1,spaceAfter=4*mm)))
    # Qizil CLT bilan jadval
    CLT2=colors.HexColor("#FDECEA")
    tbl = _rows_to_table(rows, foiz, C1, C2, CLT2, lang)
    story.append(tbl)
    story.append(Table([[""]], colWidths=[180*mm],
        style=[("BACKGROUND",(0,0),(-1,-1),C1),("ROWHEIGHT",(0,0),(-1,-1),2)]))
    story.append(Spacer(1,6*mm))
    story.append(Table([[Paragraph("Hurmat bilan,",ParagraphStyle("s",fontName=F,fontSize=9.5)),""],
        [Paragraph("Direktor:",ParagraphStyle("s2",fontName=F,fontSize=9.5)),
         Paragraph(firma.get("direktor",""),ParagraphStyle("sb2",fontName=FB,fontSize=9.5,textColor=C1))]],
        colWidths=[45*mm,100*mm]))
    doc.build(story); return out


# --- Shablon 3: Klassik ko'k ramka ---
def gen_3(firma, rows, raqam, sana, lang, foiz, out):
    BLUE=colors.HexColor("#1A3080"); RED=colors.HexColor("#C0392B")
    fn = f" (+{foiz}%)" if foiz else ""
    doc = _doc(out, margin=12)
    story = []
    lbl = ParagraphStyle("lbl3",fontName=FB,fontSize=9,textColor=RED,leading=13)
    val = ParagraphStyle("val3",fontName=F, fontSize=9,leading=13)
    rek = [[Paragraph("Rahbar F.I.Sh.:", lbl), Paragraph(firma.get("direktor",""), val)],
           [Paragraph("Manzil:",          lbl), Paragraph(firma.get("manzil",""),   val)],
           [Paragraph("STIR:",            lbl), Paragraph(firma.get("stir",""),     val)],
           [Paragraph("H/r:",             lbl), Paragraph(firma.get("hisob",""),    val)],
           [Paragraph("Bank:",            lbl), Paragraph(firma.get("bank",""),     val)],
           [Paragraph(f"MFO-{firma.get('mfo','')}", lbl), Paragraph("", val)]]

    def make_inner():
        inner = []
        inner.append(Paragraph("TIJORAT TAKLIFI",
            ParagraphStyle("tc3",fontName=FB,fontSize=18,alignment=TA_CENTER,spaceAfter=2*mm,spaceBefore=2*mm)))
        inner.append(Paragraph(f"«{firma['nomi']}»",
            ParagraphStyle("fc3",fontName=FB,fontSize=11,alignment=TA_CENTER,spaceAfter=3*mm)))
        inner.append(Paragraph(f"No{raqam}{fn}   {sana}",
            ParagraphStyle("nc3",fontName=F,fontSize=8.5,textColor=BLUE,alignment=TA_RIGHT,spaceAfter=1*mm)))
        rt = Table(rek, colWidths=[38*mm,135*mm])
        rt.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
            ("LEFTPADDING",(0,0),(-1,-1),2),
            ("BOX",(0,0),(-1,-1),1,BLUE),
            ("LINEBELOW",(0,0),(-1,-2),0.4,colors.HexColor("#AAAAAA")),
            ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F8F8FF"))]))
        inner.append(rt)
        inner.append(Spacer(1,5*mm))
        # Jadval
        rows_adj = apply_foiz(rows, foiz)
        cw=[11*mm,68*mm,18*mm,22*mm,24*mm,24*mm]
        th=ParagraphStyle("th3",fontName=FB,fontSize=9,alignment=TA_CENTER,leading=12)
        td=ParagraphStyle("td3",fontName=F, fontSize=9,alignment=TA_LEFT,  leading=12)
        tdc=ParagraphStyle("tdc3",fontName=F,fontSize=9,alignment=TA_CENTER,leading=12)
        tdr=ParagraphStyle("tdr3",fontName=F,fontSize=9,alignment=TA_RIGHT, leading=12)
        cols3=["No","Tovar nomi","O'lchov","Miqdor","Narxi","Jami"]
        data=[[Paragraph(c,th) for c in cols3]]
        total=0
        for i,r in enumerate(rows_adj):
            j=r["miqdor"]*r["narxi"]; total+=j
            data.append([Paragraph(str(i+1),tdc),Paragraph(r["nomi"],td),
                         Paragraph(r.get("olchov","dona"),tdc),
                         Paragraph(fmt(r["miqdor"]),tdc),
                         Paragraph(fmt(r["narxi"]),tdr),
                         Paragraph(fmt(j),tdr)])
        data.append(["","","","",
            Paragraph("JAMI:",ParagraphStyle("itl3",fontName=FB,fontSize=10,alignment=TA_CENTER)),
            Paragraph(fmt(total),ParagraphStyle("itv3",fontName=FB,fontSize=10,alignment=TA_RIGHT))])
        tbl=Table(data,colWidths=cw,repeatRows=1)
        tbl.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
            ("BOX",(0,0),(-1,-1),1.5,BLUE),("INNERGRID",(0,0),(-1,-1),0.5,BLUE),
            ("FONTNAME",(0,0),(-1,0),FB),("LINEBELOW",(0,0),(-1,0),1.5,BLUE),
            ("SPAN",(0,-1),(3,-1)),("LINEABOVE",(0,-1),(-1,-1),1.5,BLUE)]))
        inner.append(tbl)
        inner.append(Spacer(1,8*mm))
        inner.append(Table([[Paragraph("Rahbar:",ParagraphStyle("ss3",fontName=F,fontSize=10)),
            Paragraph(firma.get("direktor_familiya",firma.get("direktor","").split()[-1] if firma.get("direktor") else ""),
                      ParagraphStyle("sb3",fontName=FB,fontSize=10,alignment=TA_RIGHT))]],
            colWidths=[40*mm,133*mm]))
        return inner

    outer=Table([[make_inner()]],colWidths=[183*mm])
    outer.setStyle(TableStyle([("BOX",(0,0),(-1,-1),2.5,BLUE),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]))
    story.append(outer)
    doc.build(story); return out


# --- Shablon 4: Yashil ADM (kompaniya haqida + afzalliklar) ---
def gen_4(firma, rows, raqam, sana, lang, foiz, out):
    C1=colors.HexColor("#1A5C2A"); C2=colors.HexColor("#2E8B3E"); CLT=colors.HexColor("#EAF4EC")
    fn = f" (+{foiz}%)" if foiz else ""
    doc = _doc(out)
    story = []

    # Sarlavha
    ht = Table([[Paragraph("TIJORAT TAKLIFI",
        ParagraphStyle("ht4",fontName=FB,fontSize=16,textColor=colors.white,alignment=TA_CENTER,leading=20))]],
        colWidths=[180*mm])
    ht.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C1),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)]))
    story.append(ht)
    story.append(Table([[""]], colWidths=[180*mm],
        style=[("BACKGROUND",(0,0),(-1,-1),C2),("ROWHEIGHT",(0,0),(-1,-1),3)]))
    story.append(Spacer(1,5*mm))

    # Kimdan/Kimga
    lbl4=ParagraphStyle("lbl4",fontName=FB,fontSize=10,textColor=C1)
    val4=ParagraphStyle("val4",fontName=FB,fontSize=10)
    story.append(Table([
        [Paragraph("Kimdan:", lbl4), Paragraph(firma["nomi"], val4)],
        [Paragraph("Sana:",   lbl4), Paragraph(f"{sana}   No{raqam}{fn}",
            ParagraphStyle("ds4",fontName=F,fontSize=10))],
    ], colWidths=[30*mm,150*mm]))
    story.append(HRFlowable(width="100%",thickness=1.5,color=C2,spaceAfter=5*mm,spaceBefore=4*mm))

    # Rekvizitlar
    rek_line=" | ".join(filter(None,[
        f"STIR: {firma.get('stir','')}",f"H/r: {firma.get('hisob','')}",
        f"Bank: {firma.get('bank','')}",f"MFO: {firma.get('mfo','')}",
        f"Tel: {firma.get('telefon','')}",f"Manzil: {firma.get('manzil','')}",
    ]))

    def sec_t(text):
        t=Table([[Paragraph(text,ParagraphStyle("st4",fontName=FB,fontSize=11,textColor=C1))]],colWidths=[178*mm])
        t.setStyle(TableStyle([("LINEBEFORE",(0,0),(0,-1),4,C2),("LEFTPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F2FAF3"))]))
        return t

    body_s=ParagraphStyle("bs4",fontName=F,fontSize=9.5,leading=14,alignment=TA_JUSTIFY,spaceAfter=4*mm)
    rek_s =ParagraphStyle("rs4",fontName=F,fontSize=8.5,textColor=colors.HexColor("#555555"),leading=13,spaceAfter=4*mm)

    story.append(sec_t("Kompaniya haqida"))
    story.append(Paragraph(
        f"«{firma['nomi']}» — zamonaviy savdo kompaniyasi bo'lib, innovatsion yechimlar va "
        f"sifatli xizmatlarni taklif etadi. Asosiy maqsadimiz — mijoz ehtiyojini professional "
        f"yondashuv va ishonchli hamkorlik orqali to'liq qondirish.", body_s))
    story.append(Paragraph(rek_line, rek_s))

    story.append(sec_t("Taklif mohiyati"))
    story.append(Paragraph("Sizning korxonangizga quyidagi mahsulotlarni taqdim etishni taklif qilamiz:", body_s))

    # Afzalliklar
    story.append(sec_t("Bizning afzalliklarimiz"))
    adv_s=ParagraphStyle("adv4",fontName=F,fontSize=9.5,leading=15,textColor=C1)
    adv=[["[+] Moslashuvchan narx siyosati","[+] Shaxsiy menejer"],
         ["[+] Kafolatlangan sifat","[+] Bepul konsultatsiya va texnik qo'llab-quvvatlash"],
         ["[+] Buyurtmalarni tez bajarish",""]]
    adv_tbl=Table([[Paragraph(a[0],adv_s),Paragraph(a[1],adv_s)] for a in adv],colWidths=[90*mm,90*mm])
    adv_tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#EAF4EC")),
        ("BOX",(0,0),(-1,-1),1,C2),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),8)]))
    story.append(adv_tbl)
    story.append(Spacer(1,5*mm))

    story.append(_rows_to_table(rows,foiz,C1,C2,CLT,lang))
    story.append(Spacer(1,5*mm))
    story.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#AAAAAA"),spaceAfter=4*mm))
    story.append(Table([
        [Paragraph("Hurmat bilan,",ParagraphStyle("ss4",fontName=F,fontSize=9.5,textColor=colors.HexColor("#555"))),""],
        [Paragraph("Direktor:",ParagraphStyle("sd4",fontName=F,fontSize=9.5,textColor=colors.HexColor("#555"))),
         Paragraph(firma.get("direktor",""),ParagraphStyle("sb4",fontName=FB,fontSize=9.5,textColor=C1))],
    ], colWidths=[40*mm,140*mm]))
    doc.build(story); return out


GENERATORS = {1: gen_1, 2: gen_2, 3: gen_3, 4: gen_4}
SHABLON_LABELS = {
    1: "Ko'k gradient (1)",
    2: "Qizil-qora (2)",
    3: "Klassik ko'k ramka (3)",
    4: "Yashil ADM (4)",
}


def generate_pdfs(firma, rows, raqam, sana, shablon_no, foiz=None):
    """UZ va RU uchun PDF fayllar yaratadi. [(path_uz, path_ru)] qaytaradi."""
    gen = GENERATORS.get(shablon_no, gen_1)
    results = []
    for lang in ["uz", "ru"]:
        fn = f"_{foiz}pct" if foiz else ""
        out = tempfile.mktemp(suffix=f"_t{shablon_no}_{lang}{fn}.pdf")
        gen(firma, rows, raqam, sana, lang, foiz, out)
        results.append((out, lang))
    return results


# ══════════════════════════════════════════════════════════
# TELEGRAM BOT HANDLERS
# ══════════════════════════════════════════════════════════

def require_broker(func):
    async def wrapper(update, context):
        user = db.get_user(update.effective_user.id)
        if not user or user["role"] not in ("broker", "boshqaruvchi") or not user["approved"]:
            msg = update.message or update.callback_query.message
            await msg.reply_text("Bu buyruq faqat broker uchun.")
            return ConversationHandler.END
        return await func(update, context, user)
    return wrapper


# ── /tijorat ──
@require_broker
async def cmd_tijorat(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    firmalar = db.get_all_firmalar()
    if not firmalar:
        await update.message.reply_text(
            "Firmalar bazasi bo'sh.\n/firma_qosh orqali firma qo'shing."
        )
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(f["nomi"], callback_data=f"tj_firma:{f['id']}")]
          for f in firmalar]
    kb.append([InlineKeyboardButton("➕ Yangi firma qo'shish", callback_data="tj_firma:new")])
    await update.message.reply_text(
        "Qaysi firma nomidan tijorat taklifi tayyorlansin?",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return TJ_FIRMA


async def tijorat_firma_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    if val == "new":
        await query.edit_message_text("Firma nomini yozing:")
        return FIRMA_NOMI

    firma = db.get_firma(int(val))
    context.user_data["tj_firma"] = firma
    await query.edit_message_text(
        f"Firma: <b>{firma['nomi']}</b>\n\n"
        "Endi Excel fayl yuboring (tovar nomi, o'lchov, miqdor, narxi ustunlari bilan):",
        parse_mode="HTML"
    )
    return TJ_EXCEL


async def tijorat_excel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith((".xlsx", ".xls")):
        await update.message.reply_text("Iltimos, Excel fayl (.xlsx) yuboring.")
        return TJ_EXCEL

    file = await context.bot.get_file(doc.file_id)
    file_bytes = bytes(await file.download_as_bytearray())

    try:
        rows = parse_excel(file_bytes)
    except Exception as e:
        await update.message.reply_text(f"Excel o'qishda xato: {e}\nQaytadan yuboring.")
        return TJ_EXCEL

    if not rows:
        await update.message.reply_text("Excel'da tovar topilmadi. Ustunlar: nomi, olchov, miqdor, narxi.")
        return TJ_EXCEL

    context.user_data["tj_rows"] = rows
    context.user_data["tj_raqam"] = str(random.randint(10, 99))
    context.user_data["tj_sana"] = date.today().strftime("%d.%m.%Y")

    # Jadval preview
    total = sum(r["miqdor"]*r["narxi"] for r in rows)
    preview = f"✅ {len(rows)} ta tovar yuklandi. Jami: {fmt(total)} so'm\n\n"
    preview += "\n".join(f"{i+1}. {r['nomi'][:35]} — {fmt(r['narxi'])} x {fmt(r['miqdor'])}"
                          for i, r in enumerate(rows[:5]))
    if len(rows) > 5:
        preview += f"\n... va yana {len(rows)-5} ta"

    kb = [[InlineKeyboardButton(v, callback_data=f"tj_sh:{k}")]
          for k, v in SHABLON_LABELS.items()]
    await update.message.reply_text(
        preview + "\n\nQaysi shablon tanlaysiz?",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return TJ_SHABLON


async def tijorat_shablon_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shablon_no = int(query.data.split(":")[1])
    context.user_data["tj_shablon"] = shablon_no
    await query.edit_message_text(
        f"Shablon: {SHABLON_LABELS[shablon_no]}\n\nTil tanlang:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("O'zbek (UZ)", callback_data="tj_til:uz"),
            InlineKeyboardButton("Rus (RU)", callback_data="tj_til:ru"),
            InlineKeyboardButton("Ikkisi ham (UZ+RU)", callback_data="tj_til:both"),
        ]])
    )
    return TJ_TIL


async def tijorat_til_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    til = query.data.split(":")[1]
    context.user_data["tj_til"] = til
    await query.edit_message_text("PDF tayyorlanmoqda... ⏳")
    await _send_pdfs(query.message, context, foiz=None)
    return TJ_FOIZ


async def _send_pdfs(message, context, foiz=None):
    firma   = context.user_data["tj_firma"]
    rows    = context.user_data["tj_rows"]
    raqam   = context.user_data["tj_raqam"]
    sana    = context.user_data["tj_sana"]
    shablon = context.user_data["tj_shablon"]
    til     = context.user_data["tj_til"]

    gen = GENERATORS.get(shablon, gen_1)
    langs = ["uz", "ru"] if til == "both" else [til]
    fn = f"_{foiz}pct" if foiz else ""

    for lang in langs:
        out = tempfile.mktemp(suffix=f".pdf")
        gen(firma, rows, raqam, sana, lang, foiz, out)
        fname = f"tijorat_{firma['nomi'][:20]}_{lang}{fn}.pdf"
        caption = f"{'Tijorat taklifi' if lang=='uz' else 'Tijorat taklifi (RU)'}"
        if foiz:
            caption += f" +{foiz}%"
        with open(out, "rb") as f:
            await message.reply_document(document=f, filename=fname, caption=caption)
        os.unlink(out)

    # Foiz variantlari tugmalari
    if not foiz:
        await message.reply_text(
            "Boshqa firmadan ham qilasizmi? Narxni qancha oshirsin?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("+3%",  callback_data="tj_foiz:3"),
                InlineKeyboardButton("+5%",  callback_data="tj_foiz:5"),
                InlineKeyboardButton("+7%",  callback_data="tj_foiz:7"),
                InlineKeyboardButton("+10%", callback_data="tj_foiz:10"),
                InlineKeyboardButton("Tugatish", callback_data="tj_foiz:done"),
            ]])
        )


async def tijorat_foiz_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":")[1]
    if val == "done":
        await query.edit_message_text("Tijorat taklifi yakunlandi. ✅")
        context.user_data.pop("tj_firma", None)
        context.user_data.pop("tj_rows", None)
        return ConversationHandler.END

    foiz = int(val)
    await query.edit_message_text(f"+{foiz}% bilan tayyorlanmoqda... ⏳")
    await _send_pdfs(query.message, context, foiz=foiz)
    return TJ_FOIZ


# ── FIRMA QO'SHISH ──
@require_broker
async def cmd_firma_qosh(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    await update.message.reply_text("Firma nomini yozing:")
    return FIRMA_NOMI


async def firma_nomi(update, context):
    context.user_data["new_firma"] = {"nomi": update.message.text.strip()}
    await update.message.reply_text("Yuridik manzil:")
    return FIRMA_MANZIL

async def firma_manzil(update, context):
    context.user_data["new_firma"]["manzil"] = update.message.text.strip()
    await update.message.reply_text("STIR:")
    return FIRMA_STIR

async def firma_stir(update, context):
    context.user_data["new_firma"]["stir"] = update.message.text.strip()
    await update.message.reply_text("Hisob raqam (H/r):")
    return FIRMA_HISOB

async def firma_hisob(update, context):
    context.user_data["new_firma"]["hisob"] = update.message.text.strip()
    await update.message.reply_text("Bank nomi:")
    return FIRMA_BANK

async def firma_bank(update, context):
    context.user_data["new_firma"]["bank"] = update.message.text.strip()
    await update.message.reply_text("MFO:")
    return FIRMA_MFO

async def firma_mfo(update, context):
    context.user_data["new_firma"]["mfo"] = update.message.text.strip()
    await update.message.reply_text("Telefon:")
    return FIRMA_TEL

async def firma_tel(update, context):
    context.user_data["new_firma"]["telefon"] = update.message.text.strip()
    await update.message.reply_text(
        "Direktor to'liq F.I.Sh. (masalan: Islomov Rizo Muhammadovich):"
    )
    return FIRMA_DIR

async def firma_dir(update, context):
    d = context.user_data["new_firma"]
    d["direktor"] = update.message.text.strip()
    # Familiya — oxirgi so'z yoki birinchi so'z harfi
    parts = d["direktor"].split()
    d["direktor_familiya"] = parts[0][0] + "." + parts[-1] if len(parts) >= 2 else d["direktor"]

    db.add_firma(**{k: d.get(k,"") for k in
        ["nomi","manzil","stir","hisob","bank","mfo","telefon","direktor","direktor_familiya"]})

    await update.message.reply_text(
        f"✅ Firma qo'shildi:\n<b>{d['nomi']}</b>", parse_mode="HTML"
    )
    context.user_data.pop("new_firma", None)
    return ConversationHandler.END


# ── FIRMALAR RO'YXATI ──
@require_broker
async def cmd_firmalar(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    firmalar = db.get_all_firmalar()
    if not firmalar:
        await update.message.reply_text("Firmalar bazasi bo'sh. /firma_qosh orqali qo'shing.")
        return

    kb = [[InlineKeyboardButton(f"❌ {f['nomi']}", callback_data=f"del_firma:{f['id']}")]
          for f in firmalar]
    text = "📋 <b>Firmalar ro'yxati:</b>\n\n" + "\n".join(
        f"{i+1}. {f['nomi']}" for i, f in enumerate(firmalar)
    )
    await update.message.reply_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb))


async def delete_firma_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    firma_id = int(query.data.split(":")[1])
    firma = db.get_firma(firma_id)
    db.delete_firma(firma_id)
    await query.edit_message_text(f"✅ «{firma['nomi']}» o'chirildi.")


# ══════════════════════════════════════════════════════════
# HANDLERLARNI REGISTRATSIYA QILISH (main() da chaqiriladi)
# ══════════════════════════════════════════════════════════

def register_handlers(app):
    tijorat_conv = ConversationHandler(
        entry_points=[CommandHandler("tijorat", cmd_tijorat)],
        states={
            TJ_FIRMA:   [CallbackQueryHandler(tijorat_firma_chosen,  pattern="^tj_firma:")],
            TJ_EXCEL:   [MessageHandler(filters.Document.ALL, tijorat_excel_received)],
            TJ_SHABLON: [CallbackQueryHandler(tijorat_shablon_chosen, pattern="^tj_sh:")],
            TJ_TIL:     [CallbackQueryHandler(tijorat_til_chosen,     pattern="^tj_til:")],
            TJ_FOIZ:    [CallbackQueryHandler(tijorat_foiz_chosen,    pattern="^tj_foiz:")],
            # Firma qo'shish (inline dan)
            FIRMA_NOMI:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_nomi)],
            FIRMA_MANZIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_manzil)],
            FIRMA_STIR:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_stir)],
            FIRMA_HISOB:  [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_hisob)],
            FIRMA_BANK:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_bank)],
            FIRMA_MFO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_mfo)],
            FIRMA_TEL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_tel)],
            FIRMA_DIR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_dir)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    firma_qosh_conv = ConversationHandler(
        entry_points=[CommandHandler("firma_qosh", cmd_firma_qosh)],
        states={
            FIRMA_NOMI:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_nomi)],
            FIRMA_MANZIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_manzil)],
            FIRMA_STIR:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_stir)],
            FIRMA_HISOB:  [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_hisob)],
            FIRMA_BANK:   [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_bank)],
            FIRMA_MFO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_mfo)],
            FIRMA_TEL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_tel)],
            FIRMA_DIR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, firma_dir)],
        },
        fallbacks=[],
    )

    app.add_handler(tijorat_conv)
    app.add_handler(firma_qosh_conv)
    app.add_handler(CommandHandler("firmalar", cmd_firmalar))
    app.add_handler(CallbackQueryHandler(delete_firma_btn, pattern="^del_firma:"))
