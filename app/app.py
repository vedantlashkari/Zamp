import sys
import os
import time
import copy
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from extraction import extract_invoice, render_invoice_page_image
from decision_engine import run_decision_engine, load_json
from config_store import load_config, save_config
import history_store as hs

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEST_DIR = os.path.join(BASE_DIR, "test_invoices")
HISTORY_PATH = os.path.join(DATA_DIR, "run_history.json")
SEED_PATH = os.path.join(DATA_DIR, "processed_history_seed.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

VENDORS = load_json(os.path.join(DATA_DIR, "vendors.json"))["approved_vendors"]
POS = load_json(os.path.join(DATA_DIR, "pos.json"))["purchase_orders"]

hs.init_history(HISTORY_PATH, SEED_PATH)

st.set_page_config(page_title="AP Invoice Decision Engine", layout="wide", page_icon="🧾")

STATUS_ICON = {"pass": "✅", "flag": "⚠️", "fail": "❌", "info": "➖"}
DECISION_COLOR = {"Approve": "#1a7f37", "Flag": "#b35900", "Reject": "#c92a2a"}
PAGES = ["🔴 Live Run", "🟡 Review Queue", "📊 Dashboard", "📘 Guide", "⚙️ Settings"]

# ---------------- Session state defaults ----------------
if "page" not in st.session_state:
    st.session_state.page = "🔴 Live Run"
if "show_walkthrough" not in st.session_state:
    st.session_state.show_walkthrough = True
if "config" not in st.session_state:
    st.session_state.config = load_config(CONFIG_PATH)
if "reviewer_name" not in st.session_state:
    st.session_state.reviewer_name = "AP Reviewer"

CONFIG = st.session_state.config


# ---------------- Helpers ----------------
def decision_badge(decision, confidence):
    color = DECISION_COLOR.get(decision, "#555")
    st.markdown(
        f"""<div style="display:inline-block; padding:10px 20px; border-radius:8px;
        background:{color}1a; border:1.5px solid {color}; color:{color};
        font-weight:700; font-size:1.3rem;">{decision} — {confidence}% confidence</div>""",
        unsafe_allow_html=True,
    )


def review_status_badge(record):
    status = record.get("review_status", "finalized")
    if status == "pending":
        st.markdown("🟡 **Awaiting human review**")
    elif status == "resolved":
        st.markdown(f"✅ **Reviewed by {record.get('reviewed_by', 'someone')}** — "
                     f"final call: **{record.get('final_decision')}**" +
                     (f"  \n> _{record.get('review_reason')}_" if record.get("review_reason") else ""))
    else:
        st.markdown("➖ *No human review needed — system decision is final*")


def render_invoice_and_po_viewer(record, key_prefix=""):
    with st.expander("📄 View invoice & matched PO"):
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("**Invoice**")
            source_file = record.get("source_file_path")
            if source_file and os.path.exists(source_file):
                try:
                    img = render_invoice_page_image(source_file)
                    st.image(img, use_container_width=True)
                except Exception as e:
                    st.caption(f"Could not render invoice preview ({e})")
            else:
                st.caption("Original file not available for this record (historical/seed entry).")
        with col2:
            st.markdown("**Matched PO**")
            po_number = record.get("matched_po")
            po = next((p for p in POS if p["po_number"] == po_number), None)
            if po:
                st.table({
                    "Field": ["PO Number", "Vendor", "PO Amount", "Remaining Balance", "Date Issued"],
                    "Value": [po["po_number"], po["vendor"], f"Rs.{po['po_amount']:,.0f}",
                              f"Rs.{po['remaining_balance']:,.0f}", po["date_issued"]],
                })
            else:
                st.caption("No PO was matched for this invoice.")

            extracted = record.get("extracted_fields")
            if extracted:
                custom_field_names = [cf["name"] for cf in CONFIG.get("custom_fields", [])]
                extras = {k: v for k, v in extracted.items()
                          if k in custom_field_names and v}
                if extras:
                    st.markdown("**Custom fields extracted**")
                    st.json(extras)


def run_one(path, label):
    """Extraction + decision engine for a single file. Returns the full record dict."""
    history = hs.load_history(HISTORY_PATH)
    extracted = extract_invoice(path, CONFIG.get("custom_fields"))
    result = run_decision_engine(extracted, VENDORS, POS, history, CONFIG)
    record = dict(result)
    record["source_file"] = label
    record["source_file_path"] = path
    record["extracted_fields"] = {k: v for k, v in extracted.items() if k != "raw_text"}
    return record


def render_single_run_animated(record):
    st.markdown(f"**Processing:** `{record['source_file']}`")
    box = st.container()
    with box:
        st.markdown("##### Live run")
        method = record["extraction_method"]
        conf = record["extraction_confidence"]
        with st.spinner("Extracting fields from PDF..."):
            time.sleep(0.4)
        icon = "✅" if method == "text" else ("⚠️" if conf < CONFIG["ocr_confidence_flag_threshold"] else "➖")
        st.markdown(f"{icon}  **Extract fields** — Method: {method.upper()}" +
                    (f", confidence {conf}%" if method == "ocr" else " (digital PDF)"))
        with st.spinner("Applying AP policy..."):
            time.sleep(0.4)
        for s in record["stages"][1:]:
            icon = STATUS_ICON.get(s["status"], "•")
            st.markdown(f"{icon}  **{s['name']}** — {s['detail']}")
            time.sleep(0.12)

    st.divider()
    col1, col2 = st.columns([1, 2])
    with col1:
        decision_badge(record["decision"], record["confidence"])
        st.markdown("")
        review_status_badge(record)
    with col2:
        st.markdown("**Reasoning**")
        for r in record["reasons"]:
            st.markdown(f"- {r}")

    render_invoice_and_po_viewer(record)

    with st.expander("Extracted fields"):
        st.json(record["extracted_fields"])


def render_batch_result(record, idx, total):
    with st.expander(f"File {idx+1}/{total}: {record['source_file']} — "
                      f"{record['decision']} ({record['confidence']}%)", expanded=(total <= 3)):
        decision_badge(record["decision"], record["confidence"])
        review_status_badge(record)
        st.markdown("**Reasoning**")
        for r in record["reasons"]:
            st.markdown(f"- {r}")
        render_invoice_and_po_viewer(record)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("## 🧾 AP Invoice Engine")
    st.caption("Invoice → extraction → PO match → policy → decision")

    _default_idx = PAGES.index(st.session_state.page) if st.session_state.page in PAGES else 0
    _selected_page = st.radio("Navigate", PAGES, index=_default_idx, label_visibility="collapsed")
    st.session_state.page = _selected_page

    st.divider()
    st.markdown("### Run invoice(s)")
    sample_files = sorted(os.listdir(TEST_DIR)) if os.path.exists(TEST_DIR) else []
    sample_choice = st.multiselect("Load sample invoice(s)", sample_files)
    uploaded = st.file_uploader("...or upload your own invoice PDF(s)", type=["pdf"], accept_multiple_files=True)

    run_clicked = st.button("▶ Run process", type="primary", use_container_width=True)

    if run_clicked:
        batch = []
        for s in sample_choice:
            batch.append({"path": os.path.join(TEST_DIR, s), "label": s})
        for f in uploaded or []:
            fname = f"{int(time.time()*1000)}_{f.name}"
            fpath = os.path.join(UPLOAD_DIR, fname)
            with open(fpath, "wb") as out:
                out.write(f.getbuffer())
            batch.append({"path": fpath, "label": f.name})

        if not batch:
            st.warning("Select a sample or upload a PDF first.")
        else:
            st.session_state.pending_batch = batch
            st.session_state.page = "🔴 Live Run"
            st.rerun()

    st.divider()
    with st.expander("Reference data used by the policy"):
        st.markdown("**Approved vendors**")
        st.write(VENDORS)
        st.markdown("**Open POs**")
        st.dataframe(
            [{"PO": p["po_number"], "Vendor": p["vendor"], "PO Amount": p["po_amount"],
              "Remaining": p["remaining_balance"]} for p in POS],
            hide_index=True, use_container_width=True
        )

# ---------------- First-time walkthrough ----------------
if st.session_state.show_walkthrough:
    with st.container(border=True):
        c1, c2 = st.columns([10, 1])
        with c1:
            st.markdown("#### 👋 New here? Quick tour")
            st.markdown(
                "- **🔴 Live Run** — pick a sample or upload invoice PDF(s) in the sidebar, click **Run process**. "
                "You'll land here and see each policy stage fire in order.\n"
                "- **🟡 Review Queue** — any invoice the system **Flags** needs a human call. It waits here until "
                "someone approves or rejects it.\n"
                "- **📊 Dashboard** — full run history, filterable and groupable by day.\n"
                "- **📘 Guide** — how the policy works and what each term means.\n"
                "- **⚙️ Settings** — tune tolerance bands, OCR confidence cutoff, and add custom fields to extract."
            )
        with c2:
            if st.button("✕", key="dismiss_walkthrough"):
                st.session_state.show_walkthrough = False
                st.rerun()

# ================= PAGE: Live Run =================
if st.session_state.page == "🔴 Live Run":
    st.markdown("### Live Run")
    st.caption("Pick sample(s) or upload PDF(s) in the sidebar, then click **Run process**.")

    pending = st.session_state.pop("pending_batch", None)
    if pending:
        history = hs.load_history(HISTORY_PATH)
        records = []
        for item in pending:
            rec = run_one(item["path"], item["label"])
            records.append(rec)
            history.append(rec)  # so later files in the SAME batch see it for duplicate detection
        hs.save_history(HISTORY_PATH, history)

        if len(records) == 1:
            render_single_run_animated(records[0])
        else:
            st.success(f"Processed {len(records)} invoices.")
            a = sum(1 for r in records if r["decision"] == "Approve")
            f = sum(1 for r in records if r["decision"] == "Flag")
            rj = sum(1 for r in records if r["decision"] == "Reject")
            c1, c2, c3 = st.columns(3)
            c1.metric("Approved", a)
            c2.metric("Flagged (needs review)", f)
            c3.metric("Rejected", rj)
            st.divider()
            for i, rec in enumerate(records):
                render_batch_result(rec, i, len(records))

        st.info("All run(s) recorded. Flagged ones are now waiting in the **Review Queue** tab.")
    else:
        st.info("No run yet. Pick sample(s) in the sidebar (try the edge cases!) and click **Run process**.")

# ================= PAGE: Review Queue =================
elif st.session_state.page == "🟡 Review Queue":
    st.markdown("### Review Queue")
    st.caption("Every **Flag** needs a human decision before it's final. Approve or reject each one below.")

    st.text_input("Reviewing as", key="reviewer_name")

    history = hs.load_history(HISTORY_PATH)
    pending = [r for r in history if r.get("review_status") == "pending"]

    if not pending:
        st.success("Nothing waiting for review right now.")
    else:
        st.markdown(f"**{len(pending)} invoice(s) awaiting review**")
        for i, rec in enumerate(pending):
            with st.container(border=True):
                st.markdown(f"**{rec['invoice_number']}** — {rec['vendor']} — Rs.{rec.get('total_amount', 0):,.0f}")
                decision_badge(rec["decision"], rec["confidence"])
                st.markdown("**Why it was flagged:**")
                for r in rec["reasons"]:
                    st.markdown(f"- {r}")
                render_invoice_and_po_viewer(rec, key_prefix=f"rq_{i}")

                reason_key = f"review_reason_{i}_{rec['processed_at']}"
                reason = st.text_area("Reason for your decision (optional but recommended)", key=reason_key, height=60)

                bcol1, bcol2, _ = st.columns([1, 1, 4])
                with bcol1:
                    if st.button("✅ Approve", key=f"approve_{i}_{rec['processed_at']}", use_container_width=True):
                        hs.apply_review(HISTORY_PATH, rec["invoice_number"], rec["vendor"], rec["processed_at"],
                                         "Approve", st.session_state.reviewer_name, reason)
                        st.rerun()
                with bcol2:
                    if st.button("❌ Reject", key=f"reject_{i}_{rec['processed_at']}", use_container_width=True):
                        hs.apply_review(HISTORY_PATH, rec["invoice_number"], rec["vendor"], rec["processed_at"],
                                         "Reject", st.session_state.reviewer_name, reason)
                        st.rerun()

# ================= PAGE: Dashboard =================
elif st.session_state.page == "📊 Dashboard":
    st.markdown("### Dashboard — run history")
    history = hs.load_history(HISTORY_PATH)

    if not history:
        st.info("No runs yet.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total runs", len(history))
        c2.metric("Approved (final)", sum(1 for h in history if h.get("final_decision") == "Approve"))
        c3.metric("Pending review", sum(1 for h in history if h.get("review_status") == "pending"))
        c4.metric("Rejected (final)", sum(1 for h in history if h.get("final_decision") == "Reject"))
        c5.metric("Reviewed by human", sum(1 for h in history if h.get("review_status") == "resolved"))

        st.divider()

        fcol1, fcol2 = st.columns([2, 1])
        with fcol1:
            decision_filter = st.multiselect(
                "Filter by final decision", ["Approve", "Flag", "Reject"],
                default=["Approve", "Flag", "Reject"]
            )
        with fcol2:
            group_by = st.selectbox("Group by", ["None", "Day"])

        filtered = [h for h in history if h.get("final_decision", h.get("decision")) in decision_filter]
        filtered_sorted = sorted(filtered, key=lambda h: h.get("processed_at", ""), reverse=True)

        def to_row(h):
            return {
                "Invoice #": h["invoice_number"],
                "Vendor": h["vendor"],
                "Amount": h.get("total_amount"),
                "Matched PO": h.get("matched_po") or h.get("po_number", "—"),
                "System decision": h.get("decision"),
                "Final decision": h.get("final_decision", h.get("decision")),
                "Review status": h.get("review_status", "finalized"),
                "Confidence": f"{h.get('confidence', '—')}%",
                "Reason": h.get("primary_reason", (h.get("reasons") or [""])[0]),
                "Processed at": h.get("processed_at", "")[:19].replace("T", " "),
            }

        if group_by == "Day":
            by_day = {}
            for h in filtered_sorted:
                day = h.get("processed_at", "")[:10] or "Unknown"
                by_day.setdefault(day, []).append(h)
            for day in sorted(by_day.keys(), reverse=True):
                st.markdown(f"#### {day}  ·  {len(by_day[day])} run(s)")
                st.dataframe([to_row(h) for h in by_day[day]], hide_index=True, use_container_width=True)
        else:
            st.dataframe([to_row(h) for h in filtered_sorted], hide_index=True, use_container_width=True)

        st.markdown("#### Inspect a run")
        options = [f"{h['invoice_number']} — {h['vendor']} ({h.get('processed_at','')[:19].replace('T',' ')})" for h in filtered_sorted]
        if options:
            idx = st.selectbox("Select a run", range(len(options)), format_func=lambda i: options[i])
            sel = filtered_sorted[idx]
            decision_badge(sel.get("final_decision", sel["decision"]), sel.get("confidence", 0))
            review_status_badge(sel)
            st.markdown("**Reasoning:**")
            for r in sel.get("reasons", []):
                st.markdown(f"- {r}")
            render_invoice_and_po_viewer(sel, key_prefix="dash")
            with st.expander("Full stage trace"):
                for s in sel.get("stages", []):
                    icon = STATUS_ICON.get(s["status"], "•")
                    st.markdown(f"{icon}  **{s['name']}** — {s['detail']}")

# ================= PAGE: Guide =================
elif st.session_state.page == "📘 Guide":
    st.markdown("### Guide — how this app works")

    st.markdown("""
#### What this is
An automated AP (Accounts Payable) invoice-processing pipeline. You give it a raw invoice PDF;
it extracts the fields, matches the invoice to a purchase order (PO), applies an approval policy,
and returns one of three calls: **Approve**, **Flag** (needs a human to decide), or **Reject**.

#### The policy, in plain terms
1. **Required fields** — vendor, invoice number, and total amount must all be present, or the
   invoice is rejected as unprocessable.
2. **Duplicate check** — the same (vendor, invoice number) seen before is rejected automatically.
3. **Vendor check** — the vendor must be on the approved vendor list, or it's flagged.
4. **PO matching** — if the invoice states a PO number, we look it up directly. If not, we try to
   infer it by matching vendor + amount against open POs (lower confidence, always flagged for a
   quick human check).
5. **Amount tolerance** — within the "pass" band of the matched PO: auto-pass. Within the "flag"
   band: flagged for review. Beyond that: rejected as a material overage.
6. **Confidence score** — reflects how clean the extraction was (a scanned PDF via OCR scores
   lower than a clean digital PDF) and how certain the PO match was (direct reference vs. inferred).

You can tune steps 4–6's thresholds yourself in **⚙️ Settings**.

#### Glossary
- **AP (Accounts Payable)** — the team that pays what the company owes vendors.
- **PO (Purchase Order)** — the company's own record of what it agreed to buy, issued *before*
  the invoice arrives.
- **Invoice** — the vendor's bill, sent *after* delivery, which should match the PO.
- **OCR (Optical Character Recognition)** — reads text out of a scanned/image PDF that has no
  selectable text layer.
- **Tolerance** — how much an invoice amount can differ from the matched PO before it's a problem.
- **Confidence score** — how sure the system is about its own decision.

#### How to use each tab
- **🔴 Live Run** — pick sample(s) from the sidebar dropdown or upload your own PDF(s), click
  **Run process**. You can run one file (full step-by-step animation) or several at once (batch
  summary with per-file detail).
- **🟡 Review Queue** — every **Flag** lands here. Open it, check the invoice/PO side by side,
  and Approve or Reject with an optional note. That becomes the final, audited decision.
- **📊 Dashboard** — the full run history. Filter by decision, group by day, and inspect any single
  run's full reasoning and stage trace.
- **⚙️ Settings** — adjust the tolerance bands, the OCR confidence cutoff, and add/remove custom
  fields the extractor should pull out of every invoice.

#### About the sample invoices
The sidebar's sample dropdown includes the happy path plus ten edge cases: a scanned invoice
(forces OCR), a missing PO reference, an amount just over tolerance, a duplicate, an unapproved
vendor, a missing total (unprocessable), a material overage (>10%, hard reject), a split-PO final
draw, and an ambiguous PO match. Together they exercise every branch of the policy above.
""")

# ================= PAGE: Settings =================
elif st.session_state.page == "⚙️ Settings":
    st.markdown("### Settings — tune the AP policy")
    st.caption("Changes apply to every run from now on. Past decisions are not retroactively recalculated.")

    cfg = st.session_state.config

    st.markdown("#### Amount tolerance")
    col1, col2 = st.columns(2)
    with col1:
        new_pass = st.number_input("Auto-pass tolerance (%)", min_value=0.0, max_value=50.0,
                                    value=float(cfg["tolerance_pass_pct"]), step=0.5,
                                    help="Invoice within this % of the matched PO auto-passes with no flag.")
    with col2:
        new_flag_upper = st.number_input("Flag-vs-reject cutoff (%)", min_value=0.0, max_value=100.0,
                                          value=float(cfg["tolerance_flag_upper_pct"]), step=1.0,
                                          help="Between the auto-pass line and this %, the invoice is flagged for review. Beyond this, it's rejected as a material overage.")

    st.markdown("#### OCR confidence")
    new_ocr = st.number_input("Flag scanned invoices below this OCR confidence (%)", min_value=0, max_value=100,
                               value=int(cfg["ocr_confidence_flag_threshold"]), step=5)

    st.markdown("#### Custom fields to extract")
    st.caption("Add any extra field you want pulled from every invoice. Pattern is a regex with one capture group; "
               "'Required' means a missing value causes an automatic reject.")
    custom_fields = cfg.get("custom_fields", [])
    edited = st.data_editor(
        custom_fields,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn("Field key", help="Internal name, no spaces, e.g. currency"),
            "label": st.column_config.TextColumn("Display label"),
            "pattern": st.column_config.TextColumn("Regex pattern", help=r"e.g. Currency:\s*([A-Z]{3})"),
            "required": st.column_config.CheckboxColumn("Required"),
        },
        key="custom_fields_editor",
    )

    if st.button("💾 Save settings", type="primary"):
        new_cfg = {
            "tolerance_pass_pct": new_pass,
            "tolerance_flag_upper_pct": new_flag_upper,
            "ocr_confidence_flag_threshold": new_ocr,
            "custom_fields": edited,
        }
        save_config(CONFIG_PATH, new_cfg)
        st.session_state.config = new_cfg
        st.success("Settings saved — new runs will use these thresholds.")
        st.rerun()
