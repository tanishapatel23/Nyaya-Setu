"""
Citation guard.

Any sentence that cites a section or an Act not present in the facts we
retrieved for this case is dropped before the user sees it. On the offline
composer this never fires, since it only uses KB text. It exists to keep a
connected model honest, and to give us a number to test: invented citations
that reached the user.
"""

from __future__ import annotations

import re

from .kb import ACT_RE, SEC_RE, norm_act

_SPLIT = re.compile(r"(?<=[.!?।])\s+")


def verify(text, allowed, strict=True):
    violations, kept = [], []
    for para in text.split("\n"):
        if not para.strip():
            kept.append("")
            continue
        out = []
        for sent in _SPLIT.split(para):
            bad = False
            for m in SEC_RE.finditer(sent):
                if m.group(1).lower() not in allowed["sections"]:
                    violations.append({"type": "section", "value": m.group(0)})
                    bad = True
            for m in ACT_RE.finditer(sent):
                found = norm_act(m.group(1))
                if not any(found == a or found in a or a in found for a in allowed["acts"]):
                    violations.append({"type": "act", "value": m.group(1).strip()})
                    bad = True
            if not (bad and strict):
                out.append(sent)
        kept.append(" ".join(out))
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if strict and violations:
        clean += ("\n\n(Part of this answer was removed because it cited a law "
                  "I could not verify.)")
    return {"clean_text": clean, "violations": violations, "ok": not violations}
