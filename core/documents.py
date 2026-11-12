"""
Drafts the letters a person actually needs: a legal notice for a deposit,
refund or salary dispute, a reply for someone who received a notice, and a
consumer complaint for refunds. Each draft is built from the case facts and
exported as plain text and as a Word file.
"""

from __future__ import annotations

import datetime as dt
import io

from .intake import fmt_inr

BLANK = "________"


def _d(iso):
    if not iso:
        return BLANK
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def _amt(case):
    return fmt_inr(case.amount) if case.amount else f"Rs {BLANK}"


def available(case):
    """Which drafts make sense for this case, best first."""
    return {
        "deposit": ["notice"],
        "refund": ["notice", "complaint"],
        "salary": ["notice"],
        "notice": ["reply"],
    }.get(case.problem, [])


NAMES = {"notice": "Legal notice", "reply": "Reply to the notice", "complaint": "Consumer complaint"}


def suggested_position(case):
    """A first draft of 'your side' for a reply, built only from known facts."""
    n, bits = case.notice, []
    vac = n.get("vacated")
    if vac:
        bits.append(f"I vacated the premises and handed back the keys on {_d(vac)}")
    if n.get("about_tenancy") and case.deposit_known:
        bits.append(f"your client holds my interest free security deposit of {fmt_inr(case.deposit_known)}, "
                    "which your notice does not mention, and any genuine dues can only be adjusted against it")
    if n.get("claims_damage"):
        bits.append("the claim for repairs is not supported by any bills or photographs, and normal wear and "
                    "tear is not damage")
    if n.get("about_tenancy") and case.deposit_known:
        bits.append("I call upon your client to refund the balance of my deposit")
    if n.get("resigned"):
        bits.append(f"I resigned in writing on {_d(n['resigned'])}")
    if n.get("notice_pay"):
        bits.append("your client has not shown any clause in my appointment letter that allows it to recover pay for "
                    "the notice period, and I ask you to share a copy of the clause it relies on")
    if n.get("bond"):
        bits.append("I ask your client to share a copy of the training bond it relies on and a breakup of the training "
                    "costs it actually incurred, since the amount claimed has not been explained")
    return "; ".join(bits)


def prefill(case):
    """Default form values for the letters, from what the case already knows."""
    d = dict(case.draft)
    if case.problem == "notice" and "extra" not in d:
        pos = suggested_position(case)
        if pos:
            d["extra"] = pos[0].upper() + pos[1:]
    return d


def build(kind, case, det, today=None):
    today = today or dt.date.today()
    det = {k: (v or "").strip() for k, v in det.items()}
    you = det.get("your_name") or BLANK
    doc = {
        "title": {"notice": "LEGAL NOTICE", "reply": "REPLY TO LEGAL NOTICE",
                  "complaint": "CONSUMER COMPLAINT"}[kind],
        "date": f"{today.day} {today.strftime('%B %Y')}",
        "from": [you, det.get("your_address") or BLANK],
        "to": [det.get("their_name") or BLANK, det.get("their_address") or BLANK],
        "signature": you,
    }
    extra = det.get("extra")
    amt = _amt(case)
    p = case.problem

    if kind == "notice" and p == "deposit":
        doc["subject"] = f"Refund of security deposit of {amt}"
        paras = [
            f"I was your tenant at {det.get('premises') or BLANK}. At the start of the tenancy I paid you a security deposit of {amt}.",
            f"I vacated the premises and handed back the keys on or about {_d(case.date)}, leaving it in good condition apart from normal wear and tear.",
            "Despite my requests you have not refunded the deposit, and you have not given me any account of deductions, if you claim any.",
            "The deposit was held only as security. It became refundable on handover, less only such deductions as you can justify. This is also the position under Section 11 of the Model Tenancy Act, 2021, where that Act applies.",
        ]
        demand = f"refund {amt} to me"
        then = "approach the appropriate forum for recovery of the amount with interest and costs"
    elif kind == "notice" and p == "refund":
        ref = det.get("order_id")
        doc["subject"] = f"Refund of {amt}" + (f" against order {ref}" if ref else "")
        paras = [
            f"On or about {_d(case.date)} I paid you {amt}" + (f" under order {ref}" if ref else "") + ".",
            f"What I received was not as promised: {det.get('issue') or 'it was defective, which I reported to you promptly'}.",
            "Despite my complaints you have refused to refund the amount or replace the goods.",
            "This is a defect in goods or a deficiency in service under the Consumer Protection Act, 2019.",
        ]
        demand = f"refund {amt}, or replace the goods with a working unit"
        then = ("file a complaint before the District Consumer Disputes Redressal Commission "
                "and claim compensation and costs")
    elif kind == "notice" and p == "salary":
        doc["subject"] = f"Payment of unpaid salary and dues of {amt}"
        role = det.get("designation")
        paras = [
            "I was employed with you" + (f" as {role}" if role else "") + ".",
            f"My last working day was {_d(case.date)}.",
            f"Salary and dues of about {amt} remain unpaid despite my requests.",
            "Wages already earned cannot be withheld on account of exit clearance or handover, and the Code on Wages, 2019 requires them to be paid on time.",
        ]
        demand = f"pay {amt} to me, with a written breakup of any deduction you claim"
        then = "file a claim before the competent authority under the Code on Wages, 2019 and seek compensation"
    elif kind == "reply":
        nd = det.get("notice_date")
        doc["subject"] = "Reply to your legal notice" + (f" dated {nd}" if nd else "")
        paras = [
            f"I have received your notice" + (f" dated {nd}" if nd else "") +
            ("." if case.date_text == "notice date" or not case.date else f" on {_d(case.date)}."),
            "I deny the claims made in it, except anything expressly admitted below.",
            f"My position is as follows: {extra or BLANK + ' (set out your side in a few short points)'}.",
            "Nothing in this reply is an admission of liability. I am willing to resolve the matter through discussion in writing.",
            "If any proceedings are started, I will defend them and seek costs. This reply is sent without prejudice to my rights.",
        ]
        doc["paras"] = paras
        doc["closing"] = "Yours faithfully,"
        doc["notes"] = _notes(reply=True)
        return doc
    elif kind == "complaint":
        return _complaint(case, det, doc, today)
    else:
        return None

    if extra:
        paras.append(extra.rstrip(".") + ".")
    paras.append(f"I therefore call upon you to {demand} within 15 days of receiving this notice.")
    paras.append(f"If you fail to do so I will {then}, without further notice and at your risk as to costs.")
    doc["paras"] = paras
    doc["closing"] = "Yours faithfully,"
    doc["notes"] = _notes()
    return doc


def _complaint(case, det, doc, today):
    you, them = doc["from"], doc["to"]
    doc["court"] = f"BEFORE THE DISTRICT CONSUMER DISPUTES REDRESSAL COMMISSION, {(case.city or BLANK).upper()}"
    doc["parties"] = [f"{you[0]}, {you[1]}  ...Complainant", "Versus",
                      f"{them[0]}, {them[1]}  ...Opposite Party"]
    doc["subject"] = "Complaint under Section 35 of the Consumer Protection Act, 2019"
    amt = _amt(case)
    doc["paras"] = [
        f"The complainant is a consumer who paid the opposite party {amt}" +
        (f" under order {det['order_id']}" if det.get("order_id") else "") + f" on or about {_d(case.date)}.",
        f"The goods or services were defective or deficient: {det.get('issue') or BLANK}.",
        "The complainant reported the problem and asked for a refund or replacement, which the opposite party refused.",
        "This amounts to a defect in goods or a deficiency in service, and the complaint is filed within two years of the cause of action.",
        "The amount paid is within the pecuniary limit of this Commission and the cause of action arose within its territory.",
        f"The complainant prays that the opposite party be directed to refund {amt}, pay compensation for the harassment caused, and pay the costs of this complaint.",
    ]
    doc["closing"] = "Verified that the contents above are true to my knowledge and belief."
    doc["notes"] = [
        "File this on edaakhil.nic.in, or at the District Commission office, with copies of every proof attached.",
        "The commission will want an index, a list of dates and an affidavit. e-Daakhil walks you through them.",
        "This is a draft from general information, not from a lawyer. Have it checked if the amount is large.",
    ]
    return doc


def _notes(reply=False):
    n = ["Fill in every blank (____) and check each date and amount before sending.",
         "Send it by registered post with acknowledgement due, keep the receipt, and send the same text by email or WhatsApp.",
         "This draft comes from general information, not from a lawyer. For a large amount, have an advocate look at it."]
    if reply:
        n.insert(1, "Send it before the deadline in their notice. Late is better than never, but on time is much better.")
    return n


def to_text(doc):
    out = []
    if doc.get("court"):
        out += [doc["court"], ""] + doc["parties"] + [""]
    out += [doc["title"], "", f"Date: {doc['date']}", ""]
    if not doc.get("court"):
        out += ["From:"] + doc["from"] + ["", "To:"] + doc["to"] + [""]
    out += [f"Subject: {doc['subject']}", ""]
    if not doc.get("court"):
        out += ["Sir or Madam,", ""]
    for i, p in enumerate(doc["paras"], 1):
        out += [f"{i}. {p}", ""]
    out += [doc["closing"], "", doc["signature"], "", "-" * 60, "Before you send (delete this part):"]
    out += [f"- {n}" for n in doc["notes"]]
    return "\n".join(out)


def to_docx(doc):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor, Inches

    d = Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(1)
        s.top_margin = s.bottom_margin = Inches(0.9)
    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(12)

    def para(text="", bold=False, align=None, size=None, italic=False, color=None, space=6):
        p = d.add_paragraph()
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor(*color)
        if align:
            p.alignment = align
        p.paragraph_format.space_after = Pt(space)
        return p

    if doc.get("court"):
        para(doc["court"], bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        for line in doc["parties"]:
            para(line, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc["title"], bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=14, space=12)
    para(f"Date: {doc['date']}", align=WD_ALIGN_PARAGRAPH.RIGHT)
    if not doc.get("court"):
        para("From:", bold=True, space=0)
        for line in doc["from"]:
            para(line, space=0)
        para()
        para("To:", bold=True, space=0)
        for line in doc["to"]:
            para(line, space=0)
        para()
    sub = d.add_paragraph()
    r = sub.add_run("Subject: " + doc["subject"])
    r.bold = True
    r.underline = True
    if not doc.get("court"):
        para("Sir or Madam,")
    for i, p in enumerate(doc["paras"], 1):
        q = para(f"{i}. {p}")
        q.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para()
    para(doc["closing"])
    para()
    para(doc["signature"], bold=True)
    para()
    para("Before you send (delete this part)", bold=True, size=10, color=(120, 120, 120), space=2)
    for n in doc["notes"]:
        para("- " + n, size=10, italic=True, color=(120, 120, 120), space=2)

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def case_summary_docx(case, ans):
    """A one page summary the person can keep or show a lawyer."""
    from docx import Document
    from docx.shared import Pt
    from . import advise, kb
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("My case summary", level=1)
    d.add_paragraph(f"Prepared with NyaySetu on {dt.date.today().strftime('%d %B %Y')}. General information, not legal advice.")
    d.add_heading("The facts", level=2)
    rows = [("Problem", kb.pick(kb.problem(case.problem)["label"], "en") if case.problem else "Not set"),
            ("Amount", fmt_inr(case.amount) if case.amount else "Not given"),
            ("Key date", _d(case.date) if case.date else "Not given"),
            ("City", case.city or "Not given"),
            ("Proof I have", ", ".join(case.proof) or "None listed"),
            ("Documents", ", ".join(x["name"] for x in case.docs) or "None")]
    t = d.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for k, v in rows:
        r = t.add_row().cells
        r[0].text, r[1].text = k, v
    if ans:
        d.add_heading("Where I stand", level=2)
        d.add_paragraph(ans["summary"])
        for x in ans.get("insights", []):
            d.add_paragraph(x, style="List Bullet")
        if ans.get("deadline"):
            d.add_paragraph("Time limit: " + ans["deadline"]["text"])
        d.add_heading("What to do", level=2)
        for when, what in ans["steps"]:
            d.add_paragraph(f"{when}: {what}", style="List Number")
        d.add_heading("Free help", level=2)
        for h in ans["help"]:
            d.add_paragraph(f"{h['name']}: {h['contact']}", style="List Bullet")
        d.add_heading("The law this is based on", level=2)
        for x in ans["law"]:
            d.add_paragraph(f"{x['title']} ({x['cite']})", style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
