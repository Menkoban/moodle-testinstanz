---
name: moodle-testinstanz
description: >-
  Restores .mbz Moodle backups into a local, portable Moodle 4.5 lab (no
  Docker: portable PHP 8.2 + MariaDB 10.11 + format_tiles) to verify they
  actually restore — and to capture the REAL Moodle stack trace / failing SQL
  when they don't. Use this skill whenever the user wants to test/verify a
  Moodle backup restore locally ("restaurier mir diese .mbz", "teste die
  Kurssicherung", "zeig mir den Restore-Stacktrace", "warum lehnt Moodle den
  Kurs ab?", "Moodle-Lab starten/stoppen"), or when debugging any Moodle
  restore error from a generated course. Also the backend of the optional
  live-restore gate in moodle-mbz-builder / moodle-adaptive-mbz-builder
  (check_delivery.py Schritt 9 ruft scripts/run_restore.py auf).
---

# moodle-testinstanz — Live-Restore gegen das lokale Moodle-Lab

Kapselt das portable **Moodle-4.5-Lab** (kein Docker) und bietet nach außen
**ein** Entry-Skript nach festem Vertrag an. Zweck: `.mbz`-Sicherungen über
**Moodles eigenen Restore-Codepfad** testen — nur so treten echte
Restore-Zeit-Fehler (`dmlwriteexception`, contextid-Probleme, …) mitsamt
Stacktrace auf, die statische XML-Prüfung strukturell nicht fangen kann.
Jeder so gefundene Fehler wird anschließend als statischer Check in
`validate_mbz.py` der Builder-Skills verewigt (Validator-Fabrik).

## Entry-Skript & Vertrag (VERBINDLICH)

```
~/.claude/skills/moodle-testinstanz/scripts/run_restore.py
(Discovery-Override für Aufrufer: Env MOODLE_TESTINSTANZ_HOME)
```

| Aufruf | Bedeutung | Exit-Codes |
|---|---|---|
| `run_restore.py --health` | Preflight: Lab bereit? (startet MariaDB bei Bedarf selbst; billiger Ping, KEIN Restore) | `0` Lab up · `3` Lab down/fehlt |
| `run_restore.py <kurs.mbz> [--json] [--keep]` | `.mbz` in Wegwerf-Kurs restaurieren | `0` ok · `2` **echter Restore-Fehler** · `3` Lab verloren |
| `run_restore.py --shutdown` | Zusatz: Lab-DB sauber stoppen | `0` |

**Exit-Disziplin:** `3` (Umgebung down → Aufrufer: WARN + weiter) und `2`
(Kurs kaputt → Gate rot) niemals verwechseln — daran hängt die Optionalität
des Live-Restore-Gates. Vertrag im Detail:
`moodle-mbz-builder/docs/superpowers/specs/2026-07-15-moodle-testinstanz-restore-gate-design.md`.

**`--json`** liefert EIN Objekt auf stdout:

```json
{"status": "ok|restore_failed|lab_lost", "restored_course_id": 42,
 "moodle_version": "4.5.12+ (Build: 20260708)", "format_tiles": true,
 "log_tail": "…letzte Restore-Zeilen; bei Fehlern der Moodle-Stacktrace…"}
```

**Verhalten:** Restore via `php admin/cli/restore_backup.php` (exakt der
Browser-Codepfad) in einen neuen Kurs (Moodle vergibt via
`calculate_course_names` einen garantiert eindeutigen shortname).
**Teardown per Default** — alle im Lauf entstandenen Kurse (auch
Partial-Trümmer nach Fehlern) werden per `delete_course()` inkl. Kontexten
gelöscht, damit Folgeläufe keine contextid-Kollisionen erben. `--keep`
behält den Kurs zum Inspizieren (Login unten). Mehrfach sicher aufrufbar.

## Typische interaktive Nutzung

```bash
python ~/.claude/skills/moodle-testinstanz/scripts/run_restore.py --health
python ~/.claude/skills/moodle-testinstanz/scripts/run_restore.py "C:/…/kurs.mbz"
python ~/.claude/skills/moodle-testinstanz/scripts/run_restore.py "C:/…/kurs.mbz" --json
python ~/.claude/skills/moodle-testinstanz/scripts/run_restore.py "C:/…/kurs.mbz" --keep
```

- **„Warum lehnt Moodle meinen Kurs ab?"** → Restore ohne `--json` fahren;
  bei Exit 2 steht der Stacktrace/das fehlgeschlagene SQL im `log_tail`-Block.
- **Kurs anschauen:** mit `--keep` restaurieren, dann Webserver starten:
  `cd <lab>/moodle && <lab>/php/php.exe -S localhost:8088`
  → `http://localhost:8088`, Login `admin` / `Admin123!`.
  Der eingebaute Server ist auf Windows **strikt seriell** — ein hängender
  Request blockiert die Seite. `PHP_CLI_SERVER_WORKERS` ändert daran nichts
  (die Variable braucht `fork()` und ist unter Windows wirkungslos; gemessen:
  3 parallele Requests à 3 s brauchen mit wie ohne sie ~9,19 s). Zum
  Durchklicken reicht es; wer nebenläufig arbeiten will, braucht einen
  echten Webserver.

## Das Lab (alle schweren Abhängigkeiten leben HIER)

```
~/.claude/moodle-lab/          (Override: Env MOODLE_LAB_HOME)
  php\       portable PHP 8.2 (NTS x64)
  mariadb\   MariaDB 10.11 (Port 3307, root/root, Datadir db-data\)
  moodle\    Moodle 4.5 + format_tiles — config.php: debug=DEVELOPER an
  data\      moodledata
  *.zip      Rebuild-Quellen (php/mariadb/moodle/tiles)
```

- `run_restore.py` findet das Lab selbst und **startet MariaDB bei Bedarf**
  (detached, Log: `<lab>/mariadbd.log`). Fehlt das Lab → sauber Exit 3 mit
  Hinweis. Wiederaufbau (~15 min): Zips im Lab-Ordner entpacken,
  `mariadb-install-db`, DB `moodle` einspielen bzw. `admin/cli/install.php`
  — Details in `moodle-mbz-builder/references/moodle-lab.md`.
- Das Moodle ist **minimal extrahiert** (admin/cli: nur install/
  restore_backup/upgrade). Meldet ein Lauf fehlende Dateien („Attempt to
  require a JavaScript file …"), die betroffenen Pfade aus `moodle.zip`
  nachextrahieren — das ist ein Lab-Defekt, KEIN Kurs-Fehler.
- Gefundene echte Kurs-Fehler: an `validate_mbz.py` der Builder als neuen
  statischen Check zurückspielen (so entstanden die Checks für
  `$@NULL@$`-Attribute, feedback-NOT-NULL, Modulkontext-Fragenbank).

## Grenzen

- Eine Instanz (Moodle 4.5), kein Versions-Matrix-Test, kein Lasttest —
  reiner Restore-Smoke-Test mit Stacktrace-Ausbeute.
- Admin-Vorschau-Versuche in restaurierten Quizzen schreiben keine Noten;
  bewertungsabhängige Features nur mit echtem Teilnehmer prüfbar.
