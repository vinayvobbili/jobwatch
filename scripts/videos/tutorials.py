"""The seven tutorials: each two minutes or less, UI first. Narration is short and plain; a scene's clip is held as
long as its voice, so every line is said over the screen it describes."""

from __future__ import annotations

from common import Scene, Video
from extension import form_url, list_url
from stories import (
    INSTALL,
    add_a_job,
    ai_chain,
    ai_tiles,
    ai_usage,
    calendar_button,
    company_page,
    comps,
    ext_fill,
    ext_list_both,
    i_applied,
    interviews,
    onboard_about,
    onboard_ai,
    onboard_companies,
    onboard_jobs,
    open_prep,
    practised,
    prep_asks,
    queue_one,
    queue_tab,
    quiet,
    referrals,
    settings_alerts,
    sub,
    to_watch,
    today_chips,
    tracking,
    what_you_sent,
    why_score,
)


def settings_people(rec, demo):
    rec.click(sub(rec, "People & pay"), after=0.8)
    rec.scroll_to("#set-people")
    rec.hold(1.2)


def ai_show(rec, demo):
    rec.scroll_to(".ai-tiles")
    rec.hold(1.5)


def comps_rows(rec, demo):
    rec.scroll_to(rec.page.get_by_text("Include applications still at applied").first)
    rec.hold(0.8)
    rec.point_at(rec.page.get_by_text("Posted pay").first)
    rec.hold(1.0)
    rec.point_at(rec.page.get_by_text("You know").first)
    rec.hold(1.0)


TUTORIALS: dict[str, Video] = {
    "jobwatch-01-getting-started": Video(
        "jobwatch-01-getting-started", "Getting started: from install to your first ranked jobs.",
        ["Which boards do I watch?", "Which titles count?", "Where do I even begin?"],
        "Where do you start? Which boards, which titles, which companies?",
        [Scene("Install jobwatch with pipx, and open it.", html=INSTALL, seconds=5, name="install"),
         Scene("The first time, it asks a little about you, and for your resume. Your resume stays on this computer.",
               onboard_about, start="today", name="about"),
         Scene("Next, the jobs you want: titles, places and pay. Skip any step and come back later.",
               onboard_jobs, name="jobs"),
         Scene("Then the companies to watch. Type a name, or paste a link to one of their jobs.",
               onboard_companies, name="companies"),
         Scene("The last step is where the AI runs. Each choice says what it still needs.", onboard_ai, name="ai"),
         Scene("Then you land on Today: your matches, ranked, with fit and pay. The chips open on your own defaults.",
               today_chips, demo="plain", name="today")],
        demo="empty"),
    "jobwatch-02-daily-routine": Video(
        "jobwatch-02-daily-routine", "Your daily routine: ten minutes a day.",
        ["Forty tabs open", "Which job was I going to apply to?", "A spreadsheet nobody trusts"],
        "Forty tabs. A spreadsheet nobody trusts. Which job was I going to apply to?",
        [Scene("Start on Today. It opens on your own filters, and the best fits come first.", today_chips,
               name="today"),
         Scene("Open Details to see why a job scored what it did.", why_score, name="why"),
         Scene("Press Queue on the ones worth applying to.", queue_one, name="queue"),
         Scene("Apply on the company's own site. Then press I applied.", i_applied, start="queue", name="applied"),
         Scene("Every application keeps its stage, its next step, and when to follow up.", tracking,
               start="applied", name="track"),
         Scene("Before a call, open the prep sheet.", open_prep, start="applied", name="prep")]),
    "jobwatch-03-where-the-ai-runs": Video(
        "jobwatch-03-where-the-ai-runs", "Where the AI runs, and what leaves your computer.",
        ["Is my resume going to a cloud?", "Who sees the jobs I look at?", "What if the key runs out?"],
        "Your resume is private. So who gets to read it?",
        [Scene("Fit scores and the chat need a model. In Settings, you choose where it runs.", ai_show,
               start="settings/ai", name="tiles"),
         Scene("Claude's API gives the strongest scores. Antigravity uses your own Google subscription. "
               "Or a model runs on this Mac, free and private.", ai_tiles, start="settings/ai", name="choices"),
         Scene("Set a fallback chain. If one runs out of credit or is down, the next one scores the job.",
               ai_chain, start="settings/ai", name="chain"),
         Scene("A daily cap keeps the bill bounded. Past it, the fallback scores the rest.", ai_usage,
               start="settings/ai", name="usage"),
         Scene("Only the model you pick sees your resume and the postings. On this Mac, nothing leaves.",
               ai_show, start="settings/ai", name="private")]),
    "jobwatch-04-applying": Video(
        "jobwatch-04-applying", "Applying: the queue, the extension, and jobs from elsewhere.",
        ["The same form, typed again and again", "Notice period. Salary. Why us?", "Forty applications, twenty hours"],
        "Forty applications. The same questions every time. Twenty hours of retyping.",
        [Scene("Queued jobs wait on the Queue tab, with warnings to check first.", queue_tab, start="queue",
               name="queue"),
         Scene("Found a job somewhere else? Add it with a link, or the company and the title.", add_a_job,
               start="queue", name="add"),
         Scene("On the company's own form, the extension fills what it can from your details and earlier answers. "
               "It never presses Submit. You check every field, and you send it.", ext_fill, start=form_url,
               name="fill"),
         Scene("On a LinkedIn list, it reads the jobs and says how many jobwatch already had. "
               "Read the same list again, and it says so.", ext_list_both, start=list_url, name="list"),
         Scene("Companies whose jobs keep turning up, but whose board you don't watch, are suggested on Today.",
               to_watch, name="watch"),
         Scene("Job alerts and replies from application emails come in from your own mailbox.", settings_alerts,
               start="settings/alerts", name="alerts")],
        demo="more", extension=True),
    "jobwatch-05-tracking": Video(
        "jobwatch-05-tracking", "Tracking applications: stages, follow-ups and what you sent.",
        ["Did they ever reply?", "When do I follow up?", "What did I tell them?"],
        "Did they ever reply? When should you follow up? What did you even send them?",
        [Scene("Every application has a stage, a next step, and a day to follow up. Switch to a table when you "
               "like.", tracking, start="applied", name="stages"),
         Scene("Applications with no news for a few weeks are marked quiet, with a check-in to send. "
               "jobwatch only suggests.", quiet, start="applied", name="quiet"),
         Scene("Add your follow-ups and interviews to your own calendar.", calendar_button, start="applied",
               name="calendar"),
         Scene("The Interviews tab lists what's coming up, today's first.", interviews, start="interviews",
               name="interviews"),
         Scene("Press slash, type a name, and see everything about that company.", company_page, name="company"),
         Scene("Each application keeps what you sent: the resume, your answers, and the posting as it read.",
               what_you_sent, start="applied", name="sent")],
        demo="more"),
    "jobwatch-06-interview-prep": Video(
        "jobwatch-06-interview-prep", "Interview prep: a sheet, your own stories, and practice.",
        ["What did the posting ask for?", "Which story fits that question?", "What do I say about the gap?"],
        "What did the posting ask for? Which story answers that question?",
        [Scene("Open an application's Details, and press Practise. The prep sheet opens.", open_prep,
               start="applied", name="open"),
         Scene("Each ask in the posting sits next to the closest line on your resume. Where nothing is close, "
               "it says so plainly.", prep_asks, start="applied", name="asks"),
         Scene("A mock interview asks one question at a time, and the answers you save come back on the sheet.",
               practised, start="applied", name="practised")],
        demo="more"),
    "jobwatch-07-comps-and-contacts": Video(
        "jobwatch-07-comps-and-contacts", "Comps and contacts: compare options, and ask the right person.",
        ["Which offer is really better?", "Who do I know there?", "Whom do I ask first?"],
        "Which offer is really better? And who do you know there?",
        [Scene("The Comps tab puts your live opportunities side by side, with a suggestion and the reasons.", comps,
               start="comps", name="comps"),
         Scene("Pay, fit, stage and the people you know. The best value in a row gets a star.", comps_rows,
               start="comps", name="rows"),
         Scene("Your own LinkedIn data shows who you know at each company, closest first.", referrals,
               start="referrals", name="referrals"),
         Scene("Set your pay target and floor in Settings. They stay on this computer.", settings_people,
               start="settings/people", name="pay")],
        demo="more"),
}
