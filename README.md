# moodle-testinstanz

Ein Claude-Code-Skill, der `.mbz`-Moodle-Kurssicherungen gegen ein **echtes,
lokales Moodle 4.5** restauriert (portable, **kein Docker**) — als optionales
**Live-Restore-Gate** für die Builder-Skills
[`moodle-mbz-builder`](https://github.com/Menkoban/moodle-mbz-builder) /
[`moodle-adaptive-mbz-builder`](https://github.com/Menkoban/moodle-adaptive-mbz-builder)
**und** interaktiv („restaurier mir diese .mbz und zeig den Stacktrace").

Warum: Die gefährlichste Fehlerklasse generierter Backups sind
**Restore-Zeit-Fehler** (`dmlwriteexception`, Kontext-Probleme …), die keine
statische XML-Prüfung sieht. Nur ein echter Restore über Moodles eigenen
Code-Pfad erzeugt den Stacktrace — und jeder so gefundene Fehler wird
anschließend als statischer Check in `validate_mbz.py` der Builder verewigt.

## Herunterladen & installieren

Dies ist ein **[Claude-Code-Skill](https://docs.claude.com/en/docs/claude-code)**.
Schritt 1 (klonen) läuft überall; das Lab in Schritt 2 ist derzeit **Windows-only**
(portable `.exe`-Binaries).

**Schritt 1 — Skill an den festen Discovery-Pfad klonen**

Linux / macOS (auch Windows Git-Bash):

```bash
git clone https://github.com/Menkoban/moodle-testinstanz ~/.claude/skills/moodle-testinstanz
```

Windows (PowerShell):

```powershell
git clone https://github.com/Menkoban/moodle-testinstanz "$HOME\.claude\skills\moodle-testinstanz"
```

> **Privates Repo?** Vorher anmelden: `gh auth login`, dann
> `gh repo clone Menkoban/moodle-testinstanz <zielpfad>` (oder per SSH
> `git clone git@github.com:Menkoban/moodle-testinstanz <zielpfad>`).

**Schritt 2 — Lab aufbauen** (einmalig, ~10–20 min, ≈450 MB von offiziellen
Quellen: windows.php.net, archive.mariadb.org, packaging.moodle.org):

```bash
python ~/.claude/skills/moodle-testinstanz/scripts/setup_lab.py          # Git-Bash
```
```powershell
python "$HOME\.claude\skills\moodle-testinstanz\scripts\setup_lab.py"    # PowerShell
```

**Schritt 3 — prüfen:**

```bash
python ~/.claude/skills/moodle-testinstanz/scripts/run_restore.py --health
#  -> "Lab bereit — Moodle 4.5.x, format_tiles=True" (Exit 0)
```

Voraussetzungen: **Windows** (portable .exe-Binaries), **Python 3.10+**
(nur Standardbibliothek!), freier **Port 3307**, MS Visual C++ Runtime
2015–2022 (auf normalen Systemen vorhanden). Lab-Ort: `~/.claude/moodle-lab`
(Override: Env `MOODLE_LAB_HOME`). **Aktualisieren:**
`git -C ~/.claude/skills/moodle-testinstanz pull`.

Ab dann erkennt das Schluss-Gate (`check_delivery.py`) der Builder-Skills den
Skill **automatisch** und führt bei jedem Kurs-Build einen echten Restore aus.
Ohne diesen Skill laufen die Builder unverändert weiter — das Gate ist weich.

## Nutzung

```bash
run_restore.py --health              # Lab bereit? (startet MariaDB selbst)
run_restore.py kurs.mbz              # Restore + Teardown; Exit 0/2/3
run_restore.py kurs.mbz --json       # maschinenlesbar (Gate-Modus)
run_restore.py kurs.mbz --keep       # Testkurs behalten (Web-UI s. u.)
run_restore.py --shutdown            # Lab-DB sauber stoppen
```

| Exit | Bedeutung | Gate-Reaktion |
|---|---|---|
| `0` | Restore ok („Kurs geht hoch") | grün |
| `2` | **Moodle lehnt die .mbz ab** — Stacktrace im `log_tail` | **rot** |
| `3` | Lab down/fehlt (Umgebung, kein Kursfehler) | Warnung, grün |

`--json` liefert ein Objekt:
`{status, restored_course_id, moodle_version, format_tiles, log_tail}`.

**Kurs im Browser ansehen** (nach `--keep`):

```bash
cd ~/.claude/moodle-lab/moodle
../php/php.exe -S localhost:8088
# -> http://localhost:8088 · admin / Admin123!
```

> Der eingebaute PHP-Server ist unter Windows **strikt seriell**.
> `PHP_CLI_SERVER_WORKERS` hilft nicht — die Variable setzt `fork()` voraus
> und ist auf Windows wirkungslos (gemessen: 3 parallele Requests à 3 s →
> ~9,19 s mit wie ohne). Zum Durchklicken genügt das.

## Vertrag & Architektur

Die einzige Kopplungsfläche zu den Buildern ist `scripts/run_restore.py`
(Discovery: fester Pfad bzw. Env `MOODLE_TESTINSTANZ_HOME`). Vertrag im
Detail: `moodle-mbz-builder/docs/superpowers/specs/`
`2026-07-15-moodle-testinstanz-restore-gate-design.md`. Kernregeln:

- **Exit-Disziplin:** 3 (Umgebung) niemals mit 2 (Kurs kaputt) verwechseln —
  daran hängt die Optionalität des Gates.
- **Teardown per Default:** Wegwerf-Kurse (auch Fehler-Trümmer) werden nach
  dem Lauf via `delete_course()` inkl. Kontexten entfernt; der Papierkorb ist
  im Lab deaktiviert. Idempotent, beliebig oft aufrufbar.
- **Fidelity:** Restore läuft über `admin/cli/restore_backup.php` — exakt
  der Code-Pfad des Browser-Uploads, keine Nachbauten.

## Tests

`tests/` enthält zwei Vertrags-Artefakte: `ok.mbz` (muss Exit 0 geben) und
`bad.mbz` (feedback-Item mit `$@NULL@$`-name — der reale Bug vom 2026-07-15;
muss Exit 2 mit `dmlwriteexception` im `log_tail` geben). Regenerierbar über
`tests/make_test_mbz.py` (braucht den moodle-mbz-builder-Skill).

## Lizenz-Hinweis

Dieses Repo enthält **nur** den Skill-Code. PHP, MariaDB, Moodle und
format_tiles werden beim Setup von ihren offiziellen Quellen geladen und
unterliegen ihren eigenen Lizenzen (PHP License, GPLv2, GPLv3, GPLv3).
