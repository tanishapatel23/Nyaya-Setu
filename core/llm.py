"""
The only file that talks to a language model.

LLM_PROVIDER=demo (default) runs fully offline. LLM_PROVIDER=openai uses any
OpenAI compatible endpoint (OPENAI_API_KEY, OPENAI_MODEL, optional
OPENAI_BASE_URL). If a call fails, every function falls back to the offline
text, so the app never breaks because of the model.
"""

from __future__ import annotations

import os

from . import kb


def provider():
    return os.environ.get("LLM_PROVIDER", "demo").strip().lower()


def model_label():
    if provider() == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return "Offline (no API key)"


def _client():
    from openai import OpenAI
    base = os.environ.get("OPENAI_BASE_URL")
    key = os.environ.get("OPENAI_API_KEY", "")
    return OpenAI(api_key=key, base_url=base) if base else OpenAI(api_key=key)


def _chat(system, user, temperature=0.3):
    resp = _client().chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=temperature,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content.strip()


RULES = """You help ordinary people in India with everyday legal problems.
Only mention a law, section, time limit or process if it appears in the
CONTEXT. Never invent a section, an Act, a case name or a penalty. If you are
unsure, say so. Use short, plain sentences. Answer in {lang}."""


def rewrite_summary(case, facts, fallback, lang):
    ctx = "\n".join(f"[{f.id}] {f.cite()}: {kb.pick(f.plain, 'en')}" for f in facts)
    user = (f"CONTEXT:\n{ctx}\n\nPERSON'S STORY:\n{case.story}\n\nDRAFT:\n{fallback}\n\n"
            "Rewrite the draft as 3 to 4 warm, plain sentences telling this person "
            "where they stand. Keep every fact in the draft. Add nothing new.")
    try:
        return _chat(RULES.format(lang="Hindi" if lang == "hi" else "English"), user)
    except Exception:
        return fallback


def answer_question(case, answer, question, lang):
    """Free-form follow-up answered from the case's facts only, then guarded."""
    from . import guard
    facts = kb.facts(case.problem)
    ctx = "\n".join(f"[{f.id}] {f.cite()}: {kb.pick(f.plain, 'en')}" for f in facts)
    plan = "\n".join(f"{w}: {t}" for w, t in (answer or {}).get("steps", []))
    user = (f"CONTEXT:\n{ctx}\n\nTHEIR CASE:\n{case.story}\n\nTHEIR PLAN:\n{plan}\n\nQUESTION: {question}\n\n"
            "Answer in 2 to 4 plain sentences. If the context does not cover it, say you are not sure "
            "and suggest NALSA's free helpline 15100.")
    try:
        text = _chat(RULES.format(lang="Hindi" if lang == "hi" else "English"), user)
    except Exception:
        return None
    return guard.verify(text, kb.allowed_citations(facts))["clean_text"]


def opponent_reply(problem_label, history, user_line):
    system = ("You are role playing the other side in this dispute so the user can "
              f"practise: {problem_label}. Push back firmly but realistically, in one "
              "or two sentences. Do not cite any law.")
    convo = "\n".join(f"{who}: {line}" for who, line in history)
    try:
        return _chat(system, f"{convo}\nUser: {user_line}\nOther side:", temperature=0.7)
    except Exception:
        return None


def transcribe(audio_bytes):
    """Speech to text through the same endpoint. Returns None if unavailable."""
    if provider() != "openai":
        return None
    try:
        import io
        f = io.BytesIO(audio_bytes)
        f.name = "voice.wav"
        model = os.environ.get("TRANSCRIBE_MODEL", "whisper-1")
        return _client().audio.transcriptions.create(model=model, file=f).text
    except Exception:
        return None
