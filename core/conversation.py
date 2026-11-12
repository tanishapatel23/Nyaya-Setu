"""
The conversation loop. Takes a message and any attached files, and returns
the assistant's replies as a list of typed messages for the UI and tests.

Stages: start, clarify (we asked which problem), followup (we asked for a
missing fact), answered. After an answer, a message can be a question, a
correction, new facts, a new document, or a different problem altogether.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import advise, escalate, faq, intake, kb, llm, reader
from .intake import fmt_inr

_SKIP = re.compile(r"\b(skip|don'?t know|not sure|no idea|pata nahi|nahi pata|later)\b|पता नहीं", re.I)
_FACTISH = re.compile(r"\d|lakh|thousand|hazaar|hazar|\bk\b|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
                      r"yesterday|week|month|year|ago|pehle|लाख|हज़ार|हजार|पहले|महीने|साल", re.I)
_CORRECTION = re.compile(r"\b(actually|sorry|correction|i meant|not \d|it was|it is|wrong|galat|nahi balki)\b|ग़लत|गलत", re.I)


@dataclass
class Session:
    case: intake.Case | None = None
    stage: str = "start"
    forced_lang: str | None = None
    answer: dict | None = None
    flags: list = field(default_factory=list)
    today: dt.date | None = None
    case_id: int = 0
    pending: str = ""          # text of a different problem the user raised mid-case

    def lang(self):
        if self.forced_lang:
            return self.forced_lang
        return "hi" if self.case and self.case.lang == "hi" else "en"


def _today(s):
    return s.today or dt.date.today()


def _L(s, en, hi):
    return hi if s.lang() == "hi" else en


# --- documents ---------------------------------------------------------------

KIND_LABEL = {"notice": ("Legal notice", "कानूनी नोटिस"), "agreement": ("Rent agreement", "रेंट एग्रीमेंट"),
              "invoice": ("Bill or invoice", "बिल या इनवॉइस"), "job": ("Job document", "नौकरी का दस्तावेज़"),
              "unknown": ("Document", "दस्तावेज़")}


def _fmt(iso, lang):
    return advise.fmt_date(iso, lang) if iso else ""


def merge_doc(case, doc, today):
    """Fold what a document says into the case and the letter drafts."""
    f = doc.fields
    summary = {"name": doc.name, "kind": doc.kind, "method": doc.method, **f,
               "text": doc.text[:4000], "warnings": list(doc.warnings)}
    case.docs.append(summary)
    if case.problem is None and doc.problem:
        case.problem = doc.problem
    dr = case.draft
    if doc.kind == "notice":
        case.notice = f
        case.problem = "notice"
        if f.get("amount"):
            case.amount, case.amount_text = f["amount"], fmt_inr(f["amount"])
        if f.get("notice_date") and not case.date:
            nd = dt.date.fromisoformat(f["notice_date"])
            case.date, case.date_text, case.days_ago = nd.isoformat(), "notice date", (today - nd).days
        if f.get("days"):
            case.notice_days = f["days"]
        dr.setdefault("their_name", ", ".join(x for x in [f.get("advocate"), f.get("firm")] if x))
        dr.setdefault("their_address", f.get("firm_address", ""))
        dr.setdefault("your_name", f.get("to_name", ""))
        dr.setdefault("your_address", f.get("to_address", ""))
        if f.get("notice_date"):
            dr.setdefault("notice_date", _fmt(f["notice_date"], "en") + (f" (Ref. {f['ref']})" if f.get("ref") else ""))
    elif doc.kind == "agreement":
        if f.get("deposit"):
            case.deposit_known = f["deposit"]
            if case.problem == "deposit" and case.amount is None:
                case.amount, case.amount_text = f["deposit"], fmt_inr(f["deposit"])
        if "rent agreement" not in case.proof:
            case.proof.append("rent agreement")
        dr.setdefault("their_name", f.get("landlord", ""))
        dr.setdefault("their_address", f.get("landlord_address", ""))
        dr.setdefault("your_name", f.get("tenant", ""))
        dr.setdefault("premises", f.get("premises", ""))
    elif doc.kind == "invoice":
        if case.amount is None and f.get("amount"):
            case.amount, case.amount_text = f["amount"], fmt_inr(f["amount"])
        if not case.date and f.get("date"):
            d = dt.date.fromisoformat(f["date"])
            case.date, case.date_text, case.days_ago = d.isoformat(), "order date", (today - d).days
        for p in ("invoice or bill", "order id" if f.get("order_id") else None):
            if p and p not in case.proof:
                case.proof.append(p)
        dr.setdefault("their_name", f.get("seller", ""))
        dr.setdefault("their_address", f.get("seller_address", ""))
        dr.setdefault("your_name", f.get("buyer", ""))
        dr.setdefault("order_id", f.get("order_id", ""))
    elif doc.kind == "job":
        p = "salary slips" if f.get("net_pay") else "offer or appointment letter"
        if p not in case.proof:
            case.proof.append(p)
        dr.setdefault("their_name", f.get("employer", ""))
        dr.setdefault("designation", f.get("designation", ""))
    for k in [k for k, v in dr.items() if not v]:
        dr.pop(k)
    return summary


def explain_doc(summary, lang, today):
    """Rows and a plain-words note describing a document we read."""
    hi = lang == "hi"
    k = summary["kind"]
    rows, note = [], ""
    A = lambda v: fmt_inr(v) if isinstance(v, int) else v
    if k == "notice":
        rows = [(("Sent by", "किसने भेजा"), ", ".join(x for x in [summary.get("advocate"), summary.get("firm")] if x)),
                (("On behalf of", "किसकी ओर से"), summary.get("client")),
                (("Dated", "तारीख़"), _fmt(summary.get("notice_date"), lang)),
                (("Their claim", "उनका दावा"), summary.get("subject")),
                (("They want", "माँग"), (A(summary["amount"]) if summary.get("amount") else "") +
                 (f" within {summary['days']} days" if summary.get("days") and not hi else
                  f", {summary['days']} दिन में" if summary.get("days") else ""))]
        if summary.get("notice_date") and summary.get("days"):
            by = dt.date.fromisoformat(summary["notice_date"]) + dt.timedelta(days=summary["days"])
            rows.append((("Reply by", "जवाब की आख़िरी तारीख़"),
                         _fmt(by.isoformat(), lang) + (" (counted from the notice date)" if not hi else " (नोटिस की तारीख़ से)")))
        if hi:
            note = ("आसान शब्दों में: सामने वाले के वकील कह रहे हैं कि आप पर उनके क्लाइंट का पैसा बकाया है, और समय पर न देने पर वे केस कर सकते हैं। "
                    "यह माँग है, अदालत का केस नहीं। आप लिखित जवाब देकर इसका विरोध कर सकते हैं।")
        else:
            note = ("In plain words: the other side's lawyer says you owe their client money and that they may "
                    "go to court if you do not pay in time. This is a demand, not a court case. You can dispute "
                    "it with a written reply.")
            if summary.get("route") == "criminal":
                note = ("In plain words: this notice talks about criminal action, which is more serious than a "
                        "money demand. Please speak to a lawyer before replying.")
    elif k == "agreement":
        rows = [(("Landlord", "मकान मालिक"), summary.get("landlord")), (("Tenant", "किरायेदार"), summary.get("tenant")),
                (("Property", "मकान"), summary.get("premises")), (("Rent", "किराया"), A(summary.get("rent"))),
                (("Security deposit", "सिक्योरिटी डिपॉज़िट"), A(summary.get("deposit"))),
                (("Starts", "शुरुआत"), _fmt(summary.get("start_date"), lang)),
                (("Notice clause", "नोटिस की शर्त"), summary.get("notice_period"))]
        note = ("मैंने डिपॉज़िट की रकम और मकान मालिक की जानकारी आपके केस और चिट्ठी में जोड़ दी है।" if hi else
                "I have added the deposit and the landlord's details to your case and your letter.")
    elif k == "invoice":
        rows = [(("Seller", "विक्रेता"), summary.get("seller")), (("Order ID", "ऑर्डर आईडी"), summary.get("order_id")),
                (("Invoice no.", "इनवॉइस नंबर"), summary.get("invoice_no")),
                (("Order date", "ऑर्डर की तारीख़"), _fmt(summary.get("date"), lang)),
                (("Amount paid", "चुकाई रकम"), A(summary.get("amount"))),
                (("Return window", "रिटर्न का समय"), f"{summary['return_days']} days" if summary.get("return_days") else None)]
        note = ("मैंने रकम, तारीख़ और विक्रेता की जानकारी आपके केस में जोड़ दी है।" if hi else
                "I have added the amount, date and seller to your case and your letter.")
    elif k == "job":
        rows = [(("Employer", "कंपनी"), summary.get("employer")), (("Role", "पद"), summary.get("designation")),
                (("Net pay", "हाथ में वेतन"), A(summary.get("net_pay"))), (("CTC", "CTC"), A(summary.get("ctc"))),
                (("Joined", "जॉइनिंग"), _fmt(summary.get("joining"), lang))]
        note = ("मैंने कंपनी की जानकारी आपके केस में जोड़ दी है।" if hi else "I have added the employer's details to your case.")
    else:
        note = ("यह नोटिस, एग्रीमेंट या बिल नहीं लगता, इसलिए मैंने इसे आपकी कहानी के हिस्से की तरह पढ़ा है। कुछ छूटा हो तो बताइए।" if hi else
                "This does not look like a notice, agreement or bill, so I have read it as part of your story. Tell me if I missed something.")
    warn = []
    if summary["method"] == "ocr":
        warn.append("फ़ोटो से पढ़ा गया है, कृपया नाम और रकम एक बार जाँच लें।" if hi else
                    "Read from a photo, so please check the names and numbers.")
    missing = {"no_pdf": "pypdf", "no_ocr": "rapidocr-onnxruntime", "no_docx": "python-docx"}
    lib = next((missing[w] for w in summary.get("warnings", []) if w in missing), None)
    if not summary.get("text", "").strip() and lib:
        note = (f"यह फ़ाइल पढ़ने के लिए ज़रूरी लाइब्रेरी ({lib}) इस कंप्यूटर पर इंस्टॉल नहीं है। ऐप के फ़ोल्डर में "
                "pip install -r requirements.txt चलाएँ और ऐप दोबारा शुरू करें। तब तक मुख्य बातें टाइप कर दें।" if hi else
                f"I could not open this file because a library it needs ({lib}) is not installed on this computer. "
                "Run pip install -r requirements.txt in the app folder and restart the app. Until then, type the key details.")
    elif not summary.get("text", "").strip():
        note = ("इस फ़ाइल में मुझे कोई टेक्स्ट नहीं मिला। फ़ोटो हो तो सीधी और साफ़ रोशनी में दोबारा लें, या मुख्य बातें टाइप करें।" if hi else
                "I could not find any text in this file. If it is a photo, try a clearer one taken straight on in good light, or type the key details.")
    rows = [(lab[1] if hi else lab[0], v) for lab, v in rows if v]
    label = KIND_LABEL.get(k, KIND_LABEL["unknown"])[1 if hi else 0]
    return {"title": label, "file": summary["name"], "rows": rows, "note": note, "warn": warn,
            "raw": summary.get("text", ""), "method": summary.get("method", ""), "why": summary.get("warnings", [])}


# --- replies -----------------------------------------------------------------

def _ask_type(s, scores=None):
    order = [p["id"] for p in kb.problem_types()]
    if scores:
        order.sort(key=lambda p: -scores.get(p, 0))
    return {"type": "choose", "options": order, "flags": s.flags,
            "text": _L(s, "I can help with four kinds of problems. Which one is closest to yours? "
                          "If it is none of these, tap Something else.",
                       "मैं इन चार तरह की समस्याओं में मदद करता हूँ। आपकी समस्या किससे सबसे ज़्यादा मिलती है? "
                       "इनमें से कोई न हो तो 'कुछ और' दबाएँ।")}


def _ask_missing(s, miss, again=False):
    qs = kb.questions(s.case.problem)
    lang = s.lang()
    label = kb.pick(kb.problem(s.case.problem)["label"], lang)
    asks = [kb.pick(qs[m], lang) for m in miss if m in qs]
    if again:
        head = "जब तैयार हों, बस यह बताइए:" if lang == "hi" else "Whenever you are ready, just tell me:"
        return {"type": "text", "text": head + "\n" + "\n".join(f"- {a}" for a in asks)}
    if lang == "hi":
        head = f"समझ गया, मामला है: {label}। सही तारीख़ें बताने के लिए बस " + ("दो बातें" if len(asks) > 1 else "एक बात") + " बताइए:"
        tail = "पता न हो तो 'पता नहीं' लिख दें। आप रेंट एग्रीमेंट, बिल या नोटिस भी अटैच कर सकते हैं।"
    else:
        head = f"Got it, this is about: {label.lower()}. " + ("Two quick things" if len(asks) > 1 else "One quick thing") + " so I can give you exact dates:"
        tail = "If you are not sure, just say so. You can also attach the agreement, bill or notice instead."
    return {"type": "text", "flags": s.flags, "text": head + "\n" + "\n".join(f"- {a}" for a in asks) + "\n\n" + tail}


def _answer(s):
    s.flags = escalate.check(s.case)
    s.answer = advise.build_answer(s.case, _today(s), s.lang())
    s.stage = "answered"
    return [{"type": "answer", "answer": s.answer, "flags": s.flags}]


def _after_type(s):
    miss = intake.missing(s.case)
    if miss and s.stage != "followup":
        s.stage = "followup"
        s.flags = escalate.check(s.case)
        return [_ask_missing(s, miss)]
    return _answer(s)


def _faq_msg(s, item):
    return {"type": "faq", "q": kb.pick(item["q"], s.lang()), "a": kb.pick(item["a"], s.lang())}


def _elsewhere_msg(s, topic):
    return {"type": "elsewhere", "text": kb.pick(topic["message"], s.lang())}


def choose_problem(s, pid):
    if pid == "other":
        s.stage = "start"
        return [{"type": "elsewhere", "text": _L(
            s, "I only handle deposits, refunds, unpaid salary and legal notices for now, so I would rather "
               "not guess. For anything else, NALSA's free helpline 15100 can point you to the right place, "
               "and the emergency number is 112.",
            "अभी मैं सिर्फ़ डिपॉज़िट, रिफंड, बकाया वेतन और कानूनी नोटिस संभालता हूँ, इसलिए अंदाज़ा नहीं लगाऊँगा। "
            "बाकी किसी भी बात के लिए NALSA की मुफ़्त हेल्पलाइन 15100 सही जगह बता सकती है, और आपात नंबर 112 है।")}]
    s.case.problem = pid
    return _after_type(s)


def switch_case(s):
    """Start a new case from the different problem the user raised."""
    text, forced, cid = s.pending, s.forced_lang, s.case_id
    new = Session(forced_lang=forced, today=s.today, case_id=cid + 1)
    s.__dict__.update(new.__dict__)
    return reply(s, text)


def apply_edits(s, amount=None, date=None, city=None, problem=None):
    """Edits made in the case file panel."""
    c = s.case
    if problem and problem != c.problem:
        c.problem = problem
    if amount:
        c.amount, c.amount_text = int(amount), fmt_inr(int(amount))
    if date and date.isoformat() != c.date:
        c.date, c.date_text, c.days_ago = date.isoformat(), "edited", (_today(s) - date).days
    if city is not None:
        c.city = city.strip()
    return [{"type": "text", "text": _L(s, "Updated your case details.", "आपके केस की जानकारी अपडेट कर दी है।")}] + _answer(s)


def reply(s, text="", files=()):
    today = _today(s)
    text = (text or "").strip()
    out = []

    docs = [reader.read(n, b) for n, b in files]
    if text and reader.looks_like_pasted_notice(text):
        docs.append(reader.read("pasted text.txt", text.encode()))

    fresh = s.case is None
    if fresh:
        s.case = intake.structure_case(text, today)
        s.stage = "start"
    for d in docs:
        if d.kind != "unknown" and not d.fields:
            d.kind = "unknown"      # looked like a known document but nothing could be read from it
        if d.kind == "unknown" and d.text.strip():
            intake.update_case(s.case, d.text[:2000], today)
        summary = merge_doc(s.case, d, today)
        out.append({"type": "doc", "doc": explain_doc(summary, s.lang(), today)})

    # --- before we know the problem ---
    if s.stage in ("start", "clarify"):
        if text and not fresh:
            intake.update_case(s.case, text, today)
        if s.case.problem is None:
            s.flags = escalate.check(s.case)
            topic = kb.elsewhere(text) if text else None
            if topic:
                return out + [_elsewhere_msg(s, topic)]
            item, score = faq.match(text) if text else (None, 0)
            if item and faq.is_question(text):
                out.append(_faq_msg(s, item))
            _, scores = kb.classify(s.case.story)
            s.stage = "clarify"
            return out + [_ask_type(s, scores)]
        if text and faq.is_question(text):
            item, _ = faq.match(text, s.case.problem, min_score=3)
            if item:
                out.append(_faq_msg(s, item))
        return out + _after_type(s)

    if s.stage == "followup":
        topic = kb.elsewhere(text) if text else None
        if topic and not docs:
            ask = _ask_missing(s, intake.missing(s.case))
            return out + [_elsewhere_msg(s, topic), {"type": "text", "text": _L(
                s, "If you still want help with your earlier problem, answer the question above whenever you are ready.",
                "अगर आपको पहली समस्या में भी मदद चाहिए, तो ऊपर वाले सवाल का जवाब कभी भी दे दें।")}] if ask else out + [_elsewhere_msg(s, topic)]
        if text and faq.is_question(text):
            item, _ = faq.match(text, s.case.problem, min_score=3)
            if item:
                return out + [_faq_msg(s, item), _ask_missing(s, intake.missing(s.case), again=True)]
        if text and not _SKIP.search(text):
            intake.update_case(s.case, text, today)
        return out + _answer(s)

    # --- after an answer ---
    if docs and not text:
        return out + _answer(s)
    if not text:
        return out

    other, scores = kb.classify(text)
    if other and other != s.case.problem and scores[other] >= 3 and not faq.is_question(text):
        s.pending = text
        label = kb.pick(kb.problem(other)["label"], s.lang())
        return out + [{"type": "switch", "pid": other, "text": _L(
            s, f"That sounds like a separate problem: {label.lower()}. Want to start a new case for it? "
               "Your current case stays in this chat above.",
            f"यह एक अलग समस्या लगती है: {label}। क्या इसके लिए नया केस शुरू करें? मौजूदा केस ऊपर इसी चैट में रहेगा।")}]

    asking = faq.is_question(text)
    item, _ = faq.match(text, s.case.problem, min_score=2 if asking else 4)
    if item:
        return out + [_faq_msg(s, item)]

    before = (s.case.amount, s.case.date, tuple(s.case.proof), s.case.city)
    override = bool(_CORRECTION.search(text)) or (len(text.split()) <= 12 and bool(_FACTISH.search(text)))
    flags_before = [f["id"] for f in s.flags]
    intake.update_case(s.case, text, today, override=override)
    after = (s.case.amount, s.case.date, tuple(s.case.proof), s.case.city)
    if after != before:
        changed = []
        if after[0] != before[0]:
            changed.append(_L(s, f"amount {fmt_inr(after[0])}", f"रकम {fmt_inr(after[0])}"))
        if after[1] != before[1]:
            changed.append(_L(s, f"date {advise.fmt_date(after[1], 'en')}", f"तारीख़ {advise.fmt_date(after[1], 'hi')}"))
        if after[2] != before[2]:
            changed.append(_L(s, "your proof", "आपके सबूत"))
        if after[3] != before[3]:
            changed.append(_L(s, f"city {after[3]}", f"शहर {after[3]}"))
        return out + [{"type": "text", "text": _L(s, "Updated: ", "अपडेट किया: ") + ", ".join(changed) + "."}] + _answer(s)

    topic = kb.elsewhere(text)
    if topic:
        return out + [_elsewhere_msg(s, topic)]

    if [f["id"] for f in escalate.check(s.case)] != flags_before:
        return out + _answer(s)

    _, scores = kb.classify(text)
    if not asking and (any(scores.values()) or intake.parse_proof(text)):
        if s.case.problem == "refund":
            s.case.draft.setdefault("issue", text[:160])
        return out + [{"type": "text", "suggest": s.answer.get("suggest", []), "text": _L(
            s, "Noted, I have added that to your case file. Your plan above still stands. If any number or date "
               "has changed, tell me the new one and I will redo the dates.",
            "ठीक है, यह बात मैंने आपकी केस फ़ाइल में जोड़ दी है। ऊपर वाला प्लान वही रहेगा। कोई रकम या तारीख़ बदली हो तो "
            "नई बताइए, मैं तारीख़ें फिर से निकाल दूँगा।")}]

    if asking and llm.provider() != "demo":
        ans = llm.answer_question(s.case, s.answer, text, s.lang())
        if ans:
            return out + [{"type": "faq", "q": text, "a": ans, "model": True}]

    sugg = s.answer.get("suggest", []) if s.answer else []
    if asking:
        msg = _L(s, "I am not sure I have a reliable answer to that, and I would rather not guess. "
                    "Here are things I can answer, or call NALSA on 15100 for free advice.",
                 "इसका पक्का जवाब मेरे पास नहीं है, और मैं अंदाज़ा नहीं लगाना चाहता। नीचे वाले सवालों के जवाब मैं दे सकता हूँ, "
                 "या मुफ़्त सलाह के लिए NALSA 15100 पर कॉल करें।")
    else:
        msg = _L(s, "I did not quite follow that. You can correct a detail (for example, it was 50,000 not 40,000), "
                    "attach a document, or ask one of these:",
                 "यह मैं ठीक से समझ नहीं पाया। आप कोई जानकारी सुधार सकते हैं (जैसे, रकम 50,000 थी, 40,000 नहीं), "
                 "कोई दस्तावेज़ अटैच कर सकते हैं, या इनमें से कुछ पूछ सकते हैं:")
    return out + [{"type": "text", "suggest": sugg, "text": msg}]
