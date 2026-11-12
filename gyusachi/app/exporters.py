"""Xuất báo cáo ra Excel (.xlsx) và PDF (CHU1.5.2).

File này không phụ thuộc Flask: nhận một "bảng báo cáo" dạng dict và trả về bytes.

    table = {
        "title": "Báo cáo doanh thu theo ngày",
        "subtitle": "Từ 01/11/2026 đến 07/11/2026",
        "headers": ["Kỳ", "Số hoá đơn", "Doanh thu (đ)"],
        "rows": [["01/11/2026", 12, 3450000], ...],
        "footer": ["Tổng", 80, 21000000],      # có thể None
        "money_cols": [2],                      # cột là tiền (định dạng 1.234.567)
        "generated": "10/11/2026 09:30",        # tuỳ chọn
    }
"""
import io
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SHU = "C8102E"          # đỏ son, cùng tông với giao diện
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")

# font có đủ dấu tiếng Việt; ưu tiên font đi kèm project, sau đó font hệ thống
_FONT_CANDIDATES = [
    (os.path.join(FONT_DIR, "DejaVuSans.ttf"), os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_fonts = None


def _register_fonts():
    global _fonts
    if _fonts:
        return _fonts
    for regular, bold in _FONT_CANDIDATES:
        if os.path.exists(regular) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("VN", regular))
            pdfmetrics.registerFont(TTFont("VN-Bold", bold))
            _fonts = ("VN", "VN-Bold")
            return _fonts
    raise RuntimeError("Không tìm thấy font có dấu tiếng Việt để tạo PDF")


def fmt_money(n):
    return f"{int(n or 0):,}".replace(",", ".")


def _cell_text(value, is_money):
    if value is None:
        return ""
    if is_money and isinstance(value, (int, float)):
        return fmt_money(value)
    if isinstance(value, float):
        return f"{value:,.1f}".replace(",", ".")
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    return str(value)


# ------------------------------------------------------------------ Excel
def to_xlsx(table):
    wb = Workbook()
    ws = wb.active
    ws.title = (re.sub(r"[\\/*?:\[\]]", "", table["title"])[:31] or "Bao cao")

    headers = table["headers"]
    ncols = len(headers)
    money = set(table.get("money_cols", []))

    ws.append([table["title"]])
    ws.cell(row=1, column=1).font = Font(bold=True, size=14, color=SHU)
    ws.append([table.get("subtitle", "")])
    ws.append([f"Xuất lúc {table['generated']}"] if table.get("generated") else [])
    ws.append([])

    header_row = ws.max_row + 1
    ws.append(headers)
    thin = Side(style="thin", color="BBBBBB")
    for c in range(1, ncols + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=SHU)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in table["rows"]:
        ws.append(list(row))
    last_data = ws.max_row

    if table.get("footer"):
        ws.append(list(table["footer"]))
        for c in range(1, ncols + 1):
            cell = ws.cell(row=ws.max_row, column=c)
            cell.font = Font(bold=True)
            cell.border = Border(top=Side(style="medium", color="000000"))

    for r in range(header_row + 1, ws.max_row + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right")
            if (c - 1) in money and isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0"
            if r <= last_data:
                cell.border = Border(bottom=thin)

    for c in range(1, ncols + 1):
        values = [str(headers[c - 1])] + [str(row[c - 1]) for row in table["rows"]]
        if table.get("footer"):
            values.append(str(table["footer"][c - 1]))
        ws.column_dimensions[get_column_letter(c)].width = min(max(len(v) for v in values) + 4, 50)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# -------------------------------------------------------------------- PDF
def to_pdf(table):
    regular, bold = _register_fonts()
    headers = table["headers"]
    ncols = len(headers)
    money = set(table.get("money_cols", []))
    page = landscape(A4) if ncols > 5 else A4

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=table["title"])
    title_style = ParagraphStyle("t", fontName=bold, fontSize=16, textColor=colors.HexColor("#" + SHU),
                                 spaceAfter=4, leading=20)
    sub_style = ParagraphStyle("s", fontName=regular, fontSize=10, textColor=colors.HexColor("#555555"),
                               leading=14)
    body = ParagraphStyle("b", fontName=regular, fontSize=9, leading=12)
    body_bold = ParagraphStyle("bb", parent=body, fontName=bold)
    head = ParagraphStyle("h", parent=body, fontName=bold, textColor=colors.white)

    story = [Paragraph(_esc(table["title"]), title_style)]
    if table.get("subtitle"):
        story.append(Paragraph(_esc(table["subtitle"]), sub_style))
    if table.get("generated"):
        story.append(Paragraph(_esc(f"Xuất lúc {table['generated']}"), sub_style))
    story.append(Spacer(1, 8 * mm))

    # cột số (canh phải, cả tiêu đề lẫn giá trị)
    num_cols = {c for c in range(ncols)
                if c in money or (table["rows"] and all(_is_num(r[c]) for r in table["rows"]))}

    def para(value, c, style):
        right = ParagraphStyle("r", parent=style, alignment=2) if c in num_cols else style
        return Paragraph(_esc(_cell_text(value, c in money)), right)

    head_right = ParagraphStyle("hr", parent=head, alignment=2)
    data = [[Paragraph(_esc(h), head_right if c in num_cols else head) for c, h in enumerate(headers)]]
    for row in table["rows"]:
        data.append([para(v, c, body) for c, v in enumerate(row)])
    if table.get("footer"):
        data.append([para(v, c, body_bold) for c, v in enumerate(table["footer"])])

    tbl = Table(data, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + SHU)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if table.get("footer"):
        style += [("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                  ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F3F3"))]
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawRightString(page[0] - 15 * mm, 8 * mm, f"{table.get('org', 'GYUSACHI')} · Trang {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
