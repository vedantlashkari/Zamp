"""
The AP policy engine: validation -> duplicate check -> vendor check -> PO matching
-> tolerance check -> final decision.

This is the business logic itself, independent of extraction/OCR and independent
of the UI - it takes extracted fields + the PO dataset + processed history, and
returns a structured, stage-by-stage trace plus a final decision.
"""
import json
from datetime import datetime

AMOUNT_TOLERANCE_PASS = 0.02      # within 2% -> pass silently
AMOUNT_TOLERANCE_FLAG_UPPER = 0.10  # 2-10% over -> flag; >10% -> reject
OCR_CONFIDENCE_FLAG_THRESHOLD = 70  # OCR confidence below this -> flag


def load_json(path):
    with open(path) as f:
        return json.load(f)


class Stage:
    def __init__(self, name, status, detail):
        self.name = name
        self.status = status  # 'pass' | 'flag' | 'fail' | 'info'
        self.detail = detail

    def to_dict(self):
        return {"name": self.name, "status": self.status, "detail": self.detail}


def run_decision_engine(extracted: dict, vendors: list, pos: list, history: list) -> dict:
    stages = []
    flag_reasons = []
    reject_reasons = []

    vendor = extracted.get("vendor")
    invoice_number = extracted.get("invoice_number")
    invoice_date = extracted.get("invoice_date")
    po_number = extracted.get("po_number")
    total_amount = extracted.get("total_amount")
    extraction_method = extracted.get("extraction_method", "text")
    extraction_confidence = extracted.get("extraction_confidence", 100)

    # Stage 0: extraction result
    stages.append(Stage(
        "Extract fields",
        "pass" if extraction_method == "text" else ("flag" if extraction_confidence < OCR_CONFIDENCE_FLAG_THRESHOLD else "info"),
        f"Method: {extraction_method.upper()}" + (f", confidence {extraction_confidence}%" if extraction_method == "ocr" else " (digital PDF, fully reliable)")
    ))
    if extraction_method == "ocr" and extraction_confidence < OCR_CONFIDENCE_FLAG_THRESHOLD:
        flag_reasons.append(f"Low-confidence OCR extraction ({extraction_confidence}%) — scanned document, worth a visual check")

    # Stage 1: required-field validation
    missing = []
    if not vendor:
        missing.append("vendor name")
    if not invoice_number:
        missing.append("invoice number")
    if total_amount is None:
        missing.append("total amount")

    if missing:
        stages.append(Stage("Validate required fields", "fail", f"Missing: {', '.join(missing)}"))
        reject_reasons.append(f"Unprocessable — missing required field(s): {', '.join(missing)}")
        # Can't meaningfully continue without these fields.
        return _finalize(stages, flag_reasons, reject_reasons, extraction_confidence, extracted, matched_po=None)
    else:
        stages.append(Stage("Validate required fields", "pass", "Vendor, invoice number, and total amount all present"))

    if not invoice_date:
        stages.append(Stage("Check invoice date", "flag", "Invoice date missing or unreadable"))
        flag_reasons.append("Invoice date missing — needs manual confirmation")
    else:
        stages.append(Stage("Check invoice date", "pass", f"Date: {invoice_date}"))

    # Stage 2: duplicate check (overrides everything else once confirmed)
    is_duplicate = False
    dup_match = None
    for h in history:
        if h["vendor"] == vendor and h["invoice_number"] == invoice_number:
            is_duplicate = True
            dup_match = h
            break

    if is_duplicate:
        stages.append(Stage(
            "Check for duplicate",
            "fail",
            f"Already processed on {dup_match['processed_at'][:10]} — prior decision: {dup_match['decision']}"
        ))
        reject_reasons.append(
            f"Duplicate invoice — {vendor} / {invoice_number} was already processed on "
            f"{dup_match['processed_at'][:10]} (decision: {dup_match['decision']}). Paying again would be a double payment."
        )
        return _finalize(stages, flag_reasons, reject_reasons, extraction_confidence, extracted, matched_po=None)
    else:
        stages.append(Stage("Check for duplicate", "pass", "No prior invoice with this vendor + invoice number"))

    # Stage 3: vendor approval
    if vendor not in vendors:
        stages.append(Stage("Check approved vendor list", "flag", f"'{vendor}' not found in approved vendor list"))
        flag_reasons.append(f"Vendor '{vendor}' is not on the approved vendor list")
    else:
        stages.append(Stage("Check approved vendor list", "pass", f"'{vendor}' is an approved vendor"))

    # Stage 4: PO matching
    matched_po = None
    po_confidence_cap = 100

    if po_number:
        matched_po = next((p for p in pos if p["po_number"] == po_number), None)
        if matched_po is None:
            stages.append(Stage("Match to PO", "flag", f"PO reference '{po_number}' not found in system"))
            flag_reasons.append(f"PO reference '{po_number}' on the invoice does not exist in our PO records")
        elif matched_po["vendor"] != vendor:
            stages.append(Stage("Match to PO", "flag", f"PO '{po_number}' belongs to a different vendor ({matched_po['vendor']})"))
            flag_reasons.append(f"PO '{po_number}' is registered to '{matched_po['vendor']}', not '{vendor}'")
            matched_po = None
        else:
            stages.append(Stage("Match to PO", "pass", f"Direct match: invoice references PO '{po_number}' ({matched_po['vendor']})"))
    else:
        # fuzzy match by vendor + amount within tolerance
        candidates = [
            p for p in pos
            if p["vendor"] == vendor
            and p["remaining_balance"] > 0
            and total_amount is not None
            and abs(p["remaining_balance"] - total_amount) / p["remaining_balance"] <= AMOUNT_TOLERANCE_FLAG_UPPER
        ]
        if len(candidates) == 1:
            matched_po = candidates[0]
            po_confidence_cap = 80
            stages.append(Stage(
                "Match to PO",
                "flag",
                f"No PO reference on invoice — inferred PO '{matched_po['po_number']}' by vendor + amount match (capped confidence)"
            ))
            flag_reasons.append(
                f"No PO reference on invoice — PO '{matched_po['po_number']}' inferred by matching vendor "
                f"and amount (confidence capped at 80%, worth a quick human confirmation)"
            )
        elif len(candidates) == 0:
            stages.append(Stage("Match to PO", "flag", "No PO reference, and no confident vendor+amount match found"))
            flag_reasons.append("No PO reference on invoice, and no single confident match found by vendor + amount")
        else:
            stages.append(Stage("Match to PO", "flag", f"No PO reference, and {len(candidates)} ambiguous vendor+amount matches found"))
            flag_reasons.append(f"No PO reference on invoice, and {len(candidates)} POs are plausible matches — ambiguous")

    # Stage 5: amount tolerance (only if we have a matched PO)
    if matched_po is not None and total_amount is not None:
        basis = matched_po["remaining_balance"]
        is_partial = basis < matched_po["po_amount"]
        diff_pct = (total_amount - basis) / basis if basis else 0

        if total_amount <= basis * (1 + AMOUNT_TOLERANCE_PASS):
            partial_note = f" (partial draw against PO '{matched_po['po_number']}', remaining balance Rs.{basis:,.0f})" if is_partial else ""
            stages.append(Stage(
                "Check amount against PO",
                "pass",
                f"Invoice Rs.{total_amount:,.0f} vs. PO balance Rs.{basis:,.0f} — within tolerance{partial_note}"
            ))
        elif total_amount <= basis * (1 + AMOUNT_TOLERANCE_FLAG_UPPER):
            stages.append(Stage(
                "Check amount against PO",
                "flag",
                f"Invoice Rs.{total_amount:,.0f} exceeds PO balance Rs.{basis:,.0f} by {diff_pct*100:.1f}% (tolerance band)"
            ))
            flag_reasons.append(f"Invoice amount exceeds matched PO by {diff_pct*100:.1f}% — above the 2% auto-pass threshold but within the 10% review band")
        else:
            stages.append(Stage(
                "Check amount against PO",
                "fail",
                f"Invoice Rs.{total_amount:,.0f} exceeds PO balance Rs.{basis:,.0f} by {diff_pct*100:.1f}% (material overage)"
            ))
            reject_reasons.append(f"Invoice amount exceeds matched PO by {diff_pct*100:.1f}% — material overage, needs renegotiation/escalation rather than AP sign-off")
    else:
        stages.append(Stage("Check amount against PO", "info", "Skipped — no PO matched to validate against"))

    return _finalize(stages, flag_reasons, reject_reasons, extraction_confidence, extracted, matched_po,
                      po_confidence_cap=po_confidence_cap)


def _finalize(stages, flag_reasons, reject_reasons, extraction_confidence, extracted, matched_po, po_confidence_cap=100):
    if reject_reasons:
        decision = "Reject"
        reasons = reject_reasons
    elif flag_reasons:
        decision = "Flag"
        reasons = flag_reasons
    else:
        decision = "Approve"
        reasons = ["All checks passed — matched PO, vendor approved, amount within tolerance"]

    confidence = min(extraction_confidence, po_confidence_cap)
    if decision == "Reject":
        # We are highly certain about hard-rule rejections (missing data, duplicates, material overage)
        confidence = max(confidence, 90)
    confidence = round(confidence)

    stages.append(Stage(
        "Final decision",
        {"Approve": "pass", "Flag": "flag", "Reject": "fail"}[decision],
        f"{decision} — {reasons[0]}" + (f" (+{len(reasons)-1} more)" if len(reasons) > 1 else "")
    ))

    return {
        "decision": decision,
        "confidence": confidence,
        "reasons": reasons,
        "stages": [s.to_dict() for s in stages],
        "matched_po": matched_po["po_number"] if matched_po else None,
        "vendor": extracted.get("vendor"),
        "invoice_number": extracted.get("invoice_number"),
        "invoice_date": extracted.get("invoice_date"),
        "total_amount": extracted.get("total_amount"),
        "extraction_method": extracted.get("extraction_method"),
        "extraction_confidence": extracted.get("extraction_confidence"),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }
