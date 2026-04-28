"""Datasheet PDF builder — Linear-Technology-inspired clean technical style.

Generates a multi-page PDF datasheet from a Board, the rendered images, BOM,
and bringup procedure. Uses ReportLab for typography control.

Design language:
- Letter portrait, 0.6" margins
- Headers: bold sans, deep purple (#4B2C82) underlined with gold (#D4AF37)
- Body: clean serif (Times) for prose, mono for tech specs
- Section dividers: thin gold rule + small purple square ornament
- Tables: zebra-striped with subtle gold accent header
- Footer: small witty caption + page number

Result: technical density of a Linear Tech app note, with restrained colour
play and a hint of personality.
"""
from __future__ import annotations
import os
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle,
    Frame, KeepTogether, Flowable, ListFlowable, ListItem,
)
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate

from circuit_toolkit.core.board import Board


# ── Colour palette ────────────────────────────────────────────────────────────
PURPLE       = colors.HexColor("#4B2C82")    # Deep amethyst — headings, dividers
PURPLE_LIGHT = colors.HexColor("#7B5BB6")    # Sub-headings, accents
PURPLE_FAINT = colors.HexColor("#EFEAF7")    # Table zebra
GOLD         = colors.HexColor("#D4AF37")    # Accent rules, key spec highlights
GOLD_DEEP    = colors.HexColor("#A8851F")    # Bold accent
INK          = colors.HexColor("#1B1B22")    # Body text
INK_MUTED    = colors.HexColor("#5C5C68")
PAPER        = colors.HexColor("#FFFFFF")
PAPER_WARM   = colors.HexColor("#FDFCF7")    # Subtle warm-white for sidebars


# ── Witty footers (one per page, cycled) ──────────────────────────────────────
PLAYFUL_FOOTERS = [
    "Designed by photons, soldered by humans.",
    "Built with Python, tested with electrons.",
    "Resistance is not futile — it's just 5.1kΩ.",
    "If you can read this, the silkscreen worked.",
    "All datasheets feature 100% real components.",
    "Ohm's Law: still correct as of press time.",
    "Some component values may be a function of frequency.",
    "Made in a garage, fabricated globally.",
]


# ── Custom flowables ──────────────────────────────────────────────────────────
class GoldRule(Flowable):
    """Thin gold horizontal line, optionally with a small purple square."""
    def __init__(self, width: float = 7.3 * inch, with_square: bool = True):
        super().__init__()
        self.width = width
        self.with_square = with_square
        self.height = 6

    def draw(self):
        c = self.canv
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.7)
        c.line(0, 3, self.width - (10 if self.with_square else 0), 3)
        if self.with_square:
            c.setFillColor(PURPLE)
            c.rect(self.width - 6, 0, 6, 6, fill=1, stroke=0)


class SectionTitle(Flowable):
    """Big purple section title with gold underline + numeric prefix."""
    def __init__(self, number: str, title: str,
                 width: float = 7.3 * inch):
        super().__init__()
        self.number = number
        self.title = title
        self.width = width
        self.height = 30

    def draw(self):
        c = self.canv
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(GOLD_DEEP)
        c.drawString(0, 22, self.number)
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(PURPLE)
        c.drawString(28, 18, self.title.upper())
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.2)
        c.line(0, 11, self.width, 11)
        c.setFillColor(PURPLE)
        c.rect(self.width - 5, 8, 5, 5, fill=1, stroke=0)


class KeySpecBadge(Flowable):
    """Big bold key spec: "3.3V / 800mA" style. Gold + purple."""
    def __init__(self, value: str, label: str, width: float = 2.3 * inch):
        super().__init__()
        self.value = value
        self.label = label
        self.width = width
        self.height = 0.95 * inch

    def draw(self):
        c = self.canv
        c.setFillColor(PURPLE_FAINT)
        c.roundRect(0, 0, self.width, self.height, 5, fill=1, stroke=0)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.2)
        c.line(8, 6, self.width - 8, 6)
        c.setFillColor(PURPLE)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(10, self.height - 30, self.value)
        c.setFillColor(GOLD_DEEP)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(10, 12, self.label.upper())


# ── Page template (header / footer) ───────────────────────────────────────────
def _make_page_template(doc: BaseDocTemplate, board: Board, rev: str):
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id='content')

    def on_page(c, d):
        # Top header bar
        c.setFillColor(PURPLE)
        c.rect(0, letter[1] - 0.4 * inch, letter[0], 0.4 * inch, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(0.6 * inch, letter[1] - 0.27 * inch, board.name.upper())
        c.setFillColor(PAPER)
        c.setFont("Helvetica", 9)
        c.drawRightString(letter[0] - 0.6 * inch, letter[1] - 0.27 * inch,
                          f"Rev {rev} — {date.today().isoformat()}")
        # Thin gold rule beneath
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.6)
        c.line(0.6 * inch, letter[1] - 0.42 * inch,
               letter[0] - 0.6 * inch, letter[1] - 0.42 * inch)

        # Footer: witty caption + page number
        page_num = c.getPageNumber()
        footer_caption = PLAYFUL_FOOTERS[(page_num - 1) % len(PLAYFUL_FOOTERS)]
        c.setFillColor(INK_MUTED)
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(0.6 * inch, 0.4 * inch, footer_caption)
        c.setFillColor(PURPLE)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, f"Page {page_num}")
        # Footer rule
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.4)
        c.line(0.6 * inch, 0.55 * inch, letter[0] - 0.6 * inch, 0.55 * inch)

    return PageTemplate(id='main', frames=[frame], onPage=on_page)


# ── Style helpers ─────────────────────────────────────────────────────────────
def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=32, leading=38,
        textColor=PURPLE, alignment=TA_LEFT, spaceBefore=0, spaceAfter=4)
    s["subtitle"] = ParagraphStyle("subtitle", parent=base["Normal"],
        fontName="Helvetica", fontSize=14, leading=18,
        textColor=GOLD_DEEP, alignment=TA_LEFT, spaceAfter=18)
    s["h2"] = ParagraphStyle("h2", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=12, leading=16,
        textColor=PURPLE, spaceBefore=10, spaceAfter=4)
    s["body"] = ParagraphStyle("body", parent=base["Normal"],
        fontName="Times-Roman", fontSize=10, leading=14,
        textColor=INK, alignment=TA_JUSTIFY, spaceAfter=6)
    s["body_lead"] = ParagraphStyle("body_lead", parent=base["Normal"],
        fontName="Times-Italic", fontSize=11, leading=15,
        textColor=INK_MUTED, alignment=TA_LEFT, spaceAfter=10)
    s["mono"] = ParagraphStyle("mono", parent=base["Normal"],
        fontName="Courier", fontSize=9, leading=12, textColor=INK)
    s["caption"] = ParagraphStyle("caption", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=8, leading=10,
        textColor=INK_MUTED, alignment=TA_CENTER)
    return s


def _table_style(header_rows: int = 1) -> TableStyle:
    cmds = [
        # Header
        ('BACKGROUND', (0, 0), (-1, header_rows - 1), PURPLE),
        ('TEXTCOLOR',  (0, 0), (-1, header_rows - 1), GOLD),
        ('FONTNAME',   (0, 0), (-1, header_rows - 1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, header_rows - 1), 9),
        ('ALIGN',      (0, 0), (-1, header_rows - 1), 'LEFT'),
        ('LINEBELOW',  (0, header_rows - 1), (-1, header_rows - 1), 0.6, GOLD),
        ('TOPPADDING',    (0, 0), (-1, header_rows - 1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, header_rows - 1), 6),
        # Body
        ('FONTNAME', (0, header_rows), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, header_rows), (-1, -1), 9),
        ('TEXTCOLOR', (0, header_rows), (-1, -1), INK),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, header_rows), (-1, -1), 4),
        ('BOTTOMPADDING', (0, header_rows), (-1, -1), 4),
    ]
    # Zebra
    return TableStyle(cmds + [
        ('ROWBACKGROUNDS', (0, header_rows), (-1, -1),
         [PAPER, PURPLE_FAINT]),
    ])


# ── Spec extraction ───────────────────────────────────────────────────────────
def _derive_specs(board: Board) -> Dict[str, str]:
    """Auto-derive board specifications from the components present."""
    specs: Dict[str, str] = {}
    refs = {c.ref: c for c in board.components}

    has_usbc = any(c.value.startswith("HRO TYPE-C") or c.value.startswith("USB_C")
                   for c in board.components)
    if has_usbc:
        specs["Input"] = "USB-C, 5V nominal (4.75–5.25V)"
        # Detect CC pulldowns to determine max negotiated current
        cc_pulldowns = [c for c in board.components
                        if c.value in ("5.1k", "5.10k") and c.ref.startswith("R")]
        if len(cc_pulldowns) >= 2:
            specs["USB advertised role"] = "Sink, 5V/3A (Rd = 5.1kΩ × 2)"

    # AMS1117 LDO output detection
    ldo_caps = [c for c in board.components if c.value.startswith("AMS1117-")]
    if ldo_caps:
        ldo = ldo_caps[0]
        v_nom = ldo.value.replace("AMS1117-", "")
        specs["Output voltage"] = f"{v_nom}V ± 2% (regulated)"
        specs["Output current (max)"] = "800 mA continuous (datasheet AMS1117)"
        specs["Dropout voltage"] = "≤ 1.3V at 800mA"
        specs["Quiescent current"] = "≈ 5 mA (no load)"

    # LED indicator
    leds = [c for c in board.components if c.footprint.startswith("LED_SMD")]
    if leds:
        specs["Power LED"] = "On while regulated output present"

    # Board dimensions
    specs["Dimensions"] = f"{board.size[0]:g} × {board.size[1]:g} mm"
    specs["Layer count"] = f"{board.layer_count} layers, {board.thickness_mm:g}mm FR-4"

    # Operating range (best-effort)
    specs["Operating temperature"] = "0 to +70 °C (commercial)"

    return specs


def _bom_groups(board: Board) -> List[Tuple[str, str, str, str, int]]:
    """(refs, value, footprint, lcsc, qty) tuples sorted by ref letter."""
    groups: Dict[Tuple[str, str, str], List[str]] = {}
    for c in board.components:
        if c.ref.startswith("H"):
            continue   # Skip mounting holes
        key = (c.value, c.footprint, c.lcsc or "—")
        groups.setdefault(key, []).append(c.ref)
    rows = []
    for (val, fp, lcsc), refs in groups.items():
        # Strip "Library:" prefix from footprint for display
        fp_display = fp.split(":", 1)[-1] if ":" in fp else fp
        rows.append((", ".join(sorted(refs)), val, fp_display, lcsc, len(refs)))
    rows.sort(key=lambda r: (r[0][0], r[0]))
    return rows


def _pin_descriptions(board: Board) -> List[Tuple[str, str, str]]:
    """Auto-extract pin descriptions for human-facing connectors only.

    Returns (connector_ref, pin_id, description) tuples.
    """
    result = []
    for c in board.components:
        if c.ref.startswith("J"):    # connectors
            # Use net assignments to describe pins
            for net_name, net in board.nets.items():
                pads = [p for p in net.pads if p.component_ref == c.ref]
                for p in pads:
                    result.append((c.ref, p.pad_number, net_name))
    return result


# ── Section builders ──────────────────────────────────────────────────────────
def _section_cover(board: Board, rev: str, render_top: Optional[Path],
                   description: str, styles: Dict) -> List:
    s = []
    s.append(Spacer(1, 0.4 * inch))
    s.append(Paragraph(board.name.upper(), styles["title"]))
    s.append(Paragraph(description, styles["subtitle"]))
    s.append(GoldRule())
    s.append(Spacer(1, 0.25 * inch))

    # Key spec badges in a row
    derived = _derive_specs(board)
    badges = []
    if "Output voltage" in derived:
        badges.append(KeySpecBadge(derived["Output voltage"].split(" ")[0],
                                   "OUTPUT"))
    if "Output current (max)" in derived:
        badges.append(KeySpecBadge(derived["Output current (max)"].split(" ")[0]
                                   + derived["Output current (max)"].split(" ")[1],
                                   "MAX CURRENT"))
    badges.append(KeySpecBadge(f"{board.size[0]:g}×{board.size[1]:g}", "MM"))
    if badges:
        # Pack into a single-row table
        spacer_w = 0.05 * inch
        cells = []
        for b in badges:
            cells.append(b)
        t = Table([cells], colWidths=[2.4 * inch] * len(cells))
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        s.append(t)
        s.append(Spacer(1, 0.25 * inch))

    # 3D render
    if render_top and render_top.exists():
        img = Image(str(render_top), width=5.5 * inch, height=4.1 * inch,
                    kind='proportional')
        s.append(img)
        s.append(Paragraph("Figure 1. Board top view (3D render).", styles["caption"]))

    s.append(Spacer(1, 0.2 * inch))
    s.append(GoldRule(with_square=False))
    s.append(Paragraph(
        "<b>This document was generated</b> by <font color='#4B2C82'><b>circuit_toolkit</b></font> from a 25-line Python topology description. "
        "Any drift between schematic, PCB, and BOM is by construction impossible — they share a single source.",
        styles["body_lead"]))
    return s


def _section_specs(board: Board, manual_overrides: Optional[Dict[str, str]],
                   styles: Dict) -> List:
    s = [SectionTitle("1.0", "Specifications"), Spacer(1, 4)]
    s.append(Paragraph(
        "Electrical and mechanical parameters derived from the circuit topology and "
        "PCB layout. Manufacturer-rated values reference the AMS1117 datasheet "
        "and USB Type-C specification.",
        styles["body"]))
    s.append(Spacer(1, 6))

    derived = _derive_specs(board)
    if manual_overrides:
        derived.update(manual_overrides)

    rows = [["Parameter", "Value"]]
    for k, v in derived.items():
        rows.append([k, v])

    t = Table(rows, colWidths=[2.3 * inch, 4.7 * inch])
    t.setStyle(_table_style())
    s.append(t)

    s.append(Spacer(1, 12))
    s.append(Paragraph("<b>Absolute Maximum Ratings</b>", styles["h2"]))
    abs_max = [
        ["Parameter", "Min", "Max", "Unit"],
        ["VBUS input", "-0.3", "6.5", "V"],
        ["+3V3 output (continuous)", "—", "800", "mA"],
        ["Storage temperature", "-65", "+150", "°C"],
        ["Operating temperature", "0", "+70", "°C"],
        ["Junction temperature", "—", "+125", "°C"],
    ]
    t2 = Table(abs_max, colWidths=[3.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch])
    t2.setStyle(_table_style())
    s.append(t2)
    return s


def _section_schematic(schematic_svg: Optional[Path], styles: Dict) -> List:
    s = [SectionTitle("2.0", "Schematic"), Spacer(1, 4)]
    s.append(Paragraph(
        "Functional schematic auto-generated from the SKiDL netlist. "
        "Wires represent named electrical nets; symbol placement is "
        "topological rather than physically representative.",
        styles["body"]))
    s.append(Spacer(1, 8))
    if schematic_svg and schematic_svg.exists():
        try:
            # Rasterize SVG → PNG first (more reliable than embedding Drawing directly)
            png_path = schematic_svg.with_suffix(".png")
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
            drawing = svg2rlg(str(schematic_svg))
            # Render at high DPI so the embedded image is crisp
            renderPM.drawToFile(drawing, str(png_path), fmt="PNG", dpi=200,
                                bg=0xFFFFFF)
            target_w = 7.0 * inch
            target_h = 8.5 * inch
            # Image() respects 'kind=proportional' to fit within bounds
            s.append(Image(str(png_path), width=target_w, height=target_h,
                           kind='proportional'))
            s.append(Paragraph("Figure 4. Functional schematic.", styles["caption"]))
        except Exception as e:
            s.append(Paragraph(f"(Schematic embed failed: {e})", styles["caption"]))
    else:
        s.append(Paragraph("(Schematic SVG not available — run build.py first.)",
                           styles["caption"]))
    return s


def _section_pcb(render_top: Optional[Path], render_bottom: Optional[Path],
                 board: Board, styles: Dict) -> List:
    s = [SectionTitle("3.0", "PCB Layout"), Spacer(1, 4)]
    s.append(Paragraph(
        f"Two-layer FR-4, {board.thickness_mm:g} mm thickness, "
        f"{board.size[0]:g} × {board.size[1]:g} mm. Top copper carries signal "
        "and power; bottom copper hosts crossover routes. GND copper pour "
        "fills both layers.",
        styles["body"]))
    s.append(Spacer(1, 8))

    cells = []
    if render_top and render_top.exists():
        cells.append(Image(str(render_top), width=3.3 * inch, height=2.5 * inch,
                           kind='proportional'))
    if render_bottom and render_bottom.exists():
        cells.append(Image(str(render_bottom), width=3.3 * inch, height=2.5 * inch,
                           kind='proportional'))
    if cells:
        t = Table([cells], colWidths=[3.5 * inch] * len(cells))
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        s.append(t)
        captions = []
        if render_top and render_top.exists():
            captions.append("Figure 2. Top view.")
        if render_bottom and render_bottom.exists():
            captions.append("Figure 3. Bottom view.")
        s.append(Paragraph("    ".join(captions), styles["caption"]))
    return s


def _section_pins(board: Board, styles: Dict) -> List:
    s = [SectionTitle("4.0", "Connector Pin Descriptions"), Spacer(1, 4)]
    pins = _pin_descriptions(board)
    if not pins:
        s.append(Paragraph("(No connectors detected.)", styles["body"]))
        return s

    # Group by connector
    by_conn: Dict[str, List[Tuple[str, str]]] = {}
    for ref, pin, net in pins:
        by_conn.setdefault(ref, []).append((pin, net))

    for conn_ref in sorted(by_conn.keys()):
        comp = next((c for c in board.components if c.ref == conn_ref), None)
        title = f"{conn_ref} — {comp.value if comp else ''}"
        s.append(Paragraph(title, styles["h2"]))
        rows = [["Pin", "Net", "Function"]]
        for pin, net in sorted(by_conn[conn_ref], key=lambda x: x[0]):
            function = _pin_function_description(net)
            rows.append([pin, net, function])
        t = Table(rows, colWidths=[0.9 * inch, 1.5 * inch, 4.6 * inch])
        t.setStyle(_table_style())
        s.append(t)
        s.append(Spacer(1, 8))
    return s


def _pin_function_description(net_name: str) -> str:
    """Best-effort human-readable description of a net's role."""
    if net_name == "GND":  return "Ground reference"
    if net_name == "VBUS": return "USB-C bus power input (5V nominal)"
    if net_name == "+3V3": return "Regulated 3.3V output"
    if net_name == "CC1":  return "USB-C Configuration Channel 1 (Rd to GND)"
    if net_name == "CC2":  return "USB-C Configuration Channel 2 (Rd to GND)"
    if net_name.startswith("N_"): return "Internal node (intermediate signal)"
    return "Signal"


def _section_bom(board: Board, styles: Dict) -> List:
    s = [SectionTitle("5.0", "Bill of Materials"), Spacer(1, 4)]
    s.append(Paragraph(
        "All parts are JLCPCB-compatible. Where possible, basic-part LCSC "
        "numbers are used to avoid PCBA setup fees.",
        styles["body"]))
    s.append(Spacer(1, 6))

    rows = [["Designator", "Qty", "Value", "Footprint", "LCSC"]]
    for refs, val, fp, lcsc, qty in _bom_groups(board):
        rows.append([refs, str(qty), val, fp, lcsc])

    t = Table(rows, colWidths=[1.5 * inch, 0.4 * inch, 1.3 * inch,
                               2.8 * inch, 0.8 * inch])
    t.setStyle(_table_style())
    s.append(t)

    # Total parts count
    total = sum(int(r[1]) for r in rows[1:])
    s.append(Spacer(1, 6))
    s.append(Paragraph(
        f"<font color='#A8851F'><b>Total: {total} components</b></font> "
        f"across {len(rows)-1} unique part numbers. "
        f"Mounting hardware (H1–H4) is excluded from the assembly BOM.",
        styles["caption"]))
    return s


def _section_bringup(bringup_md: Optional[Path], styles: Dict) -> List:
    s = [SectionTitle("6.0", "Bringup Procedure"), Spacer(1, 4)]
    if bringup_md and bringup_md.exists():
        text = bringup_md.read_text(encoding="utf-8", errors="replace")
        # Strip the H1 (we have our own title)
        text = re.sub(r"^# .*\n", "", text, count=1)
        # Convert simple markdown to ReportLab paragraphs
        for line in text.split("\n"):
            line = line.rstrip()
            if not line:
                s.append(Spacer(1, 4))
                continue
            if line.startswith("## "):
                s.append(Paragraph(line[3:], styles["h2"]))
            elif line.startswith("### "):
                s.append(Paragraph(f"<b>{line[4:]}</b>", styles["body"]))
            elif line.startswith("- [ ]"):
                # Bullet checkbox
                content = line[5:].strip()
                # Bold the part before " — "
                if " — " in content:
                    parts = content.split(" — ", 1)
                    content = f"<b>{parts[0]}</b> — {parts[1]}"
                s.append(Paragraph(f"☐ {content}", styles["body"]))
            elif line.startswith("---"):
                s.append(GoldRule(with_square=False))
            else:
                s.append(Paragraph(line, styles["body"]))
    else:
        s.append(Paragraph(
            "(Bringup procedure not available — see bringup.md in source repo.)",
            styles["body"]))
    return s


def _section_simulation(sim_dir: Optional[Path], styles: Dict) -> List:
    """Optional section if SPICE plots are available."""
    if not sim_dir or not sim_dir.exists():
        return []
    plots = sorted(sim_dir.glob("*.png"))
    if not plots:
        return []
    s = [SectionTitle("7.0", "Simulation Results"), Spacer(1, 4)]
    s.append(Paragraph(
        "Pre-fabrication SPICE simulation results. Each plot was generated by "
        "ngspice from the same netlist that produced the PCB — circuit and "
        "simulation share a single Python source.",
        styles["body"]))
    s.append(Spacer(1, 6))
    for i, plot in enumerate(plots, start=1):
        s.append(Image(str(plot), width=6.5 * inch, height=3.5 * inch,
                       kind='proportional'))
        title = plot.stem.replace("_", " ").title()
        s.append(Paragraph(f"Figure {i}. {title}.", styles["caption"]))
        s.append(Spacer(1, 8))
    return s


# ── Public entry point ────────────────────────────────────────────────────────
def build_datasheet(board: Board, output: str | Path,
                    rev: str = "0.1",
                    description: str = "",
                    render_top: Optional[Path] = None,
                    render_bottom: Optional[Path] = None,
                    schematic_svg: Optional[Path] = None,
                    bringup_md: Optional[Path] = None,
                    sim_dir: Optional[Path] = None,
                    spec_overrides: Optional[Dict[str, str]] = None) -> Path:
    """Generate a complete board datasheet PDF.

    Args:
        board: Board object to document
        output: PDF path to write
        rev: revision string (e.g. "1.0")
        description: one-line tagline (e.g. "USB-C → 3.3V LDO power board")
        render_top, render_bottom: PNG paths from render_pcb()
        schematic_svg: SVG path from build_schematic()
        bringup_md: optional bringup.md to convert into the PDF
        sim_dir: optional directory of SPICE simulation PNGs
        spec_overrides: dict to extend/override auto-derived specs

    Returns the output Path.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not description:
        description = f"Reference design — {board.name}"

    styles = _styles()
    doc = BaseDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
        title=f"{board.name} datasheet rev {rev}",
        author="circuit_toolkit",
    )
    doc.addPageTemplates([_make_page_template(doc, board, rev)])

    flowables: List = []
    flowables += _section_cover(board, rev, render_top, description, styles)
    flowables.append(PageBreak())
    flowables += _section_specs(board, spec_overrides, styles)
    flowables.append(PageBreak())
    flowables += _section_schematic(schematic_svg, styles)
    flowables.append(PageBreak())
    flowables += _section_pcb(render_top, render_bottom, board, styles)
    flowables.append(PageBreak())
    flowables += _section_pins(board, styles)
    flowables.append(PageBreak())
    flowables += _section_bom(board, styles)
    flowables.append(PageBreak())
    flowables += _section_bringup(bringup_md, styles)
    sim_section = _section_simulation(sim_dir, styles)
    if sim_section:
        flowables.append(PageBreak())
        flowables += sim_section

    doc.build(flowables)
    return output
