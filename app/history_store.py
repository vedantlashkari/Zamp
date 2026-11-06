"""Load/save/append the run history, and apply human review decisions to it."""
import json
import os
from datetime import datetime


def init_history(history_path: str, seed_path: str):
    if not os.path.exists(history_path):
        with open(seed_path) as f:
            seed = json.load(f)["processed_invoices"]
        # Normalize seed records to the full schema so the UI never has to guess.
        for r in seed:
            r.setdefault("review_status", "finalized")
            r.setdefault("final_decision", r.get("decision"))
            r.setdefault("reviewed_by", None)
            r.setdefault("review_reason", None)
            r.setdefault("reviewed_at", None)
            r.setdefault("source_file", None)
            r.setdefault("reason_categories", [])
            r.setdefault("primary_reason", r.get("reasons", [""])[0] if r.get("reasons") else "")
        with open(history_path, "w") as f:
            json.dump(seed, f, indent=2)


def load_history(history_path: str) -> list:
    with open(history_path) as f:
        return json.load(f)


def save_history(history_path: str, history: list):
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


def append_record(history_path: str, record: dict):
    history = load_history(history_path)
    history.append(record)
    save_history(history_path, history)


def apply_review(history_path: str, invoice_number: str, vendor: str, processed_at: str,
                  new_decision: str, reviewer: str, reason: str):
    """Finds the matching pending record and applies a human Approve/Reject override."""
    history = load_history(history_path)
    for r in history:
        if (r["invoice_number"] == invoice_number and r["vendor"] == vendor
                and r.get("processed_at") == processed_at):
            r["final_decision"] = new_decision
            r["review_status"] = "resolved"
            r["reviewed_by"] = reviewer
            r["review_reason"] = reason
            r["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
            break
    save_history(history_path, history)
