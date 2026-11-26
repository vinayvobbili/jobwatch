# jobwatch for Chrome: application filler

Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest.

The extension does what those tools don't, because it works with your jobwatch:

- **It reuses your earlier answers.** Every form question you answered on a past application is kept by jobwatch.
  On a new form, the extension finds the question that reads most like each one, shows you which earlier question it
  matched (and the company and date), and puts the answer in a box you can edit. Notice period, why this kind of
  role, a time you handled an incident: write it once.
- **It drafts the new ones.** A question nothing matches gets a **Draft with jobwatch** button. The draft comes from
  your resume, your stories and the posting, and it is never filled until you tick it.
- **It attaches the job's resume.** The one saved with that job's application package, or your default.
- **It records the application when you submit.** After you press Submit and the page shows it went through,
  jobwatch marks the job applied and keeps the answers you gave, ready for the next form.

It fills only what is still empty. A field Simplify, Chrome or a password manager already filled starts unticked and
marked "already filled". The basics (name, email, phone, links, work authorization, the voluntary
self-identification questions) come from the applicant details in jobwatch's Settings, as a fallback for what is left.

It never clicks Submit, Next or any button that sends the form. You review the side panel, press **Fill selected**, read
the form, and submit it yourself.

## Set it up

1. Run `jobwatch` and open Settings, Browser extension. Copy the token.
2. In Chrome, open the extension's options (right-click its icon, Options) and paste the token. The server address is
   `http://127.0.0.1:8765` unless you started `jobwatch ui --port` differently. Press **Test**.
3. Open a job application and click the extension's icon. Chrome's side panel opens beside the page (in an installed web app's window, which has no side panel, the same panel opens as a small window beside it); press **Fill this application**.

Without jobwatch running, the side panel says so (with a link to the settings) and does nothing else. The extension
has no standalone mode.

## What you see

The review lives in Chrome's side panel, docked beside the page like Claude's, so it never covers the form. At the top
it says whether it is paired with jobwatch. Each tab has its own panel, opened by clicking the icon on that tab: switch
to another tab and its panel (or none) shows, not this one. Let the tab load another page and the rows are dropped
with a note to scan again, so a row never fills a form that is gone. List imports run one per tab, any number of tabs at once
(say LinkedIn in one window and Indeed in another); each panel shows its own tab's progress, and a second import on
the same tab is refused. Chrome stops rendering a tab that isn't visible, so the reading stalls there and the panel
says so: keep each list in its own window to read two at once. A
multi-step form that swaps its next step in place (the address stays the same) is noticed too: the panel reads the
new step by itself. If a page
was not opened with the icon (Chrome only lets the extension touch a tab after you click its icon there), click the
icon on that tab once. When the application is recorded in jobwatch after you submit, the side panel says so too (the
icon also shows a check mark). Each field of the form is a row:

| Badge | Meaning |
|---|---|
| Your details | From the applicant details in jobwatch. Ticked when the match is certain, except salary, which you tick yourself. |
| Past answer | From an earlier application. Ticked only when the old question reads almost the same; otherwise it is offered, not ticked. |
| Draft | Written by jobwatch on your request. Never ticked for you. |
| Resume | The file jobwatch has for this job. |
| Not found | Nothing to fill. Type an answer, or press Draft. |

For a dropdown or a group of radio buttons the row shows the option it will pick. Edit any value, tick the rows you
want, press **Fill selected**.

Works on Greenhouse (job-boards.greenhouse.io, boards.greenhouse.io and the form embedded in a company's own page),
Lever and Ashby, and tries its best on other single-page forms. Workday is not supported yet.

## Job lists

On a list of jobs, press **Read the jobs on this list**: LinkedIn (Jobs, a search), Indeed (Jobs for you, a search) or
Ladders ("Recommended Jobs", a search). The extension scrolls each page, reads its cards, goes on to the next page (up to the
pages you set, 4 by default) and sends them to your jobwatch, which counts the jobs it had and tracks the rest. On LinkedIn
and Indeed a script runs in your browsing for **Note jobs while I browse** (off by default); Ladders has no script of its
own, so the list is reached only on the tab where you clicked the icon (that tab's own grant), and passive mode is not offered
there. Ladders' jobs are the companies' own: the job's page on Ladders is kept in jobwatch only as a reference note, its pay
is Ladders' own estimate (kept in the note, not as the job's pay), and you apply on the company's own site. It needs a jobwatch
that lists `list-ladders` in `/ext/ping`; an older one gets a note to update, not the button.

## Jobs from LinkedIn alerts

A job that came from a LinkedIn alert has no posting text. On Today, **Open on LinkedIn** opens its LinkedIn page. There,
click the extension's icon and press **Open the company's posting**: it presses LinkedIn's Apply button (never Easy
Apply) so the company's page opens, and jobwatch reads the posting from that page when it is on a job site it supports.
On any other company page, press **Save this posting to jobwatch**. Apart from job lists, that is all the extension reads from LinkedIn, except a job page jobwatch's **Read posting** button opened (below) and a conversation you ask a reply for (after that).

### Read posting

LinkedIn and Indeed show a job's description only to a signed-in browser, so jobwatch can't read it for a job that came from
an alert email. Such a job's card on Queue and Today says why ("No posting text: LinkedIn blocks automatic reading; open it and
press Read posting") and has a **Read posting** button. It opens the job in a new tab of your own browser with `#jobwatch-read`
added to the address; the extension reads that page's description (only then: on any other page of those sites its script does
nothing), gives it to jobwatch, shows a banner and closes the tab. Back in jobwatch the card fills in and the job is scored. You
must be signed in to the site in that browser; if the page shows a sign-in or a captcha, the banner says so and nothing is sent.
With the newest extension that tab opens behind the one you are on and only that card changes; with an older one (jobwatch's
page checks) it opens in front as described, and jobwatch says once to update or reload the extension.
`jobwatch fill-text --open` lists every such job's link.

## Drafting a reply to a recruiter

On a LinkedIn conversation you have open (Messaging, or a message bubble), click the extension's icon and press **Draft reply
to this conversation**. The extension reads that one conversation as it is on the screen (no scrolling, no other
conversation) and gives it to your jobwatch, which writes a draft from your resume, your stories and what you track at
that company, with the local model on your computer. The panel shows the draft (edit it), jobwatch's warnings, what to
check before you send, and whether the draft was written on your computer: if you set `reply: {backend: chat}` in the
watchlist the thread goes to that chat model instead, and the panel says so in amber. **Put in the message box** types
the draft into LinkedIn's box (it asks before replacing text already there, and refuses if another conversation is open
now). It never presses Send: you read it and send it yourself. Needs a jobwatch with the `reply` call (the button is
absent on an older one).

## ATS check and cover letter for a job

On a job's page (a company's careers page, an application form, a posting) the Apply group has two more tiles. jobwatch has
to know the job: it is matched to the page by the board's posting id, the link it stored, a LinkedIn or Indeed job number,
or, for a job found by an alert and opened on the company's own site, by the page's company and title when exactly one open
job fits (the panel says so and asks you to check it is the right one). If it doesn't track the job the panel says to
press **Save this posting to jobwatch** first.

- **ATS check** shows the keyword score of the resume jobwatch keeps for that job (the tailored one, else your general one)
  against the posting: what a screener would miss (`*` is a term the posting asks for), what it found, and what would
  trip a parser. It is jobwatch's own keyword check on your computer, with no model, and it changes nothing. When it read
  the general resume, **Tailor a resume for this job, then check it** makes one with resume-kit and checks that.
- **Cover letter** has your jobwatch draft a letter with the model on your computer (the same draft the Prepare button on
  a queued job's card makes) and keeps it with the job as its next version. The panel shows it (edit it), where it was
  written (on this Mac, or, if you set `reply: {backend: chat}`, by the chat model, in amber), and Copy. **Fill the cover
  letter box** types it into the form's cover letter box when the page has one, only if that box is empty; **Replace what
  is in the box** is a separate press. A form that takes the letter as a file gets no fill button: copy the letter and
  attach it yourself. The extension never presses Submit.

Both need a jobwatch with the `ats` and `cover` calls (the tiles are absent on an older one). The extension sends your
jobwatch the page's address and the company and job title the page shows (not on LinkedIn or Indeed pages), nothing else.

## Privacy

Nothing leaves your computer except to jobwatch, which runs on it. See [PRIVACY.md](PRIVACY.md).

## For developers

```
manifest.json       Manifest V3: activeTab, scripting, storage, sidePanel, tabs, http://127.0.0.1 / localhost, and
                    a content script on linkedin.com / indeed.com job lists (passive mode)
background.js       service worker; the only code that talks to jobwatch (API.md); opens the side panel when the
                    icon is clicked; keeps pending submissions per tab
logic.js            classification, matching, option picking, the review plan; no DOM, tested with node
page.js             content script per frame: scan, fill, read company and title, watch for the person's submit
job-lists.js        reads LinkedIn / Indeed / Ladders job lists, paced like a person (PACING); a copy ships in jobwatch/static
passive.js          content script on LinkedIn and Indeed: notes the job cards seen while browsing (passive mode)
read-posting.js     content script on LinkedIn and Indeed: reads a job's description, only on a page opened with #jobwatch-read (Read posting)
reply.js            injected by Draft reply only: reads the one open LinkedIn conversation, types the draft into its box (never presses Send)
                    (ATS check and Cover letter inject no new script: the cover letter box is found with logic.js + page.js, and filled only on its own press)
sidepanel.*         the review panel in Chrome's side panel: pairing status, the lead card and action tiles for the page, scan, rows, fill, drafts, results
look.js             the System / Light / Dark theme (set on the options page) for the panel and the options page
options.*           the options page (server, token, theme and width)
demo/               fixture forms imitating Greenhouse, Lever and Ashby, and a generic one
tools/              make_icons.py, package.py (store zip), fake_server.py (API.md stand-in), harness.py (Playwright),
                    live_check.py (what the extension makes of a real form; reads only, never fills or submits)
API.md              the contract with jobwatch's local server
```

There is no build step and no dependency. Load it with chrome://extensions, Developer mode, Load unpacked.

Tests, from the repo root:

```
pip install -e ".[dev,browser]" && playwright install chromium
python -m pytest tests/test_extension_*.py -q
```

The end-to-end test loads the extension into Chromium, serves the demo forms under the addresses of the boards they
imitate, and runs a fake jobwatch. Automation can't click the toolbar button that docks the side panel, so it opens
`sidepanel.html?tab=<id>` in an ordinary tab, which is the same page pinned to the form's tab. It skips when
Playwright or Chromium is missing.

To see how a real board's form reads, `python chrome-extension/tools/live_check.py <application link>` prints one
line per field: what it is, where its value would come from, and whether it starts ticked. It fills nothing.

Add a system by adding an entry to `ADAPTERS` in `page.js` (how to match its host, where its field labels sit, how to
read the job title and company) and a fixture in `demo/`. Anything custom about filling goes in `fillOne`. Workday
would be the next one.

Store zip: `python chrome-extension/tools/package.py` writes `dist/jobwatch-extension-<version>.zip`. It refuses to
build when the manifest version differs from the jobwatch package's.

Parts of the React handling in `page.js` follow two open-source autofill extensions; see
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).
