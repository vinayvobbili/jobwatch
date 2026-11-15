"""The videos' stories: each scene's narration and what the mouse does while it is said.

Short, plain sentences. Show the page and the side panel, never a command (`pipx install jobwatch` is the one
exception, in the getting-started video). Scenes run on the made-up demo (scripts/demo/seed.py)."""

from __future__ import annotations

from common import Scene, Video
from extension import dock, form_url, list_url

ABOUT = "Senior software engineer. I want to build LLM products again, and I'd rather join a smaller company."


# -- finding things on the page --------------------------------------------------------------------------------------

def seg(label: str, option: str) -> str:
    """The option button of the segmented control under a hint reading `label` (Today's Narrow down chips)."""
    return f".hint:has-text('{label}') + .seg-ctl >> text='{option}'"


def btn(rec, name: str, scope: str | None = None, exact: bool = True):
    root = rec.page.locator(scope).first if scope else rec.page
    return root.get_by_role("button", name=name, exact=exact).first


def tab(rec, name: str):
    return rec.page.locator(f"#tabs button[data-tab='{name}']")


def card(rec, text: str):
    return rec.page.locator(".card", has_text=text).first


def sub(rec, name: str):
    """A Settings sub tab (the sticky bar under the header)."""
    return rec.page.get_by_role("tab", name=name)


def hold_dialog(rec, dy: float = 420):
    """Scroll inside the open dialog, then rest."""
    rec.wheel(dy, at=(768, 500))


# -- Today -----------------------------------------------------------------------------------------------------------

def today_chips(rec, demo):
    """Today opens on Fit 80+ and a Top pay chip; the two Show/Hide switches keep the rest in reach."""
    rec.hold(1.4)
    rec.point_at(seg("Fit score", "80+"))
    rec.hold(0.4)
    rec.point_at(seg("Top pay", "$175K+"))
    rec.hold(0.4)
    rec.click(seg("No score yet", "Hide"), after=1.0)
    rec.click(seg("No pay clue", "Hide"), after=1.0)
    rec.click(seg("No score yet", "Show"), after=0.5)
    rec.click(seg("No pay clue", "Show"), after=0.5)


def pay_unknown(rec, demo):
    """Loosen both chips, then scroll to the job tagged "pay unknown"."""
    rec.click(seg("Fit score", "Any"), after=0.4)
    rec.click(seg("Top pay", "Any"), after=0.6)
    rec.scroll_to(rec.page.get_by_text("pay unknown").first)
    rec.hold(1.2)


def why_score(rec, demo):
    """Open Details: why it scored what it did."""
    rec.click(btn(rec, "Details", ".card", exact=False), after=1.2)
    hold_dialog(rec, 380)
    rec.hold(0.6)
    rec.click(btn(rec, "Close", "#dialog"), after=0.5)


def queue_one(rec, demo):
    rec.click(btn(rec, "Queue", ".card"), after=1.2)
    rec.click(tab(rec, "queue"), after=1.0)
    rec.point_at(rec.page.locator(".card").first)


def queue_tab(rec, demo):
    rec.hold(1.0)
    rec.point_at(rec.page.locator(".warns, .card").first)
    rec.hold(0.8)


def i_applied(rec, demo):
    rec.hold(0.8)
    rec.click(btn(rec, "I applied", ".card", exact=False), after=1.4)
    rec.click(tab(rec, "applied"), after=1.0)


def add_a_job(rec, demo):
    rec.click(btn(rec, "Add a job", exact=False), after=0.6)
    rec.type(rec.page.get_by_placeholder("Company", exact=True), "Umbrella")
    rec.type(rec.page.get_by_placeholder("Job title", exact=True), "Staff Engineer")
    rec.hold(0.8)


# -- applications -----------------------------------------------------------------------------------------------------

def tracking(rec, demo):
    rec.hold(1.0)
    rec.point_at(".pipeline")
    rec.hold(0.8)
    rec.click(btn(rec, "Table"), after=1.2)
    rec.click(btn(rec, "Cards"), after=0.8)


def quiet(rec, demo):
    rec.scroll_to(rec.page.locator(".card", has_text="Soylent").first, margin=70)
    rec.hold(0.6)
    rec.point_at(".quiet-bar")
    rec.hold(1.0)


def interviews(rec, demo):
    rec.hold(1.2)
    rec.point_at(rec.page.locator(".card").first)
    rec.hold(0.8)


def company_page(rec, demo):
    rec.press("/", after=1.0)
    rec.type("#jump", "initech", delay=0.06, after=0.8)
    rec.press("ArrowDown", after=0.3)
    rec.press("Enter", after=1.4)
    rec.hold(0.6)


def what_you_sent(rec, demo):
    rec.click(card(rec, "Initech").get_by_role("button", name="Details").first, after=1.2)
    rec.scroll_to(rec.page.get_by_text("What you sent").first)
    rec.hold(1.0)
    rec.click(btn(rec, "Close", "#dialog"), after=0.4)


def calendar_button(rec, demo):
    rec.point_at(btn(rec, "Add to calendar", exact=False))
    rec.hold(0.8)


# -- prep, comps, contacts ----------------------------------------------------

def open_prep(rec, demo):
    """Open the prep sheet and point at what it gives you."""
    rec.click(card(rec, "Initech").get_by_role("button", name="Details").first, after=1.0)
    rec.click(btn(rec, "Practise", "#dialog"), after=1.4)
    rec.point_at(btn(rec, "Find a story", "#dialog"))
    rec.hold(0.5)
    rec.point_at(btn(rec, "Mock interview", "#dialog"))
    rec.hold(0.5)
    rec.point_at(btn(rec, "Voice interview", "#dialog", exact=False))
    rec.hold(0.6)


def prep_asks(rec, demo):
    """Their asks next to your closest resume line (the dialog scrolls, the buttons stay in view above)."""
    rec.click(card(rec, "Initech").get_by_role("button", name="Details").first, after=1.0)
    rec.click(btn(rec, "Practise", "#dialog"), after=1.4)
    rec.wheel(300, at=(768, 520))
    rec.hold(0.6)
    rec.wheel(380, at=(768, 520))
    rec.hold(0.6)


def practised(rec, demo):
    rec.click(card(rec, "Initech").get_by_role("button", name="Details").first, after=1.0)
    rec.click(btn(rec, "Practise", "#dialog"), after=1.2)
    rec.scroll_to(rec.page.get_by_role("heading", name="Practised answers"))
    rec.hold(1.0)


def comps(rec, demo):
    rec.hold(1.2)
    rec.point_at(rec.page.locator(".card, .panel").first)
    rec.scroll_to(rec.page.get_by_text("Include applications still at applied").first)
    rec.hold(1.0)


def referrals(rec, demo):
    rec.hold(1.0)
    rec.point_at(btn(rec, "Use", ".card", exact=False))
    rec.hold(0.8)


# -- settings and AI ---------------------------------------------------------------------------------------------------

def ai_tiles(rec, demo):
    rec.hold(0.6)
    rec.scroll_to(".ai-tiles")
    tiles = rec.page.locator(".ai-tile")
    for i in range(tiles.count()):
        rec.point_at(tiles.nth(i))
        rec.hold(0.9)


def ai_chain(rec, demo):
    rec.scroll_to(".ai-chain", margin=160)
    rec.hold(0.8)
    rec.point_at(".ai-chain")
    rec.hold(1.0)


def ai_usage(rec, demo):
    rec.scroll_to("#set-usage")
    rec.hold(1.2)


def settings_apply(rec, demo):
    rec.click(sub(rec, "Applying"), after=0.8)
    rec.scroll_to("#set-extension")
    rec.hold(1.0)


def settings_alerts(rec, demo):
    rec.click(sub(rec, "Alerts & skills"), after=0.8)
    rec.hold(1.0)
    rec.scroll_to("#set-incoming")
    rec.hold(1.0)


# -- onboarding ---------------------------------------------------------------

def onboard_about(rec, demo):
    rec.type(rec.page.get_by_placeholder("e.g. Staff engineer", exact=False), ABOUT, delay=0.025)
    from demo.seed import RESUME
    box = rec.page.get_by_placeholder("or paste the text of your resume", exact=False)
    rec.click(box, after=0.2)
    box.fill(RESUME)
    rec.click(btn(rec, "Use this text"), after=0.8)
    rec.click(btn(rec, "Save and continue"), after=1.0)


def skip_to(rec, target):
    """Onboarding's place isn't kept when the page reloads, so a scene that opens on a later step gets there first,
    skipping ahead until `target` shows, off the recording (begin() restarts the clip's start)."""
    for _ in range(4):
        if target.count():
            break
        btn(rec, "Skip for now").click()
        rec.page.wait_for_timeout(900)
    rec.begin()


def onboard_jobs(rec, demo):
    rec.hold(1.6)
    rec.click(btn(rec, "Skip for now"), after=0.8)


def onboard_companies(rec, demo):
    skip_to(rec, rec.page.get_by_placeholder("Company name, or paste a link", exact=False))
    rec.hold(1.2)
    rec.point_at(rec.page.get_by_role("textbox").first)
    rec.hold(1.0)
    rec.click(btn(rec, "Skip for now"), after=0.8)


def onboard_ai(rec, demo):
    skip_to(rec, rec.page.locator("summary", has_text="AI: fit scores"))
    rec.click(rec.page.locator("summary", has_text="AI: fit scores"), after=1.0)
    rec.scroll_to(".ai-tiles")
    tiles = rec.page.locator(".ai-tile")
    for i in range(tiles.count()):
        rec.point_at(tiles.nth(i))
        rec.hold(0.7)


# -- the extension -----------------------------------------------------------

def ext_fill(rec, demo):
    panel = dock(rec, demo)
    rec.hold(1.0)
    rec.click(panel.locator("#scan"), after=0.4)
    panel.locator(".row").first.wait_for(timeout=20000)
    rec.hold(1.2)
    rec.wheel(420, at=(1640, 560))
    rec.hold(0.4)
    rec.click(panel.locator("#fill"), after=0.5)
    panel.locator("#toast").wait_for(timeout=20000)
    rec.hold(0.8)
    rec.wheel(-300, at=(1640, 560))


def _passive_on(rec, demo):
    helper = demo.extra["helper"] = demo.stack.extension_page("options.html")
    helper.evaluate("() => chrome.storage.local.set({ passiveOn: true })")
    demo.stack.server.features = ["posting", "import-list"]
    rec.page.reload()
    rec.page.wait_for_timeout(800)


def ext_list(rec, demo):
    _passive_on(rec, demo)
    panel = dock(rec, demo)
    panel.locator("#passive-import").wait_for(state="visible", timeout=20000)
    rec.hold(0.8)
    rec.click(panel.locator("#passive-import"), after=0.5)
    panel.locator(".row .badge").first.wait_for(timeout=20000)
    rec.hold(1.4)


def ext_list_again(rec, demo):
    _passive_on(rec, demo)
    panel = dock(rec, demo)
    panel.locator("#passive-import").wait_for(state="visible", timeout=20000)
    rec.click(panel.locator("#passive-import"), after=0.5)
    panel.locator(".row .meta").first.wait_for(timeout=20000)
    rec.hold(1.6)


def ext_list_both(rec, demo):
    """A first import, then the same list again: the badge, then the note."""
    ext_list(rec, demo)
    rec.page.reload()
    rec.page.wait_for_timeout(800)
    panel = dock(rec, demo)
    panel.locator("#passive-import").wait_for(state="visible", timeout=20000)
    rec.click(panel.locator("#passive-import"), after=0.5)
    panel.locator(".row .meta").first.wait_for(timeout=20000)
    rec.hold(1.6)


def to_watch(rec, demo):
    rec.scroll_to(rec.page.get_by_text("Companies to watch").first)
    rec.hold(1.2)


# -- the terminal card (the one command) ----------------------------------------------------------------------------

INSTALL = """<!doctype html><meta charset="utf-8"><style>
* { margin: 0; box-sizing: border-box } body { width: 1920px; height: 1080px; background: #0e0d1f; display: grid;
  place-items: center; font-family: -apple-system, sans-serif; color: #f4f3ff;
  background: radial-gradient(1500px 900px at 85% -10%, #4b2bb8 0%, transparent 60%), #0e0d1f }
.term { width: 1200px; border-radius: 22px; overflow: hidden; box-shadow: 0 40px 100px rgba(0,0,0,.55);
  border: 1px solid rgba(255,255,255,.14) }
.bar { background: #24223a; padding: 16px 22px; display: flex; gap: 10px }
.bar i { width: 16px; height: 16px; border-radius: 50%; background: #ff5f57 }
.bar i:nth-child(2) { background: #febc2e }
.bar i:nth-child(3) { background: #28c840 }
.body { background: #14131f; padding: 56px 60px; font: 46px/1.4 "SF Mono", Menlo, monospace; color: #7ee2a8;
  height: 240px }
.cmd { display: inline-block; overflow: hidden; white-space: nowrap; width: 0; vertical-align: bottom;
  animation: type 1.6s steps(22) .6s forwards; color: #e6e4f5 }
.cur { display: inline-block; width: 22px; height: 46px; background: #b9a8ff; vertical-align: bottom;
  animation: blink .8s steps(1) infinite }
@keyframes type { to { width: 22ch } } @keyframes blink { 50% { opacity: 0 } }
</style><div class="term"><div class="bar"><i></i><i></i><i></i></div>
<div class="body">$ <span class="cmd">pipx install jobwatch</span><span class="cur"></span></div></div>"""


# -- the videos --------------------------------------------------------------

PROBLEM_TOUR = ["Twelve job boards, checked by hand", "Forty tabs and a spreadsheet that's always stale",
                "The same form, typed again and again"]

VIDEOS: dict[str, Video] = {
    "jobwatch-demo": Video(
        "jobwatch-demo", "New roles at the companies you watch, ranked for you.", PROBLEM_TOUR,
        "Hunting for a job the traditional way is a lot of work. You keep track of a dozen job boards, "
        "and check each one by hand, every day. You end up with forty tabs open, and a spreadsheet that is "
        "always out of date. Then you type the same application form, again and again. "
        "jobwatch does that grind for you. Here is how.",
        [Scene("Every morning, Today opens on your own filters: a fit of eighty or more, and a pay floor. "
               "Jobs with no score or no pay clue wait at the end, or you can hide them.", today_chips,
               name="chips"),
         Scene("A job with no pay figure says so: pay unknown. You're never guessing.", pay_unknown, name="payunknown"),
         Scene("Queue the ones worth applying to. The queue is your short list, with the warnings to check first.",
               queue_one, name="queue"),
         Scene("On the company's own form, the extension fills what it can from your details and earlier answers. "
               "You check every field, and you press Submit.", ext_fill, start=form_url, name="fill"),
         Scene("On a LinkedIn list, it shows your coverage: how many of those jobs jobwatch already had. "
               "Read the same list again, and it says so.", ext_list_both, start=list_url, name="list"),
         Scene("Then track every application: its stage, the next step, and when to follow up.",
               tracking, start="applied", name="tracking"),
         Scene("Before a call, open the prep sheet.", open_prep, start="applied", name="prep"),
         Scene("And compare your real options side by side.", comps, start="comps", name="comps")],
        demo="more", extension=True, max_seconds=100,
        problem_cues=("You keep track", "You end up with forty", "Then you type")),
}
