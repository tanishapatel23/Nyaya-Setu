# Raw outputs

Everything in this folder was produced by running the code, with nothing edited by hand. To make it again:

```bash
python tests/run_tests.py
```

The date is fixed at 10 Nov 2026 so the deadlines in every transcript can be checked. No AI model was connected, so every answer comes from the checked knowledge base.

## What is here

- `scoreboard.txt` has one line per test conversation with the checks it passed. Current result: 278 of 278.
- `01_...md` to `36_...md` are the full conversations: what the person typed or attached, every reply, the final answer, the flags raised and the letters drafted. The tests cover English, Hindi and Hinglish, vague openings, skipped questions, every red flag, false alarm traps, a planted fake law, attached PDFs and phone photos, a pasted notice, a broken file, corrections, follow up questions, fraud and violence routing, and switching to a second case.
- `documents/` holds the Word letters built for those conversations, exactly as a user would download them.
- `practice_demo.md` is one round of the practice mode, where the app plays the other side and scores a reply.
- `ui_walkthrough.txt` is a log of a browser script clicking through the running app: typing, attaching files, every button, both languages, the Documents and Practice tabs, the calendar file, sharing, feedback, saving and reopening a case, and phone width. ok means no error appeared.
- `screenshots/` shows the app during those runs.

## Test inputs

The documents attached in the tests are made up and live in `samples/` and `tests/fixtures/`. They include a landlord's notice as a PDF and a phone photo, a rent agreement, a shopping invoice, an ex-employer's notice as a PDF and a photo, a plain notes file and a broken PDF.

## Where it went wrong before it went right

The failures found along the way are listed in the solution doc and were turned into tests here. Examples: `09_no_false_alarm` (the word hit inside white once raised a violence flag), `31_detours_while_answering_questions` (I have the UPI transfer receipt was once sent to the cyber crime helpline) and `32_statement_is_not_a_question` (they refuse to refund was once answered as a question).
