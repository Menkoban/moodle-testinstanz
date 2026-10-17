"""Das Lab muss mod_hvp (H5P-Plugin) haben, sonst ueberspringt Moodle
H5P-Aktivitaeten beim Restore stillschweigend und der Test meldet trotzdem ok.
Live-Test gegen das lokale Lab; ohne Lab wird er uebersprungen."""
import json
import os
import subprocess
import sys

import pytest

HIER = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HIER, "..", "scripts", "run_restore.py")


def _health():
    return subprocess.run([sys.executable, RUN, "--health"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=180)


def test_health_meldet_mod_hvp():
    r = _health()
    if r.returncode == 3:
        pytest.skip("kein Lab auf diesem Rechner")
    assert r.returncode == 0, r.stdout
    assert "mod_hvp=True" in r.stdout, r.stdout


def test_json_enthaelt_hvp_feld():
    r = subprocess.run([sys.executable, RUN, os.path.join(HIER, "ok.mbz"), "--json"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600)
    if r.returncode == 3:
        pytest.skip("kein Lab auf diesem Rechner")
    daten = json.loads(r.stdout.strip().splitlines()[-1])
    assert daten["mod_hvp"] is True, daten
