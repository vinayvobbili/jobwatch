"""The README's demo video: its slides and narration. Writes slides/*.html (screenshots inlined) and reel.yaml
into the demo's output folder; then slidecast (https://pypi.org/project/slidecast/) renders the video:

    python scripts/demo/build.py scripts/demo/out [--music DIR]
    slidecast render scripts/demo/out/reel.yaml -o scripts/demo/out/jobwatch-demo.mp4 --poster

The folder holds the seeded demo (demo/, from seed.py) and its screenshots (shots/, from
`scripts/screenshots.py --demo`): made-up companies (Acme, Globex, Initech, Umbrella, Hooli), made-up jobs, a
made-up resume. The music bed and stings (music_bed.wav, intro_sting.wav, outro_sting.wav) are read from
--music, else from the folder itself; without them the video has the voice only.
"""

from __future__ import annotations

import argparse
import base64
import html
import re
from pathlib import Path

import yaml

from jobwatch import config, report
from jobwatch.store import Store
from jobwatch.watch import build_digest

OUT = Path(__file__).resolve().parent / "out"

CSS = """
html { zoom: 1.5; }  /* designed at 1280x720, rendered at 1920x1080 */
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1280px; height: 720px; overflow: hidden; color: #f4f3ff;
  font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(1200px 700px at 85% -10%, #4b2bb8 0%, transparent 60%),
              radial-gradient(900px 600px at -10% 110%, #1f3fb0 0%, transparent 55%), #0e0d1f; }
.brand { position: absolute; top: 26px; right: 40px; display: flex; align-items: center; gap: 10px;
  font-weight: 700; font-size: 20px; letter-spacing: -.01em; opacity: .9; }
.logo { width: 28px; height: 28px; border-radius: 8px; background: linear-gradient(135deg, #6d5cff, #b05cf6);
  display: grid; place-items: center; }
.logo::after { content: ""; width: 12px; height: 12px; border-radius: 50%; border: 3px solid #fff;
  box-shadow: 0 0 0 3px rgba(255,255,255,.35); }
.brand b { color: #b9a8ff; }
header { position: absolute; top: 24px; left: 40px; right: 220px; }
.step { display: inline-flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; color: #b9a8ff; }
.step i { font-style: normal; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: #6d5cff; color: #fff; letter-spacing: 0; font-size: 14px; }
h1 { font-size: 38px; line-height: 1.1; letter-spacing: -.02em; margin-top: 8px; }
.sub { font-size: 19px; color: #cfcbe8; margin-top: 8px; }
.frame { position: absolute; left: 40px; right: 40px; top: 160px; bottom: 28px; border-radius: 14px;
  overflow: hidden; background: #fff; box-shadow: 0 24px 60px rgba(0,0,0,.45), 0 0 0 1px rgba(255,255,255,.12); }
.bar { height: 30px; background: #ecebf3; display: flex; align-items: center; gap: 7px; padding: 0 12px; }
.bar span { width: 11px; height: 11px; border-radius: 50%; background: #ff5f57; }
.bar span:nth-child(2) { background: #febc2e; } .bar span:nth-child(3) { background: #28c840; }
.bar em { margin-left: 14px; font-style: normal; font-size: 12px; color: #6b6880; background: #fff;
  border-radius: 6px; padding: 3px 12px; }
.shot { position: absolute; top: 30px; left: 0; right: 0; bottom: 0; background-repeat: no-repeat; }
.term { position: absolute; top: 30px; left: 0; right: 0; bottom: 0; background: #14131f; color: #e6e4f5;
  font: 15.5px/1.5 "SF Mono", Menlo, monospace; padding: 18px 26px; white-space: pre-wrap; }
.term .p { color: #7ee2a8; } .term .h { color: #fff; font-weight: 700; } .term .c { color: #8f8ba8; }
.term .f { color: #ffd479; } .term .k { color: #b9a8ff; } .term .u { color: #8fc7ff; }
.note { position: absolute; bottom: 36px; right: 56px; font-size: 12px; color: #8f8ba8; }
.center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; padding: 0 120px; }
.center h1 { font-size: 64px; }
.center .sub { font-size: 24px; margin-top: 18px; max-width: 900px; line-height: 1.4; }
.chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 34px; }
.chips span { border: 1px solid rgba(185,168,255,.45); color: #dcd5ff; border-radius: 999px; padding: 7px 16px;
  font-size: 16px; background: rgba(109,92,255,.12); }
.big { width: 96px; height: 96px; border-radius: 26px; margin-bottom: 28px; }
.big::after { width: 40px; height: 40px; border-width: 8px; box-shadow: 0 0 0 8px rgba(255,255,255,.35); }
.cmd { margin-top: 34px; font: 22px "SF Mono", Menlo, monospace; background: rgba(0,0,0,.35);
  border: 1px solid rgba(255,255,255,.15); border-radius: 12px; padding: 14px 26px; color: #7ee2a8; }
"""

BRAND = '<div class="brand"><div class="logo"></div><span>job<b>watch</b></span></div>'


def page(body: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'


def data_uri(image: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()


def head(n: int, label: str, title: str, sub: str) -> str:
    return (f'<header><div class="step"><i>{n}</i>{label}</div><h1>{title}</h1>'
            f'<div class="sub">{sub}</div></header>{BRAND}')


def shot_slide(n, label, title, sub, image, *, width=1200, x=0, y=0, url="127.0.0.1 · jobwatch ui"):
    """A screenshot (2560 px wide, the page at 1280 css px) shown `width` px wide, from (x, y) in shown px."""
    frame = (f'<div class="frame"><div class="bar"><span></span><span></span><span></span><em>{url}</em></div>'
             f'<div class="shot" style="background-image:url({data_uri(image)});background-size:{width}px auto;'
             f'background-position:{-x}px {-y}px"></div></div>')
    return page(head(n, label, title, sub) + frame)


def dual_slide(n, label, title, sub, left, right, *, ly=0, ry=0):
    """Two screenshots of the same dialog side by side: its 780 css px column shown 590 px wide."""
    def half(image, y, pos):
        return (f'<div class="frame" style="{pos}:40px;width:590px;left:auto;right:auto;{pos}:40px">'
                f'<div class="bar"><span></span><span></span><span></span><em>127.0.0.1 · jobwatch ui</em></div>'
                f'<div class="shot" style="background-image:url({data_uri(image)});background-size:968px auto;'
                f'background-position:-189px {-y}px"></div></div>')
    return page(head(n, label, title, sub) + half(left, ly, "left") + half(right, ry, "right"))


def term_slide(n, label, title, sub, text, note="", size=15.5):
    frame = (f'<div class="frame"><div class="bar"><span></span><span></span><span></span><em>Terminal</em></div>'
             f'<div class="term" style="font-size:{size}px">{text}</div></div>')
    return page(head(n, label, title, sub) + frame + (f'<div class="note">{note}</div>' if note else ""))


def digest_markdown(watchlist: Path) -> str:
    """The demo's digest, as `jobwatch digest --all --peek` prints it."""
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    try:
        return report.to_markdown(build_digest(cfg, store, include_seen=True, score_top=0))
    finally:
        store.close()


def digest_text(md: str) -> str:
    """The digest as the terminal shows it after `jobwatch run`."""
    out = ['<span class="p">$</span> jobwatch run',
           '<span class="c">Checked 5 board(s): 12 open roles, 6 new.</span>', ""]
    for line in md.strip().splitlines():
        line = html.escape(line)
        line = re.sub(r"\[(.+?)\]\((.+?)\)", r'<span class="h">\1</span> <span class="u">\2</span>', line)
        line = re.sub(r"\*\*(.+?)\*\*", r'<span class="f">\1</span>', line)
        line = re.sub(r"`(.+?)`", r'<span class="k">\1</span>', line)
        if line.startswith("#"):
            line = f'<span class="h">{line}</span>'
        out.append(line)
    return "\n".join(out)


MCP = """<span class="p">$</span> claude mcp add jobwatch -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp

<span class="h">&gt; What's new today? Queue the best fit, and prep me for Thursday's panel.</span>

<span class="k">●</span> jobwatch · <span class="f">digest</span>
  <span class="c">6 matching jobs. Best fit: Staff AI Engineer at Acme, 86/100, must-haves 6/7</span>
<span class="k">●</span> jobwatch · <span class="f">mark_job</span>  greenhouse:acme:4101 → queued
<span class="k">●</span> jobwatch · <span class="f">interview_prep</span>  ashby:initech:c0
  <span class="c">AI Engineer, LLM Apps at Initech · interviewing · next: panel interview</span>

Queued Acme's Staff AI Engineer: it's your best fit today. For Initech's panel,
lead with the LLM features you shipped to production; the gap to be ready
for is Kubernetes in production. Tailor your resume and submit when ready.
"""


def slides(shots: Path, digest: str) -> list[tuple[str, str, str]]:
    """(file name, html, narration) for each slide, in order: `shots` holds the screenshots, `digest` is the
    digest's markdown."""
    hidden_brand = BRAND.replace('class="brand"', 'class="brand" style="display:none"')
    return [
        ("01-title",
         page(hidden_brand + '<div class="center"><div class="logo big"></div><h1>jobwatch</h1>'
              '<div class="sub">New roles at the companies you watch, ranked for you.</div>'
              '<div class="chips"><span>Greenhouse</span><span>Lever</span><span>Ashby</span>'
              '<span>Workable</span><span>Workday</span><span>Eightfold</span><span>Jibe</span>'
              '<span>Rippling</span></div></div>'),
         "jobwatch watches the job boards of the companies you care about, and tells you what's new."),
        ("02-watch",
         shot_slide(1, "Watch the boards", "Pick the companies you care about",
                    "Their public Greenhouse, Lever, Ashby, Workable and Workday boards. No scraping.",
                    shots / "settings.png", y=190),
         "Add companies by name, or paste a link to one of their jobs. It reads their public Greenhouse, Lever, "
         "Ashby, Workable and Workday boards. No scraping, and no API keys."),
        ("03-digest",
         term_slide(2, "Digest", "A short digest of what's new",
                    "Only new roles that match your titles, locations and pay.", digest_text(digest)),
         "Each run gives you a short digest of new roles that match your titles, locations and pay."),
        ("04-fit",
         shot_slide(3, "Fit scores", "Ranked by how well you fit",
                    "Must-haves you meet, and the gaps, judged against your resume.", shots / "today.png", y=150),
         "Add your resume, and every match gets a fit score: the must-haves you meet, and the gaps you don't."),
        ("04b-chat",
         shot_slide(4, "Ask jobwatch", "Ask about your jobs",
                    "Answers from your own jobs, fit scores and applications. Claude, or a model on your Mac.",
                    shots / "chat.png", y=20),
         "Ask jobwatch about your jobs and applications. It answers from your own data, with Claude, or a model "
         "running on your computer."),
        ("05-queue",
         shot_slide(5, "Apply queue", "Queue the ones worth applying to",
                    "Your short list. Apply on their site, then press “I applied”.", shots / "queue.png", y=150),
         "Queue the roles worth a tailored application. Once you've applied, press I applied."),
        ("06-track",
         shot_slide(5, "Application tracking", "Every application, and what's next",
                    "Applied, screening, interviewing, offer. Follow-ups due come first.",
                    shots / "applied.png", y=140),
         "Then track each one through screening, interviews and offers, with next steps and follow-up days."),
        ("07-prep",
         dual_slide(6, "Interview prep", "A prep sheet before every call",
                    "Their asks next to your closest resume line, gaps to be honest about, questions to expect.",
                    shots / "prep.png", shots / "prep-questions.png", ly=80, ry=72),
         "Before a call, the prep sheet lines up each ask in the posting with your closest resume line, "
         "and the questions to expect."),
        ("07b-skills",
         shot_slide(7, "Skills to build", "Close the gaps",
                    "What your matching jobs ask for that your resume doesn't, and where to learn it.",
                    shots / "skills.png", y=70),
         "The Skills tab shows what your matching jobs ask for that your resume doesn't, with courses and "
         "certifications to close each gap."),
        ("08-mcp",
         term_slide(8, "MCP server", "Use it from Claude",
                    "digest, apply_queue, mark_job, applications, interview_prep and more, as MCP tools.", MCP,
                    note="Illustration with the demo data", size=18),
         "It's also an MCP server, so Claude can read your digest, queue jobs, and prep with you."),
        ("09-never",
         page(hidden_brand + '<div class="center"><div class="step"><i>9</i>Never auto-applies</div>'
              '<h1 style="margin-top:18px">You press Submit.</h1>'
              '<div class="sub">jobwatch finds and ranks. You review and send every application '
              'yourself.</div><div class="cmd">pip install jobwatch</div></div>'),
         "And jobwatch never applies for you. You review, and submit, every application yourself."),
    ]


# The music bed and stings (`slidecast compose -o DIR` makes them), and how loud each plays.
AUDIO = {"music": ("music_bed.wav", {"volume": 0.3, "fade_in": 1.0, "fade_out": 3.0, "duck": True, "duck_db": 16}),
         "intro": ("intro_sting.wav", {"volume": 0.75}),
         "outro": ("outro_sting.wav", {"volume": 0.7})}


def build(out: Path, music: Path | None = None) -> dict:
    """Write slides/*.html and reel.yaml into `out`, which holds the seeded demo (demo/) and its screenshots
    (shots/). The music bed and stings come from `music`, else from `out`; without them the reel has the voice
    only. Returns the reel's spec."""
    out = out.expanduser().resolve()
    (out / "slides").mkdir(exist_ok=True)
    entries = []
    for name, body, narration in slides(out / "shots", digest_markdown(out / "demo" / "jobwatch.yaml")):
        (out / "slides" / f"{name}.html").write_text(body, encoding="utf-8")
        entries.append({"html_file": f"slides/{name}.html", "narration": narration, "tail_pad": 1.3})
    entries[0]["tail_pad"] = 1.0
    entries[-1]["tail_pad"] = 1.6
    spec = {"width": 1920, "height": 1080, "fps": 25,
            "tts": {"provider": "mlx", "voice": "af_heart",  # Kokoro in-process: pip install 'slidecast[mlx]'
                    "phonetic": {r"\bjobwatch\b": "job watch", r"\bMCP\b": "M C P", r"\bAPI\b": "A P I"}}}
    where = (music or out).expanduser().resolve()
    missing = [name for name, _ in AUDIO.values() if not (where / name).is_file()]
    if music and missing:
        raise SystemExit(f"{where} has no {', '.join(missing)}: `slidecast compose -o {where}` makes them")
    if not missing:
        for key, (name, opts) in AUDIO.items():
            spec[key] = {"file": name if where == out else str(where / name), **opts}
    spec.update({"lead_in": 1.8, "loudness": -16, "slides": entries})
    (out / "reel.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120))
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=OUT, help=f"the demo's output folder (default: {OUT})")
    ap.add_argument("--music", type=Path, metavar="DIR",
                    help="the folder holding music_bed.wav, intro_sting.wav and outro_sting.wav")
    args = ap.parse_args()
    spec = build(args.out, args.music)
    print(f"Wrote {len(spec['slides'])} slides and {args.out / 'reel.yaml'}"
          + ("" if "music" in spec else " (no music: voice only)"))


if __name__ == "__main__":
    main()
