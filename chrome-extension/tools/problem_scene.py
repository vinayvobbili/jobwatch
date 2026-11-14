"""The demo video's "problem" scene: animated HTML that shows why filling applications is a grind.

Four made-up application forms fan in and the same questions light up on all of them, a counter ticks from 1 to 40
applications, then a cursor types an essay, deletes it and starts over while a clock adds up to 20 hours. It is an
example, not a statistic. slidecast's Reel.add_animated steps the CSS animations frame by frame, so every animation
here is a keyframe track on one shared clock (TOTAL seconds): `track` turns (seconds, css) points into keyframes.
"""

from __future__ import annotations

import re

TAGLINE = "Your job hunt shouldn't be a full-time job."
TAGLINE_AT = 16.0  # when the tagline replaces the essay, as the voice says it
TOTAL = 19.0  # seconds the animation runs; the voice (about 18 s) finishes inside it, the last frame holds if not

# The four forms: made-up companies, with a platform label and an accent loosely like that kind of page.
FORMS = [
    ("Initech", "Greenhouse", "#24a47f"),
    ("Globex", "Lever", "#e8743b"),
    ("Umbrella", "Ashby", "#6d5cff"),
    ("Hooli", "Workday", "#2f7de1"),
]
# The same questions on every form, and when each is lit (seconds): the voice names the first three in turn.
QUESTIONS = [
    ("Are you authorized to work in the US?", 3.5, 5.3),
    ("Desired salary", 5.3, 6.9),
    ("Why do you want to work here?", 6.9, 8.4),
    ("Tell us about a project you're proud of", 8.4, 9.6),
]
FAN_ROT = [-5.0, -1.8, 1.8, 5.0]  # degrees, left to right
FAN_DROP = [18, 0, 0, 18]  # px lower at the ends, so the four make an arc
RECEDE = (9.5, 10.2)  # the forms step back and the essay editor comes forward
ESSAY = ["I built a tool that triages security alerts",
         "with a local model, cutting false alarms"]
# Typing: (seconds, characters shown) per line, revealed one character at a time. Both lines are typed, deleted
# (the second line first), and started over.
TYPE_RUNS = [
    [(0, 0), (10.4, 0), (11.3, 43), (12.9, 43), (13.5, 0), (14.0, 0), (14.9, 43)],
    [(0, 0), (11.4, 0), (12.1, 40), (12.4, 40), (12.9, 0), (15.0, 0), (15.6, 22)],
]
# When each line carries the caret (seconds): the line being typed or deleted.
CARET_ON = [[(10.4, 11.4), (12.9, 13.5), (14.0, 15.0)], [(11.4, 12.9), (15.0, 16.5)]]
CLOCK = (10.8, 14.8)  # the clock runs from 0 to 20 hours while the voice says "twenty hours"
COUNT = (0.4, 1.9)  # applications tick from 1 to 40 on "Forty applications"


def pct(seconds: float) -> str:
    return f"{seconds / TOTAL * 100:.3f}%"


def track(name: str, points: list) -> str:
    """A @keyframes rule from (seconds, css) points, on the scene's clock. Put `animation-timing-function` in a
    point's css to ease the stretch that starts there."""
    points = list(points)
    # A track holds its first and last values for the rest of the clock, rather than easing back to the page's own.
    if points[0][0] > 0:
        points.insert(0, (0, points[0][1]))
    if points[-1][0] < TOTAL:
        points.append((TOTAL, re.sub(r"animation-timing-function:[^;]*;?", "", points[-1][1])))
    body = "".join(f"{pct(t)} {{ {css} }}" for t, css in points)
    return f"@keyframes {name} {{ {body} }}"


def play(name: str, extra: str = "") -> str:
    return f"animation: {name} {TOTAL}s linear both; {extra}"


def typing_track(name: str, line: list) -> str:
    """Reveal a line in whole-character steps over the (seconds, characters) points."""
    points = []
    for (t, n), nxt in zip(line, [*line[1:], None], strict=True):
        steps = f"animation-timing-function: steps({max(1, abs(nxt[1] - n))}, end);" if nxt and nxt[1] != n else ""
        points.append((t, f"width: {n}ch; {steps}"))
    return track(name, points)


def counter_track(name: str, window: tuple, start: int, end: int, unit: str) -> str:
    """A number that counts from `start` to `end` over `window`, easing out: one `content` value per step."""
    first, last = window
    points = []
    for n in range(start, end + 1):
        share = (n - start) / (end - start)
        t = first + (last - first) * (1 - (1 - share) ** 2)  # ease-out: quick at first, then slowing
        points.append((t, f'content: "{n}{unit}"; animation-timing-function: step-end'))
    return track(name, points)


def form_card(i: int, company: str, platform: str, accent: str) -> str:
    rows = []
    for q, (text, _start, _end) in enumerate(QUESTIONS):
        rows.append(f'<div class="q q{q}"><label>{text}</label><i></i></div>')
    return (f'<div class="card c{i}" style="--accent:{accent}">'
            f'<header><b>{company}</b><span>{platform}</span></header>'
            f'<div class="who"><u></u><u></u></div>{"".join(rows)}</div>')


def scene_css() -> str:
    css = []
    # forms slide in, fanned, one after another
    for i, rot in enumerate(FAN_ROT):
        t = 0.5 + i * 0.25
        css.append(track(f"in{i}", [
            (0, "opacity: 0; transform: translate(0, 620px) rotate(0deg) scale(.9)"),
            (t, "opacity: 0; transform: translate(0, 620px) rotate(0deg) scale(.9); "
                "animation-timing-function: cubic-bezier(.2,.9,.25,1.05)"),
            (t + 0.9, f"opacity: 1; transform: translate(0, {FAN_DROP[i]}px) rotate({rot}deg) scale(1)"),
            (TOTAL, f"opacity: 1; transform: translate(0, {FAN_DROP[i]}px) rotate({rot}deg) scale(1)"),
        ]))
        css.append(f".c{i} {{ {play(f'in{i}')} }}")
    # the same question lights on every form together
    off = "background: transparent; box-shadow: none; transform: scale(1)"
    on = ("background: linear-gradient(90deg, rgb(109 92 255 / .34), rgb(192 74 240 / .30)); "
          "box-shadow: 0 0 0 2px rgb(185 168 255 / .85), 0 0 26px rgb(176 92 246 / .6); transform: scale(1.04)")
    for q, (_, start, end) in enumerate(QUESTIONS):
        css.append(track(f"hl{q}", [(0, off), (start - 0.05, off), (start + 0.25, on), (end - 0.2, on), (end, off)]))
        css.append(f".q{q} {{ {play(f'hl{q}')} }}")
    css.append(track("fan", [(0, "opacity: 1; filter: none; transform: none"),
                             (RECEDE[0], "opacity: 1; filter: none; transform: none; animation-timing-function: ease"),
                             (RECEDE[1], "opacity: .16; filter: blur(5px); transform: scale(.93)")]))
    css.append(f".fan {{ {play('fan')} }}")
    hidden = "opacity: 0; transform: translateY(8px)"
    css.append(track("pill", [(0, hidden), (3.2, hidden),
                              (3.6, "opacity: 1; transform: none"), (RECEDE[0], "opacity: 1; transform: none"),
                              (RECEDE[0] + 0.4, "opacity: 0")]))
    css.append(f".pill {{ {play('pill')} }}")
    # the two tiles: applications 1 -> 40, hours 0 -> 20
    css.append(track("tiles", [(0, "opacity: 0; transform: translateY(-16px)"),
                               (0.2, "opacity: 0; transform: translateY(-16px); animation-timing-function: ease-out"),
                               (0.8, "opacity: 1; transform: none")]))
    css.append(f".tile {{ {play('tiles')} }}")
    css.append(counter_track("apps", COUNT, 1, 40, ""))
    css.append(f".apps b::after {{ {play('apps')} }}")
    css.append(counter_track("hours", CLOCK, 0, 20, " hours"))
    css.append(f".hours b::after {{ {play('hours')} }}")
    css.append(track("hand", [(0, "transform: rotate(0deg)"),
                              (CLOCK[0], "transform: rotate(0deg); animation-timing-function: ease-in-out"),
                              (CLOCK[1], "transform: rotate(1800deg)")]))
    css.append(f".hand {{ {play('hand')} }}")
    # the essay: heading, editor, cursor, typing that is deleted and started over
    css.append(track("essay", [(0, "opacity: 0; transform: translateY(26px) scale(.96)"),
                               (RECEDE[0] + 0.1, "opacity: 0; transform: translateY(26px) scale(.96); "
                                                 "animation-timing-function: cubic-bezier(.2,.9,.25,1.05)"),
                               (RECEDE[1] + 0.3, "opacity: 1; transform: none"),
                               (TAGLINE_AT - 0.2, "opacity: 1; transform: none; animation-timing-function: ease-in"),
                               (TAGLINE_AT + 0.4, "opacity: 0; transform: translateY(-20px) scale(.97)")]))
    css.append(f".essay {{ {play('essay')} }}")
    css.append(track("tagline", [(0, "opacity: 0; transform: translateY(30px) scale(.95)"),
                                 (TAGLINE_AT + 0.2, "opacity: 0; transform: translateY(30px) scale(.95); "
                                                    "animation-timing-function: cubic-bezier(.2,.9,.25,1.05)"),
                                 (TAGLINE_AT + 0.9, "opacity: 1; transform: none")]))
    css.append(f".tagline {{ {play('tagline')} }}")
    for n, line in enumerate(TYPE_RUNS):
        css.append(typing_track(f"type{n}", line))
        points = [(0, "border-right-color: transparent")]
        for start, end in CARET_ON[n]:
            points += [(start, "border-right-color: #6d5cff"), (end, "border-right-color: transparent")]
        css.append(track(f"caret{n}", points))
        css.append(f".line{n} span {{ animation: type{n} {TOTAL}s linear both, caret{n} {TOTAL}s step-end both; }}")
    css.append(track("cursor", [
        (0, "opacity: 0; left: 1120px; top: 700px"),
        (RECEDE[0] + 0.2, "opacity: 0; left: 1120px; top: 700px; animation-timing-function: ease-in-out"),
        (RECEDE[0] + 0.5, "opacity: 1; left: 1120px; top: 700px; animation-timing-function: ease-in-out"),
        (10.3, "opacity: 1; left: 560px; top: 410px"),
        (10.4, "opacity: 1; left: 560px; top: 410px; transform: scale(.85)"),
        (10.5, "opacity: 1; left: 560px; top: 410px; transform: scale(1)"),
        (12.8, "opacity: 1; left: 560px; top: 410px; animation-timing-function: ease-in-out"),
        (13.2, "opacity: 1; left: 640px; top: 450px"),
        (TAGLINE_AT - 0.2, "opacity: 1; left: 640px; top: 450px"),
        (TAGLINE_AT + 0.2, "opacity: 0; left: 640px; top: 450px")]))
    css.append(f".cursor {{ {play('cursor')} }}")
    css.append(track("chip", [(0, "opacity: 0; transform: scale(.8)"), (10.8, "opacity: 0; transform: scale(.8)"),
                              (11.2, "opacity: 1; transform: none")]))
    css.append(f".chip {{ {play('chip')} }}")
    return "\n".join(css)


PROBLEM_CSS = """
  .apps b::after { content: "1"; }
  .hours b::after { content: "0 hours"; }
  body { display: block; position: relative; }
  .glow { top: 52%; width: 1000px; height: 560px; margin: -280px 0 0 -500px; opacity: .8; }
  .tiles { position: absolute; top: 22px; left: 0; right: 0; display: flex; justify-content: center; gap: 28px; }
  .tile { display: flex; align-items: center; gap: 18px; min-width: 330px; padding: 14px 26px; border-radius: 20px;
          background: linear-gradient(135deg, rgb(109 92 255 / .30), rgb(192 74 240 / .22));
          border: 1px solid rgb(185 168 255 / .4); box-shadow: 0 0 34px rgb(109 92 255 / .28); text-align: left; }
  .tile small { display: block; font-size: 15px; letter-spacing: .08em; text-transform: uppercase; color: #bdb6ea; }
  .tile b { display: block; font-size: 40px; font-weight: 800; line-height: 1.1; }
  .apps b { background: linear-gradient(90deg, #b9a8ff, #f08cff); -webkit-background-clip: text; color: transparent; }
  .hours b { background: linear-gradient(90deg, #ffd08a, #ff8f6b); -webkit-background-clip: text; color: transparent; }
  .apps i { font-style: normal; font-size: 26px; font-weight: 800; color: #b9a8ff; }
  .face { position: relative; flex: none; width: 52px; height: 52px; border-radius: 50%; border: 3px solid #ffd08a;
          box-shadow: 0 0 20px rgb(255 184 107 / .45); }
  .hand { position: absolute; left: 50%; top: 5px; width: 3px; height: 21px; margin-left: -1.5px; border-radius: 2px;
          background: #ffd08a; transform-origin: 50% 21px; }
  .pill { white-space: nowrap; padding: 8px 22px; border-radius: 999px; font-size: 20px; color: #fff; font-weight: 600;
          background: linear-gradient(90deg, #6d5cff, #c04af0); box-shadow: 0 0 26px rgb(176 92 246 / .55); }
  .pillwrap { position: absolute; left: 0; right: 0; top: 118px; display: flex; justify-content: center; z-index: 5; }
  .fan { position: absolute; left: 0; right: 0; top: 168px; height: 560px; }
  .card { position: absolute; top: 0; width: 284px; border-radius: 16px; background: #fbfbff; color: #20213a;
          text-align: left; box-shadow: 0 18px 44px rgb(0 0 0 / .5); overflow: hidden; padding-bottom: 14px; }
  .c0 { left: 48px; } .c1 { left: 348px; } .c2 { left: 648px; } .c3 { left: 948px; }
  .card header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px;
                 background: var(--accent); color: #fff; }
  .card header b { font-size: 20px; } .card header span { font-size: 12px; opacity: .92; letter-spacing: .04em;
                 background: rgb(255 255 255 / .22); padding: 3px 9px; border-radius: 999px; }
  .who { padding: 14px 16px 2px; } .who u { display: block; height: 14px; margin-bottom: 9px; border-radius: 7px;
         background: #e4e5f2; } .who u + u { width: 70%; }
  .q { margin: 3px 8px; padding: 9px 8px; border-radius: 10px; }
  .q label { display: block; font-size: 15px; font-weight: 650; line-height: 1.25; color: #26274a; min-height: 38px; }
  .q i { display: block; height: 26px; margin-top: 6px; border-radius: 8px; background: #e9eaf6;
         border: 1px solid #d5d7ea; }
  .q3 i { height: 50px; }
  .essay { position: absolute; left: 0; right: 0; top: 120px; display: flex; flex-direction: column;
           align-items: center; }
  .essay h2 { margin: 0 0 22px; font-size: 52px; font-weight: 800; letter-spacing: -0.02em; }
  .essay h2 b { background: linear-gradient(90deg, #b9a8ff, #f08cff); -webkit-background-clip: text;
                color: transparent; }
  .editor { width: 800px; border-radius: 18px; background: #fbfbff; color: #20213a; text-align: left;
            box-shadow: 0 0 60px rgb(176 92 246 / .45), 0 18px 44px rgb(0 0 0 / .5); overflow: hidden; }
  .editor header { padding: 14px 24px; background: linear-gradient(90deg, #6d5cff, #c04af0); color: #fff;
                   font-size: 20px; font-weight: 650; }
  .box { margin: 18px 22px 22px; padding: 16px 20px; height: 168px; border-radius: 12px; background: #fff;
         border: 2px solid #b9a8ff; font: 24px/1.55 ui-monospace, Menlo, monospace; color: #26274a; }
  .line { height: 37px; white-space: nowrap; }
  .line span { display: inline-block; overflow: hidden; vertical-align: top; width: 0; white-space: nowrap;
               border-right: 3px solid transparent; }
  .chip { margin-top: 20px; padding: 8px 20px; border-radius: 999px; font-size: 21px; color: #ffe2bd;
          background: rgb(255 140 100 / .16); border: 1px solid rgb(255 184 107 / .55); }
  .tagline { position: absolute; left: 120px; right: 120px; top: 270px; margin: 0; font-size: 76px; line-height: 1.15;
             font-weight: 800; letter-spacing: -0.02em; text-shadow: 0 0 40px rgb(176 92 246 / .6); }
  .tagline b { background: linear-gradient(90deg, #ffd08a, #ff8f6b); -webkit-background-clip: text;
               color: transparent; }
  .foot { position: absolute; left: 0; right: 0; bottom: 18px; font-size: 16px; color: #8f8bb8; }
  .cursor { position: absolute; z-index: 9; width: 30px; height: 30px; margin: 0; }
"""

CURSOR_SVG = ('<svg viewBox="0 0 24 24" width="30" height="30"><path d="M3 2l17 8-7 2-3 7z" fill="#fff" '
              'stroke="#20213a" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def problem_html(card_css: str, w: int, h: int) -> str:
    """The scene as one self-contained page; `card_css` is the video's card style (fonts, palette, glow)."""
    forms = "".join(form_card(i, *f) for i, f in enumerate(FORMS))
    lines = "".join(f'<div class="line line{n}"><span>{text}</span></div>' for n, text in enumerate(ESSAY))
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{card_css.format(w=w, h=h)}'
            f'{PROBLEM_CSS}\n{scene_css()}</style></head><body>'
            '<div class="glow"></div>'
            '<div class="tiles">'
            '<div class="tile apps"><div><small>Applications</small><b></b></div></div>'
            '<div class="tile clock hours"><div class="face"><div class="hand"></div></div>'
            '<div><small>Time spent</small><b></b></div></div></div>'
            '<div class="pillwrap"><div class="pill">The same questions, on every form</div></div>'
            f'<div class="fan">{forms}</div>'
            '<div class="essay"><h2>The <b>essays</b> take the longest.</h2>'
            '<div class="editor"><header>Tell us about a project you\'re proud of</header>'
            f'<div class="box">{lines}</div></div>'
            '<div class="chip">About half an hour for each one</div></div>'
            f'<div class="cursor">{CURSOR_SVG}</div>'
            "<h2 class=\"tagline\">Your job hunt shouldn't be a <b>full-time job</b>.</h2>"
            '<div class="foot">An example: 40 applications, about half an hour of retyping each.</div>'
            '</body></html>')


def main(argv=None) -> int:
    """Render the scene alone, silent, to check it: python problem_scene.py out.mp4"""
    import argparse
    from pathlib import Path

    import slidecast
    import store_assets

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args(argv)
    # The card style lives in demo_video, which imports this module, so it is read here, not at the top.
    import demo_video

    width, height = store_assets.SCREEN
    reel = slidecast.Reel(width=width, height=height, fps=args.fps)
    reel.add_animated(problem_html(demo_video.CARD_CSS, width, height), seconds=TOTAL)
    print(f"Wrote {reel.render(args.out, cache=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
