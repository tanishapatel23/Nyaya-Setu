"""HTML pieces for the Streamlit app. Kept apart so app.py stays readable."""

from __future__ import annotations

from html import escape as e

from core import advise, kb
from core.intake import fmt_inr

T = {
    "en": {"deadline": "Time limit", "steps": "What to do next", "proof": "Your proof",
           "have": "You have", "get": "Worth getting", "based": "Based on",
           "checked": "Law checked by hand on", "clean": "No unverified law in this answer",
           "file": "Case file", "problem": "Problem", "amount": "Amount", "date": "Key date",
           "place": "Place", "proofk": "Proof", "help": "Free help", "left": "left to act",
           "passed": "time limit passed", "none_yet": "Tell me what happened and I will build your case file here.",
           "unknown": "not yet", "flag": "Please read first"},
    "hi": {"deadline": "समय सीमा", "steps": "आगे क्या करें", "proof": "आपके सबूत",
           "have": "आपके पास है", "get": "जुटाने लायक", "based": "आधार",
           "checked": "कानून की जाँच हाथ से की गई", "clean": "इस जवाब में कोई बिना जाँचा कानून नहीं",
           "file": "केस फ़ाइल", "problem": "समस्या", "amount": "रकम", "date": "मुख्य तारीख़",
           "place": "जगह", "proofk": "सबूत", "help": "मुफ़्त मदद", "left": "कदम उठाने के लिए बाकी",
           "passed": "समय सीमा निकल गई", "none_yet": "बताइए क्या हुआ, मैं यहाँ आपकी केस फ़ाइल बनाता जाऊँगा।",
           "unknown": "अभी नहीं", "flag": "पहले यह पढ़ें"},
}


def flags_html(flags, lang):
    if not flags:
        return ""
    t = T[lang]
    return "".join(f'<div class="hq-flag"><b>{t["flag"]}.</b> {e(f["message"])}</div>' for f in flags)


def _deadline_class(dl):
    if not dl or dl["date"] is None:
        return "hq-none"
    if dl["days_left"] < 0:
        return "hq-late"
    if dl["days_left"] <= 180:
        return "hq-soon"
    return "hq-ok"


def _big(dl, lang):
    if not dl or dl["date"] is None:
        return "?"
    d = dl["days_left"]
    if d < 0:
        return "Late" if lang == "en" else "देर"
    if d < 120:
        return f"{d} {'days' if lang == 'en' else 'दिन'}"
    y = round(d / 365, 1)
    if y >= 1:
        return f"{y:g} {'yrs' if lang == 'en' else 'साल'}"
    return f"{round(d / 30)} {'mo' if lang == 'en' else 'महीने'}"


def answer_html(ans):
    lang = ans["lang"]
    t = T[lang]
    h = [f'<div class="hq-card"><span class="hq-label">{e(ans["label"])}</span>',
         f'<p class="hq-summary">{e(ans["summary"])}</p>', insights_html(ans.get("insights"), lang)]
    dl = ans["deadline"]
    if dl:
        h.append(f'<div class="hq-deadline {_deadline_class(dl)}"><div class="big">{_big(dl, lang)}</div>'
                 f'<div class="small"><b>{t["deadline"]}.</b> {e(dl["text"])}</div></div>')
    h.append(f'<div class="hq-h">{t["steps"]}</div><ol class="hq-steps">')
    for when, what in ans["steps"]:
        h.append(f'<li><span class="hq-when">{e(when)}</span><div class="hq-what">{e(what)}</div></li>')
    h.append("</ol>")
    if ans["proof_have"] or ans["proof_get"]:
        h.append(f'<div class="hq-h">{t["proof"]}</div><div class="hq-proof">')
        for p in ans["proof_have"]:
            h.append(f'<div class="hq-pi"><span class="hq-dot hq-have"></span><span>{e(advise.proof_label(p, lang))}</span></div>')
        for p, why in ans["proof_get"]:
            sub = f'<span class="hq-why">{e(why)}</span>' if why and lang == "en" else ""
            h.append(f'<div class="hq-pi"><span class="hq-dot hq-get"></span><span>{e(advise.proof_label(p, lang))}{sub}</span></div>')
        h.append("</div>")
    ids = ", ".join(x["id"] for x in ans["law"])
    status = t["clean"] if not ans["violations"] else f'{len(ans["violations"])} unverified citation(s) removed'
    h.append(f'<div class="hq-foot"><span>{t["based"]} {ids} &middot; {t["checked"]} {kb.last_verified()}</span>'
             f'<span class="hq-ok-dot">{status}</span></div></div>')
    return "".join(h)


def case_file_html(case, ans, flags, lang):
    t = T[lang]
    if case is None:
        return (f'<div class="hq-file"><h3>{t["file"]}</h3><div class="hq-empty-icon">&#9878;</div>'
                f'<div class="hq-empty">{t["none_yet"]}</div></div>')
    u = f'<span class="hq-muted">{t["unknown"]}</span>'
    prob = e(kb.pick(kb.problem(case.problem)["label"], lang)) if case.problem else u
    amt = e(fmt_inr(case.amount).replace("Rs ", "₹" if lang == "hi" else "Rs ")) if case.amount else u
    date = e(advise.fmt_date(case.date, lang)) if case.date else u
    place = e(case.city) if case.city else u
    proof = e(", ".join(advise.proof_label(p, lang) for p in case.proof).capitalize()) if case.proof else u
    rows = [(t["problem"], prob), (t["amount"], amt), (t["date"], date), (t["place"], place), (t["proofk"], proof)]
    h = [f'<div class="hq-file"><h3>{t["file"]}</h3>']
    h += [f'<div class="hq-row"><span class="hq-k">{k}</span><span class="hq-v">{v}</span></div>' for k, v in rows]
    if case.docs:
        names = ", ".join(e(d["name"]) for d in case.docs)
        h.append(f'<div class="hq-row"><span class="hq-k">{"दस्तावेज़" if lang == "hi" else "Documents"}</span>'
                 f'<span class="hq-v">{names}</span></div>')
    if ans and ans["deadline"] and ans["deadline"]["date"]:
        dl = ans["deadline"]
        sub = t["passed"] if dl["days_left"] < 0 else t["left"]
        h.append(f'<div class="hq-count {_deadline_class(dl)}"><div class="n">{_big(dl, lang)}</div><div class="t">{sub}</div></div>')
    if flags:
        h.append(f'<div class="hq-flag" style="margin-top:.8rem">{e(flags[0]["message"])}</div>')
    if ans:
        h.append(f'<div class="hq-help"><div class="hq-k">{t["help"]}</div>')
        for x in ans["help"]:
            h.append(f'<div><b>{e(x["name"])}</b><br>{e(x["contact"])}</div>')
        h.append("</div>")
    h.append("</div>")
    return "".join(h)


def law_html(ans):
    h = []
    for x in ans["law"]:
        h.append(f'<div class="hq-law"><div class="t">{e(x["title"])}</div><div class="x">{e(x["text"])}</div>'
                 f'<span class="hq-chip">{e(x["id"])} &middot; {e(x["cite"])}</span>'
                 f'<div class="hq-src">{e(x["note"])}</div></div>')
    return "".join(h)


def paper_html(doc):
    h = ['<div class="hq-paper">']
    if doc.get("court"):
        h.append(f'<div class="c">{e(doc["court"])}</div>')
        h += [f'<div class="c" style="font-weight:400">{e(p)}</div>' for p in doc["parties"]]
    h.append(f'<div class="c">{e(doc["title"])}</div><div class="r">Date: {e(doc["date"])}</div>')
    if not doc.get("court"):
        h.append(f'<p><b>From:</b><br>{"<br>".join(e(x) for x in doc["from"])}</p>')
        h.append(f'<p><b>To:</b><br>{"<br>".join(e(x) for x in doc["to"])}</p>')
    h.append(f'<div class="u">Subject: {e(doc["subject"])}</div>')
    if not doc.get("court"):
        h.append("<p>Sir or Madam,</p>")
    h += [f"<p>{i}. {e(p)}</p>" for i, p in enumerate(doc["paras"], 1)]
    h.append(f'<p style="margin-top:1rem">{e(doc["closing"])}</p><p><b>{e(doc["signature"])}</b></p>')
    h.append('<div class="notes">' + "<br>".join(e(n) for n in doc["notes"]) + "</div></div>")
    return "".join(h)


def doc_html(d):
    rows = "".join(f'<div class="hq-row"><span class="hq-k">{e(k)}</span><span class="hq-v">{e(str(v))}</span></div>'
                   for k, v in d["rows"])
    warn = "".join(f'<div class="hq-warn">{e(w)}</div>' for w in d["warn"])
    return (f'<div class="hq-card hq-doc"><div class="hq-doc-head"><span class="hq-label">{e(d["title"])}</span>'
            f'<span class="hq-file-name">{e(d["file"])}</span></div>{rows}'
            f'<p class="hq-doc-note">{e(d["note"])}</p>{warn}</div>')


def faq_html(m):
    tag = '<span class="hq-chip">model answer, citations checked</span>' if m.get("model") else ""
    return f'<div class="hq-card hq-faq"><div class="hq-q">{e(m["q"])}</div><div class="hq-a">{e(m["a"])}</div>{tag}</div>'


def elsewhere_html(text):
    return f'<div class="hq-card hq-else">{e(text)}</div>'


def insights_html(items, lang):
    if not items:
        return ""
    head = "ध्यान दें" if lang == "hi" else "Worth knowing"
    lis = "".join(f"<li>{e(x)}</li>" for x in items)
    return f'<div class="hq-insight"><div class="hq-h" style="margin-top:0">{head}</div><ul>{lis}</ul></div>'
