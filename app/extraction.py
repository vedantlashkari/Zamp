"""
Extraction stage: pulls structured fields out of a raw invoice PDF.

Tries direct text extraction first (clean, digitally-generated PDFs).
Falls back to OCR when the PDF has no usable text layer (scanned/image invoices),
and reports an OCR confidence score so downstream logic can treat low-confidence
extractions with appropriate caution.
"""
import re
import io
import pdfplumber
import pytesseract
from PIL import Image


def _parse_fields_from_text(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    vendor = None
    for l in lines:
        if l.upper() == "TAX INVOICE" or "SCANNED COPY" in l.upper():
            continue
        vendor = l
        break

    def find(pattern, default=None):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    invoice_number = find(r"Invoice Number:\s*([A-Za-z0-9\-]+)")
    invoice_date = find(r"Invoice Date:\s*([\d/\-]+)")
    po_number = find(r"PO Reference:\s*([A-Za-z0-9\-]+)")

    tax_raw = find(r"Tax\s*\(GST\):\s*([\d,]+\.?\d*)")
    total_raw = find(r"Total:\s*([\d,]+\.?\d*)")

    def to_num(s):
        if s is None:
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None

    return {
        "vendor": vendor,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "po_number": po_number,
        "tax_amount": to_num(tax_raw),
        "total_amount": to_num(total_raw),
    }


def extract_invoice(pdf_path: str) -> dict:
    """
    Returns a dict:
      vendor, invoice_number, invoice_date, po_number, tax_amount, total_amount,
      extraction_method ('text' | 'ocr'),
      extraction_confidence (0-100),
      raw_text (for audit trail)
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""

    if text.strip():
        fields = _parse_fields_from_text(text)
        fields["extraction_method"] = "text"
        fields["extraction_confidence"] = 100
        fields["raw_text"] = text
        return fields

    # No text layer -> OCR fallback
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        pil_image = page.to_image(resolution=200).original

    ocr_data = pytesseract.image_to_data(pil_image, output_type=pytesseract.Output.DICT)
    words = []
    confidences = []
    for word, conf in zip(ocr_data["text"], ocr_data["conf"]):
        if word.strip():
            words.append(word)
            try:
                c = float(conf)
                if c >= 0:
                    confidences.append(c)
            except (ValueError, TypeError):
                pass

    ocr_text = pytesseract.image_to_string(pil_image)
    avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0

    fields = _parse_fields_from_text(ocr_text)
    fields["extraction_method"] = "ocr"
    fields["extraction_confidence"] = avg_confidence
    fields["raw_text"] = ocr_text
    return fields
