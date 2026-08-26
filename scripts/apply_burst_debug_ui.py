#!/usr/bin/env python3
"""Rename/clarify Burst Extra as the shared RF diagnostic path.

No decoder logic is changed here. The existing burst analyzer and raw frame table
already cover Oregon/Technoline; the dedicated EC70 probe is intentionally
removed from the build to save Flash.
"""
from pathlib import Path

Import("env")
ROOT = Path(env.subst("$PROJECT_DIR"))
DASH = ROOT / "web" / "dashboard.html"


def main() -> None:
    text = DASH.read_text(encoding="utf-8")
    text = text.replace("BURST EXTRA OFF", "BURST DEBUG OFF")
    text = text.replace("BURST EXTRA ON", "BURST DEBUG ON")
    text = text.replace("Burst Analyzer / WGR Probe", "Burst Analyzer universale / WGR legacy")
    text = text.replace(
        "<b>Burst RF rilevati</b><span class=\"muted\">indipendenti dal checksum Oregon</span>",
        "<b>Burst RF rilevati</b><span class=\"muted\">Oregon + V2.1 + Technoline · diagnostica condivisa</span>",
    )
    DASH.write_text(text, encoding="utf-8")
    print("Burst debug UI: unified labels applied")


main()
