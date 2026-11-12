"""Matches a follow-up question to an answer in data/faq.yaml."""

from __future__ import annotations

import re

from . import kb

_QUESTION = re.compile(r"\?\s*$|^(what|how|can|could|should|will|would|do|does|is|are|why|when|who|which|"
                       r"kya|kaise|kab|kitna|kitne|agar|kyun)\b|^(क्या|कैसे|कब|कितना|अगर|क्यों)", re.I)


def is_question(text):
    return bool(_QUESTION.search(text.strip()))


def match(text, problem=None, min_score=2):
    """Best matching FAQ entry and its score, or (None, 0). Multi-word keys
    count double, and an entry for the current problem gets a small edge."""
    low = re.sub(r"notice\s+period", "noticeperiod", text.lower())
    best, best_s = None, 0
    for item in kb.faq():
        s = 0
        for k in map(str, item["keys"]):
            k = k.lower()
            if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", low):
                s += 2 if " " in k else 1
            elif " " in k and all(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low) for w in k.split()):
                s += 1.5
        if s and problem and problem in item["for"]:
            s += 1
        if s > best_s:
            best, best_s = item, s
    return (best, best_s) if best_s >= min_score else (None, best_s)


def suggestions(problem, n=4):
    return [f for f in kb.faq() if problem in f["for"] and f.get("show")][:n]
