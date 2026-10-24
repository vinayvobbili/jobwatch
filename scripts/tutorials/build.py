"""The tutorial videos' slides and narration: three short reels (getting started, the daily routine, where the AI
runs). Writes OUT/tutorials/<name>/slides/*.html and reel.yaml for each; slidecast renders them (make-tutorials).

    python scripts/tutorials/build.py scripts/demo/out [--music DIR]

OUT holds what scripts/demo/make-video and scripts/tutorials/shots.py made: the seeded demo's screenshots (shots/,
made-up companies Acme, Globex...) and the onboarding ones (tut-shots/). Nothing here reads a real watchlist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/: demo/
from demo.build import AUDIO, BRAND, page, shot_slide, term_slide

OUT = Path(__file__).resolve().parent.parent / "demo" / "out"
HIDDEN = BRAND.replace('class="brand"', 'class="brand" style="display:none"')


def title(heading: str, sub: str, cmd: str = "") -> str:
    return page(HIDDEN + f'<div class="center"><div class="logo big"></div><h1>{heading}</h1>'
                f'<div class="sub">{sub}</div>' + (f'<div class="cmd">{cmd}</div>' if cmd else "") + "</div>")


def card(n: int, label: str, heading: str, sub: str, chips: list[str]) -> str:
    return page(HIDDEN + f'<div class="center"><div class="step"><i>{n}</i>{label}</div>'
                f'<h1 style="margin-top:18px">{heading}</h1><div class="sub">{sub}</div>'
                '<div class="chips">' + "".join(f"<span>{c}</span>" for c in chips) + "</div></div>")


def closing(heading: str, sub: str, cmd: str) -> str:
    return page(HIDDEN + f'<div class="center"><h1>{heading}</h1><div class="sub">{sub}</div>'
                f'<div class="cmd">{cmd}</div></div>')


INSTALL = """<span class="p">$</span> pipx install jobwatch          <span class="c"># or: pip install jobwatch</span>

<span class="c"># optional extras</span>
<span class="p">$</span> pip install 'jobwatch[score]'       <span class="c"># fit scores with Claude's API</span>
<span class="p">$</span> pip install 'jobwatch[local]'       <span class="c"># fit scores on this Mac</span>
<span class="p">$</span> pip install 'jobwatch[mcp]'         <span class="c"># MCP server for Claude</span>

<span class="p">$</span> jobwatch ui
<span class="c">jobwatch is running at http://127.0.0.1:8765/</span>
"""

CONFIG = """<span class="c"># jobwatch.yaml: the same choices the page saves</span>
<span class="k">scoring</span>:
  <span class="k">backend</span>: claude          <span class="c"># or agy, or local (the default)</span>
  <span class="k">fallback</span>: [agy, local]   <span class="c"># tried in order when Claude can't score</span>
  <span class="k">daily</span>: 40                <span class="c"># Claude: 40 jobs a day, then fallback</span>
<span class="k">chat</span>:
  <span class="k">backend</span>: local           <span class="c"># agy can't run the chat: claude or local</span>
"""

CHAIN = ('<div class="center"><div class="step"><i>3</i>The fallback chain</div>'
         '<h1 style="margin-top:18px">If one can\'t score, the next one does</h1>'
         '<div class="chips" style="margin-top:40px;align-items:center;font-size:22px">'
         '<span style="font-size:24px;padding:14px 26px">Claude API</span><b style="font-size:28px">&rarr;</b>'
         '<span style="font-size:24px;padding:14px 26px">Antigravity</span><b style="font-size:28px">&rarr;</b>'
         '<span style="font-size:24px;padding:14px 26px">This Mac</span></div>'
         '<div class="sub" style="margin-top:34px">No key, out of credit, or the API is down: the next backend scores '
         'the job. A fallback score is marked, and Claude scores it again later.</div></div>')


def tutorials(tut: Path, shots: Path) -> dict[str, list[tuple[str, str, str]]]:
    """name -> [(slide file, html, narration)]. `tut` holds onboarding's screenshots, `shots` the demo's."""
    return {
        "01-getting-started": [
            ("01", title("Getting started", "From install to your first ranked jobs, in about two minutes.",
                         "pip install jobwatch"),
             "This is jobwatch, a tool that watches company job boards and ranks what's new for you. Here is how to "
             "get started."),
            ("02", term_slide(1, "Install", "One install, one command", "Python 3.10 or newer. Extras are optional.",
                              INSTALL, size=17),
             "Install it with pipx or pip. The plain install gives you discovery, filters and the daily digest. "
             "Extras add fit scores with Claude's API, fit scores on your own Mac, and an M C P server for Claude. "
             "Then run job watch u i. A page opens on your own computer."),
            ("03", shot_slide(2, "About you", "Tell it who you are", "Your resume stays on this computer.",
                              tut / "first-run.png", y=0),
             "The first time, it walks you through four short steps. Each one is saved as you go, and every one can "
             "be skipped. First, a few words about you and what you want next, and your resume. You can upload it "
             "or paste it."),
            ("04", shot_slide(3, "Jobs you want", "Titles, places and pay", "Suggestions only appear when you ask.",
                              tut / "jobs.png", y=0),
             "Next, the jobs you want: titles, places, remote, and a pay target. If a model is set up, you can ask "
             "it to suggest titles from your resume. Nothing is sent anywhere until you press that button."),
            ("05", shot_slide(4, "Companies", "Who to watch", "A name, or a link to one of their jobs.",
                              tut / "companies.png", y=0),
             "Then the companies. Type a name, or paste a link to one of their jobs, and jobwatch finds the "
             "company's own board on Greenhouse, Lever, Ashby, Workday and others. Add as many as you like."),
            ("06", shot_slide(5, "The rest", "Where the AI runs, and job alerts", "Both optional. Later leaves them "
                              "for Settings.", tut / "ai.png"),
             "The last step is optional too: where the AI that scores your fit should run. Each choice says what it "
             "still needs. There is a separate tutorial on that."),
            ("07", shot_slide(6, "Today", "Check for new jobs", "Matching roles, ranked, with fit scores.",
                              shots / "today.png", y=150),
             "Then you land on Today. Press Check for new jobs, and your matches appear, ranked, with pay and how "
             "long ago each was posted."),
            ("08", closing("That's it.", "jobwatch finds and ranks. You review and send every application "
                           "yourself.", "pip install jobwatch"),
             "That is all it takes. jobwatch never applies for you. Everything it finds, you review and send "
             "yourself."),
        ],
        "02-daily-routine": [
            ("01", title("Your daily routine", "Today, Queue, Applications: about ten minutes a day."),
             "Here is a daily routine with jobwatch: look at Today, queue the good ones, apply, and track."),
            ("02", shot_slide(1, "Today", "Start with today's picks", "The top ten, in the order you choose: best "
                              "fit, newest or top pay.", shots / "today.png", y=150),
             "Open Today. It leads with today's picks, the top ten new matches. A few good applications a day "
             "beat a long list. Each has pay, how long ago it was posted, and a fit score. Show all opens every "
             "match."),
            ("03", shot_slide(2, "Look closer", "Why this score?", "Must-haves you meet, the gaps, and quotes from "
                              "your resume.", shots / "details.png", y=40),
             "Open Details to see why a job scored the way it did: the must-haves you meet, the gaps, and the "
             "quotes from your resume behind each judgment, which jobwatch checks against the resume text."),
            ("04", shot_slide(3, "Queue", "Queue what's worth applying to", "Skip the rest. Skipped jobs stay "
                              "out of your way.", shots / "queue.png", y=150),
             "Press Queue on the ones worth a tailored application, and Skip on the rest. The Queue tab is your "
             "short list, with warnings to check first. Apply on the company's own site. Then press I applied. "
             "The pace line counts it, as advice. Nothing is ever blocked."),
            ("05", shot_slide(4, "Applications", "Track every one", "Applied, screening, interviewing, offer, "
                              "rejected. Follow-ups due come first.", shots / "applied.png", y=140),
             "Every application lives in the Applications tab, with where it stands, a next step, and a follow-up "
             "day. Those that are due come first. Jobs you found elsewhere, such as a referral, can be added by "
             "hand."),
            ("06", shot_slide(5, "Prep", "A prep sheet before every call", "Their asks next to your closest resume "
                              "line, and the gaps to be honest about.", shots / "prep.png", y=80),
             "Before an interview, open the prep sheet. It lines up each ask in the posting with your closest "
             "resume line, and lists the questions to expect."),
            ("07", closing("Ten minutes, then get on with your day.", "While the page is open it checks the boards "
                           "itself every six hours. You press Submit.", "jobwatch ui"),
             "While the page is running, it checks the boards by itself, every six hours. A job hunt shouldn't be "
             "a full time job."),
        ],
        "03-where-the-ai-runs": [
            ("01", title("Where the AI runs", "Claude API, Antigravity, or this Mac, with a fallback chain.",
                         "Settings → Your resume and fit scores"),
             "Fit scores and the chat need a model. jobwatch lets you choose where it runs, and what happens when "
             "that one can't."),
            ("02", card(1, "Three choices", "Pick the one that fits you", "Each tile says what it still needs.",
                        ["Claude API: strongest scores, billed per job",
                         "Antigravity: your Google AI subscription, no key",
                         "This Mac: free and private, nothing leaves"]),
             "There are three choices. Claude's API gives the strongest scores, and is billed per job scored, a few "
             "cents each. Antigravity uses your own Google A I subscription, with no key and no per-use bill. "
             "And your own Mac runs a smaller model, free and private."),
            ("03", shot_slide(2, "The tiles", "Each one says what it still needs", "Ready, or the steps to set it "
                              "up.", tut / "ai-settings.png"),
             "In Settings, and in the last onboarding step, each choice is a tile with a status. Ready means "
             "it works now. Otherwise it lists the steps left, such as pasting an API key, which is kept in your "
             "macOS keychain, never in the settings file."),
            ("04", page(HIDDEN + CHAIN),
             "You can also set a fallback chain. Say Claude scores first, then Antigravity, then your Mac. With no "
             "key, no credit, or the A P I down, the next one scores the job. The score says it was a fallback, "
             "and Claude scores it again later."),
            ("05", term_slide(4, "In the file", "The same choices in jobwatch dot yaml", "Settings saves exactly "
                              "this.", CONFIG, size=17),
             "It's the same in the watchlist file. A daily cap keeps Claude's bill bounded. Past it, the fallback "
             "scores the rest. Antigravity can score fit, but not run the chat, which stays on Claude or your Mac."),
            ("06", card(5, "What goes where", "You decide what leaves your computer",
                        "With Claude, postings and your resume go to Anthropic. With Antigravity, to Google. "
                        "On this Mac, nothing does.",
                        ["jobwatch itself sends nothing home", "It never applies for you"]),
             "Only the model you choose ever sees your postings and resume. With this Mac, nothing leaves your "
             "computer. And jobwatch itself sends nothing home."),
        ],
    }


def build(out: Path, music: Path | None = None) -> list[Path]:
    """Write each tutorial's slides and reel.yaml under OUT/tutorials/<name>/; returns the reel files."""
    out = out.expanduser().resolve()
    where = (music or out).expanduser().resolve()
    have_music = all((where / name).is_file() for name, _ in AUDIO.values())
    if music and not have_music:
        raise SystemExit(f"{where} is missing music files: `slidecast compose -o {where}` makes them")
    reels = []
    for name, slides in tutorials(out / "tut-shots", out / "shots").items():
        folder = out / "tutorials" / name
        (folder / "slides").mkdir(parents=True, exist_ok=True)
        entries = []
        for file, body, narration in slides:
            (folder / "slides" / f"{file}.html").write_text(body, encoding="utf-8")
            entries.append({"html_file": f"slides/{file}.html", "narration": narration, "tail_pad": 1.3})
        entries[0]["tail_pad"], entries[-1]["tail_pad"] = 1.0, 1.6
        spec = {"width": 1920, "height": 1080, "fps": 25,
                "tts": {"provider": "mlx", "voice": "af_heart",
                        "phonetic": {r"\bjobwatch\b": "job watch", r"\bMCP\b": "M C P", r"\bAPI\b": "A P I"}}}
        if have_music:
            for key, (file, opts) in AUDIO.items():
                spec[key] = {"file": str(where / file), **opts}
        spec.update({"lead_in": 1.8, "loudness": -16, "slides": entries})
        reel = folder / "reel.yaml"
        reel.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120))
        reels.append(reel)
    return reels


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=OUT, help=f"the demo's output folder (default: {OUT})")
    ap.add_argument("--music", type=Path, metavar="DIR", help="the folder holding the music bed and stings")
    args = ap.parse_args()
    for reel in build(args.out, args.music):
        print(f"Wrote {reel}")


if __name__ == "__main__":
    main()
