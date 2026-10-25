"""The tutorial videos' slides and narration: seven short reels (getting started, the daily routine, where the AI
runs, applying, tracking, interview prep, comps and contacts). Writes OUT/tutorials/<name>/slides/*.html and
reel.yaml for each; slidecast renders them (make-tutorials).

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
from demo.build import AUDIO, BRAND, data_uri, head, page, shot_slide, term_slide

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


ADD = """<span class="c"># a link to a posting on Greenhouse, Lever, Ashby, Workable, Workday...: read from there</span>
<span class="p">$</span> jobwatch add https://apply.workable.com/acme/j/A1B2C3D4E5/ --status queued

<span class="c"># LinkedIn is never read: give the company and title, and the posting's text</span>
<span class="p">$</span> jobwatch add "Umbrella" "Staff Engineer" --url https://www.linkedin.com/jobs/view/... \\
    --text posting.txt --status queued

<span class="c"># or the posting from the clipboard</span>
<span class="p">$</span> pbpaste | jobwatch add "Umbrella" "Staff Engineer" --text - --status queued
"""

ALERTS = """<span class="c"># save the alert emails from your mail app: a .eml each, a folder, or an .mbox</span>
<span class="p">$</span> jobwatch alerts ~/Downloads/alerts/ --dry-run      <span class="c"># what's in them, nothing recorded</span>
<span class="p">$</span> jobwatch alerts ~/Downloads/alerts/                <span class="c"># track the new ones</span>
<span class="p">$</span> pbpaste | jobwatch alerts -                        <span class="c"># one message, from the clipboard</span>
"""  # noqa: E501

INBOX = """<span class="c"># replies about your applications: confirmations, rejections, interviews, offers</span>
<span class="p">$</span> jobwatch inbox ~/Downloads/replies/                <span class="c"># what each email says, nothing recorded</span>
<span class="p">$</span> jobwatch inbox ~/Downloads/replies/ --apply        <span class="c"># ask y/n about each proposal</span>
<span class="p">$</span> jobwatch inbox ~/Downloads/replies/ --yes          <span class="c"># record them all</span>
"""  # noqa: E501

CALENDAR = """<span class="p">$</span> jobwatch calendar -o jobwatch.ics   <span class="c"># import this file into any calendar app</span>

<span class="c"># or press Add to calendar on the Applications tab to subscribe</span>

<span class="c"># jobwatch.yaml: a reminder before interviews and calls</span>
<span class="k">calendar</span>:
  <span class="k">remind</span>: 30    <span class="c"># minutes; 0 (the default): no reminder</span>
"""  # noqa: E501

STORIES = """<span class="c"># stories.yaml: each project you'd talk about on a call, in your own words</span>
- <span class="k">id</span>: alert-dedupe
  <span class="k">title</span>: Cut duplicate on-call alerts
  <span class="k">did</span>: Built a Python service that groups alerts about the same incident.
  <span class="k">hard</span>: The teams named the same hosts three different ways.
  <span class="k">result</span>: Pages per week went from 120 to 35 in two months.
  <span class="k">avoid</span>: [the vendor's name]    <span class="c"># optional: never said in an answer</span>

<span class="p">$</span> jobwatch stories                    <span class="c"># checks the file and lists what's there</span>
<span class="p">$</span> jobwatch prep c1 --draft           <span class="c"># 6 to 10 likely questions, answers from your stories</span>
"""  # noqa: E501

DRILL = """<span class="p">$</span> pip install 'jobwatch[video]'      <span class="c"># voices that run on your Mac</span>

<span class="p">$</span> jobwatch prep c1 --drill drill.mp4
<span class="p">$</span> jobwatch prep c1 --drill drill.mp4 --pause 60   <span class="c"># hold 60 seconds, not 75</span>
<span class="p">$</span> jobwatch prep c1 --drill drill.mp4 --no-pause   <span class="c"># a quick review</span>
"""  # noqa: E501

FIND_STORY = """<span class="p">$</span> jobwatch ask --job c1 --story                       <span class="c"># lists the gaps to pick from</span>
<span class="p">$</span> jobwatch ask --job c1 --story "running a migration"  <span class="c"># or name your own</span>

<span class="c"># it asks one question at a time, then proposes the story.</span>
<span class="c"># you check every line, edit it, and save: nothing is saved before that.</span>
<span class="p">$</span> jobwatch stories
"""  # noqa: E501

COMP = """<span class="p">$</span> jobwatch comp initech --base 190-220K --bonus "10% target" --equity "40K RSUs over 4 years" \\
    --asked 220-240K --role product --career-note "LLM apps, staff IC"
<span class="p">$</span> jobwatch health "Initech" --kind tech --listing private --stage "Series C, $90M, 2025" \\
    --headcount growing --layoffs none --rating "4.2 Glassdoor" \\
    --sources "https://example.com/initech" --as-of 2026-10-20

<span class="p">$</span> jobwatch comps                     <span class="c"># the same side by side, in the terminal</span>
"""  # noqa: E501

WEIGHTS = """<span class="c"># jobwatch.yaml: the five parts and their weights (any numbers; scaled to add up to 1)</span>
<span class="k">comps</span>:
  <span class="k">weights</span>: {career: 40, pay: 30, fit: 15, progress: 5, health: 10}

<span class="c"># your goals: the career part scores against them (Settings, Your goals)</span>
<span class="k">goals</span>:
  <span class="k">company_kinds</span>: [tech, consulting, enterprise]   <span class="c"># best first</span>
  <span class="k">roles</span>: [product, customer, internal]
"""  # noqa: E501


def panel_slide(n: int, label: str, title: str, sub: str, image: Path, width: int = 340) -> str:
    """A screenshot of one panel (narrow: not the whole page), centred."""
    frame = (f'<div class="frame" style="left:{(1280 - width) // 2}px;right:auto;width:{width}px">'
             f'<div class="bar"><span></span><span></span><span></span><em>127.0.0.1 · jobwatch ui</em></div>'
             f'<div class="shot" style="background-image:url({data_uri(image)});background-size:{width}px auto"></div>'
             '</div>')
    return page(head(n, label, title, sub) + frame)


def tutorials(tut: Path, shots: Path) -> dict[str, list[tuple[str, str, str]]]:
    """name -> [(slide file, html, narration)]. `tut` holds onboarding's screenshots, `shots` the demo's. The
    guide videos (04 to 07) use `tut`'s too: the demo seeded with the extras (shots.py)."""
    more = tut
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
        "04-applying": [
            ("01", title("Applying", "The queue, jobs from elsewhere, alerts and replies.", "jobwatch queue"),
             "Here is how applying works in jobwatch: the queue, jobs you find somewhere else, job alert emails, "
             "and the replies you get."),
            ("02", shot_slide(1, "Queue", "Your short list", "Warnings to check first, and people you know there.",
                              more / "queue.png", y=150),
             "Queued jobs leave the digest and wait in the Queue tab. Each card on Today suggests queuing or "
             "skipping, and why, from a few fixed rules. The queue flags a posting that has closed, and what to "
             "check before you apply. It lists people you know there, so you can ask for a referral first."),
            ("03", shot_slide(2, "Found elsewhere", "Add a job", "A link, or the company, the title and the "
                              "posting.", more / "queue-add.png", y=150),
             "Found a job somewhere else? Press Add a job. A link to a posting on Greenhouse, Lever, Ashby and "
             "other boards is enough. jobwatch never reads LinkedIn, so give the company and title too. For "
             "anything else, paste the posting's text."),
            ("04", term_slide(3, "The same in a terminal", "jobwatch add", "A link, or a company, a title and "
                              "the text.", ADD, size=15),
             "From a terminal, it is job watch add. Give it a link, or the company and title with the posting's "
             "text, and a status such as queued."),
            ("05", term_slide(4, "Job alerts", "Alert emails go straight in", "LinkedIn, Built In, Indeed and "
                              "others.", ALERTS, size=16),
             "Job alert emails can go straight in. Save them from your mail app and give them to jobwatch "
             "alerts. With dry run, you see what's in them first. Each job is read from the email, and looked "
             "for on the company's own board. It never asks for your email password."),
            ("06", term_slide(5, "Replies", "Status updates from application emails", "It proposes. You decide.",
                              INBOX, size=16),
             "Emails about your applications can be read too: a confirmation, a rejection, an interview "
             "invitation, an offer. Give them to jobwatch inbox. It proposes a new status and a dated note for "
             "each one, and you decide. A status only moves forward."),
            ("07", panel_slide(6, "Companies to watch", "Boards you don't watch yet", "From alerts and jobs you "
                               "added by hand.", more / "suggest.png"),
             "jobwatch only checks the boards on your watchlist. Companies whose jobs came in from alerts or by "
             "hand show up on Today as Companies to watch. Press Add to watch one, or Dismiss."),
            ("08", closing("You press Submit.", "jobwatch finds, ranks and tracks. It never applies for you.",
                           "jobwatch queue"),
             "That is the apply queue. jobwatch never applies for you. You review and submit every application."),
        ],
        "05-tracking": [
            ("01", title("Tracking applications", "Stages, follow-ups, interviews and what you sent.",
                         "jobwatch applications"),
             "Here is how jobwatch tracks your applications, from the first reply to the interview."),
            ("02", shot_slide(1, "Applications", "Every one, in one list", "Stage, next step and follow-up day. "
                              "The ones due come first.", more / "applied.png", y=140),
             "Each application has a stage: applied, screening, interviewing, offer, then rejected or "
             "withdrawn. It can have a next step and a day to follow up, and the ones due come first. The "
             "pipeline bar counts them by stage."),
            ("03", shot_slide(2, "Cards or Table", "Pick the view you like", "Sort by any column; change a stage "
                              "in place.", more / "applied-table.png", y=140),
             "Switch between cards and a table. In the table, sort by a column, and change a stage right there."),
            ("04", shot_slide(3, "Gone quiet", "Applications that go quiet", "A check-in to send, never a status "
                              "changed for you.", more / "applied-quiet.png", y=150),
             "Many applications never get a reply. One with no news for a few weeks has gone quiet: twenty one "
             "days at applied, fourteen at screening, ten at interviewing. Each gets a suggestion, and one click "
             "to snooze, mark withdrawn or rejected, or add a note. jobwatch only suggests."),
            ("05", term_slide(4, "Calendar", "Follow-ups and interviews, on your calendar", "Your calendar app "
                              "reads a feed. jobwatch never gets access to it.", CALENDAR, size=17),
             "To see follow-up days and interviews in your own calendar, press Add to calendar, or write a file "
             "with jobwatch calendar. When a next step names an interview with a date and a time, it becomes a "
             "timed event too."),
            ("06", shot_slide(5, "Interviews", "What's coming up", "Today's first, then the next two weeks.",
                              more / "interviews.png", y=140),
             "The Interviews tab lists the interviews and calls coming up: today's first, then the next two "
             "weeks. It reads them from your next steps. Click one to see everything about that application."),
            ("07", shot_slide(6, "Find a company", "Press slash, type a name", "Any status, open or closed.",
                              more / "company.png"),
             "To look up a company, press slash on any tab and type a name. Its page shows its jobs under any "
             "status, with dates, next step and note, and the people you know there."),
            ("08", shot_slide(7, "What you sent", "The resume, the answers, the posting", "Kept as you sent "
                              "them.", more / "sent.png"),
             "Each application keeps what you sent: the resume and cover letter as uploaded, your answers on the "
             "form, and the posting as it read the day you applied. When a recruiter calls three weeks later, "
             "this is what they are looking at."),
            ("09", closing("Nothing slips.", "Follow-ups, interviews and what you sent, in one place.",
                           "jobwatch applications --due"),
             "That is tracking: every application in one list, with what to do next."),
        ],
        "06-interview-prep": [
            ("01", title("Interview prep", "Prep sheets, drafted answers, a mock interview and a drill video.",
                         "jobwatch prep c1"),
             "Here is how jobwatch helps you prepare for a recruiter call or an interview."),
            ("02", shot_slide(1, "Prep sheet", "One page before every call", "Their asks next to your closest "
                              "resume line.", more / "prep.png"),
             "Open an application's Details and press Prep sheet. It's one page, ready to print. Each ask in the "
             "posting sits next to the line on your resume closest to it, or a plain nothing close. It also has "
             "a company brief, your pay target, and questions to expect."),
            ("03", term_slide(2, "Drafted answers", "Answers built from your own stories", "You write each story "
                              "once.", STORIES, size=15),
             "Drafted answers come from your own stories. Write each project once: what you did, the hard part, "
             "and the result. Then draft six to ten likely questions, each with an outline that names the "
             "stories it used. A question none of them answers says no story yet."),
            ("04", shot_slide(3, "Mock interview", "Practise one question at a time", "Saved answers come back "
                              "on the sheet.", more / "prep-practised.png"),
             "A mock interview asks the questions one at a time. You type an answer, and get short feedback and "
             "a tightened version that only uses facts from you. Save it, and it shows on the sheet under "
             "Practised answers."),
            ("05", term_slide(4, "Drill video", "A video to rehearse with", "Runs on your Mac. Nothing is sent "
                              "anywhere.", DRILL, size=16),
             "A drill video turns the sheet into something to rehearse with. A question is asked in one voice, "
             "the screen says Answer out loud and waits, then a second voice gives your answer. It only uses "
             "answers the sheet already has."),
            ("06", term_slide(5, "Find a story", "A thin spot often hides a story", "The model interviews you. "
                              "You approve every line.", FIND_STORY, size=16),
             "Where the sheet is thin, there is often a story you forgot. Find a story interviews you about it, "
             "one question at a time, then writes it up. You check every line, edit it, and press Save to my "
             "stories. Nothing is saved before that."),
            ("07", card(6, "Where it runs", "The chat's model, your choice", "With the local model, everything "
                        "stays on your computer. With Claude, the posting, your resume and your stories go to "
                        "Anthropic.",
                        ["Your pay floor never goes in a prompt for Claude",
                         "Answers may only use your stories and resume"]),
             "These run on the chat's model, the one you chose. With the local model, everything stays on your "
             "computer. With Claude, the posting, your resume and your stories go to Anthropic, but never your "
             "pay floor."),
            ("08", closing("Walk in ready.", "The sheet quotes your posting, resume and stories. "
                           "Nothing is invented.", "jobwatch prep c1"),
             "That is interview prep. The sheet quotes your posting, your resume and your stories. Nothing is "
             "made up for you."),
        ],
        "07-comps-and-contacts": [
            ("01", title("Comps and contacts", "Compare your real options, and see who you know there.",
                         "jobwatch comps"),
             "Here is how jobwatch compares your opportunities, and finds who you know at each company."),
            ("02", shot_slide(1, "Comps", "A suggestion, and the reasons", "Plain rules. No model.",
                              more / "comps.png", y=150),
             "The Comps tab puts your live opportunities side by side: the applications at screening, "
             "interviewing or offer. A suggestion at the top ranks them by plain rules, with no model, and says "
             "why."),
            ("03", shot_slide(2, "Side by side", "Pay, fit, stage and people", "The best value in a row gets a "
                              "star.", more / "comps-table.png", y=130),
             "Each column shows the stage, the next step, the pay as posted, what a recruiter told you, and the "
             "fit score. The highest value in a row gets a star. You can add any other job, or any company by "
             "name, to compare."),
            ("04", term_slide(3, "Pay and company health", "You type it in", "jobwatch looks none of it up.",
                              COMP, size=15),
             "What a recruiter says about pay, and what you know of a company, like funding, layoffs, headcount "
             "and rating, you type in. jobwatch looks none of it up. Over M C P, an assistant can search the web "
             "and record it with its source links. Health older than ninety days is marked stale."),
            ("05", term_slide(4, "The weights", "Change what matters to you", "Career, pay, fit, progress and "
                              "health.", WEIGHTS, size=16),
             "The suggestion scores five parts: career value, pay against your target, fit, how far along it "
             "is, and company health. The defaults are twenty five, thirty, twenty, ten and fifteen percent. "
             "Change them in the watchlist, and say your goals so the career part follows them."),
            ("06", shot_slide(5, "Who you know", "Referrals", "Closest ties first. Use, or Don't use.",
                              more / "referrals.png", y=140),
             "Download your LinkedIn data and upload it in the page. Each job then lists your connections at that "
             "company, and the people you actually talk to come first. The Referrals tab lists them. Press Use to "
             "put someone first, or Don't use to stop suggesting them, and keep a note."),
            ("07", card(6, "Private", "Only counts are kept", "jobwatch counts the messages you exchanged, "
                        "recommendations and endorsements. It never keeps your messages.",
                        ["Your LinkedIn data is only read on your machine",
                         "Leave anyone out with connections_skip"]),
             "Only counts are kept: messages exchanged, recommendations and endorsements, never the messages "
             "themselves. Your LinkedIn data is only read on your machine."),
            ("08", closing("Know the numbers, know the people.", "Compare options on facts you entered, and ask "
                           "the right person first.", "jobwatch comps"),
             "That is comps and contacts: compare on facts you entered, and ask the right person first."),
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
