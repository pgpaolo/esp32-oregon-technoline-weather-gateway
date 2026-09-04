Import("env")

from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
path = root / "web" / "dashboard.html"
html = path.read_text(encoding="utf-8")

# PROJECT_ATTRIBUTION_V1
# Keep authorship visible but deliberately unobtrusive. The installed firmware
# version comes from the already existing /api/state payload, so there is no
# extra HTTP polling and no duplicated version constant in the Web UI.

if ".projectAttribution{" not in html:
    css = (
        ".projectAttribution{grid-area:attribution;color:var(--muted);font-size:.66rem;"
        "line-height:1.25;margin-top:2px;opacity:.72;white-space:nowrap}"
        "@media(max-width:760px){.projectAttribution{font-size:.64rem;margin-top:0}}\n"
    )
    if "</style>" not in html:
        raise RuntimeError("Project attribution: </style> anchor missing")
    html = html.replace("</style>", css + "</style>", 1)

# The title-forecast pass runs immediately before this script. Extend its grid
# by one quiet attribution row, while preserving the forecast tile placement.
old_grid = 'grid-template-areas:"title forecast" "sub forecast"'
new_grid = 'grid-template-areas:"title forecast" "sub forecast" "attribution forecast"'
if old_grid in html:
    html = html.replace(old_grid, new_grid, 1)
elif new_grid not in html:
    raise RuntimeError("Project attribution: desktop title grid anchor missing")

old_mobile = 'grid-template-areas:"title" "forecast" "sub"'
new_mobile = 'grid-template-areas:"title" "forecast" "sub" "attribution"'
if old_mobile in html:
    html = html.replace(old_mobile, new_mobile, 1)
elif new_mobile not in html:
    raise RuntimeError("Project attribution: mobile title grid anchor missing")

if 'id="projectAttribution"' not in html:
    sub = '<div class="sub">LILYGO T3 · SX1278 OOK 433.92 MHz · decoder Oregon OSV3 + Technoline WS230x</div>'
    attribution = (
        '<div id="projectAttribution" class="projectAttribution">'
        '© 2026 Gianpaolo P. · firmware <span id="projectVersion">--</span> · GPL-3.0-or-later'
        '</div>'
    )
    if sub not in html:
        raise RuntimeError("Project attribution: gateway subtitle anchor missing")
    html = html.replace(sub, sub + attribution, 1)

# refresh() already owns /api/state. Reuse its top-level version field without
# adding a separate request or changing the API.
version_line = "const pv=E('projectVersion');if(pv)pv.textContent=s.version||sys.firmware||'--';"
if version_line not in html:
    anchor = "net.className='statusPill '+(s.wifi.connected?'ok':'bad');"
    if anchor not in html:
        raise RuntimeError("Project attribution: refresh state anchor missing")
    html = html.replace(anchor, version_line + anchor, 1)

path.write_text(html, encoding="utf-8")
print("Applied project attribution with installed firmware version")
