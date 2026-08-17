#!/usr/bin/env python3
"""Build the interactive Game of Life page.

The README can only ever show a picture — GitHub serves README images through
its own proxy, so no click inside one reaches anything. Real controls need a
real page, so this bakes the contribution grid into a self-contained HTML file
with START / PAUSE / RESTART buttons and a speed control.

Rules, cosmic-ray revivals, milestone messages and endings all mirror
game_of_life.py so the two tell the same story.
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_of_life as gol  # noqa: E402

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Conway Twitty's Game of Life</title>
<meta name="description" content="Every green square on my GitHub contribution graph is a living cell. Press start."/>
<style>
  :root {
    --gold:#F5C518; --gold-hi:#F8DE7E; --cyan:#00E5FF;
    --ink:#E8E2D2; --gray:#98A0AB; --bg-a:#0a0e13; --bg-b:#12161d;
    --mono:'Courier New',Courier,monospace;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; padding:28px 16px 56px; background:var(--bg-a); color:var(--ink);
    font-family:var(--mono);
    background-image:linear-gradient(180deg,var(--bg-a),var(--bg-b));
    min-height:100vh;
  }
  .wrap { max-width:1200px; margin:0 auto; border:1px solid rgba(245,197,24,.22);
          border-radius:12px; padding:22px 24px 26px; background:rgba(0,0,0,.25); }
  h1 { font-size:21px; letter-spacing:2px; color:var(--gold); margin:0 0 4px; }
  .sub { font-size:11px; color:var(--gray); letter-spacing:1px; margin-bottom:18px; }
  .badge { display:inline-block; border:1px solid rgba(0,229,255,.5); color:var(--cyan);
           border-radius:4px; padding:2px 10px; font-size:11px; margin-left:10px;
           vertical-align:middle; letter-spacing:1px; }
  .board { width:100%; height:auto; display:block; margin:6px 0 4px; }
  .readout { display:flex; flex-wrap:wrap; gap:22px; align-items:baseline;
             font-size:13px; margin:12px 2px 16px; }
  .readout b { color:var(--gold); font-size:19px; letter-spacing:1px; }
  .readout span { color:var(--gray); font-size:10.5px; letter-spacing:1px; }
  .controls { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
  button {
    font-family:var(--mono); font-size:14px; font-weight:700; letter-spacing:1.5px;
    color:var(--gold); background:rgba(245,197,24,.12);
    border:1.5px solid var(--gold); border-radius:8px; padding:11px 22px;
    cursor:pointer; transition:background .15s,color .15s,transform .05s;
  }
  button:hover:not(:disabled) { background:rgba(245,197,24,.26); }
  button:active:not(:disabled) { transform:translateY(1px); }
  button:disabled { opacity:.34; cursor:not-allowed; }
  button.primary { background:var(--gold); color:#0d1117; }
  button.primary:hover:not(:disabled) { background:var(--gold-hi); }
  button:focus-visible { outline:2px solid var(--cyan); outline-offset:3px; }
  label { font-size:11px; color:var(--gray); letter-spacing:1px;
          display:flex; align-items:center; gap:9px; margin-left:6px; }
  input[type=range] { accent-color:var(--gold); width:132px; }
  .msg { min-height:44px; margin:18px 2px 0; font-size:13.5px; line-height:1.5;
         color:var(--gold); }
  .msg.end { color:var(--cyan); font-weight:700; }
  .rules { margin-top:22px; padding-top:16px; border-top:1px solid rgba(245,197,24,.15);
           font-size:10.5px; color:rgba(232,226,210,.55); line-height:1.85; }
  a { color:var(--cyan); }
  @media (max-width:640px){ .readout{gap:14px} button{padding:10px 15px;font-size:12.5px} }
</style>
</head>
<body>
<div class="wrap">
  <h1>CONWAY TWITTY'S GAME OF LIFE <span class="badge">B3/S23</span></h1>
  <div class="sub">EVERY GREEN SQUARE ON MY CONTRIBUTION GRAPH IS A LIVING CELL · TORUS TOPOLOGY · MAX __MAXGEN__ GENERATIONS</div>

  <svg class="board" viewBox="0 0 __W__ __BH__" role="img" aria-label="Game of Life board">
    <rect width="__W__" height="__BH__" fill="#0d1117" rx="8"/>
    <g id="grid"></g>
    <g id="cells"></g>
  </svg>

  <div class="readout">
    <div><b id="gen">0</b> <span>GENERATION</span></div>
    <div><b id="pop">0</b> <span>LIVE CELLS</span></div>
    <div><b id="peak">0</b> <span>PEAK</span></div>
    <div><b id="seu">0</b> <span>COSMIC RAYS</span></div>
  </div>

  <div class="controls">
    <button id="run" class="primary">▶ START</button>
    <button id="restart" disabled>↻ RESTART</button>
    <button id="step" >⏭ STEP</button>
    <label>SPEED <input id="speed" type="range" min="1" max="60" value="18"/></label>
  </div>

  <div class="msg" id="msg" role="status" aria-live="polite">Press start. The board stays exactly as my contribution graph until you do.</div>

  <div class="rules">
    __RULES__
  </div>
</div>

<script>
const SEED = __SEED__, MONTHS = __MONTHS__;
const COLS = __COLS__, ROWS = __ROWS__, CELL = __CELL__, PITCH = __PITCH__;
const OX = __OX__, OY = __OY__, MAXGEN = __MAXGEN__, SEU_BUDGET = __SEU__;
const GREENS = __GREENS__, GOLD = "#F5C518", CYAN = "#00E5FF";
const MILESTONES = __MILESTONES__, WILDCARDS = __WILDCARDS__;
const EXTINCT = __EXTINCT__, STEADY = __STEADY__, CHAOTIC = __CHAOTIC__;
const PATTERNS = __PATTERNS__;

const N = COLS * ROWS;
const idx = (w, d) => w * ROWS + d;
const nbrs = [];
for (let w = 0; w < COLS; w++) for (let d = 0; d < ROWS; d++) {
  const list = [];
  for (const dw of [-1, 0, 1]) for (const dd of [-1, 0, 1]) {
    if (!dw && !dd) continue;
    list.push(idx((w + dw + COLS) % COLS, (d + dd + ROWS) % ROWS));
  }
  nbrs[idx(w, d)] = list;
}

const gridEl = document.getElementById('grid');
const cellsEl = document.getElementById('cells');
const rects = [];
let frag = '';
for (let w = 0; w < COLS; w++) for (let d = 0; d < ROWS; d++) {
  frag += `<rect x="${OX + w * PITCH}" y="${OY + d * PITCH}" width="${CELL}" height="${CELL}" rx="3" fill="none" stroke="${GOLD}" stroke-opacity=".10" stroke-width=".6"/>`;
}
gridEl.innerHTML = frag;
frag = '';
for (let w = 0; w < COLS; w++) for (let d = 0; d < ROWS; d++) {
  frag += `<rect id="c${idx(w,d)}" x="${OX + w * PITCH}" y="${OY + d * PITCH}" width="${CELL}" height="${CELL}" rx="3" fill="${GOLD}" fill-opacity="0"/>`;
}
cellsEl.innerHTML = frag;
for (let i = 0; i < N; i++) rects[i] = document.getElementById('c' + i);

// quartile thresholds so gen 0 matches GitHub's own heat levels
const counts = SEED.filter(v => v > 0).sort((a, b) => a - b);
const th = [.25, .5, .75].map(p => counts[Math.min(counts.length - 1, Math.floor(p * counts.length))] || 1);
const heat = v => GREENS[th.reduce((n, t) => n + (v > t ? 1 : 0), 0)];

let state, gen, peak, seuUsed, timer = null, seen, ended, greens = [];
for (let i = 0; i < N; i++) if (SEED[i] > 0) greens.push(i);

function paintSeed() {
  for (let i = 0; i < N; i++) {
    rects[i].setAttribute('fill', SEED[i] > 0 ? heat(SEED[i]) : GOLD);
    rects[i].setAttribute('fill-opacity', SEED[i] > 0 ? '1' : '0');
  }
}
function paint() {
  for (let i = 0; i < N; i++) {
    rects[i].setAttribute('fill', GOLD);
    rects[i].setAttribute('fill-opacity', state[i] ? '1' : '0');
  }
}
function pop() { let n = 0; for (let i = 0; i < N; i++) n += state[i]; return n; }
function key() { return state.join(''); }

function reset(showSeed) {
  stop();
  state = new Uint8Array(N);
  for (const i of greens) state[i] = 1;
  gen = 0; peak = pop(); seuUsed = 0; seen = new Map(); ended = false;
  seen.set(key(), 0);
  if (showSeed) paintSeed(); else paint();
  document.getElementById('gen').textContent = '0';
  document.getElementById('pop').textContent = peak;
  document.getElementById('peak').textContent = peak;
  document.getElementById('seu').textContent = '0';
  setMsg('Press start. The board stays exactly as my contribution graph until you do.', false);
  document.getElementById('run').textContent = '▶ START';
  document.getElementById('run').disabled = false;
  document.getElementById('step').disabled = false;
}

function setMsg(t, isEnd) {
  const el = document.getElementById('msg');
  el.textContent = t;
  el.className = 'msg' + (isEnd ? ' end' : '');
}
const pick = a => a[Math.floor(Math.random() * a.length)];

function inject() {
  const anchor = greens[Math.floor(Math.random() * greens.length)];
  const names = Object.keys(PATTERNS);
  const name = names[Math.floor(Math.random() * names.length)];
  const w0 = Math.floor(anchor / ROWS), d0 = anchor % ROWS;
  for (const [dw, dd] of PATTERNS[name])
    state[idx((w0 + dw) % COLS, (d0 + dd) % ROWS)] = 1;
  seuUsed++;
  document.getElementById('seu').textContent = seuUsed;
  const wk = String(w0).padStart(2, '0');
  setMsg(`⚡ SINGLE-EVENT UPSET at week ${wk} — ${name} injected. The colony lives again.`, false);
  seen = new Map(); seen.set(key(), gen);
}

function finish(text) {
  ended = true; stop();
  setMsg(text, true);
  document.getElementById('run').disabled = true;
  document.getElementById('step').disabled = true;
  document.getElementById('run').textContent = '▶ START';
}

function tick() {
  if (ended) return;
  const next = new Uint8Array(N);
  for (let i = 0; i < N; i++) {
    let n = 0; const list = nbrs[i];
    for (let k = 0; k < 8; k++) n += state[list[k]];
    next[i] = (n === 3 || (n === 2 && state[i])) ? 1 : 0;
  }
  state = next; gen++;
  const p = pop();
  if (p > peak) { peak = p; document.getElementById('peak').textContent = peak; }
  document.getElementById('gen').textContent = gen;
  document.getElementById('pop').textContent = p;
  paint();

  for (const m of [200, 150, 100, 50]) {
    if (gen === m) {
      const pool = MILESTONES[m].concat(m >= 100 ? WILDCARDS : []);
      setMsg(`GEN ${m} · ${pick(pool)}`, false);
      break;
    }
  }

  const k = key();
  const stalled = p === 0 ? 'extinct' : (seen.has(k) ? 'steady' : null);
  if (stalled) {
    if (seuUsed < SEU_BUDGET) { inject(); paint(); return; }
    if (stalled === 'extinct') finish(EXTINCT[Math.floor(Math.random() * EXTINCT.length)].replace('{x}', gen));
    else finish(STEADY[0].replace('{x}', seen.get(k)));
    return;
  }
  seen.set(k, gen);
  if (gen >= MAXGEN) finish(CHAOTIC.replace('{x}', gen));
}

function speedMs() { return Math.round(1000 / +document.getElementById('speed').value); }
function start() {
  if (ended || timer) return;
  paint();
  timer = setInterval(tick, speedMs());
  document.getElementById('run').textContent = '⏸ PAUSE';
  document.getElementById('restart').disabled = false;
}
function stop() {
  if (timer) { clearInterval(timer); timer = null; }
  const b = document.getElementById('run');
  if (!ended) b.textContent = gen ? '▶ RESUME' : '▶ START';
}

document.getElementById('run').onclick = () => { timer ? stop() : start(); };
document.getElementById('restart').onclick = () => {
  reset(true);
  document.getElementById('restart').disabled = true;
};
document.getElementById('step').onclick = () => { stop(); if (!gen) paint(); tick(); document.getElementById('restart').disabled = false; };
document.getElementById('speed').oninput = () => { if (timer) { clearInterval(timer); timer = setInterval(tick, speedMs()); } };
document.addEventListener('keydown', e => {
  if (e.code === 'Space') { e.preventDefault(); timer ? stop() : start(); }
  if (e.key === 'r' || e.key === 'R') document.getElementById('restart').click();
});

reset(true);
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="itsashishupadhyay")
    ap.add_argument("--out", default="docs/index.html")
    args = ap.parse_args()

    rng = random.Random()
    cal = gol.fetch_calendar(args.user) or gol.synthetic_calendar(rng)
    grid, months = cal

    seed = [grid[w][d] for w in range(gol.COLS) for d in range(gol.ROWS)]
    board_h = gol.ROWS * gol.PITCH - (gol.PITCH - gol.CELL) + 24

    rules = "<br/>".join(gol.esc(r) for r in gol.RULES)
    subs = {
        "__SEED__": json.dumps(seed),
        "__MONTHS__": json.dumps(months),
        "__COLS__": str(gol.COLS), "__ROWS__": str(gol.ROWS),
        "__CELL__": str(gol.CELL), "__PITCH__": str(gol.PITCH),
        "__OX__": "12", "__OY__": "12",
        "__W__": str(gol.COLS * gol.PITCH - (gol.PITCH - gol.CELL) + 24),
        "__BH__": str(board_h),
        "__MAXGEN__": str(gol.MAX_GEN), "__SEU__": str(gol.SEU_BUDGET),
        "__GREENS__": json.dumps(gol.GH_GREENS),
        "__MILESTONES__": json.dumps({str(k): v for k, v in gol.MILESTONE_POOLS.items()}),
        "__WILDCARDS__": json.dumps(gol.WILDCARDS),
        "__EXTINCT__": json.dumps(gol.EXTINCT),
        "__STEADY__": json.dumps(gol.STEADY),
        "__CHAOTIC__": json.dumps(gol.CHAOTIC),
        "__PATTERNS__": json.dumps(gol.PATTERNS),
        "__RULES__": rules,
    }
    html = PAGE
    for k, v in subs.items():
        html = html.replace(k, v)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"[life-page] {sum(1 for v in seed if v > 0)} live cells · max {gol.MAX_GEN} gens "
          f"-> {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
