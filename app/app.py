import sys
import os
import json
import time
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from extraction import extract_invoice
from decision_engine import run_decision_engine, load_json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEST_DIR = os.path.join(BASE_DIR, "test_invoices")
HISTORY_PATH = os.path.join(DATA_DIR, "run_history.json")
SEED_PATH = os.path.join(DATA_DIR, "processed_history_seed.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

VENDORS = load_json(os.path.join(DATA_DIR, "vendors.json"))["approved_vendors"]
POS = load_json(os.path.join(DATA_DIR, "pos.json"))["purchase_orders"]

st.set_page_config(page_title="AP Invoice Decision Engine", layout="wide", page_icon="🧾")

STATUS_ICON = {"pass": "✅", "flag": "⚠️", "fail": "❌", "info": "➖"}
DECISION_COLOR = {"Approve": "#1a7f37", "Flag": "#b35900", "Reject": "#c92a2a"}


def init_history():
    if not os.path.exists(HISTORY_PATH):
        seed = load_json(SEED_PATH)["processed_invoices"]
        with open(HISTORY_PATH, "w") as f:
            json.dump(seed, f, indent=2)


def load_history():
    init_history()
    return load_json(HISTORY_PATH)


def append_history(record):
    history = load_history()
    history.append(record)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def process_invoice(pdf_path, placeholder):
    """Runs extraction + decision engine, rendering each stage into `placeholder` as it completes."""
    history = load_history()
    stage_box = placeholder.container()
    stage_box.markdown("##### Live run")
    with stage_box:
        with st.spinner("Extracting fields from PDF..."):
            extracted = extract_invoice(pdf_path)
            time.sleep(0.4)
        method = extracted["extraction_method"]
        conf = extracted["extraction_confidence"]
        icon = "✅" if method == "text" else ("⚠️" if conf < 70 else "➖")
        st.markdown(f"{icon}  **Extract fields** — Method: {method.upper()}" +
                     (f", confidence {conf}%" if method == "ocr" else " (digital PDF)"))

        with st.spinner("Applying AP policy..."):
            result = run_decision_engine(extracted, VENDORS, POS, history)
            time.sleep(0.4)

        for s in result["stages"][1:]:  # skip duplicate "Extract fields" stage already shown
            icon = STATUS_ICON.get(s["status"], "•")
            st.markdown(f"{icon}  **{s['name']}** — {s['detail']}")
            time.sleep(0.15)

    return result


def decision_badge(decision, confidence):
    color = DECISION_COLOR.get(decision, "#555")
    st.markdown(
        f"""<div style="display:inline-block; padding:10px 20px; border-radius:8px;
        background:{color}1a; border:1.5px solid {color}; color:{color};
        font-weight:700; font-size:1.3rem;">{decision} — {confidence}% confidence</div>""",
        unsafe_allow_html=True,
    )


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("## 🧾 AP Invoice Engine")
    st.caption("Invoice → extraction → PO match → policy → decision")

    st.markdown("### Run an invoice")
    sample_files = sorted(os.listdir(TEST_DIR)) if os.path.exists(TEST_DIR) else []
    sample_choice = st.selectbox("Load a sample invoice", ["— none —"] + sample_files)
    uploaded = st.file_uploader("...or upload your own invoice PDF", type=["pdf"])

    run_clicked = st.button("▶ Run process", type="primary", use_container_width=True)

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

# ---------------- Main ----------------
tab_live, tab_dash = st.tabs(["🔴 Live Run", "📊 Dashboard"])

with tab_live:
    st.markdown("### Live Run")
    st.caption("Upload or pick a sample invoice, then click **Run process** in the sidebar.")

    if run_clicked:
        pdf_path = None
        label = None
        if uploaded is not None:
            pdf_path = os.path.join(UPLOAD_DIR, uploaded.name)
            with open(pdf_path, "wb") as f:
                f.write(uploaded.getbuffer())
            label = uploaded.name
        elif sample_choice != "— none —":
            pdf_path = os.path.join(TEST_DIR, sample_choice)
            label = sample_choice

        if pdf_path is None:
            st.warning("Upload a PDF or pick a sample invoice from the sidebar first.")
        else:
            st.markdown(f"**Processing:** `{label}`")
            placeholder = st.empty()
            result = process_invoice(pdf_path, placeholder)

            st.divider()
            col1, col2 = st.columns([1, 2])
            with col1:
                decision_badge(result["decision"], result["confidence"])
            with col2:
                st.markdown("**Reasoning**")
                for r in result["reasons"]:
                    st.markdown(f"- {r}")

            with st.expander("Extracted fields"):
                st.json({
                    "vendor": result["vendor"],
                    "invoice_number": result["invoice_number"],
                    "invoice_date": result["invoice_date"],
                    "total_amount": result["total_amount"],
                    "matched_po": result["matched_po"],
                    "extraction_method": result["extraction_method"],
                    "extraction_confidence": result["extraction_confidence"],
                })

            record = {
                "invoice_number": result["invoice_number"] or f"UNKNOWN-{int(time.time())}",
                "vendor": result["vendor"] or "Unknown",
                "invoice_date": result["invoice_date"],
                "total_amount": result["total_amount"],
                "po_number": result["matched_po"],
                "decision": result["decision"],
                "confidence": result["confidence"],
                "reasons": result["reasons"],
                "source_file": label,
                "processed_at": result["processed_at"],
            }
            append_history(record)
            st.success("Run recorded to dashboard history.")
    else:
        st.info("No run yet. Pick a sample invoice in the sidebar (try each edge case!) and click **Run process**.")

with tab_dash:
    st.markdown("### Dashboard — run history")
    history = load_history()

    if not history:
        st.info("No runs yet.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total runs", len(history))
        c2.metric("Approved", sum(1 for h in history if h["decision"] == "Approve"))
        c3.metric("Flagged", sum(1 for h in history if h["decision"] == "Flag"))
        c4.metric("Rejected", sum(1 for h in history if h["decision"] == "Reject"))

        st.divider()

        decision_filter = st.multiselect(
            "Filter by decision", ["Approve", "Flag", "Reject"], default=["Approve", "Flag", "Reject"]
        )
        filtered = [h for h in history if h["decision"] in decision_filter]
        filtered_sorted = sorted(filtered, key=lambda h: h.get("processed_at", ""), reverse=True)

        table_rows = [{
            "Invoice #": h["invoice_number"],
            "Vendor": h["vendor"],
            "Amount": h.get("total_amount"),
            "Matched PO": h.get("po_number", "—"),
            "Decision": h["decision"],
            "Confidence": f"{h.get('confidence', '—')}%",
            "Processed at": h.get("processed_at", "")[:19].replace("T", " "),
        } for h in filtered_sorted]

        st.dataframe(table_rows, hide_index=True, use_container_width=True)

        st.markdown("#### Inspect a run")
        options = [f"{h['invoice_number']} — {h['vendor']} ({h.get('processed_at','')[:19].replace('T',' ')})" for h in filtered_sorted]
        if options:
            idx = st.selectbox("Select a run", range(len(options)), format_func=lambda i: options[i])
            sel = filtered_sorted[idx]
            decision_badge(sel["decision"], sel.get("confidence", 0))
            st.markdown("**Reasoning:**")
            for r in sel.get("reasons", []):
                st.markdown(f"- {r}")
