"""Loads the knowledge base and answers simple lookups on it."""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass

import yaml

KB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "knowledge_base.yaml")


@functools.lru_cache(maxsize=1)
def _kb():
    with open(KB_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def pick(field, lang):
    """Fields are either plain strings or {en, hi} dicts."""
    if isinstance(field, dict):
        return (field.get(lang) or field.get("en") or "").strip()
    return (field or "").strip()


def disclaimer(lang="en"):
    return pick(_kb()["meta"]["disclaimer"], lang)


def last_verified():
    return _kb()["meta"]["last_verified"]


def problem_types():
    return _kb()["problem_types"]


def problem(pid):
    for p in problem_types():
        if p["id"] == pid:
            return p
    return None


@dataclass
class Fact:
    id: str
    problem_type: str
    statute: str
    section: str
    title: dict
    plain: dict
    source_note: str

    def cite(self):
        if self.statute and self.section:
            return f"{self.statute}, {self.section}"
        return self.statute or "General practice"


def facts(pid):
    out = []
    for f in _kb()["facts"]:
        if f["problem_type"] == pid:
            out.append(Fact(f["id"], f["problem_type"], f.get("statute", ""),
                            f.get("section", ""), f["title"], f["plain"],
                            f.get("source_note", "").strip()))
    return out


def fact(fid):
    for pt in problem_types():
        for f in facts(pt["id"]):
            if f.id == fid:
                return f
    return None


def helplines(pid):
    return [h for h in _kb()["helplines"] if pid in h["for"]]


def objections(pid):
    return _kb()["objections"].get(pid, [])


def questions(pid):
    return _kb()["questions"].get(pid, {})


def red_flags():
    return _kb()["red_flags"]


def red_flag(rid):
    for r in red_flags():
        if r["id"] == rid:
            return r
    return None


# --- classification ---------------------------------------------------------

_RECEIVED = re.compile(r"(received|got|get|came|sent me|served|aaya|mila|मिला|आया)\b[^.]{0,40}\bnotice|notice\b[^.]{0,25}\b(received|came|aaya|mila|मिला|आया)|notice from (a |the |my |his |her )?(lawyer|advocate|vakil)")
_SENDING = re.compile(r"(send|sending|draft|write|issue|bhejna|bhejni)\w*\s+(a\s+|him\s+a\s+|her\s+a\s+|them\s+a\s+)?(legal\s+)?notice")


def _hits(text, words):
    n = 0
    for w in words:
        if re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", text):
            n += 1
    return n


def classify(text):
    """
    Score each problem type: strong words count 3, weak words 1. Returns
    (problem_id or None, scores). None means nothing matched well enough, or
    two types are too close to call, and the app should ask.
    """
    low = re.sub(r"notice\s+period", "noticeperiod", text.lower())
    scores = {}
    for p in problem_types():
        scores[p["id"]] = 3 * _hits(low, p.get("strong", [])) + _hits(low, p.get("weak", []))
    if _SENDING.search(low) and not _RECEIVED.search(low):
        scores["notice"] = 0          # wanting to send a notice is not having received one
    elif _RECEIVED.search(low):
        scores["notice"] += 4
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < 2 or (s2 >= 2 and s1 - s2 <= 1):
        return None, scores
    return best, scores


def elsewhere(text):
    """Out of scope topic for this text, or None."""
    low = text.lower()
    for t in _kb().get("elsewhere", []):
        if any(re.search(p, low) for p in t["triggers"]):
            return t
    return None


def faq():
    path = os.path.join(os.path.dirname(KB_PATH), "faq.yaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["faq"]


# --- citation whitelist for the guard ---------------------------------------

SEC_RE = re.compile(r"(?:section|sec\.|धारा)\s*(\d+[a-z]?(?:\([0-9a-z]+\))?)", re.I)
ACT_RE = re.compile(r"([A-Z][A-Za-z ]*?(?:Act|Code),?\s+\d{4})")


def norm_act(s):
    return re.sub(r"\s+", " ", s.replace(",", "").strip().lower())


def allowed_citations(fact_list):
    """Every section number and Act the given facts actually mention."""
    acts, secs = set(), set()
    for f in fact_list:
        text = " ".join([f.statute, f.section, pick(f.plain, "en"), pick(f.title, "en")])
        if f.statute:
            acts.add(norm_act(f.statute))
        acts.update(norm_act(m) for m in ACT_RE.findall(text))
        secs.update(m.lower() for m in SEC_RE.findall(text))
    return {"acts": acts, "sections": secs}
