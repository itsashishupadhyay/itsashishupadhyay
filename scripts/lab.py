#!/usr/bin/env python3
"""THE LAB — self-hosted project cards.

Replaces the github-readme-stats pin cards (503-ing) with one SVG card per
project, generated from live repo metadata. Each card is a normal file in
assets/projects/, so the gallery can never be taken down by someone else's
Vercel quota.

Hero art, in priority order:
  1. a real photo at assets/projects/photos/<repo>.(jpg|jpeg|png|webp)
     — embedded as a data URI, because GitHub's image proxy will not resolve
     external or relative refs from inside an SVG
  2. otherwise a circuit motif deterministically derived from the repo name,
     so every project still looks intentional and no two look alike

Also emits the README table markup (--emit-markdown) so the gallery layout
stays in sync with whatever repos actually exist.
"""
import argparse
import base64
import hashlib
import json
import os
import random
import re
import sys
import urllib.request

API = "https://api.github.com"
GOLD, GOLD_HI, GOLD_LO = "#F5C518", "#F8DE7E", "#D9A514"
CYAN = "#00E5FF"
INK, GRAY = "#E8E2D2", "#98A0AB"
BG_A, BG_B = "#0a0e13", "#12161d"
MONO = "'Courier New',Courier,monospace"

CARD_W, CARD_H = 420, 232
HERO_H = 104
PHOTO_DIR = "assets/projects/photos"
EXT = (".jpg", ".jpeg", ".png", ".webp")

# Repos that are infrastructure rather than portfolio pieces.
SKIP = {"itsashishupadhyay", "ManojUpadhyaySite"}

# Fallback one-liners for repos whose GitHub description is empty. Kept
# deliberately factual (what it is, from name + language) — set a real
# description on the repo and it wins automatically.
FALLBACK = {
    "Space_Navigation": "Spacecraft navigation routines in C++",
    "object_detection_opencv_cpp": "Real-time object detection with OpenCV",
    "Meta_Smartglasses_Mission_control": "Companion control app for smart glasses, in Swift",
    "Hey_Ashish": "Source for heyashish.com",
    "encrypt_decrypt_AES": "AES encryption / decryption implemented from scratch",
    "ESP32-Wireless_Audio": "Wireless audio streaming on the ESP32",
    "Anagrams_Derived": "Anagram solver in C++",
}

LANG_TAG = {
    "C++": "C++", "C": "C", "Python": "PYTHON", "Swift": "SWIFT", "GAMS": "GAMS",
    "HTML": "WEB", "Ruby": "RUBY", "JavaScript": "JS", "CMake": "CMAKE",
}


def api(path, token):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "the-lab"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def wrap(text, width, lines):
    """Greedy wrap to `lines` lines, ellipsising the overflow."""
    words, out, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= width:
            cur = trial
        else:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if cur and len(out) < lines:
        out.append(cur)
    if not out:
        return [""]
    used = len(" ".join(out).split())
    if used < len(words):
        tail = out[-1]
        out[-1] = (tail[:width - 1].rstrip() + "…") if len(tail) > width - 1 else tail + " …"
    return out


def find_photo(repo, root):
    for ext in EXT:
        p = os.path.join(root, PHOTO_DIR, repo + ext)
        if os.path.exists(p):
            return p
    return None


def data_uri(path):
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}[
        path.rsplit(".", 1)[1].lower()]
    with open(path, "rb") as f:
        return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()


def motif(repo, seed_salt=""):
    """Deterministic circuit art — same repo always yields the same board."""
    h = hashlib.sha256((repo + seed_salt).encode()).hexdigest()
    rng = random.Random(int(h[:16], 16))
    parts = []
    y_rows = [26, 52, 78]
    for row, y in enumerate(y_rows):
        x = rng.randint(-20, 10)
        while x < CARD_W:
            seg = rng.choice(["trace", "res", "cap", "coil", "pad", "chip"])
            if seg == "trace":
                w = rng.randint(30, 70)
                parts.append(f'<path d="M{x},{y} h{w}"/>')
                x += w
            elif seg == "res":
                parts.append(f'<path d="M{x},{y} h8 l4,-7 l8,14 l8,-14 l8,14 l4,-7 h8"/>')
                x += 48
            elif seg == "cap":
                parts.append(f'<path d="M{x},{y} h12 m0,-8 v16 m6,-16 v16 m0,-8 h12"/>')
                x += 30
            elif seg == "coil":
                parts.append(
                    f'<path d="M{x},{y} h6 a5,5 0 1,1 10,0 a5,5 0 1,1 10,0 '
                    f'a5,5 0 1,1 10,0 h6"/>')
                x += 42
            elif seg == "pad":
                parts.append(f'<path d="M{x},{y} h10"/>')
                parts.append(f'<circle cx="{x + 16}" cy="{y}" r="4" fill="none"/>')
                x += 26
            else:
                w, hh = rng.randint(24, 38), 16
                parts.append(f'<path d="M{x},{y} h6"/>')
                parts.append(f'<rect x="{x + 6}" y="{y - hh // 2}" width="{w}" '
                             f'height="{hh}" rx="2" fill="none"/>')
                for k in range(3):
                    parts.append(f'<path d="M{x + 12 + k * 8},{y - hh // 2} v-4"/>')
                x += w + 12
    vias = "".join(
        f'<circle cx="{rng.randint(20, CARD_W - 20)}" cy="{rng.choice(y_rows)}" '
        f'r="2.2" fill="{CYAN}" fill-opacity=".55"/>' for _ in range(5))
    return (f'<g stroke="{GOLD}" stroke-opacity=".30" stroke-width="1.4" fill="none" '
            f'stroke-linecap="round">{"".join(parts)}</g>{vias}')


def card(repo, root):
    name = repo["name"]
    desc = repo.get("description") or FALLBACK.get(name) or "—"
    lang = repo.get("language") or "—"
    stars = repo.get("stargazerCount", repo.get("stargazers_count", 0))
    photo = find_photo(name, root)

    if photo:
        hero = (f'<image href="{data_uri(photo)}" x="0" y="0" width="{CARD_W}" '
                f'height="{HERO_H}" preserveAspectRatio="xMidYMid slice"/>'
                f'<rect width="{CARD_W}" height="{HERO_H}" fill="#0a0e13" fill-opacity=".28"/>')
    else:
        hero = motif(name)

    title = name if len(name) <= 30 else name[:29] + "…"
    body = wrap(desc, 46, 2)
    desc_svg = "".join(
        f'<text x="18" y="{HERO_H + 52 + i * 17}" font-family={MONO!r} font-size="11" '
        f'fill="{GRAY}">{esc(line)}</text>' for i, line in enumerate(body))

    tag = LANG_TAG.get(lang, lang.upper()[:8]) if lang != "—" else ""
    chips = []
    if tag:
        chips.append(f'<g><rect x="18" y="{CARD_H - 34}" width="{9 + len(tag) * 7}" '
                     f'height="20" rx="4" fill="{GOLD}" fill-opacity=".14"/>'
                     f'<text x="{22.5 + len(tag) * 3.5}" y="{CARD_H - 20}" '
                     f'text-anchor="middle" font-family={MONO!r} font-size="10" '
                     f'font-weight="700" fill="{GOLD}">{esc(tag)}</text></g>')
    star_svg = ""
    if stars:
        star_svg = (f'<text x="{CARD_W - 18}" y="{CARD_H - 20}" text-anchor="end" '
                    f'font-family={MONO!r} font-size="11" font-weight="700" '
                    f'fill="{CYAN}">★ {stars}</text>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}" height="{CARD_H}" viewBox="0 0 {CARD_W} {CARD_H}" role="img" aria-labelledby="t">
  <title id="t">{esc(name)} — {esc(desc)}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_A}"/><stop offset="1" stop-color="{BG_B}"/>
    </linearGradient>
    <clipPath id="hero"><rect width="{CARD_W}" height="{HERO_H}"/></clipPath>
  </defs>
  <rect width="{CARD_W}" height="{CARD_H}" rx="10" fill="url(#bg)"/>
  <g clip-path="url(#hero)">{hero}</g>
  <line x1="0" y1="{HERO_H}" x2="{CARD_W}" y2="{HERO_H}" stroke="{GOLD}" stroke-opacity=".35"/>
  <text x="18" y="{HERO_H + 30}" font-family={MONO!r} font-size="14.5" font-weight="700"
        fill="{GOLD}" letter-spacing="0.5">{esc(title)}</text>
  {desc_svg}{"".join(chips)}{star_svg}
  <rect x="0.5" y="0.5" width="{CARD_W - 1}" height="{CARD_H - 1}" rx="10" fill="none"
        stroke="{GOLD}" stroke-opacity=".28"/>
</svg>
"""


def markdown(repos, owner, cols=2):
    """README table markup — clickable cards, two per row."""
    out = ["<table>"]
    for i in range(0, len(repos), cols):
        out.append("<tr>")
        for r in repos[i:i + cols]:
            n = r["name"]
            out.append(
                f'<td width="50%" align="center">'
                f'<a href="https://github.com/{owner}/{n}">'
                f'<img src="assets/projects/{n}.svg" width="100%" alt="{esc(n)}"/>'
                f'</a></td>')
        if len(repos[i:i + cols]) < cols:
            out.append('<td width="50%"></td>')
        out.append("</tr>")
    out.append("</table>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="itsashishupadhyay")
    ap.add_argument("--root", default=".")
    ap.add_argument("--emit-markdown", action="store_true")
    args = ap.parse_args()

    token = (os.environ.get("METRICS_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        sys.exit("[lab] need METRICS_TOKEN or GITHUB_TOKEN")

    repos = [r for r in api("/user/repos?per_page=100&affiliation=owner", token)
             if not r["fork"] and not r["private"] and r["name"] not in SKIP]
    repos.sort(key=lambda r: (-r["stargazers_count"], r["updated_at"]), reverse=False)
    repos.sort(key=lambda r: -r["stargazers_count"])

    outdir = os.path.join(args.root, "assets/projects")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(os.path.join(args.root, PHOTO_DIR), exist_ok=True)

    withphoto = 0
    for r in repos:
        svg = card(r, args.root)
        with open(os.path.join(outdir, r["name"] + ".svg"), "w") as f:
            f.write(svg)
        if find_photo(r["name"], args.root):
            withphoto += 1

    if args.emit_markdown:
        featured, rest = repos[:6], repos[6:]
        md = [markdown(featured, args.user)]
        if rest:
            md += [
                "",
                "<details>",
                f"<summary><b>🔍 Expand the full bench — {len(rest)} more projects</b></summary>",
                "<br/>",
                "",
                markdown(rest, args.user),
                "",
                "Full interactive gallery lives at **[heyashish.com](https://heyashish.com)** — "
                "including the button that changes the lights in my actual room. Yes, really.",
                "",
                "</details>",
            ]
        with open(os.path.join(args.root, "assets/projects/_table.md"), "w") as f:
            f.write("\n".join(md) + "\n")

    missing = [r["name"] for r in repos
               if not r.get("description") and r["name"] not in FALLBACK]
    print(f"[lab] {len(repos)} cards -> {outdir} · {withphoto} with photos · "
          f"{len(repos) - withphoto} using generated motifs")
    if missing:
        print(f"[lab] no description and no fallback: {', '.join(missing)}")


if __name__ == "__main__":
    main()
