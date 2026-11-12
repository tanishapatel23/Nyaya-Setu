"""
Reads documents people attach: a legal notice they received, a rent agreement,
a bill or invoice, an offer letter or salary slip. Works offline.

Text comes from the PDF text layer, Word files, plain text, or OCR for photos
and scanned PDFs. Then we work out what kind of document it is and pull out the
fields that matter for the case and for the letters we draft.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import re
from dataclasses import dataclass, field

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
ACCEPTED = ["pdf", "docx", "txt", "png", "jpg", "jpeg", "webp", "heic", "heif"]


@dataclass
class Doc:
    name: str
    kind: str = "unknown"      # notice | agreement | invoice | job | unknown
    method: str = ""           # text | ocr | docx | txt
    text: str = ""
    fields: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def problem(self):
        return {"notice": "notice", "agreement": "deposit", "invoice": "refund",
                "job": "salary"}.get(self.kind)


# --- getting text out --------------------------------------------------------

_ocr = None


def _ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _ocr_image(img):
    import numpy as np
    eng = _ocr_engine()
    res, _ = eng(np.array(img.convert("RGB")))
    if not res:
        return ""
    # rebuild lines top to bottom
    rows = sorted(res, key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
    return "\n".join(r[1] for r in rows)


def _open_image(data):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if max(img.size) > 2200:
        img.thumbnail((2200, 2200))
    return img


def _pdf_text(data):
    """Text layer of a PDF with whichever library this computer has. Returns
    (text, found_a_library)."""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages[:6]), True
    except ImportError:
        pass
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        return "\n".join(pdf[i].get_textpage().get_text_range() for i in range(min(6, len(pdf)))), True
    except ImportError:
        pass
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=data, filetype="pdf")
        return "\n".join(doc[i].get_text() for i in range(min(6, len(doc)))), True
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages[:6]), True
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text as pm
        return pm(io.BytesIO(data), maxpages=6), True
    except ImportError:
        return "", False


def missing_libraries():
    """Optional readers that are not installed, for a setup hint in the app."""
    out = []
    for mod, pip in [("pypdf", "pypdf"), ("pypdfium2", "pypdfium2"), ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
                     ("docx", "python-docx")]:
        try:
            __import__(mod)
        except Exception:
            out.append(pip)
    return out


def extract_text(name, data):
    ext = os.path.splitext(name.lower())[1]
    warnings = []
    try:
        if ext == ".pdf":
            text, ok = _pdf_text(data)
            if len(text.strip()) >= 80:
                return text, "text", warnings
            # scanned PDF: render pages and OCR them
            try:
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(data)
                parts = [_ocr_image(pdf[i].render(scale=2).to_pil()) for i in range(min(4, len(pdf)))]
                warnings.append("ocr")
                return "\n".join(parts), "ocr", warnings
            except ImportError:
                return text, "text", ["no_ocr" if ok else "no_pdf"]
        if ext == ".docx":
            try:
                from docx import Document
            except ImportError:
                return "", "none", ["no_docx"]
            d = Document(io.BytesIO(data))
            lines = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    lines.append("  ".join(c.text for c in row.cells))
            return "\n".join(lines), "docx", warnings
        if ext in (".txt", ".md"):
            return data.decode("utf-8", "ignore"), "txt", warnings
        if ext in IMAGE_EXT:
            try:
                return _ocr_image(_open_image(data)), "ocr", ["ocr"]
            except ImportError:
                return "", "none", ["no_ocr"]
    except Exception as exc:  # a broken or locked file should not crash the app
        return "", "none", [f"unreadable: {exc.__class__.__name__}"]
    return "", "none", ["unsupported"]


def normalise(text):
    """Undo common OCR damage: words glued to numbers, O read for 0."""
    t = text.replace("₹", "Rs ").replace("₹", "Rs ")
    for _ in range(3):   # 1,20,o00 and 60,O00: letter O inside a number
        t = re.sub(r"(?:(?<=\d)|(?<=\d,))[oO](?=[\doO,]*\b)", "0", t)
    t = re.sub(r"(\d)([A-Za-z]{3,})", r"\1 \2", t)
    t = re.sub(r"\b([A-Z]?[a-z]{2,}|Rs)(\d)", r"\1 \2", t)
    t = re.sub(r"\b(Mr|Mrs|Ms|Dr|Smt|Adv)\.(?=[A-Z])", r"\1. ", t)
    t = re.sub(r"Rs\s*\.?\s*", "Rs ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t


# --- what kind of document --------------------------------------------------

_KIND_CUES = {
    "notice": ["legal notice", "call upon you", "under instructions", "on behalf of my client",
               "failing which", "advocate", "notice under section", "constrained to"],
    "agreement": ["leave and licence", "leave and license", "rent agreement", "licensor", "licensee",
                  "landlord", "tenant", "security deposit", "monthly rent", "lessor", "lessee"],
    "invoice": ["tax invoice", "invoice", "order id", "order no", "gstin", "sold by", "grand total",
                "bill to", "hsn"],
    "job": ["offer letter", "appointment letter", "ctc", "salary slip", "payslip", "net pay",
            "designation", "date of joining", "relieving letter", "gross salary"],
}


def classify(text):
    low = text.lower()
    scores = {k: sum(low.count(c) for c in cues) for k, cues in _KIND_CUES.items()}
    if "call upon you" in low or "legal notice" in low:
        scores["notice"] += 3
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "unknown"


# --- field helpers ------------------------------------------------------------

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_MON = {m[:3]: i + 1 for i, m in enumerate(_MONTHS)}
_DATE_PATTERNS = [
    (r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:day of\s*)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(20\d{2})", "dmy_name"),
    (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?,?\s*(20\d{2})", "mdy_name"),
    (r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b", "dmy"),
    (r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", "ymd"),
]


def dates(text):
    out = []
    low = text.lower()
    for pat, kind in _DATE_PATTERNS:
        for m in re.finditer(pat, low):
            g = m.groups()
            try:
                if kind == "dmy_name":
                    d = dt.date(int(g[2]), _MON[g[1][:3]], int(g[0]))
                elif kind == "mdy_name":
                    d = dt.date(int(g[2]), _MON[g[0][:3]], int(g[1]))
                elif kind == "dmy":
                    d = dt.date(int(g[2]), int(g[1]), int(g[0]))
                else:
                    d = dt.date(int(g[0]), int(g[1]), int(g[2]))
                out.append((m.start(), d))
            except (ValueError, KeyError):
                pass
    return sorted(out)


_AMT = re.compile(r"(?:rs|inr|rupees)\s*[.:]?\s*(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?", re.I)


def amounts(text):
    return [(m.start(), int(m.group(1).replace(",", ""))) for m in _AMT.finditer(text)]


def _amount_near(text, words, window=90):
    """Amount closest after a cue word; one just before it only as a fallback."""
    low = text.lower()
    after, before = None, None
    for w in words:
        for m in re.finditer(w, low):
            for pos, val in amounts(text):
                dist = pos - m.start()
                if 0 <= dist <= window and (after is None or dist < after[0]):
                    after = (dist, val)
                elif -20 <= dist < 0 and (before is None or -dist < before[0]):
                    before = (-dist, val)
    best = after or before
    return best[1] if best else None


def _split_camel(s):
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", s).strip(" ,.;:")


_HON = r"(?:Mr|Mrs|Ms|Smt|Shri|Sri|Kumari|Dr|M/s)\.?"
_NAME = r"([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3})"


# Words common in notices, used only to split words that OCR glued together
# (noticefor, MEHTALAWCHAMBERS). A token is split only if the pieces are known.
_VOCAB = set("""a an and are as at be been by bond by can client company costs date dated days dear due email for from
had has have having he her his i in into is it its law lawyer legal letter limited lakh madam my no not notice
of office on or our pay payable period private recovery rent rs said salary she sir solicitors speed post sum
that the their them this to towards training under upon was we were which with within you your associates
advocates advocate chambers partners consultants and co llp floor road residency street nagar layout cross
period shortfall agreement deposit damages licence fee amount only thousand hundred rupees reply""".split())


_FIRM_WORDS = {"law", "legal", "chambers", "associates", "advocates", "advocate", "partners", "solicitors",
               "consultants", "and", "co", "llp", "company"}


def _segment(word, allow_unknown=False):
    """Split a glued lowercase word into known words, or return None. With
    allow_unknown, one unknown piece (a surname) may sit beside firm words."""
    n = len(word)
    best = [None] * (n + 1)      # (unknown chars, pieces, list, has unknown)
    best[0] = (0, 0, [], False)
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 2, n + 1):
            piece = word[i:j]
            if piece in _VOCAB:
                unk = 0
            elif allow_unknown and len(piece) >= 3 and not best[i][3] and j - i < n:
                unk = len(piece)
            else:
                continue
            cand = (best[i][0] + unk, best[i][1] + 1, best[i][2] + [piece], best[i][3] or unk > 0)
            if best[j] is None or cand[:2] < best[j][:2]:
                best[j] = cand
    out = best[n]
    if not out or out[1] < 2:
        return None
    if out[3] and not all(p in _FIRM_WORDS for p in out[2] if p in _VOCAB):
        return None
    return out[2]


def unglue(text, names=False):
    """Put back spaces OCR dropped between words. With names, one unknown piece
    (a surname in a firm name) is allowed in an all caps token."""
    def fix(m):
        w = m.group(0)
        if w.lower() in _VOCAB or len(w) < 6:
            return w
        parts = _segment(w.lower(), allow_unknown=names and w.isupper())
        if not parts:
            return w
        out, k = [], 0
        for p in parts:
            out.append(w[k:k + len(p)])
            k += len(p)
        return " ".join(out)
    text = re.sub(r"(?<=\w)&(?=\w)", " & ", text)
    return re.sub(r"[A-Za-z]+", fix, text)


def _person_after(text, cue):
    m = re.search(cue + r"\s*,?\s*(" + _HON + r"\s*" + r"[A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3})", text)
    if m:
        name = _split_camel(m.group(1))
        name = re.split(r",|\bresiding|\baged|\bson of|\bwife of|\bR/o", name)[0]
        return name.strip()
    return ""


def _line_after(text, label, n=1):
    lines = [l.strip() for l in text.splitlines()]
    for i, l in enumerate(lines):
        if re.match(label, l, re.I):
            rest = re.sub(label, "", l, flags=re.I).strip(" ,:")
            got = [rest] if rest else []
            j = i + 1
            while len(got) < n and j < len(lines):
                if lines[j]:
                    got.append(lines[j])
                j += 1
            return got
    return []


def _sentence_with(text, cue):
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"[^.]*" + cue + r"[^.]*\.", flat, re.I)
    return m.group(0).strip() if m else ""


# --- per kind extraction ------------------------------------------------------

def _notice(text):
    f = {}
    ds = dates(text)
    m = re.search(r"date[d]?\s*[:.-]?\s*", text, re.I)
    if m:
        after = [d for pos, d in ds if pos >= m.start()]
        if after:
            f["notice_date"] = after[0].isoformat()
    if "notice_date" not in f and ds:
        f["notice_date"] = ds[0][1].isoformat()
    m = re.search(r"\bref(?:erence)?\.?\s*(?:no\.?)?\s*[:.-]\s*([A-Z0-9][A-Z0-9/.-]{3,})", text, re.I)
    if m:
        f["ref"] = m.group(1)
    m = re.search(r"\(?\s*Adv(?:ocate)?\.?\s*([A-Z][A-Za-z]+(?:\s*[A-Z][A-Za-z]+){0,3})", text)
    if m:
        f["advocate"] = "Adv. " + _split_camel(m.group(1))
    firm_lines = [l.strip() for l in text.splitlines()[:6] if re.search(r"associates|advocates?|law|legal|chambers|solicitors", l, re.I)]
    if firm_lines:
        f["firm"] = re.sub(r"\s+", " ", unglue(_split_camel(firm_lines[0]), names=True).replace("&", " & "))
    addr = [l.strip() for l in text.splitlines()[:8] if re.search(r"\b\d{6}\b", l)]
    if addr:
        f["firm_address"] = addr[0]
    f["client"] = _person_after(text, r"(?:my|our)\s+client")
    if not f["client"]:     # a company rather than a person
        m = re.search(r"(?:my|our)\s*client\s*,?\s*((?:M/s\.?\s*)?[A-Z][\w&.]*(?:\s+[A-Z&][\w&.]*){0,6})", text)
        if m:
            f["client"] = re.split(r",|\s+having\b|\s+residing\b", re.sub(r"\s+", " ", m.group(1)))[0].strip()
    to = _line_after(text, r"^to\s*[,:]?\s*$", 2) or _line_after(text, r"^to\s*[,:]", 2)
    if to:
        f["to_name"] = _split_camel(to[0])
        if len(to) > 1:
            f["to_address"] = to[1]
    sub = _line_after(text, r"^sub(?:ject)?\s*[:.-]", 3)
    if sub:     # a long subject wraps onto the next line
        keep = [sub[0]]
        for l in sub[1:]:
            if re.match(r"(sir|madam|dear|respected|\d+\s*\.|under instructions)", l, re.I):
                break
            keep.append(l)
        sub = [unglue(" ".join(keep))]
    if sub:
        f["subject"] = sub[0]
    demand = _sentence_with(text, r"call\s*upon\s*you")
    if demand:
        f["demand"] = demand
    m = re.search(r"within\s*(\d{1,3})\s*days", text, re.I)
    if m:
        f["days"] = int(m.group(1))
    amt = None
    if demand:
        a = amounts(demand)
        amt = a[0][1] if a else None
    if amt is None and f.get("subject"):
        a = amounts(f["subject"])
        amt = a[0][1] if a else None
    if amt is None:
        a = amounts(text)
        amt = max(v for _, v in a) if a else None
    if amt:
        f["amount"] = amt
    vac = _sentence_with(text, r"vacated")
    vd = dates(vac) if vac else []
    if vd:
        f["vacated"] = vd[0][1].isoformat()
    fail = _sentence_with(text, r"failing\s*which")
    low = text.lower()
    if re.search(r"criminal|\bfir\b|police|\bipc\b|\bbns\b|section\s*(?:420|406|138)", low):
        f["route"] = "criminal"
    elif re.search(r"civil|recovery|suit", fail.lower() or low):
        f["route"] = "civil"
    f["cheque"] = bool(re.search(r"cheque|dishono", low))
    f["about_tenancy"] = bool(re.search(r"licen[cs]e|\btenan|\brent\b|\bflat\b|premises|\bvacat", low))
    f["about_job"] = bool(re.search(r"\bemploy|appointment letter|\bresign|\bsalary|relieving|\bhr\b", low))
    f["notice_pay"] = bool(f["about_job"] and re.search(r"notice\s*period|in lieu of\s*(?:the\s*)?notice", low))
    f["bond"] = bool(re.search(r"\bbond\b|training\s*cost", low))
    m = re.search(r"resign\w*", text, re.I)
    if m and f["about_job"]:
        ds = [d for pos, d in dates(text) if pos >= m.start()]
        if ds:
            f["resigned"] = ds[0].isoformat()
    f["claims_damage"] = bool(re.search(r"damage|repair|repaint|painting|broken", low))
    return {k: v for k, v in f.items() if v not in ("", None)}


def _agreement(text):
    f = {}
    f["landlord"] = (_person_after(text, r"between") or
                     _person_after(text, r"(?:licensor|landlord|owner|lessor)\s*[:,]?"))
    f["tenant"] = (_person_after(text, r"(?:licensor|landlord|owner|lessor)\W{0,40}?\band") or
                   _person_after(text, r"(?:licensee|tenant|lessee)\s*[:]"))
    if not f["tenant"]:
        names = re.findall(_HON + r"\s*[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}", text)
        names = [_split_camel(n) for n in names]
        others = [n for n in names if n != f["landlord"]]
        f["tenant"] = others[0] if others else ""
    m = re.search(r"premises\s*(?:being|situated at|at|known as)?\s*[:,]?\s*((?:Flat|House|Room|Shop|Plot|Unit|No)[^()\n]{5,120}?\b\d{6}\b)", text, re.I)
    if not m:
        m = re.search(r"((?:Flat|House|Room|Shop|Plot)\s*(?:No\.?)?\s*\w+[^()\n]{5,100}?\b\d{6}\b)", text)
    if m:
        f["premises"] = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(_re_name(f.get("landlord", "")) + r"[^.]{0,20}?residing at\s*([^,]+(?:,[^,]+){0,3}?\b\d{6}\b)", text) if f.get("landlord") else None
    if m:
        f["landlord_address"] = re.sub(r"\s+", " ", m.group(1)).strip()
    f["deposit"] = _amount_near(text, [r"deposit"], 110)
    f["rent"] = _amount_near(text, [r"monthly (?:licen[cs]e fee|rent)", r"\brent\b", r"licen[cs]e fee"], 80)
    ds = dates(text)
    if ds:
        f["start_date"] = ds[0][1].isoformat()
    m = re.search(r"(one|two|three|1|2|3)\s*months?\s*(?:'s\s*)?(?:prior\s*)?notice", text, re.I)
    if m:
        f["notice_period"] = m.group(0)
    return {k: v for k, v in f.items() if v not in ("", None)}


def _re_name(name):
    return re.escape(name) if name else r"(?!x)x"


def _invoice(text):
    f = {}
    m = re.search(r"order\s*(?:id|no\.?|number)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{5,})", text, re.I)
    if m:
        f["order_id"] = m.group(1)
    m = re.search(r"invoice\s*(?:no\.?|number)\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{3,})", text, re.I)
    if m:
        f["invoice_no"] = m.group(1)
    m = re.search(r"order\s*date\s*[:]?\s*", text, re.I)
    ds = dates(text)
    if m:
        after = [d for pos, d in ds if pos >= m.start()]
        if after:
            f["date"] = after[0].isoformat()
    if "date" not in f and ds:
        f["date"] = ds[0][1].isoformat()
    seller = _line_after(text, r"^\s*(?:sold\s*by|seller)\s*[:]", 2)
    if seller:
        f["seller"] = seller[0]
        if len(seller) > 1:
            f["seller_address"] = seller[1]
    bill = _line_after(text, r"^\s*bill(?:ed)?\s*to\s*[:]", 1)
    if bill:
        f["buyer"] = bill[0].split(",")[0].strip()
    tot = _amount_near(text, [r"grand\s*total", r"total\s*amount", r"amount\s*payable", r"net\s*amount"], 60)
    if not tot:
        a = amounts(text)
        tot = max(v for _, v in a) if a else None
    if tot:
        f["amount"] = tot
    m = re.search(r"return[s]?[^.]{0,40}?within\s*(\d+)\s*days", text, re.I)
    if m:
        f["return_days"] = int(m.group(1))
    return {k: v for k, v in f.items() if v not in ("", None)}


def _job(text):
    f = {}
    for l in text.splitlines()[:10]:
        if re.search(r"(private limited|pvt\.? ?ltd|limited|llp|technologies|solutions|services|labs)\b", l, re.I):
            f["employer"] = l.strip()
            break
    m = re.search(r"(?:designation|position|role)\s*[:]\s*(.+)", text, re.I)
    if m:
        f["designation"] = m.group(1).strip()
    f["net_pay"] = _amount_near(text, [r"net\s*(?:pay|salary)", r"take\s*home"], 50)
    f["ctc"] = _amount_near(text, [r"\bctc\b", r"cost to company"], 60)
    m = re.search(r"date\s*of\s*joining\s*[:]?\s*", text, re.I)
    ds = dates(text)
    if m:
        after = [d for pos, d in ds if pos >= m.start()]
        if after:
            f["joining"] = after[0].isoformat()
    return {k: v for k, v in f.items() if v not in ("", None)}


def tidy_address(a):
    """OCR often drops the spaces in an address line: OfficeNo.14,LaxmiChambers,FCRoad."""
    a = re.sub(r",(?=\S)", ", ", a)
    a = re.sub(r"([a-z])([A-Z])", r"\1 \2", a)
    a = re.sub(r"\b(No|Opp|Nr)\.(?=\w)", r"\1. ", a)
    a = re.sub(r"([A-Z])([A-Z][a-z]{2,})", r"\1 \2", a)
    a = re.sub(r"(?<=[A-Za-z])(?=\d{6}\b)", " ", a)
    a = re.sub(r"\b(\d+)\s+(st|nd|rd|th)\b", r"\1\2", a)
    return re.sub(r"\s+", " ", a).strip(" ,")


def read(name, data):
    raw, method, warnings = extract_text(name, data)
    text = normalise(raw)
    doc = Doc(name=name, method=method, text=text, warnings=warnings)
    if len(text.strip()) < 30:
        doc.warnings.append("empty")
        return doc
    doc.kind = classify(text)
    doc.fields = {"notice": _notice, "agreement": _agreement, "invoice": _invoice,
                  "job": _job}.get(doc.kind, lambda t: {})(text)
    for k, v in doc.fields.items():
        if k.endswith("address") and isinstance(v, str):
            doc.fields[k] = tidy_address(v)
    return doc


def looks_like_pasted_notice(text):
    return len(text) > 300 and classify(normalise(text)) == "notice"
