import os
import re
import tempfile

import fitz  # PyMuPDF
import pdfplumber

from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

# --- LAYOUT CONSTANTS ---

PAGE_W, PAGE_H = landscape(A4)  # 842 x 595
BORDER_MARGIN = 15
SIGNATURE_BBOX_FRACTIONS = (0.55, 0.72, 0.98, 0.95)


# --- SOURCE PDF EXTRACTION ---

def extract_signature_image(source_pdf_path, bbox_fractions=None, zoom=4):
    if bbox_fractions is None:
        bbox_fractions = SIGNATURE_BBOX_FRACTIONS

    doc = fitz.open(source_pdf_path)

    target_page = doc[0]
    top_rects = []
    bottom_rects = []

    for page in doc:
        t_rects = page.search_for("Digitally signed by")
        b_rects = page.search_for("Drawing and Disbursement Officer")
        if t_rects and b_rects:
            target_page = page
            top_rects = t_rects
            bottom_rects = b_rects
            break

    rect = target_page.rect

    if top_rects and bottom_rects:
        y0 = min([r.y0 for r in top_rects]) - 5
        y1 = max([r.y1 for r in bottom_rects]) + 5
        x0 = min([r.x0 for r in top_rects]) - 10
        x1 = x0 + 230

        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(rect.width, x1), min(rect.height, y1)
        clip = fitz.Rect(x0, y0, x1, y1)
    else:
        target_page = doc[-1]
        rect = target_page.rect
        l, t, r, b = bbox_fractions
        clip = fitz.Rect(rect.width * l, rect.height * t, rect.width * r, rect.height * b)

    mat = fitz.Matrix(zoom, zoom)
    pix = target_page.get_pixmap(matrix=mat, clip=clip)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    pix.save(tmp.name)
    doc.close()
    return tmp.name, (clip.width, clip.height)


def _find_value(text, label):
    pattern = re.escape(label) + r"\s*[:：]\s*(.+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip().splitlines()[0].strip()
    return ""


def extract_data_from_pdf(filepath):
    text = ""
    table_data = []

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text += page_text + "\n"

            tables = page.extract_tables()
            if tables:
                table_data.extend(tables[0])

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    header_lines = []
    for l in lines:
        if re.match(r"^(Name of Office|Head of Account)", l, re.IGNORECASE):
            break
        header_lines.append(l)
    header_lines += [""] * (4 - len(header_lines))

    data = {
        "header_1": header_lines[0],
        "header_2": header_lines[1],
        "header_3": header_lines[2],
        "header_4": header_lines[3],
        "dept": _find_value(text, "Name of Office/Dept/Ministry"),
        "head_of_account": _find_value(text, "Head of Account"),
        "grant_no": _find_value(text, "Grant No."),
        "ddo": _find_value(text, "DDO Code & Name"),
        "treasury": _find_value(text, "Treasury Code & Name"),
        "bill_no": _find_value(text, "Bill No"),
        "bill_date": _find_value(text, "Bill Date"),
        "remarks": _find_value(text, "Remarks"),
        "table_data": table_data,
        "notes": "",
        "_source_pdf": filepath,
    }

    notes_start = None
    for i, l in enumerate(lines):
        if l.strip().lower().startswith("note"):
            notes_start = i
            break

    if notes_start is not None:
        data["notes"] = "<br/>".join(lines[notes_start:])

    return data


# --- PDF GENERATION LOGIC ---

def draw_page_border(canvas, doc):
    """Draws only the physical border on every page."""
    canvas.saveState()
    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(1)
    canvas.rect(BORDER_MARGIN, BORDER_MARGIN, PAGE_W - 2 * BORDER_MARGIN, PAGE_H - 2 * BORDER_MARGIN)
    canvas.restoreState()


class AbsoluteFooter(Flowable):
    """A custom layout block that takes up 0 space but paints notes at the absolute bottom of whatever page it lands on."""

    def __init__(self, notes_html):
        Flowable.__init__(self)
        self.width = 0
        self.height = 0
        self.notes_html = notes_html

    def draw(self):
        if not self.notes_html:
            return

        canvas = self.canv
        abs_x, abs_y = canvas.absolutePosition(0, 0)

        styles = getSampleStyleSheet()
        note_style = ParagraphStyle(name='Notes', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=10)
        note_bold_style = ParagraphStyle(name='NotesBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=10)

        plain_notes = re.sub(r"<b>|</b>", "", self.notes_html)
        note_lines = [l.strip() for l in plain_notes.split("<br/>") if l.strip()]

        current_abs_y = BORDER_MARGIN + 60

        for line in note_lines:
            if line.lower().startswith("note"):
                p = Paragraph(f"<b>{line}</b>", note_bold_style)
            else:
                p = Paragraph(line, note_style)

            w, h = p.wrap(PAGE_W - 2 * BORDER_MARGIN - 20, PAGE_H)
            current_abs_y -= h

            rel_y = current_abs_y - abs_y
            rel_x = (BORDER_MARGIN + 10) - abs_x

            p.drawOn(canvas, rel_x, rel_y)


def create_landscape_bill(data, output_filename, custom_signature_path=None):
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=(PAGE_W, PAGE_H),
        rightMargin=30,
        leftMargin=30,
        topMargin=20,
        bottomMargin=85,
    )

    elements = []
    styles = getSampleStyleSheet()

    center_normal = ParagraphStyle(name='CenterNormal', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica', spaceAfter=1)
    normal_style = ParagraphStyle(name='NormalTighter', parent=styles['Normal'], spaceAfter=2)

    elements.append(Paragraph(f"<b>{data['header_1']}</b>", center_normal))
    elements.append(Paragraph(f"<b>{data['header_2']}</b>", center_normal))
    elements.append(Paragraph(data['header_3'], center_normal))
    elements.append(Paragraph(f"<b>{data['header_4']}</b>", center_normal))
    elements.append(Spacer(1, 3))

    meta_data = [
        ["Name of Office/Dept/Ministry", f": {data['dept']}"],
        ["Head of Account", f": {data['head_of_account']}"],
        ["Grant No.", f": {data['grant_no']}"],
        ["DDO Code & Name", f": {data['ddo']}"],
        ["Treasury Code & Name", f": {data['treasury']}"],
        ["Bill No", f": {data['bill_no']}"],
        ["Bill Date", f": {data['bill_date']}"],
        ["Remarks", f": {data['remarks']}"]
    ]

    meta_table = Table(meta_data, colWidths=[200, 582], hAlign='LEFT')
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTNAME', (1, 0), (1, 1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 3))

    elements.append(Paragraph("<b>Details of Payee</b>", normal_style))
    col_widths = [40, 222, 140, 130, 130, 120]

    clean_table = []
    table_styles = [
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]

    for row in data['table_data']:
        clean_row = [str(cell).replace('\n', ' ').strip() if cell else "" for cell in row]

        if not any(clean_row):
            continue

        row_str = "".join(clean_row).upper()
        if len(clean_table) > 0 and "S.NO" in row_str and "PAYEE" in row_str:
            continue

        if len(clean_row) > 6:
            clean_row = clean_row[:6]
        elif len(clean_row) < 6:
            clean_row += [""] * (6 - len(clean_row))

        clean_table.append(clean_row)

    for row_idx, row in enumerate(clean_table):
        row_str = " ".join(row).upper()
        if "TOTAL" in row_str:
            table_styles.append(('FONTNAME', (0, row_idx), (-1, row_idx), 'Helvetica-Bold'))
            table_styles.append(('SPAN', (0, row_idx), (3, row_idx)))
            table_styles.append(('ALIGN', (4, row_idx), (4, row_idx), 'RIGHT'))
        elif any(word in row_str for word in ["LAKH", "THOUSAND", "HUNDRED", "CRORE"]):
            table_styles.append(('SPAN', (0, row_idx), (-1, row_idx)))
            table_styles.append(('ALIGN', (0, row_idx), (-1, row_idx), 'CENTER'))
            table_styles.append(('FONTNAME', (0, row_idx), (-1, row_idx), 'Helvetica-Bold'))

    main_table = Table(clean_table, colWidths=col_widths, repeatRows=1)
    main_table.setStyle(TableStyle(table_styles))
    elements.append(main_table)

    # --- SIGNATURE BLOCK ---
    bottom_elements = [Spacer(1, 5)]

    sig_cell = ""
    sig_temp_img_path = None
    MAX_W, MAX_H = 260, 95

    if custom_signature_path and os.path.exists(custom_signature_path):
        try:
            img_reader = ImageReader(custom_signature_path)
            w, h = img_reader.getSize()
            scale = min(MAX_W / float(w), MAX_H / float(h), 1.0)
            sig_cell = Image(custom_signature_path, width=w * scale, height=h * scale)
        except Exception as e:
            sig_cell = Paragraph(f"[Custom image load failed: {e}]", normal_style)
    else:
        source_pdf = data.get('_source_pdf')
        if source_pdf and os.path.exists(source_pdf):
            try:
                img_path, (crop_w, crop_h) = extract_signature_image(source_pdf)
                if crop_w <= 1 or crop_h <= 1:
                    raise ValueError("Cropped signature region is empty.")
                sig_temp_img_path = img_path
                scale = min(MAX_W / crop_w, MAX_H / crop_h, 1.0)
                sig_cell = Image(img_path, width=crop_w * scale, height=crop_h * scale)
            except Exception as e:
                sig_cell = Paragraph(f"[Signature extraction failed: {e}]", normal_style)
        else:
            sig_cell = Paragraph("[Source PDF not available]", normal_style)

    sig_table = Table([
        ["", sig_cell]
    ], colWidths=[500, 282])

    sig_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('VALIGN', (1, 0), (1, -1), 'TOP'),
    ]))

    bottom_elements.append(sig_table)
    bottom_elements.append(AbsoluteFooter(data.get('notes', '')))

    elements.append(KeepTogether(bottom_elements))

    try:
        doc.build(elements, onFirstPage=draw_page_border, onLaterPages=draw_page_border)
    finally:
        if sig_temp_img_path and os.path.exists(sig_temp_img_path):
            try:
                os.remove(sig_temp_img_path)
            except OSError:
                pass
