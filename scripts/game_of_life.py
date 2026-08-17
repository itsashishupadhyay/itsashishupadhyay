#!/usr/bin/env python3
"""Conway Twitty's Game of Life — contribution-graph edition.

Seeds a 53x7 toroidal Game of Life board from the user's GitHub contribution
calendar (every green square = a living cell), simulates it, and renders the
whole run as a self-contained SMIL-animated SVG instrument panel.

Zero dependencies (stdlib only). Designed to run in GitHub Actions with
GITHUB_TOKEN; falls back to a synthetic calendar for local previews.

Outcomes:
  - extinction  -> "YOUR GENERATION LASTED X MULTIPLICATIONS ..."
  - steady state (cycle detected) -> still-lifes/oscillators message
  - still chaotic at the sim cap  -> colony outlives the budget

Milestone captions at generations 50/100/150/200 are drawn from approved
message pools, rotated by the daily seed.
"""
import argparse
import datetime
import json
import os
import random
import sys
import urllib.request

COLS, ROWS = 53, 7
MAX_GEN = 1000
DT = 0.12          # seconds per generation
T0 = 7.0           # hold the raw contribution map this long before the sim ticks

GOLD, GOLD_HI, GOLD_LO = "#F5C518", "#F8DE7E", "#D9A514"
CYAN = "#00E5FF"
INK = "#E8E2D2"
GRAY = "#98A0AB"
BG_A, BG_B = "#0a0e13", "#12161d"
MONO = "'Courier New',Courier,monospace"

W, H = 1200, 368
CELL, PITCH = 14, 17
BOARD_W = COLS * PITCH - (PITCH - CELL)
BOARD_X = (W - BOARD_W) / 2
BOARD_Y = 76

DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
# GitHub dark-theme heatmap greens, L1..L4
GH_GREENS = ["#0e4429", "#006d32", "#26a641", "#39d353"]
T_GOLD = 2.0       # final stretch of the hold: green blinks over to gold

MILESTONE_POOLS = {
    50: [
        "Fifty multiplications and no sign of settling down. Your cells have clearly found their duty cycle — and it's aggressive.",
        "50 generations in and the whole board is coupling. Capacitively, inductively, enthusiastically.",
    ],
    100: [
        "100 multiplications. Your MAC unit is doing multiply-and-ACCUMULATE in front of everyone, and nobody's complaining.",
        "Triple digits — the colony has achieved mutual inductance. When one cell flips, every neighbor feels it.",
    ],
    150: [
        "150 generations of sustained oscillation. Somebody should check the thermal budget, because it is getting hot in here.",
        "Still multiplying at 150. This stopped being a simulation a while ago — it's a breeder reactor now.",
    ],
    200: [
        "200+ multiplications. 'Prolific' is underselling it — this colony has a serious fan-out situation.",
        "Two hundred generations, rising edges everywhere. Active high? Extremely.",
    ],
}
WILDCARDS = [
    "Forward-biased and fully saturated. The datasheet swore this operating region was safe.",
    "Gain > 1 with positive feedback — the textbook definition of 'things escalating quickly.'",
]
EXTINCT = [
    "YOUR GENERATION LASTED {x} MULTIPLICATIONS — then undervoltage lockout. Even great oscillators need a nap.",
    "EXTINCT AT GENERATION {x}. Cause of death: insufficient decoupling. Story of every breakup.",
    "{x} MULTIPLICATIONS, THEN SILENCE. The magic smoke has left the colony. Pour one out (≤ 42 mW).",
]
STEADY = [
    "STEADY STATE AT GEN {x} — the survivors formed still lifes and oscillators: technically alive, allergic to change. Like legacy code.",
]
CHAOTIC = "SIM WINDOW ENDED AT GEN {x} — COLONY OUTLIVED THE BUDGET. UNBOTHERED."

RULES = [
    "RULE B3/S23 — no relation to the country singer, though both fill a board with hits.",
    "Every green square from my contribution graph is a living cell. Fewer than 2 neighbors: dies of underpopulation — nobody to pair-program with.",
    "More than 3: dies of thermal throttling. Exactly 3: a new cell is born, and we don't ask questions.",
    "The edges wrap, because all good universes are toruses.",
]

GRAPHQL = """query($login:String!){ user(login:$login){ contributionsCollection{
  contributionCalendar{ weeks{ contributionDays{ contributionCount weekday date }}}}}}"""


def fetch_calendar(user):
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        return None
    body = json.dumps({"query": GRAPHQL, "variables": {"login": user}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json",
                 "User-Agent": "conway-twitty"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except Exception as e:  # noqa: BLE001 - any failure falls back to synthetic
        print(f"[life] calendar fetch failed ({e}); using synthetic board", file=sys.stderr)
        return None
    grid = [[0] * ROWS for _ in range(COLS)]
    months = [0] * COLS
    for wi, wk in enumerate(weeks[-COLS:]):
        days = wk["contributionDays"]
        months[wi] = int(days[0]["date"][5:7]) if days else months[max(wi - 1, 0)]
        for day in days:
            grid[wi][day["weekday"]] = day["contributionCount"]
    return grid, months


def synthetic_calendar(rng):
    grid = [[0] * ROWS for _ in range(COLS)]
    start = datetime.date.today() - datetime.timedelta(weeks=COLS - 1)
    months = [(start + datetime.timedelta(weeks=w)).month for w in range(COLS)]
    for w in range(COLS):
        heat = 0.55 if (w % 9) not in (4, 8) else 0.2      # some quiet weeks
        for d in range(ROWS):
            p = heat * (1.25 if 1 <= d <= 5 else 0.5)       # weekday-heavy
            grid[w][d] = rng.randint(1, 9) if rng.random() < p else 0
    return grid, months


# ----------------------------------------------------------------------------
# simulation on a 53x7 torus, bitmask states
# ----------------------------------------------------------------------------

def neighbors():
    nbr = []
    for i in range(COLS * ROWS):
        w, d = divmod(i, ROWS)
        cells = []
        for dw in (-1, 0, 1):
            for dd in (-1, 0, 1):
                if dw == dd == 0:
                    continue
                cells.append(((w + dw) % COLS) * ROWS + (d + dd) % ROWS)
        nbr.append(cells)
    return nbr


# cosmic-ray payloads: (dw, dd) offsets, anchored on an original green square
PATTERNS = {
    "GLIDER": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)],
    "R-PENTOMINO": [(0, 1), (0, 2), (1, 0), (1, 1), (2, 1)],
    "LWSS": [(1, 0), (4, 0), (0, 1), (0, 2), (4, 2), (0, 3), (1, 3), (2, 3), (3, 3)],
}
SEU_BUDGET = 6


def step(s, nbr):
    ns = 0
    for i in range(COLS * ROWS):
        n = sum((s >> j) & 1 for j in nbr[i])
        if n == 3 or (n == 2 and (s >> i) & 1):
            ns |= 1 << i
    return ns


def inject(s, anchor, pattern):
    w0, d0 = divmod(anchor, ROWS)
    for dw, dd in PATTERNS[pattern]:
        s |= 1 << (((w0 + dw) % COLS) * ROWS + (d0 + dd) % ROWS)
    return s


def simulate(seed_mask, rng, greens):
    """Run B3/S23 on the torus. A stalled colony (extinct or cycling) gets
    revived by a cosmic-ray SEU at one of the original commit squares, until
    the SEU budget runs out. Returns (states, outcome, events)."""
    nbr = neighbors()
    states = [seed_mask]
    seen = {seed_mask: 0}
    events = []                       # (gen, anchor, pattern)
    budget = SEU_BUDGET
    s = seed_mask
    g = 0
    while g < MAX_GEN:
        g += 1
        s = step(s, nbr)
        stall = None
        if s == 0:
            stall = ("extinct", g, 0)
        elif s in seen:
            stall = ("steady", seen[s], g - seen[s])
        if stall is None:
            states.append(s)
            seen[s] = g
            continue
        if budget > 0:
            budget -= 1
            anchor = rng.choice(greens)
            pattern = rng.choice(list(PATTERNS))
            s = inject(s, anchor, pattern)
            events.append((g, anchor, pattern))
            states.append(s)
            seen = {s: g}
            continue
        kind, x, period = stall
        states.append(s)
        if kind == "steady":
            # keep enough frames to show the loop twice
            for _ in range(max(0, min(x + 2 * period - g, MAX_GEN - g))):
                s = step(s, nbr)
                states.append(s)
        return states, (kind, x if kind == "steady" else g, period), events
    return states, ("chaotic", MAX_GEN, 0), events


# ----------------------------------------------------------------------------
# SMIL helpers: toggle-encoded discrete opacity animation
# ----------------------------------------------------------------------------

def toggle_animate(attr, timeline, total, initial):
    """timeline: sorted [(t, value)] changes. Emits one discrete animate."""
    if not timeline:
        return ""
    vals, keys = [str(initial)], ["0"]
    for t, v in timeline:
        kt = max(0.0, min(1.0, t / total))
        vals.append(str(v))
        keys.append(f"{kt:.4f}")
    return (f'<animate attributeName="{attr}" calcMode="discrete" '
            f'values="{";".join(vals)}" keyTimes="{";".join(keys)}" '
            f'begin="0s" dur="{total:.2f}s" fill="freeze"/>')


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------------------------
# SVG assembly
# ----------------------------------------------------------------------------

def build_svg(grid, months, rng, seed_label):
    alive0 = [[grid[w][d] > 0 for d in range(ROWS)] for w in range(COLS)]
    live_idx = [w * ROWS + d for w in range(COLS) for d in range(ROWS) if alive0[w][d]]
    if not live_idx:
        alive0[COLS // 2][ROWS // 2] = True
        live_idx = [(COLS // 2) * ROWS + ROWS // 2]

    genesis = rng.choice(live_idx)
    gw, gd = divmod(genesis, ROWS)

    seed_mask = 0
    for i in live_idx:
        seed_mask |= 1 << i
    states, (kind, x, period), events = simulate(seed_mask, rng, live_idx)
    n_frames = len(states)                      # states[0] .. states[n-1]
    total = T0 + (n_frames - 1) * DT + 2.2      # timeline incl. ending hold-in
    t_end = T0 + (n_frames - 1) * DT + 0.4

    # ---- ending + milestone messages ----
    if kind == "extinct":
        ending = rng.choice(EXTINCT).format(x=x)
        ending_col = GOLD
    elif kind == "steady":
        ending = rng.choice(STEADY).format(x=x)
        ending_col = CYAN
    else:
        ending = CHAOTIC.format(x=x)
        ending_col = GOLD
    last_gen = n_frames - 1
    crossed = [m for m in (50, 100, 150, 200) if m <= last_gen]
    used, cap_texts = set(), []
    for m in crossed:
        pool = list(MILESTONE_POOLS[m]) + (WILDCARDS if m >= 100 else [])
        pool = [p for p in pool if p not in used] or list(MILESTONE_POOLS[m])
        msg = rng.choice(pool)
        used.add(msg)
        cap_texts.append((m, msg))

    # ---- cells ----
    # gen-0 cells start as the GitHub-green heatmap (quartile intensity levels),
    # then blink over to gold in the last stretch of the intro hold
    counts = sorted(grid[w][d] for w in range(COLS) for d in range(ROWS) if grid[w][d] > 0)
    th = [counts[min(len(counts) - 1, int(p * len(counts)))] for p in (.25, .5, .75)] \
        if counts else [1, 2, 3]

    cell_rects, green_overlays = [], []
    ever_alive = set()
    for i in range(COLS * ROWS):
        for s in states:
            if (s >> i) & 1:
                ever_alive.add(i)
                break
    for i in sorted(ever_alive):
        w, d = divmod(i, ROWS)
        cx = BOARD_X + w * PITCH
        cy = BOARD_Y + d * PITCH
        init = (states[0] >> i) & 1
        timeline, cur = [], init
        for g in range(1, n_frames):
            v = (states[g] >> i) & 1
            if v != cur:
                timeline.append((T0 + g * DT, v))
                cur = v
        anim = toggle_animate("fill-opacity", timeline, total, init)
        cell_rects.append(
            f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{CELL}" height="{CELL}" rx="3" '
            f'fill="{GOLD}" fill-opacity="{init}">{anim}</rect>')
        if init:
            # GitHub-green heatmap overlay: covers the gold cell through the
            # intro hold, then blinks away to reveal gold as the sim ignites
            green = GH_GREENS[sum(grid[w][d] > t for t in th)]
            green_overlays.append(
                f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{CELL}" height="{CELL}" rx="3" '
                f'fill="{green}"><animate attributeName="fill-opacity" calcMode="discrete" '
                f'values="1;0;1;0;1;0" begin="{T0 - T_GOLD:.2f}s" dur="{T_GOLD:.2f}s" '
                f'fill="freeze"/></rect>')

    # ---- month labels along the X axis, GitHub style ----
    trans = [w for w in range(COLS) if w == 0 or months[w] != months[w - 1]]
    if len(trans) > 1 and trans[1] - trans[0] < 3:
        trans = trans[1:]                       # drop a crowded partial first month
    labels_svg = "".join(
        f'<text x="{BOARD_X + w * PITCH:.1f}" y="69" font-family={MONO!r} font-size="9.5" '
        f'fill="{GRAY}" fill-opacity=".7" letter-spacing="1">{MONTHS[months[w] - 1]}</text>'
        for w in trans)

    grid_bg = (f'<pattern id="gg" width="{PITCH}" height="{PITCH}" patternUnits="userSpaceOnUse" '
               f'x="{BOARD_X}" y="{BOARD_Y}">'
               f'<rect width="{CELL}" height="{CELL}" rx="3" fill="none" '
               f'stroke="{GOLD}" stroke-opacity=".10" stroke-width="0.6"/></pattern>')

    # genesis square blinks cyan rapidly through the intro hold, then the
    # simulation takes the cell back
    blink_dur = 0.3
    blink_n = int((T0 - 0.4) / blink_dur)
    genesis_svg = (f'<rect x="{BOARD_X + gw * PITCH:.1f}" y="{BOARD_Y + gd * PITCH:.1f}" '
                   f'width="{CELL}" height="{CELL}" rx="3" fill="{CYAN}" '
                   f'filter="url(#glow)" opacity="0">'
                   f'<animate attributeName="opacity" calcMode="discrete" values="1;0" '
                   f'begin="0.4s" dur="{blink_dur}s" repeatCount="{blink_n}"/></rect>')

    # ---- GEN counter (3 digit slots, stacked glyphs, toggle-encoded) ----
    def digit_at(gen, slot):
        return (gen // (10 ** slot)) % 10

    counter = []
    for slot in range(3):
        dx = 1112 - slot * 15
        for digit in range(10):
            init = 1 if digit_at(0, slot) == digit else 0
            timeline, cur = [], init
            for g in range(1, n_frames):
                v = 1 if digit_at(g, slot) == digit else 0
                if v != cur:
                    timeline.append((T0 + g * DT, v))
                    cur = v
            anim = toggle_animate("opacity", timeline, total, init)
            counter.append(
                f'<text x="{dx}" y="47" font-family={MONO!r} font-size="24" font-weight="700" '
                f'fill="{CYAN}" text-anchor="middle" opacity="{init}">{digit}{anim}</text>')
    counter_svg = "\n    ".join(counter)

    # ---- captions ----
    caps = [
        f'<text x="{W / 2}" y="226" text-anchor="middle" font-family={MONO!r} '
        f'font-size="13.5" fill="{INK}" fill-opacity=".85" opacity="0">'
        f'GEN 000 · CONTRIBUTION MAP LOADED — EVERY GREEN SQUARE IS A LIVING CELL'
        f'<set attributeName="opacity" to="1" begin="0.6s" fill="freeze"/>'
        f'<set attributeName="opacity" to="0" begin="{T0:.2f}s" fill="freeze"/></text>']
    for idx, (m, msg) in enumerate(cap_texts):
        t_on = T0 + m * DT
        t_off = (T0 + cap_texts[idx + 1][0] * DT) if idx + 1 < len(cap_texts) else None
        sets = f'<set attributeName="opacity" to="1" begin="{t_on:.2f}s" fill="freeze"/>'
        if t_off:
            sets += f'<set attributeName="opacity" to="0" begin="{t_off:.2f}s" fill="freeze"/>'
        caps.append(f'<text x="{W / 2}" y="226" text-anchor="middle" font-family={MONO!r} '
                    f'font-size="13.5" fill="{GOLD}" opacity="0">GEN {m} · {esc(msg)}{sets}</text>')
    caps.append(f'<text x="{W / 2}" y="252" text-anchor="middle" font-family={MONO!r} '
                f'font-size="13.5" font-weight="700" fill="{ending_col}" opacity="0">'
                f'{esc(ending)}<set attributeName="opacity" to="1" begin="{t_end:.2f}s" '
                f'fill="freeze"/></text>')
    for idx, (g, anchor, pattern) in enumerate(events):
        ew, ed = divmod(anchor, ROWS)
        t_on = T0 + g * DT
        ey = 61 + (idx % 2) * 13
        caps.append(
            f'<text x="{W - 44}" y="{ey}" text-anchor="end" font-family={MONO!r} '
            f'font-size="10.5" fill="{CYAN}" opacity="0">⚡ SEU @ WK {ew:02d}·{DAYS[ed]} — '
            f'{pattern}<set attributeName="opacity" to="0.9" begin="{t_on:.2f}s"/>'
            f'<set attributeName="opacity" to="0" begin="{t_on + 1.8:.2f}s" fill="freeze"/></text>')
    caps_svg = "\n  ".join(caps)

    rules_svg = "\n  ".join(
        f'<text x="{W / 2}" y="{288 + i * 16}" text-anchor="middle" font-family={MONO!r} '
        f'font-size="10.5" fill="{INK}" fill-opacity=".55">{esc(l)}</text>'
        for i, l in enumerate(RULES))

    chrome = (f'SEED {seed_label} · REFRESHED DAILY · TORUS TOPOLOGY · '
              f'GENESIS NODE @ WK {gw:02d} · {DAYS[gd]} · '
              f'SEU EVENTS: {len(events)} · RAD-HARD: NO')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t">
  <!-- hello darlin'. rule B3/S23. -->
  <title id="t">Conway Twitty's Game of Life — seeded from my contribution graph</title>
  <defs>
    <linearGradient id="bgg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_A}"/><stop offset="1" stop-color="{BG_B}"/>
    </linearGradient>
    {grid_bg}
    <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation="2.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <rect width="{W}" height="{H}" rx="12" fill="url(#bgg)"/>
  <rect x="14" y="14" width="{W - 28}" height="{H - 28}" rx="8" fill="none"
        stroke="{GOLD}" stroke-opacity=".22" stroke-width="1"/>

  <text x="40" y="47" font-family={MONO!r} font-size="21" font-weight="700"
        fill="{GOLD}" letter-spacing="2">CONWAY TWITTY'S GAME OF LIFE</text>
  <rect x="472" y="29" width="94" height="24" rx="4" fill="none" stroke="{CYAN}" stroke-opacity=".5"/>
  <text x="519" y="45" text-anchor="middle" font-family={MONO!r} font-size="12"
        fill="{CYAN}">B3/S23</text>
  <text x="1064" y="47" text-anchor="end" font-family={MONO!r} font-size="13"
        fill="{GOLD}" letter-spacing="2">GEN</text>
  <g>
    {counter_svg}
  </g>

  {labels_svg}
  <rect x="{BOARD_X}" y="{BOARD_Y}" width="{BOARD_W}" height="{ROWS * PITCH - (PITCH - CELL)}"
        fill="url(#gg)"/>
  {"".join(cell_rects)}
  {"".join(green_overlays)}
  {genesis_svg}

  {caps_svg}
  <line x1="40" y1="264" x2="{W - 40}" y2="264" stroke="{GOLD}" stroke-opacity=".15"/>
  {rules_svg}
  <text x="{W / 2}" y="348" text-anchor="middle" font-family={MONO!r} font-size="9.5"
        fill="{GRAY}" fill-opacity=".55" letter-spacing="1">{chrome}</text>
</svg>
"""
    return svg, (kind, x, n_frames - 1)


def render_static(grid, months, seed_label):
    """The README poster: gen 0 as a plain GitHub heatmap, plus a RUN button.

    A README <img> is served through GitHub's image proxy, so nothing inside it
    can receive a click — the button is the affordance and the surrounding
    markdown link is what actually navigates. Nothing animates here, so the
    board simply sits as the contribution map until someone chooses to run it.
    """
    counts = sorted(grid[w][d] for w in range(COLS) for d in range(ROWS) if grid[w][d] > 0)
    th = [counts[min(len(counts) - 1, int(p * len(counts)))] for p in (.25, .5, .75)] \
        if counts else [1, 2, 3]

    cells = []
    live = 0
    for w in range(COLS):
        for d in range(ROWS):
            if grid[w][d] <= 0:
                continue
            live += 1
            cells.append(
                f'<rect x="{BOARD_X + w * PITCH:.1f}" y="{BOARD_Y + d * PITCH:.1f}" '
                f'width="{CELL}" height="{CELL}" rx="3" '
                f'fill="{GH_GREENS[sum(grid[w][d] > t for t in th)]}"/>')

    trans = [w for w in range(COLS) if w == 0 or months[w] != months[w - 1]]
    if len(trans) > 1 and trans[1] - trans[0] < 3:
        trans = trans[1:]
    labels = "".join(
        f'<text x="{BOARD_X + w * PITCH:.1f}" y="69" font-family={MONO!r} font-size="9.5" '
        f'fill="{GRAY}" fill-opacity=".7" letter-spacing="1">{MONTHS[months[w] - 1]}</text>'
        for w in trans)

    bw, bh = 300, 44
    bx, by = (W - bw) / 2, 214
    button = f"""
  <g>
    <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" fill="{GOLD}" fill-opacity=".12"
          stroke="{GOLD}" stroke-width="1.5"/>
    <path d="M{bx + 34},{by + 14} L{bx + 34},{by + 30} L{bx + 48},{by + 22} Z" fill="{GOLD}"/>
    <text x="{bx + 62}" y="{by + 28}" font-family={MONO!r} font-size="16" font-weight="700"
          fill="{GOLD}" letter-spacing="2">RUN THE SIMULATION</text>
  </g>
  <text x="{W / 2}" y="{by + 68}" text-anchor="middle" font-family={MONO!r} font-size="11"
        fill="{CYAN}">Click to open the live board — start, pause, and restart it yourself.</text>"""

    rules_svg = "\n  ".join(
        f'<text x="{W / 2}" y="{300 + i * 16}" text-anchor="middle" font-family={MONO!r} '
        f'font-size="10.5" fill="{INK}" fill-opacity=".55">{esc(l)}</text>'
        for i, l in enumerate(RULES[:2]))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="360" viewBox="0 0 {W} 360" role="img" aria-labelledby="t">
  <title id="t">Conway Twitty's Game of Life — {live} live cells seeded from my contribution graph</title>
  <defs>
    <linearGradient id="bgg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_A}"/><stop offset="1" stop-color="{BG_B}"/>
    </linearGradient>
    <pattern id="gg" width="{PITCH}" height="{PITCH}" patternUnits="userSpaceOnUse"
             x="{BOARD_X}" y="{BOARD_Y}">
      <rect width="{CELL}" height="{CELL}" rx="3" fill="none" stroke="{GOLD}"
            stroke-opacity=".10" stroke-width="0.6"/>
    </pattern>
  </defs>
  <rect width="{W}" height="360" rx="12" fill="url(#bgg)"/>
  <rect x="14" y="14" width="{W - 28}" height="332" rx="8" fill="none"
        stroke="{GOLD}" stroke-opacity=".22" stroke-width="1"/>
  <text x="40" y="47" font-family={MONO!r} font-size="21" font-weight="700"
        fill="{GOLD}" letter-spacing="2">CONWAY TWITTY'S GAME OF LIFE</text>
  <rect x="472" y="29" width="94" height="24" rx="4" fill="none" stroke="{CYAN}" stroke-opacity=".5"/>
  <text x="519" y="45" text-anchor="middle" font-family={MONO!r} font-size="12" fill="{CYAN}">B3/S23</text>
  <text x="{W - 40}" y="47" text-anchor="end" font-family={MONO!r} font-size="11"
        fill="{GRAY}" letter-spacing="1">GEN 000 · READY</text>
  {labels}
  <rect x="{BOARD_X}" y="{BOARD_Y}" width="{BOARD_W}" height="{ROWS * PITCH - (PITCH - CELL)}"
        fill="url(#gg)"/>
  {"".join(cells)}
  {button}
  {rules_svg}
  <text x="{W / 2}" y="338" text-anchor="middle" font-family={MONO!r} font-size="9.5"
        fill="{GRAY}" fill-opacity=".55" letter-spacing="1">SEED {seed_label} · {live} LIVE CELLS · TORUS TOPOLOGY · MAX {MAX_GEN} GENERATIONS</text>
</svg>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="itsashishupadhyay")
    ap.add_argument("--out", default="dist/game-of-life.svg")
    ap.add_argument("--seed", default=None)
    ap.add_argument("--static", action="store_true",
                    help="render the non-animated README poster with a RUN button")
    args = ap.parse_args()

    seed = args.seed or os.urandom(4).hex()
    seed_label = args.seed or f"0x{seed.upper()}"
    rng = random.Random(seed)

    cal = fetch_calendar(args.user)
    if cal is None:
        cal = synthetic_calendar(rng)
    grid, months = cal

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if args.static:
        with open(args.out, "w") as f:
            f.write(render_static(grid, months, seed_label))
        print(f"[life] static poster -> {args.out} ({os.path.getsize(args.out)} bytes)")
        return

    svg, (kind, x, frames) = build_svg(grid, months, rng, seed_label)
    with open(args.out, "w") as f:
        f.write(svg)
    print(f"[life] outcome={kind} at gen {x}, {frames} frames, "
          f"{os.path.getsize(args.out)} bytes -> {args.out}")


if __name__ == "__main__":
    main()
