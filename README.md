# moodle-testinstanz 🧪⚡

[![Moodle 4.5 LTS](https://img.shields.io/badge/Moodle-4.5%20LTS-orange.svg)](https://moodle.org/)
[![Port 8088](https://img.shields.io/badge/Web--UI-Port%208088-brightgreen.svg)](http://localhost:8088)
[![Port 3307](https://img.shields.io/badge/MariaDB-Port%203307-blue.svg)](README.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Steriles, lokales Moodle-4.5-Lab für automatisierte Live-Restore-Checks (.mbz QA-Gate).**  
Dient als Backend für **Gate 7** in `moodle-mbz-builder`. Führt bei jedem Kurs-Build einen echten Moodle-Restore über Moodles originären PHP-Code-Pfad durch, um tiefe Datenbank- und XML-Fehler (`dmlwriteexception`, Kontext-Inkonsistenzen) mit echtem PHP-Stacktrace sofort abzufangen.

---

## 💻 Installation & Setup

**Antigravity / Gemini CLI:**
```powershell
git clone https://github.com/Menkoban/moodle-testinstanz.git "$HOME\.gemini\config\skills\moodle-testinstanz"
```

**Einmaliges Setup des sterilen Labs:**
```bash
python scripts/setup_lab.py
```

**Health-Check:**
```bash
python scripts/run_restore.py --health
# -> "Lab bereit — Moodle 4.5.x, format_tiles=True" (Exit 0)
```

---

## 🚀 Nutzung

```bash
# Echten Restore testen & Teardown durchführen (Exit 0 = Grün, Exit 2 = Fehler)
python scripts/run_restore.py mein-kurs.mbz

# Im JSON-Modus (für Pipeline-Gates)
python scripts/run_restore.py mein-kurs.mbz --json

# Kurs nach Restore zur Inspektion im Browser behalten
python scripts/run_restore.py mein-kurs.mbz --keep
# -> Web-UI auf http://localhost:8088 (admin / Admin123!)
```

---

## 📄 Lizenz

Dieses Projekt ist unter der **MIT-Lizenz** lizenziert.
