"""
Generates realistic test invoice PDFs for the AP decision-engine case study.

5 invoices:
  1. happy_path_INV-AC-301.pdf   - clean, all fields present, matches PO-1002 exactly
  2. edge_scanned_INV-CR-150.pdf - image-only PDF (no text layer) -> forces OCR path
  3. edge_missing_po_INV-CR-220.pdf - no PO reference printed -> forces fuzzy PO match
  4. edge_tolerance_INV-QF-500.pdf  - amount 6.7% over matched PO -> tolerance flag
  5. edge_duplicate_INV-5050.pdf    - same vendor+invoice# as an already-processed invoice
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = "/tmp/zamp-ap/test_invoices"
os.makedirs(OUT_DIR, exist_ok=True)


def draw_invoice_text_pdf(path, vendor, invoice_number, invoice_date, po_number,
                           line_items, tax, total, bill_to="Brightpath Technologies Pvt Ltd",
                           note=None):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, vendor)
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "TAX INVOICE")
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Invoice Number: {invoice_number}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Invoice Date: {invoice_date}")
    y -= 6 * mm
    if po_number:
        c.drawString(20 * mm, y, f"PO Reference: {po_number}")
        y -= 6 * mm
    c.drawString(20 * mm, y, f"Bill To: {bill_to}")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(130 * mm, y, "Amount (INR)")
    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    for desc, amt in line_items:
        c.drawString(20 * mm, y, desc)
        c.drawRightString(185 * mm, y, f"{amt:,.2f}")
        y -= 6 * mm

    y -= 2 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 7 * mm
    c.drawString(130 * mm, y, "Tax (GST):")
    c.drawRightString(185 * mm, y, f"{tax:,.2f}")
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(130 * mm, y, "Total:")
    c.drawRightString(185 * mm, y, f"{total:,.2f}")

    if note:
        y -= 15 * mm
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(20 * mm, y, note)

    c.showPage()
    c.save()


def draw_invoice_as_image_pdf(path, vendor, invoice_number, invoice_date, po_number,
                               line_items, tax, total, bill_to="Brightpath Technologies Pvt Ltd"):
    """Renders the invoice as a rasterized image with no text layer, simulating a scanned document."""
    img = Image.new("RGB", (1240, 1754), "white")  # A4 at ~150dpi
    draw = ImageDraw.Draw(img)
    try:
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except Exception:
        font_bold = font = font_small = ImageFont.load_default()

    y = 90
    draw.text((80, y), vendor, font=font_bold, fill="black")
    y += 55
    draw.text((80, y), "TAX INVOICE (scanned copy)", font=font_small, fill="black")
    y += 60
    draw.text((80, y), f"Invoice Number: {invoice_number}", font=font, fill="black")
    y += 38
    draw.text((80, y), f"Invoice Date: {invoice_date}", font=font, fill="black")
    y += 38
    if po_number:
        draw.text((80, y), f"PO Reference: {po_number}", font=font, fill="black")
        y += 38
    draw.text((80, y), f"Bill To: {bill_to}", font=font, fill="black")
    y += 70

    draw.text((80, y), "Description", font=font, fill="black")
    draw.text((850, y), "Amount (INR)", font=font, fill="black")
    y += 35
    draw.line((80, y, 1150, y), fill="black", width=2)
    y += 30
    for desc, amt in line_items:
        draw.text((80, y), desc, font=font, fill="black")
        draw.text((900, y), f"{amt:,.2f}", font=font, fill="black")
        y += 40

    y += 10
    draw.line((80, y, 1150, y), fill="black", width=2)
    y += 35
    draw.text((780, y), f"Tax (GST): {tax:,.2f}", font=font, fill="black")
    y += 42
    draw.text((780, y), f"Total: {total:,.2f}", font=font_bold, fill="black")

    # slight blur/noise to feel like a real scan
    import random
    px = img.load()
    random.seed(42)
    for _ in range(12000):
        rx = random.randint(0, img.width - 1)
        ry = random.randint(0, img.height - 1)
        px[rx, ry] = (235, 235, 235)

    img.save(path, "PDF", resolution=150.0)


# ---- 1. Happy path ----
draw_invoice_text_pdf(
    f"{OUT_DIR}/happy_path_INV-AC-301.pdf",
    vendor="Apex Cloud Services",
    invoice_number="INV-AC-301",
    invoice_date="2026-11-02",
    po_number="PO-1002",
    line_items=[
        ("Cloud infrastructure - Nov 2026 (annual plan, prorated)", 230000.00),
    ],
    tax=20000.00,
    total=250000.00,
)

# ---- 2. Scanned / image-only PDF ----
draw_invoice_as_image_pdf(
    f"{OUT_DIR}/edge_scanned_INV-CR-150.pdf",
    vendor="Crestline Office Supplies",
    invoice_number="INV-CR-150",
    invoice_date="2026-10-28",
    po_number="PO-1001",
    line_items=[
        ("Office furniture & stationery - Q4 restock", 42000.00),
    ],
    tax=3000.00,
    total=45000.00,
)

# ---- 3. Missing PO reference ----
draw_invoice_text_pdf(
    f"{OUT_DIR}/edge_missing_po_INV-CR-220.pdf",
    vendor="Crestline Office Supplies",
    invoice_number="INV-CR-220",
    invoice_date="2026-11-01",
    po_number=None,  # intentionally missing
    line_items=[
        ("Workstation setup - new hires batch", 75000.00),
    ],
    tax=5000.00,
    total=80000.00,
    note="Note: vendor did not reference a PO number on this invoice.",
)

# ---- 4. Amount over tolerance ----
draw_invoice_text_pdf(
    f"{OUT_DIR}/edge_tolerance_INV-QF-500.pdf",
    vendor="Quantum Facilities Mgmt",
    invoice_number="INV-QF-500",
    invoice_date="2026-10-30",
    po_number="PO-1005",
    line_items=[
        ("Facility maintenance - October 2026 (incl. emergency HVAC repair surcharge)", 60500.00),
    ],
    tax=3500.00,
    total=64000.00,  # PO-1005 is 60000 -> 6.67% over
)

# ---- 5. Duplicate invoice ----
draw_invoice_text_pdf(
    f"{OUT_DIR}/edge_duplicate_INV-5050.pdf",
    vendor="Apex Cloud Services",
    invoice_number="INV-5050",  # already in processed_history_seed.json
    invoice_date="2026-10-20",
    po_number="PO-1006",
    line_items=[
        ("Cloud infrastructure - Oct 2026", 92000.00),
    ],
    tax=8000.00,
    total=100000.00,
)

print("Generated 5 test invoices in", OUT_DIR)
for f in sorted(os.listdir(OUT_DIR)):
    print(" -", f)
