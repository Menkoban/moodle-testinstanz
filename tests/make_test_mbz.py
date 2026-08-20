# -*- coding: utf-8 -*-
"""Baut Mini-Test-Artefakte fuer die run_restore-Vertragstests:
   ok.mbz  = kleiner gueltiger Kurs (page + feedback mit Label-Item)
   bad.mbz = identisch, aber feedback-Item <name>$@NULL@$</name>
             (der reale dmlwriteexception-Killer von 2026-07-15)."""
import io, json, os, subprocess, sys, tarfile

BASE = os.path.dirname(os.path.abspath(__file__))

def _find_mbz_skill():
    candidates = [
        os.path.normpath(os.path.join(BASE, "..", "..", "moodle-mbz-builder")),
        os.path.expanduser("~/.gemini/config/skills/moodle-mbz-builder"),
        os.path.expanduser("~/.claude/skills/moodle-mbz-builder"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]

SKILL = _find_mbz_skill()

course = {
    "filename": "ok.mbz",
    "course": {
        "fullname": "Testinstanz Vertragstest",
        "shortname": "TI-VERTRAG",
        "format": "topics",
        "summary": "<p>Wegwerf-Kurs für run_restore-Vertragstests.</p>",
    },
    "sections": [
        {"name": "Test", "summary": "<p>Testsektion</p>", "activities": [
            {"type": "page", "name": "Testseite",
             "content": "<p>Inhalt für den Vertragstest.</p>"},
            {"type": "feedback", "name": "Test-Feedback",
             "intro": "<p>Testet den historischen NULL-Bug-Pfad.</p>",
             "items": [
                 {"type": "label", "text": "<p>Label-Item (name muss '' sein)</p>"},
                 {"type": "multichoice", "name": "Testfrage?",
                  "options": ["a", "b"]},
             ]},
        ]},
    ],
}

cj = os.path.join(BASE, "ti_course.json")
json.dump(course, open(cj, "w", encoding="utf-8"), ensure_ascii=False)

ok = os.path.join(BASE, "ok.mbz")
r = subprocess.run(
    [sys.executable, os.path.join(SKILL, "scripts", "build_mbz.py"), cj,
     "-o", ok, "--wwwroot", "https://moodle.example.edu"],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
print("build ok.mbz rc=", r.returncode, (r.stdout or r.stderr).strip()[-120:])

# bad.mbz: feedback.xml-Item-name -> $@NULL@$ (Attribut-Reihenfolge erhalten)
bad = os.path.join(BASE, "bad.mbz")
with tarfile.open(ok, "r:gz") as tin, tarfile.open(bad, "w:gz") as tout:
    for m in tin.getmembers():
        data = tin.extractfile(m).read() if m.isfile() else b""
        if m.isfile() and m.name.endswith("feedback.xml") and b"<items>" in data:
            data = data.replace(b"<name></name>", b"<name>$@NULL@$</name>", 1)
            m.size = len(data)
            print("bad.mbz: NULL in", m.name, "injiziert")
        tout.addfile(m, io.BytesIO(data) if m.isfile() else None)
print("done:", os.path.getsize(ok), "/", os.path.getsize(bad), "bytes")
