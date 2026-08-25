from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Guida_Codifiche_RF_Oregon_Technoline_V6.3.0_Edizione_2.pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"
OUTPUT_DIR = ROOT / "output" / "pdf"
TMP_ADDENDUM = TMP_DIR / "rf_guide_v64_addendum.pdf"
OUTPUT = OUTPUT_DIR / "Guida_Codifiche_RF_Oregon_Technoline_V6.4.0_Edizione_3.pdf"

NAVY = colors.HexColor("#081A2F")
BLUE = colors.HexColor("#0D5C8C")
CYAN = colors.HexColor("#29B6D8")
GREEN = colors.HexColor("#15966A")
LIGHT = colors.HexColor("#EAF4F8")
MUTED = colors.HexColor("#526879")
RED = colors.HexColor("#A33A45")


def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor("#C8D7E1"))
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, 9 * mm, "ESP32 Oregon + Technoline Weather Gateway | Addendum SdFat")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"Pagina A{doc.page}")
    canvas.restoreState()


def p(text, style):
    return Paragraph(text, style)


def build_addendum():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
    ))
    styles.add(ParagraphStyle(
        name="CoverSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=17,
        textColor=BLUE,
        alignment=TA_CENTER,
        spaceAfter=7 * mm,
    ))
    styles.add(ParagraphStyle(
        name="H1x",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=NAVY,
        spaceBefore=2 * mm,
        spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        name="H2x",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=BLUE,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Bodyx",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.6,
        leading=13.2,
        textColor=colors.HexColor("#1A2833"),
        alignment=TA_LEFT,
        spaceAfter=2.5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Smallx",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.2,
        leading=11,
        textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        name="Cell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1A2833"),
    ))
    styles.add(ParagraphStyle(
        name="CellHead",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    ))

    doc = SimpleDocTemplate(
        str(TMP_ADDENDUM),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title="Guida RF Oregon Technoline V6.4.0 - Edizione 3",
        author="esp32-oregon-technoline-weather-gateway project",
    )

    story = [
        Spacer(1, 7 * mm),
        p("GUIDA TECNICA ALLE CODIFICHE RF", styles["CoverTitle"]),
        p("Oregon Scientific OSV2.1 / OSV3 e Technoline / La Crosse WS23xx", styles["CoverSub"]),
    ]

    banner = Table(
        [[p("EDIZIONE 3 - ADDENDUM MICROSD SDFAT", styles["CellHead"])],
         [p("Branch: codex/sdfat-write-status | 25 agosto 2026", styles["Cell"])]],
        colWidths=[174 * mm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.8, BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [banner, Spacer(1, 7 * mm)]

    story += [
        p("Scopo dell'Edizione 3", styles["H1x"]),
        p(
            "Questa edizione documenta la correzione microSD verificata sul gateway reale. "
            "La scheda rispondeva al comando SPI CMD0 ma il precedente percorso Arduino SD non completava "
            "l'inizializzazione e non poteva avviare la formattazione. Il firmware usa ora Greiman SdFat 2.3.1, "
            "mantiene il decoder RF separato e rende visibili mount, scritture ed errori nella barra superiore.",
            styles["Bodyx"],
        ),
        p("Risultato hardware", styles["H2x"]),
    ]

    status_data = [
        [p("Verifica", styles["CellHead"]), p("Esito", styles["CellHead"]), p("Confine della prova", styles["CellHead"])],
        [p("Mount microSD", styles["Cell"]), p("CONFERMATO", styles["Cell"]), p("T3 V1.6.1 fisica", styles["Cell"])],
        [p("Formato FAT", styles["Cell"]), p("CONFERMATO", styles["Cell"]), p("Azione Web FORMATTA SD", styles["Cell"])],
        [p("RF Oregon V2.1", styles["Cell"]), p("PASS", styles["Cell"]), p("6 validi, 6 corrotti respinti", styles["Cell"])],
        [p("Build T3 / T3-S3", styles["Cell"]), p("PASS / PASS", styles["Cell"]), p("PlatformIO locale", styles["Cell"])],
    ]
    status = Table(status_data, colWidths=[45 * mm, 38 * mm, 91 * mm], repeatRows=1)
    status.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#A9BEC9")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TEXTCOLOR", (1, 1), (1, -1), GREEN),
    ]))
    story += [status, Spacer(1, 5 * mm)]

    note = Table([[p(
        "Le pagine RF dell'Edizione 2 sono riprodotte integralmente come Parte II. Restano riferite alla baseline "
        "V6.3.0 perché la migrazione SdFat non cambia timing, framing, checksum, Manchester, MIC o conversioni "
        "meteorologiche.", styles["Bodyx"]) ]], colWidths=[174 * mm])
    note.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF6DD")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#D39C24")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [note, PageBreak()]

    story += [
        p("Addendum tecnico - microSD e indicatore scritture", styles["H1x"]),
        p("1. Inizializzazione e formato", styles["H2x"]),
        p(
            "La microSD usa un'istanza HSPI dedicata. Sul T3 V1.6.1 i segnali sono CS13, SCK14, MOSI15 e MISO2. "
            "SdFat prova 4 MHz; dopo un cleanup completo del bus esegue un solo fallback a 400 kHz. I byte "
            "sdErrorCode e sdErrorData vengono esposti via API e Web.", styles["Bodyx"]),
        p(
            "Se il trasporto scheda e inizializzato ma FAT e assente o non valida, FORMATTA SD avvia il formatter "
            "SdFat e rimonta la scheda. Se il trasporto non e inizializzato, il formato non parte: il firmware "
            "mantiene un errore diagnostico invece di simulare un successo.", styles["Bodyx"]),
        p("2. Separazione dal percorso RF", styles["H2x"]),
        p(
            "Un frame entra nel datalogger solo dopo la normale validazione Oregon o Technoline. Il decoder copia "
            "la riga in una coda RAM fissa; il servizio storage scrive batch limitati fuori dal percorso RF critico. "
            "Scheda assente, piena o guasta non deve fermare ricezione, MQTT, OLED o Web.", styles["Bodyx"]),
        p("3. Badge superiore", styles["H2x"]),
    ]

    badge_data = [
        [p("Badge", styles["CellHead"]), p("Significato", styles["CellHead"])],
        [p("SD OFF", styles["Cell"]), p("Datalogger disabilitato", styles["Cell"])],
        [p("SD PRONTA", styles["Cell"]), p("Scheda montata, logger disabilitato", styles["Cell"])],
        [p("SD ON", styles["Cell"]), p("Scheda montata e logger attivo", styles["Cell"])],
        [p("SD SCRIVE", styles["Cell"]), p("Il contatore delle righe scritte e aumentato dall'ultimo polling", styles["Cell"])],
        [p("SD KO / SD ERR", styles["Cell"]), p("Mount fallito / endpoint di stato non leggibile", styles["Cell"])],
    ]
    badges = Table(badge_data, colWidths=[42 * mm, 132 * mm], repeatRows=1)
    badges.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#A9BEC9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 1), (0, -1), LIGHT),
    ]))
    story += [badges, Spacer(1, 4 * mm)]

    build_data = [
        [p("Target", styles["CellHead"]), p("RAM", styles["CellHead"]), p("Applicazione / slot", styles["CellHead"]), p("Uso", styles["CellHead"])],
        [p("T3 V1.6.1", styles["Cell"]), p("100.592 / 327.680 B", styles["Cell"]), p("1.276.865 / 1.966.080 B", styles["Cell"]), p("64,9%", styles["Cell"])],
        [p("T3-S3", styles["Cell"]), p("99.552 / 327.680 B", styles["Cell"]), p("1.220.777 / 1.966.080 B", styles["Cell"]), p("62,1%", styles["Cell"])],
    ]
    builds = Table(build_data, colWidths=[34 * mm, 48 * mm, 68 * mm, 24 * mm], repeatRows=1)
    builds.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#A9BEC9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [p("4. Spazio firmware", styles["H2x"]), builds, Spacer(1, 3 * mm)]
    story += [p(
        "Entrambi i target usano min_spiffs.csv: il progetto non usa SPIFFS, conserva NVS e due slot OTA, e "
        "porta ogni slot applicativo a 1.966.080 byte. Le prove confermano mount e formato; scheda piena, read-only, "
        "deep sleep con coda pendente e concorrenza RF di lunga durata restano verifiche separate.", styles["Smallx"])]
    story += [
        p("5. Più trasmettitori UVN800", styles["H2x"]),
        p(
            "La Dashboard mantiene separati più UVN800 D874 usando codice sensore, canale e rolling ID. Il rolling "
            "ID compare su ogni riquadro UV, quindi due unità sullo stesso canale restano riconoscibili. Il registro "
            "live contiene fino a 10 trasmettitori Oregon complessivi, condivisi tra termo-igro, vento, pioggia e UV.",
            styles["Bodyx"]),
        p(
            "Per MQTT con più D874 usare oregon/sensor/D874/ch&lt;CHANNEL&gt;/id&lt;ROLLING&gt;/uv. I topic oregon/uv e "
            "oregon/uv/D874/index restano compatibili ma rappresentano l'ultimo valore ricevuto e non identificano "
            "due UVN800 dello stesso modello.", styles["Smallx"]),
    ]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def merge_pdf():
    addendum = PdfReader(str(TMP_ADDENDUM))
    baseline = PdfReader(str(SOURCE))
    if len(addendum.pages) != 2:
        raise RuntimeError(f"Expected 2 addendum pages, found {len(addendum.pages)}")
    if len(baseline.pages) != 17:
        raise RuntimeError(f"Expected 17 baseline pages, found {len(baseline.pages)}")

    writer = PdfWriter()
    for page in addendum.pages:
        writer.add_page(page)
    for page in baseline.pages:
        writer.add_page(page)
    writer.add_metadata({
        "/Title": "Guida codifiche RF Oregon Technoline V6.4.0 - Edizione 3",
        "/Author": "esp32-oregon-technoline-weather-gateway project",
        "/Subject": "Addendum SdFat hardware-validated plus RF V6.3 baseline",
        "/Keywords": "ESP32 Oregon Technoline SdFat microSD RF 433.92 MHz",
    })
    writer.add_outline_item("Parte I - Addendum SdFat V6.4", 0)
    writer.add_outline_item("Parte II - Baseline RF V6.3", 2)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)

    TMP_ADDENDUM.unlink(missing_ok=True)
    print(OUTPUT)


if __name__ == "__main__":
    if not SOURCE.exists():
        raise SystemExit(f"Source PDF not found: {SOURCE}")
    build_addendum()
    merge_pdf()
