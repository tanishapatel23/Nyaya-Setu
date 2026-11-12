"""
Runs every conversation in test_cases.yaml through the app's engine, checks the
expectations, and writes what the user would actually see to raw_outputs/.

    python3 tests/run_tests.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import advise, conversation, documents, guard, kb, practice  # noqa: E402

TODAY = dt.date(2026, 11, 10)
OUT = os.path.join(ROOT, "raw_outputs")
DOCS = os.path.join(OUT, "documents")


def known_citations():
    allf = [f for p in kb.problem_types() for f in kb.facts(p["id"])]
    return kb.allowed_citations(allf)


def citations_ok(text, known):
    for m in kb.SEC_RE.finditer(text):
        if m.group(1).lower() not in known["sections"]:
            return False
    for m in kb.ACT_RE.finditer(text):
        a = kb.norm_act(m.group(1))
        if not any(a == k or a in k or k in a for k in known["acts"]):
            return False
    return True


def _turn(t):
    """A turn is plain text, or a dict with text, files (from samples/), pick or switch."""
    if isinstance(t, str):
        return {"text": t}
    return t


def _bot_text(m):
    t = m["type"]
    if t == "choose":
        return m["text"] + "\n[Deposit] [Refund] [Salary] [Legal notice] [Something else]"
    if t == "doc":
        d = m["doc"]
        rows = "\n".join(f"  {k}: {v}" for k, v in d["rows"])
        warn = "".join(f"\n  ! {w}" for w in d["warn"])
        return f"[Read {d['file']} as: {d['title']}]\n{rows}\n{d['note']}{warn}"
    if t == "faq":
        return f"Q: {m['q']}\nA: {m['a']}"
    if t == "elsewhere":
        return "[Outside what I handle] " + m["text"]
    if t == "switch":
        return m["text"] + "\n[Start a new case for it] [Keep going with this one]"
    text = m["text"]
    if m.get("suggest"):
        text += "\n" + "\n".join(f"[{q}]" for q in m["suggest"][:4])
    return text


def _fixture(name):
    for d in ("samples", os.path.join("tests", "fixtures")):
        p = os.path.join(ROOT, d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


def run_conversation(c):
    s = conversation.Session(today=TODAY)
    log, seen = [], {"asked_type": False, "followup": False, "types": [], "docs": [], "said": []}
    for raw in c["turns"]:
        t = _turn(raw)
        if "pick" in t:
            log.append(("user", f"(taps {t['pick']})"))
            msgs = conversation.choose_problem(s, t["pick"])
        elif "switch" in t:
            log.append(("user", "(taps Start a new case for it)"))
            msgs = conversation.switch_case(s)
        else:
            files = [(f, open(_fixture(f), "rb").read()) for f in t.get("files", [])]
            shown = t.get("text", "") + "".join(f"\n(attached {f})" for f, _ in files)
            log.append(("user", shown.strip()))
            msgs = conversation.reply(s, t.get("text", ""), files)
        for m in msgs:
            seen["types"].append(m["type"])
            if m["type"] == "choose":
                seen["asked_type"] = True
            if m["type"] == "text" and s.stage == "followup":
                seen["followup"] = True
            if m["type"] == "doc":
                seen["docs"].append(m["doc"]["title"])
            if m["type"] == "answer":
                txt = advise.render_text(m["answer"], m["flags"])
                log.append(("answer", txt))
            else:
                txt = _bot_text(m)
                log.append(("bot", txt))
            seen["said"].append(txt)
    return s, log, seen


def check(c, s, seen, known):
    e = c["expect"]
    case, ans = s.case, s.answer
    r = {}
    if "problem" in e:
        r["problem"] = case.problem == e["problem"]
    if "followup" in e:
        r["followup"] = seen["followup"] == e["followup"]
    if "asked_type" in e:
        r["asked type"] = seen["asked_type"] == e["asked_type"]
    if "types" in e:
        r["message types"] = all(t in seen["types"] for t in e["types"])
    if "not_types" in e:
        r["no wrong messages"] = not any(t in seen["types"] for t in e["not_types"])
    if "docs_read" in e:
        r["documents read"] = seen["docs"] == e["docs_read"]
    said = "\n".join(seen["said"]).lower()
    for i, frag in enumerate(e.get("said", [])):
        r[f"said {i + 1}"] = frag.lower() in said
    for i, frag in enumerate(e.get("not_said", [])):
        r[f"did not say {i + 1}"] = frag.lower() not in said
    if "prefill" in e:
        pre = documents.prefill(case)
        r["letter prefilled"] = all(v.lower() in pre.get(k, "").lower() for k, v in e["prefill"].items())
    if "answered" in e:
        r["answered"] = (ans is not None) == e["answered"]
    if "amount" in e:
        r["amount"] = case.amount == e["amount"]
    if "date" in e:
        r["date"] = case.date == e["date"]
    if "deadline" in e:
        r["deadline"] = bool(ans and ans["deadline"] and ans["deadline"]["date"] == e["deadline"])
    if "reply_by" in e:
        rd = advise.reply_deadline(case, TODAY)
        r["reply by"] = bool(rd and rd.isoformat() == e["reply_by"])
    if "flags" in e:
        r["flags"] = sorted(f["id"] for f in s.flags) == sorted(e["flags"])
    if "lang" in e and ans:
        r["language"] = ans["lang"] == e["lang"]
    if "proof_has" in e:
        r["proof"] = all(p in case.proof for p in e["proof_has"])
    if ans:
        shown = advise.render_text(ans, s.flags)
        r["citations"] = citations_ok(shown.replace(_flag_text(s.flags), ""), known)
        ok_docs = True
        for kind in documents.available(case):
            d = documents.build(kind, case, documents.prefill(case), TODAY)
            ok_docs &= d is not None and "None" not in documents.to_text(d)
            documents.to_docx(d)
        if "docs" in e:
            ok_docs &= documents.available(case) == e["docs"]
        r["documents"] = ok_docs
    return r


def _flag_text(flags):
    return "\n".join("! " + f["message"] for f in flags)


def write_transcript(c, s, log):
    lines = [f"# {c['id']}", "", f"_Test date fixed at {TODAY.isoformat()}. Offline model._", ""]
    for who, text in log:
        if who == "user":
            lines += ["**User:**", "", "> " + text.replace("\n", "\n> "), ""]
        elif who == "bot":
            lines += ["**NyaySetu:**", "", text.replace("\n", "  \n"), ""]
        else:
            lines += ["**NyaySetu (answer):**", "", "```", text, "```", ""]
    if s.answer:
        for kind in documents.available(s.case):
            d = documents.build(kind, s.case, documents.prefill(s.case), TODAY)
            lines += [f"**Draft: {documents.NAMES[kind]}**", "", "```", documents.to_text(d), "```", ""]
            with open(os.path.join(DOCS, f"{c['id']}_{kind}.docx"), "wb") as fh:
                fh.write(documents.to_docx(d))
    with open(os.path.join(OUT, f"{c['id']}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def run_poison(c):
    facts = kb.facts(c["poison_problem"])
    g = guard.verify(c["poison"].strip(), kb.allowed_citations(facts))
    e = c["expect"]
    r = {"violations": len(g["violations"]) == e["violations"],
         "keeps real cite": e["keeps"] in g["clean_text"]}
    with open(os.path.join(OUT, f"{c['id']}.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {c['id']}\n\nA made-up model answer pushed through the citation guard.\n\n"
                 f"**Model said:**\n\n> {c['poison'].strip()}\n\n"
                 f"**Guard removed:** {', '.join(v['value'] for v in g['violations'])}\n\n"
                 f"**User sees:**\n\n> {g['clean_text']}\n")
    return r


def extras_checks():
    """The calendar file, the shared summary, read aloud text, and save then reopen."""
    from core import extras
    r = {}
    s = conversation.Session(today=TODAY)
    msgs = conversation.reply(s, "Landlord in Pune kept my 18000 deposit, I vacated on 1 Oct. I have the agreement.")
    ics = extras.calendar_file(s.answer, TODAY).decode()
    lines = ics.split("\r\n")
    r["calendar has 3 dated events"] = ics.count("BEGIN:VEVENT") == 3 and "DTSTART;VALUE=DATE:20261112" in ics
    r["calendar lines are folded"] = max(len(l.encode()) for l in lines) <= 75
    r["calendar has reminders"] = ics.count("BEGIN:VALARM") == 3
    share = extras.share_text(s.case, s.answer)
    r["share text has amount and steps"] = "Rs 18,000" in share and "1. Today" in share and "15100" in share
    r["read aloud says rupees"] = "rupees 18,000" in extras.speech_text(s.answer)
    raw = extras.save_case(s, [{"role": "assistant", "type": "answer", "answer": s.answer, "flags": []}])
    later = TODAY + dt.timedelta(days=10)
    s2, m2 = extras.load_case(raw, conversation.Session, later)
    r["reopened case keeps facts"] = (s2.case.amount, s2.case.date, s2.case.city) == (18000, "2026-10-01", "Pune")
    r["reopened case redoes dates"] = s2.answer["steps"][1][0] == "By 22 Nov 2026"
    r["reopened case can continue"] = any(m["type"] == "faq" for m in conversation.reply(s2, "do I need a lawyer?"))
    try:
        extras.load_case(b'{"app": "other"}', conversation.Session)
        r["rejects other files"] = False
    except ValueError:
        r["rejects other files"] = True
    sn = conversation.Session(today=TODAY)
    conversation.reply(sn, "I got a legal notice on 2 Nov asking me to pay 50000 within 15 days")
    ev = sn.answer["events"]
    r["notice reminders before the reply date"] = [e[0] for e in ev] == ["2026-11-14", "2026-11-17"]
    return r


def practice_demo():
    lines = ["# Practice tab, offline", ""]
    for pid, answers in [("deposit", ["Please return it, I need the money.",
                                      "Normal wear and tear is not damage. Send me the bills and photos or return the full amount."]),
                         ("salary", ["Clearance cannot hold back wages I already earned. Release my pay and confirm in writing what is pending."])]:
        obj = practice.rounds(pid)[0]
        for a in answers:
            res = practice.score(obj, a)
            lines += [f"**Other side ({pid}):** {obj['they_say']}", "", f"**User:** {a}", "",
                      f"**Check:** {res['verdict']}. {practice.feedback(res)}", "",
                      f"**A strong reply:** {res['model']} ({res['basis']})", ""]
    with open(os.path.join(OUT, "practice_demo.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    a = practice.score(practice.rounds("deposit")[0],
                       "Normal wear and tear is not damage. Send me the bills and photos or return the full amount.")
    b = practice.score(practice.rounds("deposit")[0], "Please return it, I need the money.")
    return a["verdict"] == "strong" and b["verdict"] == "weak"


def main():
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(ROOT, "tests", "test_cases.yaml"), encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)["cases"]
    known = known_citations()
    rows, total, passed = [], 0, 0
    for c in cases:
        if "poison" in c:
            r = run_poison(c)
        else:
            s, log, seen = run_conversation(c)
            r = check(c, s, seen, known)
            write_transcript(c, s, log)
        total += len(r)
        passed += sum(r.values())
        bad = [k for k, v in r.items() if not v]
        rows.append((c["id"], len(r), sum(r.values()), bad))
    pr = practice_demo()
    total += 1
    passed += pr
    ex = extras_checks()
    total += len(ex)
    passed += sum(ex.values())

    out = ["NyaySetu test run", f"date fixed at {TODAY}, offline model", ""]
    for cid, n, ok, bad in rows:
        out.append(f"{cid:34} {ok}/{n}" + (f"   FAILED: {', '.join(bad)}" if bad else ""))
    out.append(f"{'practice scoring':34} {int(pr)}/1")
    bad_ex = [k for k, v in ex.items() if not v]
    out.append(f"{'calendar, sharing, save and reopen':34} {sum(ex.values())}/{len(ex)}"
               + (f"   FAILED: {', '.join(bad_ex)}" if bad_ex else ""))
    out += ["", f"checks passed: {passed}/{total}"]
    text = "\n".join(out)
    print(text)
    with open(os.path.join(OUT, "scoreboard.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
