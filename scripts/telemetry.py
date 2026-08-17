#!/usr/bin/env python3
"""LIVE TELEMETRY — a self-hosted GitHub metrics dashboard.

Replaces the third-party README cards (github-readme-stats et al) that keep
503-ing. Pulls real numbers straight from the GitHub API and renders a
bench-instrument dashboard SVG in the profile's design language.

GitHub only retains 14 days of traffic data, so each run merges today's
per-day numbers into a history file on the output branch — that gives a
genuine RUNNING clone total that survives the rolling window.

Token: cross-repo traffic needs a PAT with `repo` scope (METRICS_TOKEN).
Falls back to GITHUB_TOKEN, which can only see traffic for its own repo;
traffic panels degrade gracefully rather than failing the run.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"

# --- design system (shared with header.svg / game-of-life.svg) ---
GOLD, GOLD_HI, GOLD_LO, GOLD_DIM = "#F5C518", "#F8DE7E", "#D9A514", "#8A6A10"
CYAN = "#00E5FF"
INK, GRAY = "#E8E2D2", "#98A0AB"
BG_A, BG_B = "#0a0e13", "#12161d"
MONO = "'Courier New',Courier,monospace"

W = 1200
PAD = 26

GRAPHQL = """
query($login:String!){
  user(login:$login){
    followers{totalCount}
    repositories(first:100, ownerAffiliations:OWNER, isFork:false){
      totalCount
      nodes{
        name isPrivate stargazerCount forkCount
        languages(first:10, orderBy:{field:SIZE,direction:DESC}){
          edges{ size node{ name } }
        }
      }
    }
    contributionsCollection{
      contributionCalendar{
        totalContributions
        weeks{ contributionDays{ contributionCount date } }
      }
    }
  }
}"""


def api(url, token, method="GET"):
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": f"bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "live-telemetry"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def graphql(token, login):
    body = json.dumps({"query": GRAPHQL, "variables": {"login": login}}).encode()
    req = urllib.request.Request(f"{API}/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "live-telemetry"})
    with urllib.request.urlopen(req, timeout=25) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def traffic(login, repo, token, kind):
    """Per-day traffic. Returns [] when the token lacks push access (403)."""
    try:
        data = api(f"{API}/repos/{login}/{repo}/traffic/{kind}", token)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise
    return data.get(kind, [])


def load_history(login, path):
    """Prior run's per-day traffic, from disk or the published output branch."""
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = (f"https://raw.githubusercontent.com/{login}/{login}/"
           f"output/telemetry-history.json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "live-telemetry"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return {}


def streaks(days):
    """(current, longest) daily contribution streaks."""
    vals = [d["contributionCount"] for d in days]
    longest = run = 0
    for v in vals:
        run = run + 1 if v > 0 else 0
        longest = max(longest, run)
    # today may legitimately be empty — don't let it zero the current streak
    tail = vals[:-1] if vals and vals[-1] == 0 else vals
    cur = 0
    for v in reversed(tail):
        if v == 0:
            break
        cur += 1
    return cur, longest


def collect(login, token, hist_path):
    user = graphql(token, login)
    repos = user["repositories"]["nodes"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [d for wk in cal["weeks"] for d in wk["contributionDays"]]

    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]

    history = load_history(login, hist_path)
    public = [r for r in repos if not r["isPrivate"]]
    denied = 0
    for r in public:
        rows = traffic(login, r["name"], token, "clones")
        if rows is None:
            denied += 1
            continue
        bucket = history.setdefault(r["name"], {})
        for row in rows:
            bucket[row["timestamp"][:10]] = [row["count"], row["uniques"]]

    # 14-day window anchored on the newest day that actually has data, so a
    # partially-elapsed today never renders as a cliff down to zero
    today = datetime.datetime.now(datetime.timezone.utc).date()
    seen = [d for b in history.values() for d in b]
    end = min(today, max((datetime.date.fromisoformat(d) for d in seen), default=today))
    window = {(end - datetime.timedelta(days=i)).isoformat() for i in range(14)}
    per_repo, daily = {}, {}
    all_time = all_uniq = 0
    for name, bucket in history.items():
        recent = 0
        for date, (count, uniq) in bucket.items():
            all_time += count
            all_uniq += uniq
            if date in window:
                recent += count
                d = daily.setdefault(date, [0, 0])
                d[0] += count
                d[1] += uniq
        if recent:
            per_repo[name] = recent

    cur, longest = streaks(days)
    active = sum(1 for d in days if d["contributionCount"] > 0)
    return {
        "active_days": active,
        "login": login,
        "repos_total": len(repos),
        "repos_public": len(public),
        "repos_private": len(repos) - len(public),
        "stars": sum(r["stargazerCount"] for r in repos),
        "forks": sum(r["forkCount"] for r in repos),
        "followers": user["followers"]["totalCount"],
        "contributions": cal["totalContributions"],
        "streak_cur": cur,
        "streak_max": longest,
        "clones_14d": sum(per_repo.values()),
        "clones_all": all_time,
        "uniques_all": all_uniq,
        "per_repo": per_repo,
        "daily": daily,
        "window_end": end.isoformat(),
        "langs": langs,
        "denied": denied,
        "tracked_days": len({d for b in history.values() for d in b}),
        "history": history,
    }


# ----------------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------------

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def ramp(rank, n):
    """Sequential gold ramp, brightest = largest value (one hue, light->dark)."""
    steps = [GOLD_HI, GOLD, GOLD_LO, GOLD_DIM]
    if n <= 1:
        return steps[1]
    return steps[min(len(steps) - 1, int(rank / max(1, n - 1) * (len(steps) - 1)))]


def kpi_row(m, y):
    tiles = [
        (m["repos_total"], "REPOSITORIES", f'{m["repos_public"]} PUBLIC · {m["repos_private"]} PRIVATE'),
        (m["clones_all"], "CLONES TRACKED", f'{m["clones_14d"]} IN LAST 14 DAYS'),
        (m["stars"], "STARS EARNED", f'{m["forks"]} FORKS'),
        (m["contributions"], "CONTRIBUTIONS", "TRAILING 12 MONTHS"),
        (m["active_days"], "ACTIVE DAYS", f'BEST STREAK {m["streak_max"]}'),
        (m["followers"], "FOLLOWERS", "AND CLIMBING"),
    ]
    n = len(tiles)
    gap = 10
    tw = (W - 2 * PAD - gap * (n - 1)) / n
    out = []
    for i, (val, label, sub) in enumerate(tiles):
        x = PAD + i * (tw + gap)
        out.append(
            f'<g><rect x="{x:.1f}" y="{y}" width="{tw:.1f}" height="86" rx="6" '
            f'fill="#0d1117" stroke="{GOLD}" stroke-opacity=".28"/>'
            f'<text x="{x + tw / 2:.1f}" y="{y + 40}" text-anchor="middle" '
            f'font-family={MONO!r} font-size="30" font-weight="700" fill="{GOLD}">{val}</text>'
            f'<text x="{x + tw / 2:.1f}" y="{y + 60}" text-anchor="middle" '
            f'font-family={MONO!r} font-size="10" fill="{INK}" letter-spacing="1">{label}</text>'
            f'<text x="{x + tw / 2:.1f}" y="{y + 75}" text-anchor="middle" '
            f'font-family={MONO!r} font-size="8" fill="{GRAY}" fill-opacity=".8">{esc(sub)}</text></g>')
    return "".join(out), y + 86


def scope(m, y):
    """CH1 clones/day, CH2 unique cloners/day — a real 14-day waveform."""
    h, top = 150, y + 34
    x0, x1 = PAD + 8, W - PAD - 8
    end = datetime.date.fromisoformat(m["window_end"])
    dates = [(end - datetime.timedelta(days=13 - i)).isoformat() for i in range(14)]
    series = [m["daily"].get(d, [0, 0]) for d in dates]
    peak = max([s[0] for s in series] + [1])
    sx = (x1 - x0) / 13
    sy = (h - 30) / peak

    def pts(idx):
        return [(x0 + i * sx, top + h - 22 - s[idx] * sy) for i, s in enumerate(series)]

    clone_pts, uniq_pts = pts(0), pts(1)
    line = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}"
                    for i, (px, py) in enumerate(clone_pts))
    area = (line + f" L{clone_pts[-1][0]:.1f},{top + h - 22:.1f} "
                   f"L{clone_pts[0][0]:.1f},{top + h - 22:.1f} Z")
    uline = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}"
                     for i, (px, py) in enumerate(uniq_pts))

    grat = "".join(
        f'<line x1="{x0}" y1="{top + h - 22 - k * (h - 30) / 3:.1f}" x2="{x1}" '
        f'y2="{top + h - 22 - k * (h - 30) / 3:.1f}" stroke="{GOLD}" stroke-opacity=".09"/>'
        for k in range(4))
    ylab = "".join(
        f'<text x="{x0 - 6}" y="{top + h - 18 - k * (h - 30) / 3:.1f}" text-anchor="end" '
        f'font-family={MONO!r} font-size="8" fill="{GRAY}" fill-opacity=".75">'
        f'{round(peak * k / 3)}</text>' for k in range(4))
    xlab = "".join(
        f'<text x="{x0 + i * sx:.1f}" y="{top + h - 6:.1f}" text-anchor="middle" '
        f'font-family={MONO!r} font-size="8" fill="{GRAY}" fill-opacity=".75">'
        f'{dates[i][5:]}</text>' for i in range(0, 14, 2))
    dots = "".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.6" fill="{GOLD}"/>'
        for px, py in clone_pts)
    # peak gets the only direct value label — no number on every point
    pi = max(range(14), key=lambda i: series[i][0])
    peak_lab = (f'<text x="{clone_pts[pi][0]:.1f}" y="{clone_pts[pi][1] - 9:.1f}" '
                f'text-anchor="middle" font-family={MONO!r} font-size="10" '
                f'font-weight="700" fill="{INK}">{series[pi][0]}</text>'
                if series[pi][0] else "")

    return f"""
  <text x="{PAD}" y="{y + 16}" font-family={MONO!r} font-size="12" font-weight="700"
        fill="{GOLD}" letter-spacing="2">CLONE WAVEFORM — 14 DAY WINDOW</text>
  <g font-family={MONO!r} font-size="9">
    <line x1="{W - PAD - 210}" y1="{y + 12}" x2="{W - PAD - 190}" y2="{y + 12}"
          stroke="{GOLD}" stroke-width="2"/>
    <text x="{W - PAD - 185}" y="{y + 15}" fill="{INK}">CH1 CLONES</text>
    <line x1="{W - PAD - 96}" y1="{y + 12}" x2="{W - PAD - 76}" y2="{y + 12}"
          stroke="{CYAN}" stroke-width="2" stroke-dasharray="4 3"/>
    <text x="{W - PAD - 71}" y="{y + 15}" fill="{INK}">CH2 UNIQUE</text>
  </g>
  <rect x="{x0}" y="{top}" width="{x1 - x0}" height="{h - 22}" fill="none"
        stroke="{GOLD}" stroke-opacity=".22"/>
  {grat}{ylab}{xlab}
  <path d="{area}" fill="{GOLD}" fill-opacity=".13"/>
  <path d="{line}" fill="none" stroke="{GOLD}" stroke-width="2"
        stroke-linejoin="round" stroke-linecap="round"/>
  <path d="{uline}" fill="none" stroke="{CYAN}" stroke-width="2" stroke-dasharray="4 3"
        stroke-linejoin="round" stroke-linecap="round"/>
  {dots}{peak_lab}""", top + h + 12


def bars(title, rows, x, y, width, unit=""):
    """Horizontal ranked bars: sequential gold ramp, every bar direct-labeled."""
    out = [f'<text x="{x}" y="{y + 12}" font-family={MONO!r} font-size="12" '
           f'font-weight="700" fill="{GOLD}" letter-spacing="2">{esc(title)}</text>']
    if not rows:
        out.append(f'<text x="{x}" y="{y + 40}" font-family={MONO!r} font-size="11" '
                   f'fill="{GRAY}">NO DATA IN WINDOW</text>')
        return "".join(out), y + 60
    peak = max(v for _, v in rows) or 1
    lab_w, val_w = 176, 46
    track = width - lab_w - val_w
    bh, gap = 15, 8            # >=2px surface gap between adjacent bars
    for i, (name, val) in enumerate(rows):
        by = y + 30 + i * (bh + gap)
        bw = max(3, track * val / peak)
        label = name if len(name) <= 22 else name[:21] + "…"
        out.append(
            f'<text x="{x}" y="{by + 11.5}" font-family={MONO!r} font-size="10.5" '
            f'fill="{INK}">{esc(label)}</text>'
            f'<rect x="{x + lab_w}" y="{by}" width="{track:.1f}" height="{bh}" rx="3" '
            f'fill="{GOLD}" fill-opacity=".07"/>'
            f'<rect x="{x + lab_w}" y="{by}" width="{bw:.1f}" height="{bh}" rx="3" '
            f'fill="{ramp(i, len(rows))}"/>'
            f'<text x="{x + lab_w + track + 8}" y="{by + 11.5}" font-family={MONO!r} '
            f'font-size="10.5" font-weight="700" fill="{INK}">{val}{unit}</text>')
    return "".join(out), y + 30 + len(rows) * (bh + gap)


def render(m):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = []
    y = 76

    tiles, y = kpi_row(m, y)
    body.append(tiles)
    y += 22

    wave, y = scope(m, y)
    body.append(wave)
    y += 10

    col_w = (W - 2 * PAD - 30) / 2
    top_repos = sorted(m["per_repo"].items(), key=lambda kv: -kv[1])[:7]
    total_bytes = sum(m["langs"].values()) or 1
    top_langs = [(k, round(v / total_bytes * 100))
                 for k, v in sorted(m["langs"].items(), key=lambda kv: -kv[1])[:7]]

    left, y1 = bars("MOST CLONED — 14 DAY", top_repos, PAD, y, col_w)
    right, y2 = bars("LANGUAGE SPECTRUM — BY BYTES", top_langs,
                     PAD + col_w + 30, y, col_w, unit="%")
    body += [left, right]
    y = max(y1, y2) + 26

    note = (f'TRAFFIC WINDOW 14 DAYS (GITHUB RETENTION) · RUNNING TOTAL FROM '
            f'{m["tracked_days"]} TRACKED DAYS · {m["uniques_all"]} UNIQUE CLONERS')
    if m["denied"]:
        note += f' · {m["denied"]} REPOS NEED METRICS_TOKEN'
    body.append(
        f'<line x1="{PAD}" y1="{y - 14}" x2="{W - PAD}" y2="{y - 14}" stroke="{GOLD}" '
        f'stroke-opacity=".15"/>'
        f'<text x="{W / 2}" y="{y}" text-anchor="middle" font-family={MONO!r} '
        f'font-size="8.5" fill="{GRAY}" fill-opacity=".75" letter-spacing="1">{note}</text>')
    h = y + 20

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" viewBox="0 0 {W} {h:.0f}" role="img" aria-labelledby="ti">
  <title id="ti">Live telemetry — {m["repos_total"]} repos, {m["clones_all"]} tracked clones, {m["stars"]} stars, {m["contributions"]} contributions</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_A}"/><stop offset="1" stop-color="{BG_B}"/>
    </linearGradient>
    <filter id="gl" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation="2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect width="{W}" height="{h:.0f}" rx="12" fill="url(#bg)"/>
  <rect x="12" y="12" width="{W - 24}" height="{h - 24:.0f}" rx="8" fill="none"
        stroke="{GOLD}" stroke-opacity=".22"/>
  <text x="{PAD}" y="48" font-family={MONO!r} font-size="26" font-weight="700"
        fill="{GOLD}" letter-spacing="3">LIVE TELEMETRY</text>
  <circle cx="{W - PAD - 250}" cy="42" r="3.4" fill="{CYAN}" filter="url(#gl)">
    <animate attributeName="opacity" calcMode="discrete" values="1;0" dur="1.6s"
             repeatCount="indefinite"/>
  </circle>
  <text x="{W - PAD - 240}" y="45" font-family={MONO!r} font-size="9" fill="{CYAN}"
        letter-spacing="1">ACQUIRING</text>
  <text x="{W - PAD}" y="45" text-anchor="end" font-family={MONO!r} font-size="9"
        fill="{GRAY}" letter-spacing="1">SAMPLED {stamp}</text>
  {"".join(body)}
</svg>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="itsashishupadhyay")
    ap.add_argument("--out", default="dist/telemetry.svg")
    ap.add_argument("--history", default="dist/telemetry-history.json")
    args = ap.parse_args()

    token = (os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        sys.exit("[telemetry] need METRICS_TOKEN or GITHUB_TOKEN")

    m = collect(args.user, token, args.history)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(render(m))
    if args.history:
        os.makedirs(os.path.dirname(args.history) or ".", exist_ok=True)
        with open(args.history, "w") as f:
            json.dump(m["history"], f, separators=(",", ":"), sort_keys=True)

    print(f"[telemetry] {m['repos_total']} repos · {m['clones_all']} clones tracked "
          f"({m['clones_14d']} in 14d) · {m['stars']} stars · {m['contributions']} contribs "
          f"· streak {m['streak_cur']}/{m['streak_max']} · {m['denied']} denied "
          f"-> {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
