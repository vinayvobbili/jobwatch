"""The cards around the screen recordings: the title card (also the closing card's base) and the animated problem
scene. 1920 x 1080, jobwatch's violet look; accent text takes slidecast's brand gradient."""

from __future__ import annotations

import html

from slidecast import Theme

THEME = Theme()

BASE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1920px; height: 1080px; overflow: hidden; color: #f4f3ff; position: relative;
  font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(1500px 900px at 85% -10%, #4b2bb8 0%, transparent 60%),
              radial-gradient(1200px 800px at -10% 110%, #1f3fb0 0%, transparent 55%), #0e0d1f; }
.logo { width: 150px; height: 150px; border-radius: 40px; background: linear-gradient(135deg, #6d5cff, #b05cf6);
  display: grid; place-items: center; box-shadow: 0 30px 80px rgba(109,92,255,.45); }
.logo::after { content: ""; width: 62px; height: 62px; border-radius: 50%; border: 12px solid #fff;
  box-shadow: 0 0 0 12px rgba(255,255,255,.35); }
"""


def _page(css: str, body: str) -> str:
    head = f'<!doctype html><html><head><meta charset="utf-8"><style>{BASE}{css}</style></head>'
    return f"{head}<body>{body}</body></html>"


def title_card(subtitle: str) -> str:
    """The opening card, shown silent for about 3 s, and again at the end under the tagline."""
    css = """
    .card { position: absolute; inset: 0 0 160px; display: flex; flex-direction: column; align-items: center;
      justify-content: center; text-align: center; }
    h1 { font-size: 128px; letter-spacing: -.03em; margin-top: 44px; line-height: 1; }
    p { font-size: 44px; margin-top: 30px; color: #cfcbe8; line-height: 1.35; max-width: 1400px; }
    """
    body = (f'<div class="card"><div class="logo"></div><h1>job{THEME.accent("watch")}</h1>'
            f"<p>{html.escape(subtitle)}</p></div>")
    return _page(css, body)


def problem_scene(lines: list[str], seconds: float, delays: list[float] | None = None) -> str:
    """The pain, before the payoff: each line drops in as a card, one after another, and the pile gets heavier.

    `delays` are when each line drops in (seconds), to match the narration; without them the lines fall at even
    gaps over `seconds`. Animated with CSS only (slidecast steps the animations frame by frame); the last frame
    holds for as long as the narration runs."""
    gap = max(0.9, (seconds - 1.5) / max(1, len(lines)))
    delays = delays or [0.4 + i * gap for i in range(len(lines))]
    cards = "".join(
        f'<div class="line" style="animation-delay:{delays[i]:.2f}s;--tilt:{(-1) ** i * (1 + i % 3) * .35:.2f}deg">'
        f"{html.escape(line)}</div>" for i, line in enumerate(lines))
    css = """
    .stack { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 26px; }
    .line { font-size: 54px; font-weight: 650; letter-spacing: -.01em; padding: 26px 56px; border-radius: 24px;
      background: rgba(255,255,255,.07); border: 1px solid rgba(185,168,255,.35); opacity: 0;
      transform: translateY(-60px) rotate(var(--tilt)); animation: drop .7s cubic-bezier(.2,.9,.3,1.2) forwards;
      box-shadow: 0 24px 60px rgba(0,0,0,.35); }
    @keyframes drop { to { opacity: 1; transform: translateY(0) rotate(var(--tilt)); } }
    """
    return _page(css, f'<div class="stack">{cards}</div>')
