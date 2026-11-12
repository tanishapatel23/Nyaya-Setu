"""
Practice: the app plays the other side using the objections in the knowledge
base, then checks the user's answer for the points that actually win the
argument, and shows a model reply tied to a KB fact.
"""

from __future__ import annotations

import re

from . import kb


def rounds(problem):
    return kb.objections(problem)


def score(objection, answer):
    low = answer.lower()
    hit, miss = [], []
    for group in objection["key_points"]:
        if any(re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", low) for w in group):
            hit.append(group[0])
        else:
            miss.append(group[0])
    total = len(objection["key_points"])
    if not answer.strip():
        verdict = "empty"
    elif len(hit) == total:
        verdict = "strong"
    elif hit:
        verdict = "partial"
    else:
        verdict = "weak"
    f = kb.fact(objection["fact"])
    return {"verdict": verdict, "hit": hit, "miss": miss, "total": total,
            "model": objection["reply"].strip(),
            "basis": f"[{f.id}] {f.cite()}" if f else ""}


def _join(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def feedback(result):
    v = result["verdict"]
    if v == "strong":
        return "That covers everything that matters. Say it calmly and put it in writing afterwards."
    if v == "partial":
        return (f"Good start, you raised {_join(result['hit'])}. "
                f"To close it off, also bring in {_join(result['miss'])}.")
    if v == "weak":
        return (f"That answer lets them off the hook. Try bringing in {_join(result['miss'])}.")
    return "Type what you would say back, then check it."
