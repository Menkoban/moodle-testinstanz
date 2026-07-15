#!/usr/bin/env python3
"""setup_lab.py — baut das portable Moodle-Restore-Lab von Null auf.

Laedt alle Komponenten von den OFFIZIELLEN Quellen (nichts wird aus diesem
Repo mitgeliefert) und installiert ein lauffaehiges Moodle 4.5 mit
format_tiles, so wie es `run_restore.py` erwartet:

    <lab>/php       portable PHP 8.2 (NTS x64, windows.php.net)
    <lab>/mariadb   MariaDB 10.11 (archive.mariadb.org)
    <lab>/db-data   MariaDB-Datadir (root/root, Port 3307)
    <lab>/moodle    Moodle 4.5 (packaging.moodle.org) + format_tiles
    <lab>/data      moodledata
    <lab>/_dl       heruntergeladene Zips (Rebuild-Cache)

Ziel:    Env MOODLE_LAB_HOME  oder  ~/.claude/moodle-lab
Aufruf:  python setup_lab.py [--force] [--port 3307]
Dauer:   ~10–20 min (≈450 MB Download + DB-Install)
Nur Windows (portable .exe-Binaries). Danach: run_restore.py --health → 0.

Voraussetzung auf dem Zielrechner: Microsoft Visual C++ Runtime 2015–2022
(auf normalen Windows-Systemen vorhanden; sonst vc_redist.x64 von Microsoft).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

LAB = os.environ.get("MOODLE_LAB_HOME", os.path.expanduser("~/.claude/moodle-lab"))
DL = os.path.join(LAB, "_dl")

PHP_VER = "8.2.32"
PHP_URLS = [
    f"https://windows.php.net/downloads/releases/php-{PHP_VER}-nts-Win32-vs16-x64.zip",
    f"https://windows.php.net/downloads/releases/archives/php-{PHP_VER}-nts-Win32-vs16-x64.zip",
]
MARIADB_VER = "10.11.9"
MARIADB_URL = (f"https://archive.mariadb.org/mariadb-{MARIADB_VER}/"
               f"winx64-packages/mariadb-{MARIADB_VER}-winx64.zip")
MOODLE_URL = "https://packaging.moodle.org/stable405/moodle-latest-405.zip"
TILES_API = ("https://download.moodle.org/api/1.3/pluginfo.php"
             "?plugin=format_tiles&minversion=0&branch=4.5&format=json")

PHP_EXTENSIONS = ["curl", "fileinfo", "gd", "intl", "mbstring", "exif",
                  "mysqli", "openssl", "soap", "sodium", "zip"]

CONFIG_TEMPLATE = """<?php  // Moodle configuration file (Testinstanz-Lab)

unset($CFG);
global $CFG;
$CFG = new stdClass();

$CFG->dbtype    = 'mariadb';
$CFG->dblibrary = 'native';
$CFG->dbhost    = '127.0.0.1';
$CFG->dbname    = 'moodle';
$CFG->dbuser    = 'root';
$CFG->dbpass    = 'root';
$CFG->prefix    = 'mdl_';
$CFG->dboptions = array (
  'dbpersist' => 0,
  'dbport' => {port},
  'dbsocket' => '',
  'dbcollation' => 'utf8mb4_unicode_ci',
);

$CFG->wwwroot   = 'http://localhost:8088';
$CFG->dataroot  = '{dataroot}';
$CFG->admin     = 'admin';

$CFG->directorypermissions = 02777;

// Debug IMMER an — der ganze Zweck des Labs sind lesbare Stacktraces.
$CFG->debug = (E_ALL | E_STRICT);
$CFG->debugdisplay = 1;
require_once(__DIR__ . '/lib/setup.php');
"""


def log(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[setup] FEHLER: {msg}", flush=True)
    sys.exit(1)


def download(urls, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 1024 * 1024:
        log(f"Download-Cache: {os.path.basename(dest)} vorhanden")
        return dest
    if isinstance(urls, str):
        urls = [urls]
    last = None
    for url in urls:
        try:
            log(f"lade {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "moodle-testinstanz-setup/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                total, got = int(r.headers.get("Content-Length") or 0), 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        print(f"\r[setup]   {got // (1<<20)}/{total // (1<<20)} MB", end="", flush=True)
            print()
            return dest
        except Exception as e:  # noqa: BLE001 — naechste Quelle probieren
            last = e
            log(f"  fehlgeschlagen: {e}")
    die(f"Download nicht moeglich: {last}")


def extract(zip_path: str, target: str, strip_top: bool) -> None:
    log(f"entpacke {os.path.basename(zip_path)} -> {os.path.relpath(target, LAB)}")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        top = names[0].split("/")[0] + "/" if strip_top else ""
        for n in names:
            if n.endswith("/"):
                continue
            rel = n[len(top):] if strip_top and n.startswith(top) else n
            if not rel:
                continue
            dest = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def run(cmd, cwd=None, timeout=1800, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        die(f"{os.path.basename(str(cmd[0]))} rc={r.returncode}\n"
            f"{(r.stdout or '')[-800:]}\n{(r.stderr or '')[-800:]}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="Moodle-Testinstanz-Lab aufbauen")
    ap.add_argument("--force", action="store_true",
                    help="vorhandenes (Teil-)Lab weiterverwenden/ueberschreiben")
    ap.add_argument("--port", type=int, default=3307)
    args = ap.parse_args()

    if os.name != "nt":
        die("nur Windows (portable .exe-Binaries)")
    if os.path.exists(os.path.join(LAB, "moodle", "config.php")) and not args.force:
        die(f"Lab existiert schon unter {LAB} — mit --force fortsetzen/reparieren")

    php = os.path.join(LAB, "php", "php.exe")
    mariadbd = os.path.join(LAB, "mariadb", "bin", "mariadbd.exe")
    mariadb = os.path.join(LAB, "mariadb", "bin", "mariadb.exe")
    installdb = os.path.join(LAB, "mariadb", "bin", "mariadb-install-db.exe")
    moodle = os.path.join(LAB, "moodle")
    dbdata = os.path.join(LAB, "db-data")
    dataroot = os.path.join(LAB, "data")
    os.makedirs(DL, exist_ok=True)

    # 1) PHP ----------------------------------------------------------------
    if not os.path.exists(php):
        extract(download(PHP_URLS, os.path.join(DL, "php.zip")),
                os.path.join(LAB, "php"), strip_top=False)
    ini = os.path.join(LAB, "php", "php.ini")
    ext_lines = "\n".join(f"extension={e}" for e in PHP_EXTENSIONS)
    with open(ini, "w", encoding="utf-8") as f:
        f.write("; generiert von setup_lab.py\n"
                "memory_limit = 512M\nmax_execution_time = 0\n"
                "post_max_size = 256M\nupload_max_filesize = 256M\n"
                "max_input_vars = 5000\n"  # Moodle-Umgebungscheck verlangt >= 5000
                f'extension_dir = "ext"\n{ext_lines}\n')
    r = run([php, "-v"], check=False)
    if r.returncode != 0:
        die("php.exe startet nicht — fehlt die VC++-Runtime (vc_redist.x64)?")
    log(f"PHP ok: {r.stdout.splitlines()[0]}")

    # 2) MariaDB ------------------------------------------------------------
    if not os.path.exists(mariadbd):
        extract(download(MARIADB_URL, os.path.join(DL, "mariadb.zip")),
                os.path.join(LAB, "mariadb"), strip_top=True)
    if not os.path.exists(os.path.join(dbdata, "mysql")):
        log("initialisiere MariaDB-Datadir (root/root)")
        run([installdb, f"--datadir={dbdata}", "--password=root"], timeout=600)
    if not port_open(args.port):
        log(f"starte mariadbd auf Port {args.port}")
        flags = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
        with open(os.path.join(LAB, "mariadbd.log"), "ab") as lf:
            subprocess.Popen([mariadbd, f"--datadir={dbdata}",
                              f"--port={args.port}", "--console"],
                             stdout=lf, stderr=lf, creationflags=flags)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not port_open(args.port):
            time.sleep(0.5)
        if not port_open(args.port):
            die("MariaDB kommt nicht hoch — siehe mariadbd.log")
    run([mariadb, f"--port={args.port}", "-h", "127.0.0.1", "-u", "root",
         "-proot", "-e",
         "CREATE DATABASE IF NOT EXISTS moodle "
         "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"])
    log("MariaDB laeuft, DB 'moodle' bereit")

    # 3) Moodle-Code + format_tiles ------------------------------------------
    if not os.path.exists(os.path.join(moodle, "version.php")):
        extract(download(MOODLE_URL, os.path.join(DL, "moodle.zip")),
                LAB, strip_top=False)  # Zip enthaelt bereits moodle/-Prefix
    tiles_dir = os.path.join(moodle, "course", "format", "tiles")
    if not os.path.exists(os.path.join(tiles_dir, "version.php")):
        log("frage Moodle-Plugin-API nach format_tiles (Branch 4.5)")
        req = urllib.request.Request(TILES_API, headers={"User-Agent": "moodle-testinstanz-setup/1.0"})
        info = json.load(urllib.request.urlopen(req, timeout=60))
        dl_url = info["pluginfo"]["version"]["downloadurl"]
        log(f"  Version {info['pluginfo']['version']['release']}")
        extract(download(dl_url, os.path.join(DL, "format_tiles.zip")),
                os.path.join(moodle, "course", "format"), strip_top=False)

    # 4) config.php + Datenbank-Install ---------------------------------------
    os.makedirs(dataroot, exist_ok=True)
    with open(os.path.join(moodle, "config.php"), "w", encoding="utf-8") as f:
        f.write(CONFIG_TEMPLATE.format(port=args.port,
                                       dataroot=dataroot.replace("\\", "/")))
    marker = run([php, "-r",
                  "define('CLI_SCRIPT',1);require 'config.php';"
                  "echo $DB->get_manager()->table_exists('config') ? 'JA' : 'NEIN';"],
                 cwd=moodle, check=False)
    if "JA" not in (marker.stdout or ""):
        log("installiere Moodle-Datenbank (dauert einige Minuten) …")
        run([php, os.path.join("admin", "cli", "install_database.php"),
             "--agree-license", "--fullname=Moodle Testinstanz Lab",
             "--shortname=lab", "--adminuser=admin", "--adminpass=Admin123!",
             "--adminemail=admin@example.invalid"],
            cwd=moodle, timeout=3600)
    else:
        log("Moodle-DB existiert schon — Upgrade-Lauf")
        run([php, os.path.join("admin", "cli", "upgrade.php"),
             "--non-interactive"], cwd=moodle, timeout=3600, check=False)

    # 5) Feinschliff: recyclebin aus (Teardown = echtes Loeschen), Caches ----
    run([mariadb, f"--port={args.port}", "-h", "127.0.0.1", "-u", "root",
         "-proot", "moodle", "-e",
         "INSERT INTO mdl_config_plugins (plugin,name,value) VALUES "
         "('tool_recyclebin','coursebinenable','0'),"
         "('tool_recyclebin','categorybinenable','0') "
         "ON DUPLICATE KEY UPDATE value='0';"])
    run([php, "-r", "define('CLI_SCRIPT',1);require 'config.php';"
         "purge_all_caches(); echo 'caches ok';"], cwd=moodle)

    log("FERTIG. Naechster Schritt: run_restore.py --health  (erwartet Exit 0)")
    log(f"Lab: {LAB} · Admin: admin/Admin123! · DB: 127.0.0.1:{args.port} root/root")
    return 0


if __name__ == "__main__":
    sys.exit(main())
