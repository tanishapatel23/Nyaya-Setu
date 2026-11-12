"""Decide when to tell someone plainly that they need a real lawyer."""

from __future__ import annotations

import re

from . import kb

DISTRICT_LIMIT = 50_00_000   # Consumer Protection (Jurisdiction) Rules 2021


def check(case):
    fired = []
    low = (case.story + " " + " ".join(d.get("text", "") for d in case.docs)).lower()
    for rf in kb.red_flags():
        if any(re.search(p, low) for p in rf.get("triggers", [])):
            fired.append(rf["id"])

    if case.amount and case.amount > DISTRICT_LIMIT and case.problem in ("refund", "deposit", "salary"):
        fired.append("RF-amount")

    p = kb.problem(case.problem) if case.problem else None
    if p and p.get("limitation_days") and case.days_ago is not None:
        if case.days_ago > p["limitation_days"]:
            fired.append("RF-late")

    out = []
    for rid in fired:
        if rid not in out:
            out.append(rid)
    return [{"id": r, "message": kb.pick(kb.red_flag(r)["message"], _lang(case))} for r in out]


def _lang(case):
    return "hi" if case.lang == "hi" else "en"
