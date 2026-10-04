from pathlib import Path
from html import escape

from docx import Document
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer


def _style_sheet():
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#17324D")
    steel = colors.HexColor("#4D6478")
    accent = colors.HexColor("#B38B59")
    styles.add(
        ParagraphStyle(
            name="CvHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=12.5,
            textColor=navy,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.15,
            leading=11.4,
            textColor=colors.HexColor("#1F1F1F"),
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvContact",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.7,
            leading=10,
            alignment=1,
            textColor=steel,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=20,
            alignment=1,
            textColor=navy,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvSubtitle",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=11,
            alignment=1,
            textColor=steel,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvJob",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=11.2,
            textColor=navy,
            spaceBefore=5,
            spaceAfter=1,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvJobMeta",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.7,
            leading=10.5,
            textColor=steel,
            spaceAfter=2.5,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CvBullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.9,
            leading=11,
            leftIndent=0.32 * cm,
            firstLineIndent=-0.16 * cm,
            textColor=colors.HexColor("#1F1F1F"),
            spaceAfter=2.4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LetterName",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=navy,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LetterContact",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=steel,
            spaceAfter=1,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LetterSubject",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=navy,
            spaceBefore=8,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LetterBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#202428"),
            spaceAfter=8,
        )
    )
    styles.add(ParagraphStyle(name="AccentMeta", parent=styles["BodyText"], textColor=accent))
    return styles


def _is_job_line(text):
    lowered = text.lower()
    return " | " in text and any(
        marker in lowered
        for marker in [
            "consultant",
            "trainee",
            "officer",
            "analyst",
            "manager",
            "eurus",
            "ap-hp",
            "dxc",
            "unesco",
        ]
    )


def docx_to_pdf(docx_path):
    docx_path = Path(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")
    document = Document(docx_path)
    styles = _style_sheet()
    story = []

    for paragraph in document.paragraphs:
        style_name = paragraph.style.name.lower()
        if style_name == "cv page break":
            story.append(PageBreak())
            continue
        text = paragraph.text.strip()
        if not text:
            continue
        if style_name == "cv name" or "title" in style_name:
            style = styles["CvTitle"]
        elif style_name == "cv headline":
            style = styles["CvSubtitle"]
        elif style_name == "cv contact":
            style = styles["CvContact"]
        elif style_name == "cv section" or "heading" in style_name:
            style = styles["CvHeading"]
            story.append(Spacer(1, 0.05 * cm))
        elif style_name == "cv job" or _is_job_line(text):
            style = styles["CvJob"]
        elif style_name == "cv job meta":
            style = styles["CvJobMeta"]
        elif style_name == "cv bullet":
            style = styles["CvBullet"]
        else:
            style = styles["CvBody"]
            if "list" in style_name:
                text = "- " + text
                style = styles["CvBullet"]
        story.append(Paragraph(escape(text), style))
        if style is styles["CvTitle"]:
            story.append(Spacer(1, 0.05 * cm))
        if style_name == "cv contact" and text.lower().startswith("linkedin"):
            story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#B38B59"), spaceBefore=4, spaceAfter=5))

    pdf = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.45 * cm,
        leftMargin=1.45 * cm,
        topMargin=1.15 * cm,
        bottomMargin=1.15 * cm,
        title=docx_path.stem,
    )
    def later_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#617386"))
        canvas.drawString(1.45 * cm, A4[1] - 0.75 * cm, "Demo Candidate | Curriculum Vitae")
        canvas.drawRightString(A4[0] - 1.45 * cm, 0.7 * cm, f"Page {doc.page}")
        canvas.restoreState()

    pdf.build(story, onLaterPages=later_page)
    return pdf_path


def text_to_pdf(text, pdf_path, title=None):
    pdf_path = Path(pdf_path)
    styles = _style_sheet()
    story = []
    blocks = text.splitlines()
    nonempty_index = 0
    for block in blocks:
        block = block.strip()
        if not block:
            story.append(Spacer(1, 0.12 * cm))
            continue
        lower = block.lower()
        if nonempty_index == 0 and block == "Demo Candidate":
            style = styles["LetterName"]
        elif nonempty_index in {1, 2} and ("@" in block or "linkedin.com" in lower or "+33" in block):
            style = styles["LetterContact"]
        elif lower.startswith("application for ") or lower.startswith("re: application"):
            style = styles["LetterSubject"]
        else:
            style = styles["LetterBody"]
        story.append(Paragraph(escape(block), style))
        nonempty_index += 1

    pdf = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.7 * cm,
        leftMargin=1.7 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=title or "Demo Candidate - Cover Letter",
    )
    pdf.build(story)
    return pdf_path
