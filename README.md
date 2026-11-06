# AP Invoice Decision Engine — Zamp ASA Case Study (PS-1)

A working automated process that takes a raw invoice PDF (clean or scanned), extracts the
relevant fields, matches it against a purchase-order dataset, applies an AP approval policy,
and produces an auditable Approve / Flag / Reject decision with full reasoning.

## Run locally

```bash
pip install -r requirements.txt
# Also needs the tesseract-ocr binary on your system (for scanned invoices):
#   macOS:  brew install tesseract
#   Ubuntu: sudo apt-get install tesseract-ocr
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki

streamlit run app/app.py
```

Then open http://localhost:8501

## Project structure

```
app/
  app.py              - Streamlit UI (live run view + dashboard)
  extraction.py       - PDF text extraction + OCR fallback for scanned invoices
  decision_engine.py  - The AP policy: validation, duplicate check, PO matching, tolerance rules
data/
  vendors.json                 - approved vendor list
  pos.json                     - purchase order dataset
  processed_history_seed.json  - seed history (for duplicate detection demo)
  run_history.json             - accumulates every run (created on first launch)
test_invoices/
  happy_path_INV-AC-301.pdf       - clean invoice, direct PO match, auto-approves
  edge_scanned_INV-CR-150.pdf     - image-only PDF, no text layer -> forces OCR path
  edge_missing_po_INV-CR-220.pdf  - no PO reference -> forces fuzzy vendor+amount match
  edge_tolerance_INV-QF-500.pdf   - amount 6.7% over matched PO -> tolerance flag
  edge_duplicate_INV-5050.pdf     - same vendor+invoice# as an already-processed invoice
```

## The AP policy (business logic)

1. **Required fields** — vendor, invoice number, total amount must be present, or the invoice
   is rejected as unprocessable.
2. **Duplicate check** — same (vendor, invoice number) seen before -> auto-reject, overrides
   every other check.
3. **Vendor check** — vendor must be on the approved vendor list, else flagged.
4. **PO matching** — direct match on PO reference if present; otherwise a fuzzy match by
   vendor + amount (capped at 80% confidence) against POs with remaining balance.
5. **Amount tolerance** — within 2% of the matched PO: auto-pass. 2–10% over: flagged.
   >10% over: rejected as a material overage.
6. **Confidence score** — reflects extraction quality (OCR vs. digital text) and match
   certainty (direct vs. inferred PO), shown on every decision.

## Deploying so you have a public link

The brief asks for a live, runnable link. Fastest free option — **Streamlit Community Cloud**:

1. Push this folder to a new GitHub repo (public or private).
2. Go to https://share.streamlit.io -> "New app" -> pick the repo -> set main file path to
   `app/app.py` -> Deploy.
3. Streamlit Cloud reads `requirements.txt` and `packages.txt` (for the `tesseract-ocr`
   system package) automatically. First deploy takes ~2-3 minutes.
4. You'll get a public URL like `https://<something>.streamlit.app` — that's your submission link.
