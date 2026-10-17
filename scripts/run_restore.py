#!/usr/bin/env python3
"""run_restore.py — Vertrags-Entry des Skills `moodle-testinstanz`.

Kapselt das portable Moodle-4.5-Lab (kein Docker: portable PHP 8.2 +
MariaDB 10.11 + Moodle 4.5 + format_tiles) hinter EINEM Skript. Vertrag:
moodle-mbz-builder/docs/superpowers/specs/
2026-07-15-moodle-testinstanz-restore-gate-design.md, Abschnitt 5.

Aufrufe & Exit-Codes (VERBINDLICH — daran hängt das Live-Restore-Gate):

  run_restore.py --health
      0 = Lab bereit (MariaDB up + Moodle-CLI antwortet)
      3 = Lab down/fehlt/nicht bootstrapbar
  run_restore.py <kurs.mbz> [--json] [--keep]
      0 = Restore ok
      2 = ECHTER Restore-Fehler (Moodle lehnt die .mbz ab)
      3 = Lab fehlt/während des Restores verloren

  3 (Umgebung) und 2 (Kurs kaputt) duerfen NIE verwechselt werden:
  der Aufrufer macht bei 3 "WARN + weiter" und nur bei 2 "Gate rot".

--json  → EIN Objekt auf stdout:
  {"status": "ok"|"restore_failed"|"lab_lost",
   "restored_course_id": int|null,
   "moodle_version": "4.5.12+ (Build: 20260708)",
   "format_tiles": true|false,
   "mod_hvp": true|false,
   "log_tail": "…letzte Restore-/Stacktrace-Zeilen…"}

Verhalten: Restore ueber Moodles EIGENE CLI (admin/cli/restore_backup.php,
exakt der Browser-Codepfad) in einen Wegwerf-Kurs; Moodle vergibt per
calculate_course_names einen garantiert eindeutigen shortname. TEARDOWN per
Default (alle in diesem Lauf entstandenen Kurse werden via delete_course()
inkl. Kontexten geloescht — verhindert contextid-Kollisionen bei
Folgelaeufen); --keep behaelt den Kurs. Mehrfach sicher aufrufbar.
MariaDB wird bei Bedarf automatisch gestartet (Teil von "Lab bereit").

Extras (nicht Teil des Vertrags): --shutdown stoppt die Lab-DB sauber.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time

# --------------------------------------------------------------------------- #
# Lab-Discovery (Vertrag 5.5): stabiler Ort + Env-Override
# --------------------------------------------------------------------------- #
LAB_HOME = os.environ.get(
    "MOODLE_LAB_HOME", os.path.expanduser("~/.claude/moodle-lab")
)
PHP = os.path.join(LAB_HOME, "php", "php.exe")
MARIADBD = os.path.join(LAB_HOME, "mariadb", "bin", "mariadbd.exe")
MARIADB = os.path.join(LAB_HOME, "mariadb", "bin", "mariadb.exe")
DB_DATA = os.path.join(LAB_HOME, "db-data")
MOODLE = os.path.join(LAB_HOME, "moodle")
RESTORE_CLI = os.path.join(MOODLE, "admin", "cli", "restore_backup.php")
DB_LOG = os.path.join(LAB_HOME, "mariadbd.log")

DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME = "127.0.0.1", 3307, "root", "root", "moodle"

EXIT_OK, EXIT_RESTORE_FAIL, EXIT_LAB_DOWN = 0, 2, 3
LOG_TAIL_LINES = 40

# Muster, die "DB waehrend des Restores verloren" von "Kurs kaputt" trennen
DB_LOST_RX = re.compile(
    r"server has gone away|Can't connect to|Connection refused|"
    r"Lost connection to|No connection could be made",
    re.I,
)
# Erfolgs-Marker der Moodle-CLI (deutsch + englisch, sprachrobust)
COURSE_ID_RX = re.compile(
    r"(?:ID des wiederhergestellten Kurses|Restored course id)\D*(\d+)", re.I
)


def port_open(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((DB_HOST, DB_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def lab_files_ok() -> str | None:
    """None wenn alles da, sonst Beschreibung des Fehlenden."""
    missing = [p for p in (PHP, MARIADBD, MARIADB, DB_DATA, RESTORE_CLI,
                           os.path.join(MOODLE, "config.php")) if not os.path.exists(p)]
    if missing:
        return ("Lab unvollstaendig/fehlt unter %s (Env MOODLE_LAB_HOME "
                "setzen oder Lab aufbauen — siehe SKILL.md). Fehlt: %s"
                % (LAB_HOME, ", ".join(os.path.relpath(m, LAB_HOME) for m in missing)))
    return None


def ensure_db(boot_timeout: float = 30.0) -> bool:
    """MariaDB erreichbar machen: laeuft sie nicht, selbst starten (detached)."""
    if port_open():
        return True
    try:
        logf = open(DB_LOG, "ab")
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [MARIADBD, f"--datadir={DB_DATA}", f"--port={DB_PORT}", "--console"],
            stdout=logf, stderr=logf, creationflags=flags, close_fds=True,
        )
        logf.close()
    except OSError:
        return False
    deadline = time.monotonic() + boot_timeout
    while time.monotonic() < deadline:
        if port_open():
            return True
        time.sleep(0.5)
    return port_open()


def php_run(code: str, timeout: float = 90.0) -> subprocess.CompletedProcess:
    """php -r im Moodle-Ordner (CLI_SCRIPT-Bootstrap macht der Code selbst)."""
    return subprocess.run(
        [PHP, "-d", "error_reporting=E_ALL & ~E_DEPRECATED", "-r", code],
        cwd=MOODLE, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )


def moodle_meta() -> dict | None:
    """Billiger Moodle-CLI-Ping, liefert zugleich release + format_tiles-/mod_hvp-Bool."""
    r = php_run(
        "define('CLI_SCRIPT',1);require 'config.php';global $DB,$CFG;"
        "$t=$DB->get_field('config_plugins','value',"
        "['plugin'=>'format_tiles','name'=>'version']);"
        "$h=$DB->get_field('config_plugins','value',"
        "['plugin'=>'mod_hvp','name'=>'version']);"
        "echo '@@',json_encode(['release'=>$CFG->release,'tiles'=>(bool)$t,"
        "'hvp'=>(bool)$h]),'@@';"
    )
    m = re.search(r"@@(\{.*\})@@", r.stdout or "")
    if r.returncode != 0 or not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def sql(query: str) -> str:
    r = subprocess.run(
        [MARIADB, f"--port={DB_PORT}", "-h", DB_HOST, "-u", DB_USER,
         f"-p{DB_PASS}", "-N", "-B", DB_NAME, "-e", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    return (r.stdout or "").strip()


def teardown(pre_max_id: int) -> str:
    """Alle Kurse dieses Laufs (id > pre_max_id) inkl. Kontexten loeschen."""
    ids = [i for i in sql(
        f"SELECT id FROM mdl_course WHERE id > {int(pre_max_id)}"
    ).split() if i.isdigit()]
    if not ids:
        return "teardown: nichts zu loeschen"
    idlist = ",".join(ids)
    r = php_run(
        "define('CLI_SCRIPT',1);require 'config.php';"
        # delete_course braucht im CLI-Kontext explizite requires
        # (course_get_format lebt in course/format/lib.php):
        "require_once($CFG->dirroot.'/course/lib.php');"
        "require_once($CFG->dirroot.'/course/format/lib.php');"
        f"foreach ([{idlist}] as $id) {{ delete_course($id, false); }}"
        "fix_course_sortorder(); echo 'deleted';",
        timeout=300,
    )
    if r.returncode == 0 and "deleted" in (r.stdout or ""):
        return f"teardown: Kurs(e) {idlist} geloescht"
    return f"teardown-WARNUNG: Loeschen von {idlist} unvollstaendig ({(r.stdout or r.stderr)[-120:]})"


def tail(text: str, n: int = LOG_TAIL_LINES) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def emit(as_json: bool, status: str, course_id, meta: dict | None,
         log_tail: str, human: str) -> None:
    if as_json:
        print(json.dumps({
            "status": status,
            "restored_course_id": course_id,
            "moodle_version": (meta or {}).get("release"),
            "format_tiles": (meta or {}).get("tiles", False),
            "mod_hvp": (meta or {}).get("hvp", False),
            "log_tail": log_tail,
        }, ensure_ascii=False))
    else:
        print(human)
        if log_tail and status != "ok":
            print("--- log_tail ---")
            print(log_tail)


# --------------------------------------------------------------------------- #
# Kommandos
# --------------------------------------------------------------------------- #
def cmd_health() -> int:
    err = lab_files_ok()
    if err:
        print(f"LAB DOWN: {err}")
        return EXIT_LAB_DOWN
    if not ensure_db():
        print(f"LAB DOWN: MariaDB auf {DB_HOST}:{DB_PORT} nicht startbar "
              f"(Log: {DB_LOG})")
        return EXIT_LAB_DOWN
    meta = moodle_meta()
    if not meta:
        print("LAB DOWN: Moodle-CLI antwortet nicht (config.php-Bootstrap fehlgeschlagen)")
        return EXIT_LAB_DOWN
    print(f"Lab bereit — Moodle {meta['release']}, format_tiles={meta['tiles']}, "
          f"mod_hvp={meta.get('hvp', False)}, "
          f"DB {DB_HOST}:{DB_PORT}")
    return EXIT_OK


def cmd_shutdown() -> int:
    if not port_open():
        print("Lab-DB laeuft nicht.")
        return EXIT_OK
    subprocess.run(
        [MARIADB, f"--port={DB_PORT}", "-h", DB_HOST, "-u", DB_USER,
         f"-p{DB_PASS}", "-e", "SHUTDOWN;"],
        capture_output=True, timeout=30,
    )
    print("Lab-DB gestoppt.")
    return EXIT_OK


def cmd_restore(mbz: str, as_json: bool, keep: bool) -> int:
    # -- Preflight (Umgebung): alles hier ist Exit 3, nie 2 ------------------ #
    err = lab_files_ok()
    if err:
        emit(as_json, "lab_lost", None, None, "", f"LAB DOWN: {err}")
        return EXIT_LAB_DOWN
    if not ensure_db():
        emit(as_json, "lab_lost", None, None, "",
             f"LAB DOWN: MariaDB nicht startbar (Log: {DB_LOG})")
        return EXIT_LAB_DOWN
    meta = moodle_meta()
    if not meta:
        emit(as_json, "lab_lost", None, None, "",
             "LAB DOWN: Moodle-CLI antwortet nicht")
        return EXIT_LAB_DOWN

    mbz_abs = os.path.abspath(mbz)
    if not os.path.isfile(mbz_abs):
        # Caller-Fehler = kein Umgebungsproblem -> wie Restore-Fehler behandeln
        emit(as_json, "restore_failed", None, meta, "",
             f"RESTORE FAIL: .mbz nicht gefunden: {mbz_abs}")
        return EXIT_RESTORE_FAIL

    try:
        pre_max = int(sql("SELECT COALESCE(MAX(id),1) FROM mdl_course") or 1)
    except (ValueError, subprocess.TimeoutExpired):
        emit(as_json, "lab_lost", None, meta, "",
             "LAB DOWN: DB-Abfrage vor Restore fehlgeschlagen")
        return EXIT_LAB_DOWN

    # -- Der echte Restore (Moodles eigener Codepfad) ------------------------ #
    try:
        r = subprocess.run(
            [PHP, RESTORE_CLI, f"--file={mbz_abs}", "--categoryid=1"],
            cwd=MOODLE, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=1800,
        )
        output = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        rc = r.returncode
    except subprocess.TimeoutExpired as e:
        output = tail((e.stdout or "") if isinstance(e.stdout, str) else "")
        rc = -1
        output += "\nTIMEOUT: Restore nach 1800 s abgebrochen"

    m = COURSE_ID_RX.search(output)
    course_id = int(m.group(1)) if m else None
    log_tail = tail(output)

    if rc == 0 and course_id is not None:
        if keep:
            note = f"--keep: Kurs {course_id} bleibt zum Inspizieren"
        else:
            note = teardown(pre_max)
        # Teardown-Ergebnis IMMER sichtbar machen (auch im --json-Modus):
        # ein stiller Teardown-Fehler wuerde die Idempotenz-Zusage brechen.
        emit(as_json, "ok", course_id, meta, note,
             f"RESTORE OK: Kurs {course_id} ({note}) — "
             f"Moodle {meta['release']}, tiles={meta['tiles']}")
        return EXIT_OK

    # -- Fehlerfall: Umgebung verloren (3) vs. Moodle lehnt ab (2) ----------- #
    if not port_open() or DB_LOST_RX.search(output):
        emit(as_json, "lab_lost", None, meta, log_tail,
             "LAB LOST: Datenbank waehrend des Restores verloren")
        return EXIT_LAB_DOWN

    # Partial-Reste dieses Laufs wegputzen (kein --keep bei Fehlern noetig,
    # aber --keep respektieren, damit man Truemmer inspizieren kann)
    if not keep:
        try:
            teardown(pre_max)
        except Exception:  # noqa: BLE001 — Teardown darf den Exit nicht kippen
            pass
    emit(as_json, "restore_failed", None, meta, log_tail,
         "RESTORE FAIL: Moodle lehnt die .mbz ab (Stacktrace in log_tail)")
    return EXIT_RESTORE_FAIL


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Live-Restore einer .mbz gegen das lokale Moodle-Lab "
                    "(Vertrag: Exit 0=ok, 2=Restore-Fehler, 3=Lab down).")
    ap.add_argument("mbz", nargs="?", help="Pfad zur .mbz-Kurssicherung")
    ap.add_argument("--health", action="store_true",
                    help="Preflight: Lab bereit? (Exit 0/3, kein Restore)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="Ergebnis als EIN JSON-Objekt auf stdout")
    ap.add_argument("--keep", action="store_true",
                    help="Testkurs nach dem Restore NICHT loeschen")
    ap.add_argument("--shutdown", action="store_true",
                    help="Lab-DB sauber stoppen (Zusatzfunktion)")
    args = ap.parse_args()

    if args.health:
        return cmd_health()
    if args.shutdown:
        return cmd_shutdown()
    if not args.mbz:
        ap.error("entweder --health, --shutdown oder ein .mbz-Pfad")
    return cmd_restore(args.mbz, args.as_json, args.keep)


if __name__ == "__main__":
    sys.exit(main())
