"""
Builds the answer for a case: where the person stands, what to do and by when,
what proof to gather, and where to get free help.

Everything here is computed from the case and the knowledge base. A connected
model may rewrite the opening summary in friendlier words, but the dates, the
steps and the law stay as computed, and the summary goes through the guard.
"""

from __future__ import annotations

import datetime as dt
import re

from . import faq, guard, kb, llm
from .intake import fmt_inr

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त",
             "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def _have(case):
    """Proof the user has, counting documents they attached."""
    have = list(case.proof)
    kinds = {d["kind"] for d in case.docs}
    if "notice" in kinds and "the notice and its envelope" not in have:
        have.insert(0, "the notice and its envelope")
    return have


def _covered(case):
    """Proof already covered by an attached document of another name."""
    kinds = {d["kind"] for d in case.docs}
    return {"your own records of the deal"} if kinds & {"agreement", "invoice", "job"} else set()


def _unpaid_span(case):
    return bool(re.search(r"^(for|since|from)\b|(se|से)$", (case.date_text or "").strip()))


def fmt_date(d, lang):
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    if lang == "hi":
        return f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}"
    return f"{d.day} {d.strftime('%b %Y')}"


def _ago(days, lang):
    if days is None:
        return ""
    if lang == "hi":
        if days <= 1:
            return "कल" if days == 1 else "आज"
        if days < 14:
            return f"{days} दिन पहले"
        if days < 60:
            return f"लगभग {round(days / 7)} हफ़्ते पहले"
        if days < 730:
            return f"लगभग {round(days / 30)} महीने पहले"
        return f"लगभग {round(days / 365)} साल पहले"
    if days <= 1:
        return "yesterday" if days == 1 else "today"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"about {round(days / 7)} weeks ago"
    if days < 730:
        n = round(days / 30)
        return f"about {n} month{'s' if n != 1 else ''} ago"
    n = round(days / 365)
    return f"about {n} year{'s' if n != 1 else ''} ago"


def _left(days, lang):
    if days < 120:
        return f"{days} दिन" if lang == "hi" else f"{days} day{'s' if days != 1 else ''}"
    y, m = divmod(round(days / 30.4), 12)
    if lang == "hi":
        parts = ([f"{y} साल"] if y else []) + ([f"{m} महीने"] if m else [])
        return "लगभग " + " ".join(parts)
    parts = ([f"{y} year{'s' if y > 1 else ''}"] if y else []) + ([f"{m} month{'s' if m > 1 else ''}"] if m else [])
    return "about " + " and ".join(parts)


def _when(case, lang):
    if not case.date:
        return ""
    ago = _ago(case.days_ago, lang)
    if lang == "hi":
        return f"{ago} ({fmt_date(case.date, lang)} के आसपास)"
    return f"{ago} (around {fmt_date(case.date, lang)})"


# --- the situation in the person's own facts --------------------------------

def _situation(case, lang):
    amt = fmt_inr(case.amount) if case.amount else None
    w = _when(case, lang)
    p = case.problem
    if lang == "hi":
        amt_hi = amt.replace("Rs ", "₹") if amt else None
        if p == "deposit":
            a = f"आपने {amt_hi} का डिपॉज़िट दिया था" if amt_hi else "आपने सिक्योरिटी डिपॉज़िट दिया था"
            b = f" और {w} मकान खाली किया।" if w else " और मकान खाली कर दिया है।"
            return a + b
        if p == "refund":
            a = f"आपने {amt_hi} दिए" if amt_hi else "आपने पैसे दिए"
            if case.date_text == "order date":
                return a + f" ({fmt_date(case.date, lang)} को), पर आपको वह नहीं मिला जिसके लिए पैसे दिए थे।"
            b = f" और {w} से समस्या है।" if w else " पर आपको वह नहीं मिला जिसके लिए पैसे दिए थे।"
            return a + b
        if p == "salary":
            a = f"आपका लगभग {amt_hi} वेतन बाकी है" if amt_hi else "आपका वेतन बाकी है"
            b = (f", और यह लगभग {fmt_date(case.date, lang)} से बाकी है।" if _unpaid_span(case)
                 else f", और आपका आख़िरी दिन {w} था।" if w else "।")
            return a + b
        if p == "notice":
            n = case.notice
            if n:
                who = n.get("advocate") or n.get("firm") or "एक वकील"
                part = f"{who} ने" + (f" {n['client']} की ओर से" if n.get("client") else "") + " आपको नोटिस भेजा है"
                if case.amount:
                    part += f", जिसमें {amt_hi} माँगे गए हैं"
                if n.get("days"):
                    part += f" और {n['days']} दिन का समय दिया है"
                return part + "।"
            return f"आपको {w} एक कानूनी नोटिस मिला है।" if w else "आपको एक कानूनी नोटिस मिला है।"
        return ""
    if p == "deposit":
        a = f"You paid a deposit of {amt}" if amt else "You paid a security deposit"
        return a + (f" and moved out {w}." if w else " and have moved out.")
    if p == "refund":
        a = f"You paid {amt}" if amt else "You paid"
        if case.date_text == "order date":
            return a + f" on {fmt_date(case.date, lang)}, and did not get what you paid for."
        return a + (f" and the trouble started {w}." if w else " and did not get what you paid for.")
    if p == "salary":
        a = f"About {amt} of your pay is still owed" if amt else "Some of your pay is still owed"
        if _unpaid_span(case):
            return a + f", and it has been unpaid since about {fmt_date(case.date, lang)}."
        return a + (f", and your last working day was {w}." if w else ".")
    if p == "notice":
        n = case.notice
        if n:
            who = n.get("advocate") or n.get("firm") or "A lawyer"
            part = f"{who} has sent you a legal notice" + (f" on behalf of {n['client']}" if n.get("client") else "")
            if case.amount:
                part += f", demanding {amt}"
            if n.get("days"):
                part += f" within {n['days']} days"
            return part + "."
        base = f"You received a legal notice {w}" if w else "You received a legal notice"
        return base + (f" asking for {amt}." if amt else ".")
    return ""


_LEAD = {
    "deposit": {
        "en": "The landlord can only keep money for unpaid rent or real damage he can show. The rest has been due since you handed back the keys.",
        "hi": "मकान मालिक सिर्फ़ बकाया किराए या साबित किए जा सकने वाले नुकसान का पैसा रख सकता है। बाकी पैसा चाबी लौटाते ही आपका हो गया था।"},
    "refund": {
        "en": "That counts as a defect or a deficiency in service under the Consumer Protection Act, 2019, so you can ask for a refund, a replacement or compensation.",
        "hi": "उपभोक्ता संरक्षण कानून में इसे दोष या सेवा में कमी माना जाता है, इसलिए आप रिफंड, बदला हुआ सामान या मुआवज़ा माँग सकते हैं।"},
    "salary": {
        "en": "Wages for days you already worked cannot be held back over clearance or handover. The employer can only adjust what your contract allows, and should show you the calculation.",
        "hi": "जिन दिनों आपने काम किया, उनका वेतन क्लीयरेंस या हैंडओवर के नाम पर नहीं रोका जा सकता। कंपनी सिर्फ़ कॉन्ट्रैक्ट के हिसाब से कटौती कर सकती है और उसे हिसाब दिखाना चाहिए।"},
    "notice": {
        "en": "A notice is not a court case. It is usually the step before one, so it deserves a calm written reply before the deadline.",
        "hi": "नोटिस अदालत का केस नहीं है। आमतौर पर यह केस से पहले का कदम होता है, इसलिए समय सीमा से पहले शांत लिखित जवाब देना ठीक रहता है।"},
}

_KEY_PROOF = {
    "deposit": ["rent agreement", "payment record", "photos or video", "messages or emails"],
    "refund": ["invoice or bill", "order id", "photos or video", "messages or emails"],
    "salary": ["offer or appointment letter", "salary slips", "payment record", "messages or emails"],
    "notice": ["the notice and its envelope", "your own records of the deal"],
}
_PROOF_HI = {
    "rent agreement": "रेंट एग्रीमेंट", "invoice or bill": "बिल या इनवॉइस",
    "payment record": "भुगतान का रिकॉर्ड (बैंक या UPI)", "messages or emails": "मैसेज या ईमेल",
    "salary slips": "सैलरी स्लिप", "offer or appointment letter": "ऑफ़र या अपॉइंटमेंट लेटर",
    "photos or video": "फ़ोटो या वीडियो", "order id": "ऑर्डर आईडी",
    "the notice and its envelope": "नोटिस और उसका लिफ़ाफ़ा",
    "your own records of the deal": "सौदे से जुड़े आपके अपने काग़ज़ और मैसेज",
}
_PROOF_WHY = {
    "rent agreement": "shows the deposit and the notice terms",
    "payment record": "shows the money actually moved",
    "photos or video": "shows the condition at handover or the defect",
    "messages or emails": "anything where they admit the amount or the delay",
    "invoice or bill": "proves what you paid and to whom",
    "order id": "lets the commission trace the purchase",
    "salary slips": "shows your monthly pay",
    "offer or appointment letter": "shows the agreed terms",
    "the notice and its envelope": "the postmark shows when your reply clock started",
    "your own records of the deal": "agreements, receipts or chats that support your side",
}


def proof_label(p, lang):
    return _PROOF_HI.get(p, p) if lang == "hi" else p


def _strength(case, lang):
    key = _KEY_PROOF.get(case.problem, [])[:2]
    have = [p for p in key if p in case.proof]
    if case.problem == "notice":
        return ""
    if len(have) == 2:
        return ("आपके पास सबसे ज़रूरी काग़ज़ हैं, तो आपकी स्थिति मज़बूत है।" if lang == "hi"
                else "You have the two papers that matter most, so your position is strong.")
    if have:
        return ("आपकी स्थिति ठीक है, और बाकी सबूत जोड़ने से यह और मज़बूत होगी।" if lang == "hi"
                else "Your position is sound, and it gets stronger with the rest of the proof below.")
    need = {"deposit": ("the agreement and proof you paid the deposit", "एग्रीमेंट और डिपॉज़िट देने का सबूत"),
            "refund": ("the invoice and order details", "बिल और ऑर्डर की जानकारी"),
            "salary": ("your offer letter and salary slips", "ऑफ़र लेटर और सैलरी स्लिप")}[case.problem]
    return (f"कानून आपके साथ है। अब सबसे ज़रूरी काम है {need[1]} इकट्ठा करना।" if lang == "hi"
            else f"The law is on your side. The most useful next job is getting {need[0]} together.")


# --- steps with real dates --------------------------------------------------

def _steps(case, today, lang):
    d = lambda n: fmt_date(today + dt.timedelta(days=n), lang)
    hi = lang == "hi"
    p = case.problem
    if p == "deposit":
        return [
            ("आज" if hi else "Today",
             "अपने सबूत एक जगह रखें। अगर हो सके तो मकान सौंपते समय की फ़ोटो भी जोड़ें।" if hi else
             "Put your proof in one place. If you can, add photos from the day you handed the flat back."),
            (f"{d(2)} तक" if hi else f"By {d(2)}",
             "डॉक्यूमेंट्स टैब से लिखित माँग रजिस्टर्ड डाक से भेजें, और वही बात व्हाट्सएप या ईमेल पर भी। 15 दिन का समय दें।" if hi else
             "Send the written demand from the Documents tab by registered post, and the same text on WhatsApp or email. Give 15 days."),
            (f"{d(17)} के बाद" if hi else f"After {d(17)}",
             "तब तक पैसा न मिले तो रेंट अथॉरिटी (अगर आपके राज्य में है) या सिविल कोर्ट जाएँ। केस दायर करने में मदद के लिए 15100 पर कॉल करें।" if hi else
             "No refund by then? Go to the Rent Authority if your State has one, otherwise file a civil suit for recovery. Call 15100 for a free lawyer to help you file."),
        ]
    if p == "refund":
        return [
            ("आज" if hi else "Today",
             "डॉक्यूमेंट्स टैब से लिखित माँग विक्रेता के सपोर्ट ईमेल और पते पर भेजें। 15 दिन दें।" if hi else
             "Send the written demand from the Documents tab to the seller's support email and registered address. Give 15 days."),
            ("आज ही" if hi else "Same day",
             "राष्ट्रीय उपभोक्ता हेल्पलाइन पर मुफ़्त शिकायत दर्ज करें: 1915 पर कॉल करें या consumerhelpline.gov.in पर जाएँ। डॉकेट नंबर लिख लें।" if hi else
             "Register a free grievance with the National Consumer Helpline: call 1915 or use consumerhelpline.gov.in. Note the docket number."),
            (f"{d(15)} के बाद" if hi else f"After {d(15)}",
             "फिर भी हल न हो तो edaakhil.nic.in पर ज़िला उपभोक्ता आयोग में शिकायत दर्ज करें। शिकायत का ड्राफ़्ट डॉक्यूमेंट्स टैब में है।" if hi else
             "Still nothing? File on e-Daakhil (edaakhil.nic.in) before the District Commission. The complaint draft is in the Documents tab."),
        ]
    if p == "salary":
        return [
            ("आज" if hi else "Today",
             "HR को ईमेल करके बकाया रकम और भुगतान की तारीख़ लिखित में माँगें। छोटा और विनम्र रखें।" if hi else
             "Email HR asking for the exact amount due and the date it will be paid. Keep it short and polite, the point is to get it in writing."),
            (f"{d(2)} तक" if hi else f"By {d(2)}",
             "डॉक्यूमेंट्स टैब से लिखित माँग भेजें और 15 दिन दें।" if hi else
             "Send the written demand from the Documents tab and give 15 days."),
            (f"{d(17)} के बाद" if hi else f"After {d(17)}",
             "भुगतान न हो तो samadhan.labour.gov.in पर या लेबर कमिश्नर के दफ़्तर में दावा दर्ज करें।" if hi else
             "Not paid? File a claim on SAMADHAN (samadhan.labour.gov.in) or at your Labour Commissioner's office."),
        ]
    if p == "notice":
        rdl = reply_deadline(case, today)
        when = (f"{fmt_date(rdl, lang)} तक" if hi else f"Before {fmt_date(rdl, lang)}") if rdl else ("समय सीमा से पहले" if hi else "Before the deadline")
        return [
            ("आज" if hi else "Today",
             "लिख लें कि नोटिस कब मिला और लिफ़ाफ़ा संभाल कर रखें। जवाब न देना सबसे बुरा विकल्प है।" if hi else
             "Write down the date you got it and keep the envelope. Not replying at all is the worst option."),
            (when,
             "डॉक्यूमेंट्स टैब से जवाब रजिस्टर्ड डाक से भेजें। जो बात सच नहीं है उसे न मानें।" if hi else
             "Send a written reply by registered post. A draft is in the Documents tab. Do not admit anything that is not true."),
            ("अगर ज़रूरत हो" if hi else "If needed",
             "नोटिस चेक, प्रॉपर्टी, पुलिस या अदालत से जुड़ा हो तो जवाब से पहले वकील से बात करें। 15100 मुफ़्त है।" if hi else
             "If it involves a cheque, property, the police or a court date, talk to a lawyer before replying. 15100 is free."),
        ]
    return []


def _events(case, today, lang):
    """Dated reminders for a calendar: (iso date, title, details)."""
    hi = lang == "hi"
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    label = kb.pick(kb.problem(case.problem)["label"], lang)
    p, out = case.problem, []
    if p in ("deposit", "salary"):
        out += [(d(2), "लिखित माँग भेजें" if hi else "Send the written demand",
                 "NyaySetu के डॉक्यूमेंट्स टैब वाला पत्र रजिस्टर्ड डाक से भेजें।" if hi else
                 "Send the letter from the NyaySetu Documents tab by registered post."),
                (d(17), "जवाब आया? अगला कदम" if hi else "Did they pay? Take the next step",
                 ("रेंट अथॉरिटी या सिविल कोर्ट। मदद: 15100" if p == "deposit" else "SAMADHAN या लेबर कमिश्नर। मदद: 15100") if hi else
                 ("Rent Authority or a civil suit. Free help: 15100." if p == "deposit" else
                  "File on SAMADHAN or with the Labour Commissioner. Free help: 15100."))]
    elif p == "refund":
        out += [(d(0), "माँग भेजें और 1915 पर शिकायत करें" if hi else "Send the demand and call 1915",
                 "डॉकेट नंबर लिख लें।" if hi else "Note the docket number."),
                (d(15), "रिफंड आया? नहीं तो e-Daakhil" if hi else "Refund in? If not, file on e-Daakhil",
                 "edaakhil.nic.in")]
    elif p == "notice":
        rdl = reply_deadline(case, today)
        if rdl and rdl >= today:
            out.append((max(today, rdl - dt.timedelta(days=3)).isoformat(),
                        "नोटिस का जवाब तैयार करें" if hi else "Finish your reply to the notice",
                        "रजिस्टर्ड डाक से भेजने का समय रखें।" if hi else "Leave time to send it by registered post."))
            out.append((rdl.isoformat(), "नोटिस के जवाब की आख़िरी तारीख़" if hi else "Last day to reply to the notice", ""))
    dl = _deadline(case, today, lang)
    if dl and p != "notice" and dl.get("date") and (dl.get("days_left") or 0) >= 0:
        out.append((dl["date"], ("आख़िरी तारीख़: " if hi else "Last day to act: ") + label, dl["text"]))
    return out


def reply_deadline(case, today):
    if case.problem != "notice":
        return None
    start = dt.date.fromisoformat(case.date) if case.date else today
    return start + dt.timedelta(days=case.notice_days or 15)


def _deadline(case, today, lang):
    if case.problem == "notice" and (case.date or case.notice):
        by = reply_deadline(case, today)
        left = (by - today).days
        if left < 0:
            txt = (f"नोटिस में दिया समय {fmt_date(by, lang)} को ख़त्म हो गया। फिर भी जितनी जल्दी हो सके जवाब भेजें।" if lang == "hi"
                   else f"The time given in the notice ended on {fmt_date(by, lang)}. Reply anyway, as soon as you can.")
        else:
            txt = (f"नोटिस का जवाब {fmt_date(by, lang)} तक भेजें, यानी " + ("आज ही।" if left == 0 else f"{_left(left, lang)} बाकी।") if lang == "hi"
                   else f"Reply to the notice by {fmt_date(by, lang)}, " + ("which is today." if left == 0 else f"{_left(left, lang)} from now."))
        return {"date": by.isoformat(), "days_left": left, "text": txt, "urgent": left <= 7}
    p = kb.problem(case.problem)
    if not p or not p.get("limitation_days"):
        return None
    label = kb.pick(p["limitation_label"], lang)
    years = round(p["limitation_days"] / 365)
    if not case.date:
        txt = (f"आमतौर पर {label} के लिए {years} साल मिलते हैं। तारीख़ बताएँ तो मैं सही आख़िरी दिन निकाल दूँगा।" if lang == "hi"
               else f"You generally get {years} years to {label}. Tell me the date and I will work out your exact last day.")
        return {"date": None, "days_left": None, "text": txt, "urgent": False}
    last = dt.date.fromisoformat(case.date) + dt.timedelta(days=p["limitation_days"])
    left = (last - today).days
    if left < 0:
        txt = (f"सामान्य समय सीमा लगभग {fmt_date(last, lang)} को ख़त्म हो गई।" if lang == "hi"
               else f"The normal time limit to {label} ended around {fmt_date(last, lang)}.")
    else:
        txt = (f"{label} की आख़िरी तारीख़ लगभग {fmt_date(last, lang)} है, यानी {_left(left, lang)} बाकी।" if lang == "hi"
               else f"Last day to {label}: around {fmt_date(last, lang)}, {_left(left, lang)} from now.")
    return {"date": last.isoformat(), "days_left": left, "text": txt, "urgent": 0 <= left <= 90}


# --- connections between the documents and the story ------------------------

def insights(case, lang):
    hi = lang == "hi"
    out = []
    n = case.notice
    if case.problem == "notice" and n.get("about_tenancy") and case.deposit_known:
        d = fmt_inr(case.deposit_known)
        out.append(f"नोटिस में आपके {d.replace('Rs ', '₹')} के सिक्योरिटी डिपॉज़िट का ज़िक्र नहीं है, जो मकान मालिक के पास है। "
                   "जवाब में यह ज़रूर लिखें कि कोई भी असली बकाया इसी डिपॉज़िट से एडजस्ट हो सकता है।" if hi else
                   f"The notice does not mention your security deposit of {d}, which the landlord still holds. "
                   "Your reply should say that any genuine dues can only be adjusted against it.")
    elif case.problem == "notice" and n.get("about_tenancy"):
        out.append("अगर आपने मकान मालिक को सिक्योरिटी डिपॉज़िट दिया था, तो जवाब में उसका ज़िक्र करें। रेंट एग्रीमेंट अटैच करें तो मैं रकम निकाल दूँगा।" if hi else
                   "If you paid the landlord a security deposit, your reply should mention it. Attach the rent agreement and I will pick out the amount.")
    if case.problem == "notice" and n.get("claims_damage"):
        out.append("नोटिस में मरम्मत या नुकसान का पैसा माँगा गया है। बिल और फ़ोटो माँगें। सामान्य घिसावट नुकसान नहीं होती।" if hi else
                   "The notice claims repair or damage costs. Ask for the bills and photos behind that figure. Normal wear and tear is not damage.")
    if case.problem == "notice" and n.get("route") == "civil":
        out.append("उन्होंने दीवानी (सिविल) कार्रवाई की बात कही है, यानी पैसे की वसूली का केस। यह आपराधिक मामला नहीं है।" if hi else
                   "They threaten civil proceedings, meaning a case to recover money. That is not a criminal matter.")
    if case.problem == "notice" and n.get("notice_pay"):
        out.append("वे नोटिस पीरियड पूरा न करने का पैसा माँग रहे हैं। यह तभी वसूला जा सकता है जब आपके अपॉइंटमेंट लेटर में ऐसा लिखा हो, "
                   "और उतना ही जितना उसमें लिखा है। उनसे वह शर्त लिखित में माँगें।" if hi else
                   "They want pay for the notice period you did not serve. That can only be recovered if your appointment "
                   "letter says so, and only up to what it says. Ask them for the exact clause in writing.")
    if case.problem == "notice" and n.get("bond"):
        out.append("ट्रेनिंग बॉन्ड लागू हो सकता है, पर आमतौर पर सिर्फ़ उचित रकम तक। बॉन्ड की कॉपी और ट्रेनिंग पर असल ख़र्च का हिसाब माँगें, "
                   "ताकि आप देख सकें कि माँगी गई रकम ठीक है या नहीं। बड़ी रकम हो तो वकील से बात करें।" if hi else
                   "A training bond can be enforced, but usually only for a reasonable amount. Ask for a copy of the bond and "
                   "what the training actually cost, so you can judge whether the figure is fair. If it is large, talk to a lawyer.")
    if case.problem == "notice" and n.get("about_job"):
        out.append("अगर कंपनी पर आपका वेतन, छुट्टियों का पैसा या फ़ुल एंड फ़ाइनल सेटलमेंट बाकी है, तो जवाब में यह ज़रूर लिखें।" if hi else
                   "If the company still owes you salary, leave encashment or your full and final settlement, say so in "
                   "your reply. Their claim and your dues should be settled together.")
    ret = next((d.get("return_days") for d in case.docs if d.get("return_days")), None)
    if case.problem == "refund" and ret:
        out.append(f"बिल में {ret} दिन की रिटर्न नीति लिखी है। ख़राब सामान पर आपका दावा इससे ख़त्म नहीं होता।" if hi else
                   f"The invoice mentions a {ret} day return window. That does not cancel your claim if the product was defective.")
    np = next((d.get("notice_period") for d in case.docs if d.get("notice_period")), None)
    if case.problem == "deposit" and np:
        out.append(f"आपके एग्रीमेंट में नोटिस की शर्त है ({np})। अगर आपने लिखित में नोटिस दिया था, तो अपनी माँग में उसकी तारीख़ लिखें।" if hi else
                   f"Your agreement has a notice clause ({np}). If you gave notice in writing, mention the date in your demand.")
    return out


# --- public -----------------------------------------------------------------

def build_answer(case, today=None, lang=None):
    today = today or dt.date.today()
    lang = lang or ("hi" if case.lang == "hi" else "en")
    if not case.problem:
        return None
    fl = kb.facts(case.problem)
    allowed = kb.allowed_citations(fl)

    summary = " ".join(x for x in [_situation(case, lang), _LEAD[case.problem][lang],
                                   _strength(case, lang)] if x)
    if llm.provider() != "demo":
        summary = llm.rewrite_summary(case, fl, summary, lang)
    g = guard.verify(summary, allowed)

    key = _KEY_PROOF.get(case.problem, [])
    return {
        "lang": lang,
        "problem": case.problem,
        "label": kb.pick(kb.problem(case.problem)["label"], lang),
        "summary": g["clean_text"],
        "violations": g["violations"],
        "law": [{"id": f.id, "title": kb.pick(f.title, lang), "text": kb.pick(f.plain, lang),
                 "cite": f.cite(), "note": f.source_note} for f in fl],
        "steps": _steps(case, today, lang),
        "deadline": _deadline(case, today, lang),
        "events": _events(case, today, lang),
        "proof_have": _have(case),
        "proof_get": [(p, _PROOF_WHY.get(p, "")) for p in key
                      if p not in _have(case) and p not in _covered(case)],
        "help": [{"name": kb.pick(h["name"], lang), "contact": h["contact"],
                  "what": kb.pick(h["what"], lang)} for h in kb.helplines(case.problem)],
        "allowed": allowed,
        "insights": insights(case, lang),
        "suggest": [kb.pick(f["q"], lang) for f in faq.suggestions(case.problem)],
    }


def render_text(ans, flags=()):
    """Plain text version of an answer, used for raw outputs and exports."""
    hi = ans["lang"] == "hi"
    L = (lambda en, h: h if hi else en)
    out = []
    for f in flags:
        out.append("! " + f["message"])
    if flags:
        out.append("")
    out.append(ans["summary"])
    out.append("")
    if ans["deadline"]:
        out.append(L("Time limit: ", "समय सीमा: ") + ans["deadline"]["text"])
        out.append("")
    if ans.get("insights"):
        out.append(L("Worth knowing", "ध्यान दें"))
        for x in ans["insights"]:
            out.append("- " + x)
        out.append("")
    out.append(L("What to do", "क्या करें"))
    for i, (when, text) in enumerate(ans["steps"], 1):
        out.append(f"{i}. {when}: {text}")
    out.append("")
    if ans["proof_have"] or ans["proof_get"]:
        out.append(L("Your proof", "आपके सबूत"))
        for p in ans["proof_have"]:
            out.append(f"   [have] {proof_label(p, ans['lang'])}")
        for p, why in ans["proof_get"]:
            tail = f" ({why})" if why and not hi else ""
            out.append(f"   [get]  {proof_label(p, ans['lang'])}{tail}")
        out.append("")
    out.append(L("The law, in plain words", "कानून, आसान शब्दों में"))
    for item in ans["law"]:
        out.append(f"[{item['id']}] {item['title']}")
        out.append(f"    {item['text']}")
        out.append(f"    Source: {item['cite']}")
    out.append("")
    out.append(L("Free help", "मुफ़्त मदद"))
    for h in ans["help"]:
        out.append(f"   {h['name']}: {h['contact']}. {h['what']}")
    out.append("")
    out.append(kb.disclaimer(ans["lang"]))
    return "\n".join(out)
