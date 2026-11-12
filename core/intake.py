"""Pull the facts that matter out of a messy story: amount, date, proof, place."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field

from . import kb


@dataclass
class Case:
    story: str = ""
    lang: str = "en"                 # en | hi | hinglish
    problem: str | None = None
    amount: int | None = None
    amount_text: str = ""
    date: str = ""                   # ISO date of the key event
    date_text: str = ""
    days_ago: int | None = None
    notice_days: int | None = None   # "within 15 days" in a notice
    proof: list = field(default_factory=list)
    city: str = ""
    docs: list = field(default_factory=list)      # summaries of attached documents
    draft: dict = field(default_factory=dict)     # prefill for the letters
    notice: dict = field(default_factory=dict)    # fields read from a received notice
    deposit_known: int | None = None              # deposit amount seen in an agreement

    def to_dict(self):
        return asdict(self)


# --- language ---------------------------------------------------------------

_HINGLISH = {"hai", "nahi", "nahin", "mera", "meri", "mujhe", "kar", "raha", "rahi",
             "diya", "diye", "wapas", "paisa", "paise", "kya", "ko", "ne", "se",
             "abhi", "tak", "bhi", "hua", "gaya", "mahine", "pehle", "saal", "kiya"}


def detect_lang(text):
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & _HINGLISH) >= 3:
        return "hinglish"
    return "en"


# --- amount -----------------------------------------------------------------

_NUM = r"(\d+(?:,\d{2,3})*(?:\.\d+)?)"


def _n(s):
    return float(s.replace(",", ""))


_AMT_WORDS = {"one": 1, "ek": 1, "two": 2, "do": 2, "three": 3, "teen": 3, "four": 4, "char": 4,
              "five": 5, "paanch": 5, "panch": 5, "ten": 10, "das": 10, "fifteen": 15, "twenty": 20,
              "bees": 20, "twenty five": 25, "thirty": 30, "tees": 30, "forty": 40, "chalis": 40,
              "fifty": 50, "pachas": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
              "half": 0.5, "dedh": 1.5, "dhai": 2.5}


def parse_amount(text):
    low = text.lower()
    words = "|".join(sorted(map(re.escape, _AMT_WORDS), key=len, reverse=True))
    m = re.search(rf"\b({words})\s+(lakh|lakhs|lac|thousand|hazar|hazaar|crore)\b", low)
    if m and not re.search(r"\d", low[max(0, m.start() - 4):m.start()]):
        mult = {"lakh": 1_00_000, "lakhs": 1_00_000, "lac": 1_00_000, "crore": 1_00_00_000}.get(m.group(2), 1000)
        return int(_AMT_WORDS[m.group(1)] * mult), m.group(0)
    rules = [
        (_NUM + r"\s*(crore|crores|cr)\b", 1_00_00_000),
        (_NUM + r"\s*(lakh|lakhs|lac|lacs|लाख)", 1_00_000),
        (_NUM + r"\s*(hazar|hazaar|hajar|हज़ार|हजार|thousand)", 1000),
        (_NUM + r"\s*k\b", 1000),
        (r"(?:rs\.?|inr|₹|rupees)\s*" + _NUM, 1),
        (_NUM + r"\s*(?:/-|rs\b|rupees|रुपये|रुपए|rupaye)", 1),
    ]
    for pat, mult in rules:
        m = re.search(pat, low)
        if m:
            return int(_n(m.group(1)) * mult), m.group(0).strip()
    # a bare number of 4 or more digits that is not a year
    for m in re.finditer(r"(?<![\d/-])(\d{1,3}(?:,\d{2,3})+|\d{4,})(?![\d/-])", low):
        v = int(_n(m.group(1)))
        if 1900 <= v <= 2100:
            continue
        return v, m.group(0)
    return None, ""


def fmt_inr(v):
    """40000 -> Rs 40,000 using Indian grouping."""
    s = str(int(v))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return f"Rs {s}"


# --- dates ------------------------------------------------------------------

_WORDNUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
            "twelve": 12, "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
            "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5}
_UNITS = {"day": 1, "days": 1, "din": 1, "दिन": 1,
          "week": 7, "weeks": 7, "hafte": 7, "hafta": 7, "हफ्ते": 7, "हफ़्ते": 7,
          "month": 30, "months": 30, "mahine": 30, "mahina": 30, "महीने": 30, "महीना": 30,
          "year": 365, "years": 365, "saal": 365, "साल": 365}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
_MON = {m[:3]: i + 1 for i, m in enumerate(_MONTHS)}


def _ago(today, days, text):
    d = today - dt.timedelta(days=days)
    return d.isoformat(), text, days


def parse_date(text, today):
    low = text.lower()
    nums = "|".join(map(re.escape, sorted(_WORDNUM, key=len, reverse=True)))
    units = "|".join(map(re.escape, sorted(_UNITS, key=len, reverse=True)))
    m = re.search(rf"(\d+|{nums})\s*({units})\s*(ago|back|pehle|पहले|se)", low)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _WORDNUM[m.group(1)]
        return _ago(today, n * _UNITS[m.group(2)], m.group(0))
    rel = [(r"\byesterday\b", 1), (r"\blast week\b|pichle hafte|पिछले हफ्ते", 7),
           (r"\blast month\b|pichle mahine|पिछले महीने", 30),
           (r"\blast year\b|pichle saal|पिछले साल", 365), (r"\btoday\b|\baaj\b|आज", 0)]
    for pat, days in rel:
        m = re.search(pat, low)
        if m:
            return _ago(today, days, m.group(0))
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", low)
    if m:
        return _mk(today, int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(0))
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b", low)
    if m:
        return _mk(today, int(m.group(3)), int(m.group(2)), int(m.group(1)), m.group(0))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(20\d{2}))?", low)
    if m:
        y = int(m.group(3)) if m.group(3) else None
        return _mk(today, y, _MON[m.group(2)], int(m.group(1)), m.group(0))
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(20\d{2}))?", low)
    if m:
        y = int(m.group(3)) if m.group(3) else None
        return _mk(today, y, _MON[m.group(1)], int(m.group(2)), m.group(0))
    m = re.search(r"\b(?:in\s+)?(january|february|march|april|june|july|august|september|october|november|december)(?:\s+(20\d{2}))?\b", low)
    if m:
        y = int(m.group(2)) if m.group(2) else None
        return _mk(today, y, _MONTHS.index(m.group(1)) + 1, 1, m.group(0))
    return "", "", None


def _mk(today, y, mo, d, text):
    try:
        if y is None:
            y = today.year
            if dt.date(y, mo, d) > today:
                y -= 1
        day = dt.date(y, mo, d)
    except ValueError:
        return "", "", None
    return day.isoformat(), text, (today - day).days


# --- proof, place, notice deadline -----------------------------------------

_PROOF = {
    "rent agreement": ["rent agreement", "agreement", "lease", "एग्रीमेंट", "अनुबंध"],
    "invoice or bill": ["invoice", "bill", "receipt", "रसीद", "बिल"],
    "payment record": ["bank", "upi", "transfer", "statement", "gpay", "phonepe", "paytm", "transaction"],
    "messages or emails": ["whatsapp", "message", "messages", "chat", "email", "emails", "sms", "मैसेज", "व्हाट्सएप"],
    "salary slips": ["salary slip", "salary slips", "payslip", "payslips", "pay slip"],
    "offer or appointment letter": ["offer letter", "appointment letter"],
    "photos or video": ["photo", "photos", "picture", "video", "screenshot", "फोटो", "वीडियो"],
    "order id": ["order id", "order number", "order no"],
}
_NEG = re.compile(r"\b(no|not|without|never|don't|dont|didn't|lost|nahi|nahin)\b|नहीं")

_CITIES = {"mumbai": "Mumbai", "pune": "Pune", "delhi": "Delhi", "new delhi": "Delhi",
           "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "hyderabad": "Hyderabad",
           "chennai": "Chennai", "kolkata": "Kolkata", "ahmedabad": "Ahmedabad",
           "jaipur": "Jaipur", "lucknow": "Lucknow", "dhanbad": "Dhanbad", "ranchi": "Ranchi",
           "patna": "Patna", "indore": "Indore", "nagpur": "Nagpur", "gurgaon": "Gurugram",
           "gurugram": "Gurugram", "noida": "Noida", "kochi": "Kochi", "bhopal": "Bhopal",
           "surat": "Surat", "chandigarh": "Chandigarh", "दिल्ली": "Delhi", "मुंबई": "Mumbai",
           "पुणे": "Pune", "पटना": "Patna", "धनबाद": "Dhanbad", "रांची": "Ranchi",
           "लखनऊ": "Lucknow", "जयपुर": "Jaipur", "कोलकाता": "Kolkata"}


def parse_proof(text):
    low = text.lower()
    found = []
    for label, cues in _PROOF.items():
        for cue in cues:
            for m in re.finditer(r"(?<!\w)" + re.escape(cue) + r"(?!\w)", low):
                before = low[max(0, m.start() - 25):m.start()]
                if _NEG.search(before.split(".")[-1]):
                    continue
                found.append(label)
                break
            if label in found:
                break
    return found


def parse_city(text):
    low = text.lower()
    for k, v in _CITIES.items():
        if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", low):
            return v
    return ""


def parse_notice_days(text):
    m = re.search(r"(?:within|in)\s+(\d+)\s+days|(\d+)\s*(?:days|दिन)\s*(?:ke andar|के अंदर|में)", text.lower())
    if m:
        return int(m.group(1) or m.group(2))
    return None


# --- public -----------------------------------------------------------------

def structure_case(text, today=None):
    today = today or dt.date.today()
    case = Case(story=text.strip(), lang=detect_lang(text))
    case.problem, _ = kb.classify(text)
    update_case(case, text, today, first=True)
    return case


_DURATION = re.compile(r"(?:for|since|from)\s+(?:the\s+)?(?:last|past)?\s*(\d+|two|three|four|five|six|do|teen)\s*(months?|weeks?|mahine|mahino)"
                       r"|(\d+|do|teen)\s*(mahine|mahino|महीने)\s*(?:se|से)")


_PER_MONTH = re.compile(r"\b(a|per|every|each)\s+month\b|\bmonthly\b|/\s*month|\bpm\b|mahina|महीना|प्रति माह", re.I)


def _duration(text, today):
    m = _DURATION.search(text.lower())
    if not m:
        return "", "", None
    n_raw = m.group(1) or m.group(3)
    unit = m.group(2) or m.group(4)
    n = int(n_raw) if n_raw.isdigit() else _WORDNUM.get(n_raw, 0)
    days = n * (7 if unit.startswith("week") else 30)
    return _ago(today, days, m.group(0))


def update_case(case, text, today=None, first=False, override=False):
    """Merge facts from a follow-up message into an existing case. With
    override, a newly stated amount or date replaces the old one."""
    today = today or dt.date.today()
    if not first:
        case.story = (case.story + "\n" + text.strip()).strip()
        if case.problem is None:
            case.problem, _ = kb.classify(case.story)
    amt, amt_text = parse_amount(text)
    if amt and case.problem == "salary" and _PER_MONTH.search(text):
        m = _DURATION.search(case.story.lower())
        n_raw = (m.group(1) or m.group(3)) if m else ""
        n = int(n_raw) if n_raw.isdigit() else _WORDNUM.get(n_raw, 0)
        unit = (m.group(2) or m.group(4)) if m else ""
        if n > 1 and not unit.startswith("week"):
            amt, amt_text = amt * n, f"{fmt_inr(amt)} a month for {n} months"
    if amt and (case.amount is None or override):
        case.amount, case.amount_text = amt, amt_text
    d, dtext, dago = parse_date(text, today)
    if not d and case.problem == "salary":
        d, dtext, dago = _duration(text, today)
    if d and (not case.date or override):
        case.date, case.date_text, case.days_ago = d, dtext, dago
    if case.notice_days is None:
        case.notice_days = parse_notice_days(text)
    for p in parse_proof(text):
        if p not in case.proof:
            case.proof.append(p)
    if not case.city:
        case.city = parse_city(text)
    return case


def missing(case):
    """Which of the two facts we ask about are still unknown."""
    out = []
    if case.amount is None and case.problem != "notice":
        out.append("amount")
    if not case.date:
        out.append("date")
    return out
