"""
Small helpers that make an answer easier to use outside the app: a calendar
file, a short summary to share, text to read aloud, saving and reopening a
case, and anonymous feedback.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid

from . import advise, intake

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDBACK = os.path.join(HERE, "feedback", "feedback.jsonl")
SAVE_VERSION = 1


# --- calendar ---------------------------------------------------------------

def _ics_escape(t):
    t = t.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
    return t.replace("\n", "\\n")


def calendar_file(ans, today=None):
    """An .ics file with one all day event per dated step, each with a reminder."""
    today = today or dt.date.today()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NyaySetu//EN", "CALSCALE:GREGORIAN"]
    for iso, title, details in ans.get("events", []):
        day = dt.date.fromisoformat(iso)
        lines += ["BEGIN:VEVENT", f"UID:{uuid.uuid4()}@nyaysetu", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_escape('NyaySetu: ' + title)}",
                  f"DESCRIPTION:{_ics_escape(details + chr(10) + 'Free legal aid: NALSA 15100')}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(title)}",
                  "TRIGGER:-PT15H", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(l) for l in lines) + "\r\n").encode("utf-8")


def _fold(line, limit=74):
    """Calendar lines longer than 75 bytes continue on the next line after a space."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > limit:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    return "\r\n".join(out + [cur])


# --- sharing and reading aloud -----------------------------------------------

def share_text(case, ans):
    """A short plain summary for WhatsApp or a lawyer: what happened, the deadline, the steps."""
    hi = ans["lang"] == "hi"
    out = [("मेरा मामला: " if hi else "My case: ") + ans["label"]]
    if case.amount:
        out.append(("रकम: " if hi else "Amount: ") + intake.fmt_inr(case.amount))
    if case.date:
        out.append(("तारीख़: " if hi else "Key date: ") + advise.fmt_date(case.date, ans["lang"]))
    out.append("")
    out.append(ans["summary"])
    if ans.get("deadline"):
        out += ["", ans["deadline"]["text"]]
    out += ["", "क्या करना है:" if hi else "What to do:"]
    out += [f"{i}. {w}: {t}" for i, (w, t) in enumerate(ans["steps"], 1)]
    out += ["", "मुफ़्त कानूनी सहायता: NALSA 15100" if hi else "Free legal aid: NALSA 15100"]
    return "\n".join(out)


def speech_text(ans):
    """What the read aloud button says: the answer, the deadline and the steps."""
    hi = ans["lang"] == "hi"
    parts = [ans["summary"]]
    if ans.get("deadline"):
        parts.append(ans["deadline"]["text"])
    parts.append("आपको क्या करना है।" if hi else "Here is what to do.")
    parts += [f"{w}. {t}" for w, t in ans["steps"]]
    text = " ".join(parts)
    text = re.sub(r"\bRs\b\.?", "रुपये" if hi else "rupees", text)
    return re.sub(r"\s+", " ", text)


# --- saving and reopening a case -----------------------------------------------

def save_case(sess, msgs):
    """Everything needed to pick a case up later, as JSON. Uploaded files are not
    kept, only what was read from them."""
    data = {"app": "nyaysetu", "version": SAVE_VERSION, "saved": dt.date.today().isoformat(),
            "case": sess.case.to_dict() if sess.case else None, "stage": sess.stage,
            "forced_lang": sess.forced_lang, "pending": sess.pending, "messages": msgs}
    return json.dumps(data, ensure_ascii=False, indent=1, default=str).encode("utf-8")


def load_case(raw, session_cls, today=None):
    """Rebuild a Session and its messages from save_case output. The answer is
    worked out again for today, so the days left are current."""
    data = json.loads(raw.decode("utf-8"))
    if data.get("app") not in ("nyaysetu", "haqdar", "nyaya-saathi") or not data.get("case"):
        raise ValueError("not a NyaySetu case file")
    known = set(intake.Case.__dataclass_fields__)
    case = intake.Case(**{k: v for k, v in data["case"].items() if k in known})
    sess = session_cls(case=case, stage=data.get("stage", "answered"), forced_lang=data.get("forced_lang"),
                       pending=data.get("pending", ""), today=today)
    msgs = data.get("messages", [])
    if case.problem and sess.stage in ("answered", "followup"):
        from . import escalate
        sess.flags = escalate.check(case)
        if sess.stage == "answered":
            sess.answer = advise.build_answer(case, today, sess.lang())
            for m in reversed(msgs):
                if m.get("type") == "answer":
                    m["answer"], m["flags"] = sess.answer, sess.flags
                    break
    return sess, msgs


# --- feedback -------------------------------------------------------------------

def record_feedback(problem, rating, where="answer"):
    """One line per rating. No story, names or amounts are stored."""
    os.makedirs(os.path.dirname(FEEDBACK), exist_ok=True)
    with open(FEEDBACK, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "problem": problem,
                             "rating": rating, "where": where}) + "\n")
