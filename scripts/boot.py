#!/usr/bin/env python3
"""COLD BOOT — a phosphor-CRT terminal that mounts every repo.

Renders the profile intro as an old green-screen boot sequence: ASCII banner,
power-on self test, then a live scan that mounts every public repository as a
volume. Pure SMIL animation so it plays inside GitHub's image proxy, and the
repo list comes from the API so it can never drift from reality.

Dependency-free: the block font below is hand-built rather than shelling out
to figlet, which isn't available on the runner.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

API = "https://api.github.com"

# --- phosphor palette -------------------------------------------------------
P_HI = "#7CFFA0"      # highlight / headings
P_ON = "#00FF41"      # standard phosphor
P_MID = "#00C233"     # body text
P_DIM = "#0B7A24"     # leaders, chrome
AMBER = "#FFB000"     # warnings
SCREEN = "#020604"    # inside of the tube
BEZEL = "#0A0F0C"

MONO = "'Courier New',Courier,monospace"
FS = 16.5             # font size — few big columns, like a real VT terminal
CW = FS * 0.6         # monospace advance
LH = 21               # line height
PADX, PADY = 34, 28
BAR_CELLS = 20        # width of each volume's progress bar

SKIP = {"itsashishupadhyay", "ManojUpadhyaySite"}

# 5-row block font, 1 space between glyphs. Only the letters we need.
FONT = {
    "A": ["  ██  ", " ████ ", "██  ██", "██████", "██  ██"],
    "S": [" █████", "██    ", " ████ ", "    ██", "█████ "],
    "H": ["██  ██", "██  ██", "██████", "██  ██", "██  ██"],
    "I": ["██████", "  ██  ", "  ██  ", "  ██  ", "██████"],
    "U": ["██  ██", "██  ██", "██  ██", "██  ██", " ████ "],
    "P": ["█████ ", "██  ██", "█████ ", "██    ", "██    "],
    "D": ["█████ ", "██  ██", "██  ██", "██  ██", "█████ "],
    "Y": ["██  ██", " ████ ", "  ██  ", "  ██  ", "  ██  "],
    " ": ["   ", "   ", "   ", "   ", "   "],
}


def banner(text):
    rows = ["", "", "", "", ""]
    for ch in text.upper():
        glyph = FONT.get(ch)
        if not glyph:
            continue
        for i in range(5):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows]


def api(path, token):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "cold-boot"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def leader(left, right, width):
    """`left ....... right` dot leaders, the way a real POST screen aligns."""
    dots = max(3, width - len(left) - len(right) - 2)
    return f"{left} {'.' * dots} {right}"


POST = [
    ("OK", "CPU", "caffeine-driven @ 11.4 GHz (overclocked, unregretted)"),
    ("OK", "/dev/solder_iron", "350 °C · tinned, tempered, ready"),
    ("OK", "Oscilloscope", "4 channels locked · probes compensated"),
    ("OK", "Power budget", "every milliwatt accounted for (42 of them)"),
    ("WARN", "sleep.service", "not found — skipping, as usual"),
    ("OK", "Shipped devices", "2,000,000+ verified in the wild"),
    ("OK", "Humor module", "dangerously enabled"),
]


def build(repos, stars, login):
    W = 1200
    inner = int((W - 2 * PADX) / CW)          # usable columns

    art = banner("ASHISH")
    lines = []          # (text, color, bold)

    def add(text="", color=P_MID, bold=False):
        lines.append((text, color, bold))

    for row in art:
        add(row, P_ON, True)
    add()
    add(f"ASHISH-BIOS v5.0 · POWER-ON SELF TEST · {datetime.date.today().isoformat()}", P_HI, True)
    add("─" * inner, P_DIM)

    for status, label, detail in POST:
        col = AMBER if status == "WARN" else P_MID
        add(f"[{status:^4}] " + leader(label, detail, inner - 7), col)

    add()
    add(f"> scanning /dev/github — enumerating volumes …", P_HI, True)
    add("─" * inner, P_DIM)

    # Volume rows are assembled per-column (below) so each bar can fill on its
    # own clock; reserve one blank line each so the vertical rhythm still holds.
    first_vol = len(lines)
    for _ in repos:
        add()
    add("─" * inner, P_DIM)
    add(f"  {len(repos)} volumes mounted · {stars} stars · 0 errors · "
        f"filesystem clean", P_HI, True)
    add()
    add("System online. Welcome, visitor. Scroll for schematics.", P_ON, True)

    # ---- timing ----
    t0, dt = 0.35, 0.075
    art_dt = 0.09
    vol_dt = 0.26            # cadence between volumes
    fill = 0.2               # how long one bar takes to fill
    times, t = [], t0
    for i, (text, _, _) in enumerate(lines):
        times.append(t)
        if first_vol <= i < first_vol + len(repos):
            t += vol_dt
        elif i < 5:
            t += art_dt
        else:
            t += dt if text.strip() else dt * 0.4
    t_end = t + 0.15

    H = int(PADY * 2 + len(lines) * LH + 26)

    body = []
    for i, (text, color, bold) in enumerate(lines):
        if not text:
            continue
        y = PADY + 14 + i * LH
        weight = ' font-weight="700"' if bold else ""
        body.append(
            f'<text x="{PADX}" y="{y:.1f}" fill="{color}"{weight} opacity="0" '
            f'xml:space="preserve">{esc(text)}'
            f'<set attributeName="opacity" to="1" begin="{times[i]:.2f}s" fill="freeze"/>'
            f'</text>')

    # ---- volume rows: name, dot leader, filling bar, then the verdict ----
    name_w = max(len(r["name"]) for r in repos)
    c_name = 10                       # after "  [MOUNT] "
    c_bar = c_name + name_w + 2
    c_meta = c_bar + BAR_CELLS + 3

    def col(c):
        return PADX + c * CW

    for j, r in enumerate(repos):
        i = first_vol + j
        y = PADY + 14 + i * LH
        t_row = times[i]
        lang = (r.get("language") or "—")[:11]
        st = r["stargazers_count"]

        def at(x, text, color, t, bold=False, anchor=""):
            w = ' font-weight="700"' if bold else ""
            a = f' text-anchor="{anchor}"' if anchor else ""
            return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}"{w}{a} opacity="0" '
                    f'xml:space="preserve">{esc(text)}'
                    f'<set attributeName="opacity" to="1" begin="{t:.2f}s" fill="freeze"/>'
                    f'</text>')

        body.append(at(col(2), "[MOUNT]", P_DIM, t_row))
        body.append(at(col(c_name), r["name"], P_ON, t_row))
        body.append(at(col(c_name + len(r["name"]) + 1),
                       "." * (c_bar - c_name - len(r["name"]) - 2), P_DIM, t_row))
        # empty track first, then the fill paints over it, then the brackets
        # last so a full bar can't cover its own closing bracket
        for k in range(BAR_CELLS):
            body.append(at(col(c_bar + 1 + k), "·", P_DIM, t_row))
        for k in range(BAR_CELLS):
            body.append(at(col(c_bar + 1 + k), "█", P_MID,
                           t_row + fill * k / BAR_CELLS))
        body.append(at(col(c_bar), "[", P_HI, t_row))
        body.append(at(col(c_bar + BAR_CELLS + 1), "]", P_HI, t_row))
        t_done = t_row + fill
        body.append(at(col(c_meta), lang, P_MID, t_done))
        if st:
            body.append(at(col(c_meta + 12), f"★{st}", P_HI, t_done, bold=True))
        body.append(at(col(c_meta + 17), "MOUNTED", P_ON, t_done, bold=True))

    # cursor parks after the final line
    cy = PADY + 14 + (len(lines) - 1) * LH
    cx = PADX + (len("System online. Welcome, visitor. Scroll for schematics.") + 1) * CW
    cursor = (f'<rect x="{cx:.1f}" y="{cy - 10:.1f}" width="{CW:.1f}" height="13" '
              f'fill="{P_ON}" opacity="0">'
              f'<set attributeName="opacity" to="1" begin="{t_end:.2f}s" fill="freeze"/>'
              f'<animate attributeName="opacity" values="1;0" calcMode="discrete" '
              f'dur="1.06s" begin="{t_end + 0.2:.2f}s" repeatCount="indefinite"/></rect>')

    # a scan line sweeping down the tube while it boots
    sweep = (f'<rect x="2" y="0" width="{W - 4}" height="42" fill="{P_ON}" '
             f'fill-opacity=".045">'
             f'<animate attributeName="y" from="-40" to="{H}" dur="{max(t_end, 2):.2f}s" '
             f'begin="0s" fill="freeze"/></rect>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t">
  <title id="t">Cold boot — power-on self test and {len(repos)} repositories mounted</title>
  <desc>{esc(login)}'s repositories, enumerated as volumes on a green-phosphor terminal.</desc>
  <defs>
    <radialGradient id="tube" cx="50%" cy="45%" r="78%">
      <stop offset="0" stop-color="#04120A"/>
      <stop offset="70%" stop-color="{SCREEN}"/>
      <stop offset="100%" stop-color="#000200"/>
    </radialGradient>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="2" fill="#000" fill-opacity=".26"/>
    </pattern>
    <filter id="phos" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.15" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="vig" cx="50%" cy="50%" r="72%">
      <stop offset="55%" stop-color="#000" stop-opacity="0"/>
      <stop offset="100%" stop-color="#000" stop-opacity=".72"/>
    </radialGradient>
  </defs>

  <rect width="{W}" height="{H}" rx="14" fill="{BEZEL}"/>
  <rect x="4" y="4" width="{W - 8}" height="{H - 8}" rx="11" fill="url(#tube)"/>

  <g font-family={MONO!r} font-size="{FS}" filter="url(#phos)">
    {"".join(body)}
    {cursor}
  </g>

  {sweep}
  <rect x="4" y="4" width="{W - 8}" height="{H - 8}" rx="11" fill="url(#scan)"/>
  <rect x="4" y="4" width="{W - 8}" height="{H - 8}" rx="11" fill="url(#vig)"/>
  <rect x="4.5" y="4.5" width="{W - 9}" height="{H - 9}" rx="11" fill="none"
        stroke="{P_ON}" stroke-opacity=".18"/>
</svg>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="itsashishupadhyay")
    ap.add_argument("--out", default="assets/boot.svg")
    args = ap.parse_args()

    token = (os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        sys.exit("[boot] need METRICS_TOKEN or GITHUB_TOKEN")

    repos = [r for r in api(f"/users/{args.user}/repos?per_page=100&type=owner", token)
             if not r["fork"] and r["name"] not in SKIP]
    repos.sort(key=lambda r: (-r["stargazers_count"], r["name"].lower()))
    stars = sum(r["stargazers_count"] for r in repos)

    svg = build(repos, stars, args.user)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(svg)
    print(f"[boot] {len(repos)} volumes · {stars} stars -> {args.out} "
          f"({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
