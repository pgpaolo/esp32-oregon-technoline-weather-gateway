from pathlib import Path

html = Path("web/dashboard.html").read_text(encoding="utf-8")

checks = {
    "attribution marker": 'id="projectAttribution"',
    "version element": 'id="projectVersion"',
    "author": '© 2026 Gianpaolo P.',
    "license": 'GPL-3.0-or-later',
    "dynamic installed version": "pv.textContent=s.version||sys.firmware||'--'",
    "desktop attribution grid": '"attribution forecast"',
    "mobile attribution grid": '"attribution"',
}

missing = [name for name, token in checks.items() if token not in html]
if missing:
    raise SystemExit("Project attribution validation failed: missing " + ", ".join(missing))

if html.count('id="projectAttribution"') != 1:
    raise SystemExit("Project attribution validation failed: duplicate projectAttribution")
if html.count('id="projectVersion"') != 1:
    raise SystemExit("Project attribution validation failed: duplicate projectVersion")

print("Project attribution validation OK")
