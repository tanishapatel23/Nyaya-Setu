"""
NyaySetu, a legal helper for everyday problems in India.

    pip install -r requirements.txt
    streamlit run app.py

Runs offline by default. See README for connecting a model.
"""

from __future__ import annotations

import datetime as dt
import inspect
import os

import json
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from core import advise, conversation, documents, extras, kb, llm, practice, reader
from ui import render

HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title="NyaySetu", page_icon=":material/verified_user:",
                   layout="wide", initial_sidebar_state="collapsed")
with open(os.path.join(HERE, "ui", "style.css"), encoding="utf-8") as fh:
    st.markdown(f"<style>{fh.read()}</style>", unsafe_allow_html=True)

EXAMPLES = [
    "My landlord in Pune kept my Rs 40,000 deposit. I moved out on 5 September and I have the rent agreement.",
    "I ordered a phone for Rs 15,000 last month. It arrived damaged and the seller will not refund it.",
    "My boss hasn't paid my salary for 2 months and HR keeps saying the settlement is pending.",
    "मकान मालिक ने मेरा 25000 रुपये का डिपॉज़िट वापस नहीं किया। मैंने 3 महीने पहले घर खाली किया था।",
]
SAMPLES = [("Notice photo", "notice_photo.jpg"), ("Rent agreement", "agreement.pdf"),
           ("Shopping invoice", "invoice.pdf")]
TYPES = [("deposit", "Deposit", "डिपॉज़िट"), ("refund", "Refund", "रिफंड"), ("salary", "Salary", "वेतन"),
         ("notice", "Legal notice", "कानूनी नोटिस")]
VOICE = llm.provider() != "demo"

ss = st.session_state
if "sess" not in ss:
    ss.sess = conversation.Session()
    ss.msgs, ss.round, ss.checked, ss.spar = [], 0, None, []


def lang():
    return ss.sess.lang()


HI = {
    'Download my case summary': 'केस का सारांश डाउनलोड करें',
    'I filled in what I could from your conversation and documents. Check every line.': 'बातचीत और दस्तावेज़ों से जो भर सका, भर दिया है। हर लाइन जाँच लें। चिट्ठी अंग्रेज़ी में है क्योंकि कानूनी पत्र आमतौर पर अंग्रेज़ी में भेजे जाते हैं।',
    'Your name': 'आपका नाम',
    'Your address': 'आपका पता',
    'Their name (landlord, company, seller or their lawyer)': 'सामने वाले का नाम (मकान मालिक, कंपनी, विक्रेता या उनके वकील)',
    'Their address': 'सामने वाले का पता',
    'Address of the rented place': 'किराये के मकान का पता',
    'Order or invoice number': 'ऑर्डर या इनवॉइस नंबर',
    'What went wrong, in a few words': 'क्या गड़बड़ हुई, कुछ शब्दों में',
    'Your job title': 'आपका पद',
    'Date written on their notice': 'उनके नोटिस पर लिखी तारीख़',
    'Your side of the story': 'आपका पक्ष',
    'Anything else to add (optional)': 'कुछ और जोड़ना हो (वैकल्पिक)',
    'Word file': 'Word फ़ाइल',
    'Text file': 'टेक्स्ट फ़ाइल',
    'What would you say back?': 'आप क्या जवाब देंगे?',
    'Check my answer': 'मेरा जवाब जाँचें',
    'Next line': 'अगली बात',
    'Save this case to continue later': 'केस सेव करें, बाद में जारी रखें',
    'Keeps what you told me and what I read from your files. Open it again from the first screen.': 'आपकी बताई बातें और फ़ाइलों से पढ़ी जानकारी सेव रहती है। पहली स्क्रीन से इसे फिर खोलें।',
    'Share with a lawyer or family': 'वकील या परिवार को भेजें',
    'Copy this with the icon in its corner, or send it straight away.': 'कोने वाले आइकन से कॉपी करें, या सीधे भेज दें।',
}


def tr(en):
    return HI.get(en, en) if lang() == "hi" else en


def push(results):
    for r in results:
        ss.msgs.append({"role": "assistant", **r})


def handle(text="", files=()):
    text = (text or "").strip()
    if not text and not files:
        return
    ss.msgs.append({"role": "user", "type": "text", "text": text, "files": [n for n, _ in files]})
    push(conversation.reply(ss.sess, text, files))


def take(value):
    """Turn a chat_input value (text, files, audio) into a call to handle()."""
    if value is None:
        return
    text = getattr(value, "text", value if isinstance(value, str) else "") or ""
    files = [(f.name, f.getvalue()) for f in (getattr(value, "files", None) or [])]
    audio = getattr(value, "audio", None)
    if audio is not None:
        heard = llm.transcribe(audio.getvalue())
        text = (text + " " + heard).strip() if heard else text
    handle(text, files)
    st.rerun()


def new_case():
    forced = ss.sess.forced_lang
    ss.sess = conversation.Session(forced_lang=forced, case_id=ss.sess.case_id + 1)
    ss.msgs, ss.round, ss.checked, ss.spar = [], 0, None, []


def chips(items, key):
    cols = st.columns(min(len(items), 2) or 1)
    for j, q in enumerate(items):
        if cols[j % len(cols)].button(q, key=f"sg_{key}_{j}", use_container_width=True):
            handle(q)
            st.rerun()


# Older Streamlit versions lack some chat_input options, so only pass what this one supports.
_CI = inspect.signature(st.chat_input).parameters
CHAT_FILES = "accept_file" in _CI
CHAT_AUDIO = "accept_audio" in _CI and VOICE


def box(key):
    """A container with a CSS hook, on Streamlit versions that support keys."""
    try:
        return st.container(key=key)
    except TypeError:
        return st.container()


def read_aloud(ans, key):
    """A button that reads the answer out with the browser's own voice. Works offline."""
    hi = ans["lang"] == "hi"
    payload = json.dumps({"text": extras.speech_text(ans), "lang": "hi-IN" if hi else "en-IN",
                          "play": "सुनें" if hi else "Read aloud", "stop": "रोकें" if hi else "Stop"})
    components.html("""
<style>
 body{margin:0;font-family:Manrope,system-ui,sans-serif}
 button{width:100%;height:40px;border:1px solid #CFE3E1;border-radius:10px;background:#F4FAF9;color:#075E5A;font-weight:600;
        font-size:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px}
 button:hover{border-color:#0B7A75;background:#E3F2F1}
 button.on{background:#0B7A75;border-color:#0B7A75;color:#fff}
</style>
<button id="b"><span id="i">&#128266;</span><span id="t"></span></button>
<script>
const P = __PAYLOAD__; const b = document.getElementById('b'), t = document.getElementById('t');
const synth = window.speechSynthesis; t.textContent = P.play;
if (!synth) { b.disabled = true; t.textContent = 'Not supported here'; }
function voice(){ const v = synth.getVoices(); const base = P.lang.slice(0,2);
  return v.find(x => x.lang === P.lang) || v.find(x => x.lang.startsWith(base)) || null; }
function stop(){ synth.cancel(); b.classList.remove('on'); t.textContent = P.play; }
b.onclick = () => {
  if (synth.speaking) { stop(); return; }
  const parts = P.text.match(/[^.!?\u0964]+[.!?\u0964]?/g) || [P.text];
  parts.forEach((s, k) => { const u = new SpeechSynthesisUtterance(s.trim()); u.lang = P.lang; u.rate = 0.95;
    const v = voice(); if (v) u.voice = v; if (k === parts.length - 1) u.onend = stop; synth.speak(u); });
  b.classList.add('on'); t.textContent = P.stop;
};
</script>""".replace("__PAYLOAD__", payload), height=44)


def answer_actions(ans, i):
    """Read aloud, add the dates to a calendar, share on WhatsApp, and rate the answer."""
    hi = ans["lang"] == "hi"
    c1, c2, c3 = st.columns(3)
    with c1:
        read_aloud(ans, i)
    if ans.get("events"):
        c2.download_button("कैलेंडर में जोड़ें" if hi else "Add to calendar", extras.calendar_file(ans),
                           file_name="nyaysetu_dates.ics", mime="text/calendar", icon=":material/event:",
                           use_container_width=True, key=f"ics_{ss.sess.case_id}_{i}")
    c3.link_button("व्हाट्सएप पर भेजें" if hi else "Share on WhatsApp",
                   "https://wa.me/?text=" + quote(extras.share_text(ss.sess.case, ans)),
                   icon=":material/share:", use_container_width=True)
    rate(ans["problem"], f"{ss.sess.case_id}_{i}", "answer")


def rate(problem, key, where):
    if not hasattr(st, "feedback"):
        return
    done = ss.setdefault("rated", {})
    k = f"fb_{where}_{key}"
    if k in done:
        st.caption("Thanks, noted." if lang() == "en" else "धन्यवाद, नोट कर लिया।")
        return
    c1, c2 = st.columns([1, 2.6], vertical_alignment="center")
    c1.caption("Was this useful?" if lang() == "en" else "क्या यह काम आया?")
    with c2:
        v = st.feedback("thumbs", key=k)
    if v is not None:
        extras.record_feedback(problem, "up" if v == 1 else "down", where)
        done[k] = v
        st.rerun()


def open_saved(key):
    """Reopen a case saved earlier with Save this case."""
    up = st.file_uploader("Open a case you saved earlier" if lang() == "en" else "पहले सेव किया केस खोलें",
                          type=["json"], key=f"open_{key}_{ss.get('openn', 0)}")
    if up is not None:
        try:
            sess, msgs = extras.load_case(up.getvalue(), conversation.Session)
        except Exception:
            st.error("This does not look like a NyaySetu case file." if lang() == "en"
                     else "यह NyaySetu की केस फ़ाइल नहीं लगती।")
            return
        sess.case_id = ss.sess.case_id + 1
        ss.sess, ss.msgs, ss.round, ss.checked = sess, msgs, 0, None
        ss.msgs.append({"role": "assistant", "type": "text", "text": (
            "Welcome back. I have reopened your case and worked out the dates again for today."
            if sess.lang() == "en" else "फिर से स्वागत है। आपका केस खुल गया है और तारीख़ें आज के हिसाब से फिर से निकाल दी हैं।")})
        ss.openn = ss.get("openn", 0) + 1
        st.rerun()


def composer(key):
    hint = ("Type what happened, or attach a notice or bill"
            if lang() == "en" else "जो हुआ वह लिखें, या नोटिस या बिल अटैच करें")
    kw = {}
    if CHAT_FILES:
        kw.update(accept_file="multiple", file_type=reader.ACCEPTED)
    if CHAT_AUDIO:
        kw["accept_audio"] = True
    return st.chat_input(hint, key=key, **kw)


def uploader(key):
    """Separate file picker, used only when chat_input cannot take files."""
    if CHAT_FILES:
        return
    up = st.file_uploader("Attach a notice, agreement or bill" if lang() == "en" else "नोटिस, एग्रीमेंट या बिल अटैच करें",
                          type=reader.ACCEPTED, accept_multiple_files=True, key=f"up_{key}_{ss.get('upn', 0)}")
    if up and st.button("Read these files" if lang() == "en" else "ये फ़ाइलें पढ़ें", key=f"upgo_{key}",
                        type="primary"):
        handle("", [(f.name, f.getvalue()) for f in up])
        ss.upn = ss.get("upn", 0) + 1
        st.rerun()


def pills(label, options, default, key, fmt=str):
    """segmented_control where available, a horizontal radio otherwise."""
    if hasattr(st, "segmented_control"):
        return st.segmented_control(label, options, default=default, key=key, format_func=fmt,
                                    label_visibility="collapsed") or default
    return st.radio(label, options, index=options.index(default), key=key, format_func=fmt,
                    horizontal=True, label_visibility="collapsed")


# --- header -------------------------------------------------------------------
with box("topbar"):
    h1, h2, h3 = st.columns([3.1, 1.5, 0.9], vertical_alignment="center")
with h1:
    st.markdown('<div class="hq-brand"><div class="hq-mark">न</div><div><h1>NyaySetu<span class="dev">न्यायसेतु</span></h1>'
                '<p class="hq-tag">Get back what is yours. Deposits, refunds, unpaid salary and legal notices, '
                'in plain words with real dates.</p></div></div>', unsafe_allow_html=True)
with h2:
    choice = pills("Reply in", ["Auto", "English", "हिन्दी"], "Auto", "langpick")
    forced = {"English": "en", "हिन्दी": "hi"}.get(choice)
    if forced != ss.sess.forced_lang:
        ss.sess.forced_lang = forced
        if ss.sess.answer:
            ss.sess.answer = advise.build_answer(ss.sess.case, ss.sess.today, lang())
            for m in reversed(ss.msgs):
                if m.get("type") == "answer":
                    m["answer"] = ss.sess.answer
                    break
with h3, box("newcase"):
    if st.button("New case", icon=":material/add:", use_container_width=True):
        new_case()
        st.rerun()

MISSING = reader.missing_libraries()
if MISSING:
    st.warning("Some document readers are not installed on this computer (" + ", ".join(MISSING) + "), so "
               "attached files may not be read. In the app folder run: pip install -r requirements.txt "
               "then restart the app.", icon=":material/build:")

st.write("")
right, left = st.columns([1, 2.1], gap="large")

# --- conversation ---------------------------------------------------------------
with left:
    if not ss.msgs:
        st.markdown('<div class="hq-hero"><div class="eyebrow">Start here</div>'
                    '<h2>Tell me what happened, in your own words.</h2>'
                    '<p>English, Hindi or a mix is fine. Got a notice or an agreement? Attach it with the clip '
                    'icon and I will read it.</p><div class="hq-steps3">'
                    '<div><b>1. Tell</b>Describe the problem or attach the paper you got.</div>'
                    '<div><b>2. Understand</b>See where you stand, your deadline and dated next steps.</div>'
                    '<div><b>3. Act</b>Download a ready letter and practise what to say.</div>'
                    '</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="hq-compose-label">Type here <span>or attach a photo or PDF</span></div>',
                    unsafe_allow_html=True)
        take(composer("first"))
        uploader("first")
        st.markdown('<div class="hq-kicker">Start from an example</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        for i, ex in enumerate(EXAMPLES):
            with (c1 if i % 2 == 0 else c2):
                if st.button(ex, key=f"ex{i}", use_container_width=True):
                    handle(ex)
                    st.rerun()
        st.markdown('<div class="hq-kicker">No document handy? Try a sample file</div>', unsafe_allow_html=True)
        sc = st.columns(3)
        for col, (label, fname) in zip(sc, SAMPLES):
            if col.button(label, key=f"sample_{fname}", icon=":material/attach_file:", use_container_width=True):
                handle("", [(fname, open(os.path.join(HERE, "samples", fname), "rb").read())])
                st.rerun()
        with st.expander("Continue a case you saved earlier", icon=":material/folder_open:"):
            open_saved("welcome")

    last = len(ss.msgs) - 1
    last_answer = max([j for j, x in enumerate(ss.msgs) if x.get("type") == "answer"], default=-1)
    for i, m in enumerate(ss.msgs):
        if m["role"] == "user":
            with st.chat_message("user", avatar=":material/person:"):
                if m.get("text"):
                    st.markdown(m["text"])
                for n in m.get("files", []):
                    st.markdown(f":material/attach_file: `{n}`")
            continue
        with st.chat_message("assistant", avatar=":material/verified_user:"):
            t = m["type"]
            if m.get("flags") and t in ("text", "choose"):
                st.markdown(render.flags_html(m["flags"], lang()), unsafe_allow_html=True)
            if t == "text":
                st.markdown(m["text"])
                if m.get("suggest") and i == last:
                    chips(m["suggest"], f"t{i}")
            elif t == "choose":
                st.markdown(m["text"])
                if i == last and ss.sess.stage == "clarify":
                    cols = st.columns(5)
                    names = {p: (en, hi) for p, en, hi in TYPES}
                    for col, pid in zip(cols, m["options"] + ["other"]):
                        label = ("कुछ और" if lang() == "hi" else "Something else") if pid == "other" \
                            else names[pid][1 if lang() == "hi" else 0]
                        if col.button(label, key=f"pick_{pid}_{i}", use_container_width=True):
                            push(conversation.choose_problem(ss.sess, pid))
                            st.rerun()
            elif t == "doc":
                d = m["doc"]
                st.markdown(render.doc_html(d), unsafe_allow_html=True)
                how = {"text": "text layer of the PDF", "ocr": "photo, read with OCR", "docx": "Word file",
                       "txt": "text file"}.get(d.get("method"), "nothing could be read")
                with st.expander(("Show the text I read" if lang() == "en" else "पढ़ा गया टेक्स्ट देखें") + f" ({how})",
                                 icon=":material/description:"):
                    if d.get("raw", "").strip():
                        try:
                            st.code(d["raw"][:4000], language=None, wrap_lines=True)
                        except TypeError:
                            st.code(d["raw"][:4000], language=None)
                    else:
                        st.caption("No text came out of this file. Details: " + (", ".join(d.get("why", [])) or "none"))
            elif t == "faq":
                st.markdown(render.faq_html(m), unsafe_allow_html=True)
                if i == last:
                    rate(ss.sess.case.problem if ss.sess.case else None, f"{ss.sess.case_id}_{i}", "faq")
            elif t == "elsewhere":
                st.markdown(render.elsewhere_html(m["text"]), unsafe_allow_html=True)
            elif t == "switch":
                st.markdown(m["text"])
                if i == last:
                    a, b = st.columns(2)
                    if a.button("Start a new case for it" if lang() == "en" else "नया केस शुरू करें",
                                key=f"sw_new_{i}", use_container_width=True, type="primary"):
                        push(conversation.switch_case(ss.sess))
                        ss.round, ss.checked = 0, None
                        st.rerun()
                    if b.button("Keep going with this one" if lang() == "en" else "इसी केस पर रहें",
                                key=f"sw_keep_{i}", use_container_width=True):
                        ss.sess.pending = ""
                        ss.msgs.append({"role": "assistant", "type": "text",
                                        "text": "Okay, staying with this case." if lang() == "en" else "ठीक है, इसी केस पर रहते हैं।"})
                        st.rerun()
            elif t == "answer":
                html = render.flags_html(m["flags"], m["answer"]["lang"]) + render.answer_html(m["answer"])
                if i == last_answer:
                    st.markdown(html, unsafe_allow_html=True)
                    if ss.sess.answer and m["answer"].get("problem") == ss.sess.answer.get("problem"):
                        answer_actions(ss.sess.answer, i)
                else:
                    head = ("पिछला जवाब: " if lang() == "hi" else "Earlier answer: ") + m["answer"]["label"]
                    with st.expander(head, icon=":material/history:"):
                        st.markdown(html, unsafe_allow_html=True)
            if t in ("answer", "faq", "doc") and i == last and ss.sess.answer:
                asked = {x.get("q") for x in ss.msgs if x.get("type") == "faq"}
                left_q = [q for q in ss.sess.answer.get("suggest", []) if q not in asked]
                if left_q:
                    st.markdown('<div class="hq-sub">You might also ask</div>' if lang() == "en"
                                else '<div class="hq-sub">आप यह भी पूछ सकते हैं</div>', unsafe_allow_html=True)
                    chips(left_q[:4], f"a{i}")

with right, box("casefile"):
    case, ans = ss.sess.case, ss.sess.answer
    st.markdown(render.case_file_html(case, ans, ss.sess.flags, lang()), unsafe_allow_html=True)
    if case and case.problem:
        with st.expander("Edit the details" if lang() == "en" else "जानकारी बदलें", icon=":material/edit:"):
            with st.form(f"edit_{ss.sess.case_id}"):
                pids = [p for p, _, _ in TYPES]
                prob = st.selectbox("Problem", pids, index=pids.index(case.problem),
                                    format_func=lambda p: dict((x, y) for x, y, _ in TYPES)[p])
                amt = st.number_input("Amount (Rs)", min_value=0, step=500, value=int(case.amount or 0))
                when = st.date_input("Key date", value=dt.date.fromisoformat(case.date) if case.date else None,
                                     max_value=dt.date.today(), format="DD/MM/YYYY")
                city = st.text_input("City", value=case.city)
                if st.form_submit_button("Update my answer", type="primary", use_container_width=True):
                    push(conversation.apply_edits(ss.sess, amount=amt or None, date=when, city=city, problem=prob))
                    st.rerun()
    if ans:
        try:
            st.download_button(tr("Download my case summary"), documents.case_summary_docx(case, ans),
                               file_name="my_case_summary.docx", icon=":material/download:",
                               use_container_width=True)
        except ImportError:
            st.caption("Install python-docx to download a summary.")
    if case and case.problem:
        st.download_button(tr("Save this case to continue later"), extras.save_case(ss.sess, ss.msgs),
                           file_name=f"nyaysetu_case_{dt.date.today():%Y%m%d}.json", mime="application/json",
                           icon=":material/save:", use_container_width=True)
        st.caption(tr("Keeps what you told me and what I read from your files. Open it again from the first screen."))
    if ans:
        with st.expander(tr("Share with a lawyer or family"), icon=":material/share:"):
            text = extras.share_text(case, ans)
            st.caption(tr("Copy this with the icon in its corner, or send it straight away."))
            try:
                st.code(text, language=None, wrap_lines=True)
            except TypeError:
                st.code(text, language=None)
            a, b = st.columns(2)
            a.link_button("WhatsApp", "https://wa.me/?text=" + quote(text), use_container_width=True)
            b.link_button("Email", "mailto:?subject=" + quote("My case: " + ans["label"]) + "&body=" + quote(text),
                          use_container_width=True)
    st.caption(f"Model: {llm.model_label()}. Law last checked {kb.last_verified()}.")
    st.caption("NyaySetu is an independent project. It is not affiliated with the Government of India "
               "or the Ministry of Law and Justice Nyaya Setu service."
               if lang() == "en" else "NyaySetu एक स्वतंत्र प्रोजेक्ट है। इसका भारत सरकार या कानून मंत्रालय की Nyaya Setu सेवा से कोई संबंध नहीं है।")

# --- tools, once there is an answer ------------------------------------------------
ans = ss.sess.answer
if ans:
    L = ans["lang"]
    st.markdown('<div class="hq-section">अपने केस पर काम करें<span>चिट्ठी, बहस की तैयारी और कानून</span></div>' if L == "hi"
                else '<div class="hq-section">Work on your case<span>Draft the letter, practise your reply and read the law behind it</span></div>',
                unsafe_allow_html=True)
    case = ss.sess.case
    cid = f"{ss.sess.case_id}_{len(case.docs)}"
    t_doc, t_prac, t_law = st.tabs(["चिट्ठी बनाएँ", "बहस की तैयारी", "कानून और स्रोत"] if L == "hi"
                                   else ["Documents", "Practice", "The law"])

    with t_doc:
        kinds = documents.available(case)
        kind = pills("Draft", kinds, kinds[0], f"dockind_{cid}", lambda k: documents.NAMES[k])
        pre = documents.prefill(case)
        if pre:
            st.caption(tr("I filled in what I could from your conversation and documents. Check every line."))
        p, f = st.columns([1.4, 1], gap="large")
        with f:
            def field(label, name, area=False, h=68):
                w = st.text_area if area else st.text_input
                kw = {"height": h} if area else {}
                return w(label, value=pre.get(name, ""), key=f"{name}_{cid}", **kw)
            det = {"your_name": field(tr("Your name"), "your_name"),
                   "your_address": field(tr("Your address"), "your_address", True),
                   "their_name": field(tr("Their name (landlord, company, seller or their lawyer)"), "their_name"),
                   "their_address": field(tr("Their address"), "their_address", True)}
            if case.problem == "deposit":
                det["premises"] = field(tr("Address of the rented place"), "premises")
            if case.problem == "refund":
                det["order_id"] = field(tr("Order or invoice number"), "order_id")
                det["issue"] = field(tr("What went wrong, in a few words"), "issue")
            if case.problem == "salary":
                det["designation"] = field(tr("Your job title"), "designation")
            if kind == "reply":
                det["notice_date"] = field(tr("Date written on their notice"), "notice_date")
                det["extra"] = field(tr("Your side of the story"), "extra", True, 140)
            else:
                det["extra"] = field(tr("Anything else to add (optional)"), "extra", True)
        doc = documents.build(kind, case, det)
        with p:
            st.markdown(render.paper_html(doc), unsafe_allow_html=True)
            d1, d2 = st.columns(2)
            try:
                d1.download_button(tr("Word file"), documents.to_docx(doc), file_name=f"{kind}.docx",
                                   icon=":material/download:", use_container_width=True, type="primary",
                                   key=f"dl_docx_{cid}")
            except ImportError:
                d1.caption("Install python-docx for the Word file.")
            d2.download_button(tr("Text file"), documents.to_text(doc), file_name=f"{kind}.txt",
                               icon=":material/download:", use_container_width=True, key=f"dl_txt_{cid}")

    with t_prac:
        rounds = practice.rounds(ans["problem"])
        obj = rounds[ss.round % len(rounds)]
        n_r = ss.round % len(rounds) + 1
        st.caption(f"राउंड {n_r} / {len(rounds)}। सामने वाला कहता है:" if L == "hi"
                   else f"Round {n_r} of {len(rounds)}. The other side says:")
        st.markdown(f'<div class="hq-them"><small>Other side</small>{obj["they_say"]}</div>',
                    unsafe_allow_html=True)
        said = st.text_area(tr("What would you say back?"), key=f"prac_{cid}_{ss.round}", height=90)
        b1, b2 = st.columns(2)
        if b1.button(tr("Check my answer"), type="primary", use_container_width=True, key=f"chk_{cid}"):
            ss.checked = practice.score(obj, said)
        if b2.button(tr("Next line"), use_container_width=True, key=f"nxt_{cid}"):
            ss.round += 1
            ss.checked = None
            st.rerun()
        if ss.checked:
            r = ss.checked
            v = r["verdict"] if r["verdict"] != "empty" else "partial"
            st.markdown(f'<div class="hq-verdict hq-v-{v}">{practice.feedback(r)}</div>'
                        f'<div class="hq-model"><b>A strong reply:</b> {r["model"]}'
                        f'<br><span class="hq-src">{r["basis"]}</span></div>', unsafe_allow_html=True)
        if VOICE:
            with st.expander("Free sparring with the model"):
                for who, line in ss.spar:
                    st.markdown(f"**{who}:** {line}")
                line = st.text_input("You", key=f"spar_{len(ss.spar)}")
                if line:
                    back = llm.opponent_reply(ans["label"], ss.spar, line)
                    ss.spar += [("You", line), ("Other side", back or "...")]
                    st.rerun()

    with t_law:
        st.markdown(render.law_html(ans), unsafe_allow_html=True)
        st.caption(kb.disclaimer(L))

if ss.msgs:
    with left:
        uploader("main")
    take(composer("main"))
