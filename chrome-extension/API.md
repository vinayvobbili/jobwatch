# The extension's API (jobwatch side)

The browser extension fills job application forms alongside the autofill people already use (Simplify, Chrome's
autofill, a password manager), which fills the basics. Paired with `jobwatch ui` on the same computer, it fills
what those can't: answers given on earlier applications, drafted answers to new questions, the resume kept for
the job, and any basic field still empty; and it records the application when the person submits it. It needs
jobwatch: without it, it does nothing.

Everything stays on the person's computer: the extension talks to `http://127.0.0.1:<port>` (8765 unless
`jobwatch ui --port` says otherwise) and to nothing else.

## Pairing

`jobwatch ui` shows an extension token in Settings, under **Browser extension**. The person pastes it into the
extension's options once. The token is kept in jobwatch's state folder (`extension-token`), so it stays the same
across restarts; **New token** in Settings replaces it, and the old one stops working.

Every request below sends it as the header `X-Jobwatch-Extension: <token>`. A missing or wrong token gets
`403 {"error": "..."}`. All replies are JSON (`{"error": "..."}` with a 4xx or 5xx status when something's
wrong), except `/ext/resume`, which is the file itself.

## Applicant details

One flat object, as the watchlist's `applicant:` section keeps it. Every field is text; an empty string means
"not set, leave the form's field alone". The extension fills these only into fields that are still empty.

| Field | Example | Notes |
|---|---|---|
| `first_name`, `last_name` | `Jordan`, `Rivera` | |
| `preferred_name` | `Jo` | |
| `email` | `jordan@example.com` | |
| `phone` | `+1 555 0100` | |
| `city`, `state`, `country` | `Boulder`, `CO`, `United States` | |
| `postal_code` | `80301` | |
| `linkedin`, `github`, `website` | full links | |
| `work_authorized` | `yes` / `no` | Legally allowed to work in the job's country. |
| `needs_sponsorship` | `yes` / `no` | Now or in the future. |
| `relocate` | `yes` / `no` | |
| `notice_period` | `2 weeks` | |
| `salary` | `180000` or `180K-190K` | jobwatch fills it from `pay.target` (and `pay.target_max`) when unset, never `pay.floor`. The extension offers it unticked. |
| `gender`, `race`, `hispanic`, `veteran`, `disability` | `decline` | Voluntary self-identification. `decline` picks the form's "I don't wish to answer" choice. jobwatch defaults each to `decline`. |

## Endpoints

### `GET /ext/ping`

`{"ok": true, "version": "0.9.0", "features": ["posting", "import-list"]}`. Used by the options page to test pairing. `features`
names what jobwatch offers beyond filling: the side panel shows **Save this posting to jobwatch** only when it has
`posting` (`POST /ext/posting`), so an older jobwatch, which sends no `features`, gets no button that would fail. The
other names: `import-list`, `reply`, `ats` (`POST /ext/ats`), `cover` (`POST /ext/cover`) and `list-ladders` (a jobwatch
that takes Ladders records in `POST /ext/import-list`: it keeps a Ladders job's page only as a reference note and its pay
estimate out of the job's pay; without it the panel offers no Read the jobs on this list on a Ladders list) and
`auto-read` (`GET /ext/read-queue` and `POST /ext/read-report`, below: the extension offers reading postings by itself only
to a jobwatch that has them).

### How a page is matched to a job

`context`, `resume`, `tailor`, `draft`, `ats` and `cover` all take the page's `url` and, optionally, the `company` and
`title` the page shows (the extension sends them on a page that is not LinkedIn or Indeed; on those two it sends the
address only). The job is found, in this order, by:

1. the posting id of a supported board's address (`matched_by: "board"`);
2. a link jobwatch stored for the job (`"link"`);
3. a LinkedIn job number (the address's `currentJobId` or `/jobs/view/<n>`, in the job's link or in the note saying where
   an alert found it) (`"linkedin"`), or an Indeed `jk` or `vjk` (in the job's link, or a note) (`"indeed"`);
4. company plus normalised title (`"name"`): only for a page on a company's own site (not linkedin.com or indeed.com, and
   not a supported board's page with a posting id of its own), and only when exactly one open job at that company has
   that title. Never a guess among several; a closed job is never matched this way.

`matched_by` is in `job` (`context`) and in every `ats` and `cover` answer, so the panel can tell the person when a job
was matched by name alone. A page with no match: `job` is `null` (`context`), or `404 {"error": "jobwatch doesn't track
this job yet: save the posting to jobwatch first"}` (`ats`, `cover`). `/ext/submitted` and `/ext/answers` still match by
address only (a wrong name match there would mark the wrong job applied).

### `GET /ext/context?url=<the page's address>&company=&title=`

What jobwatch knows for the application on that page.

```json
{
  "job": {"key": "ashby:initech/4f1c…", "title": "Platform Engineer", "company": "Initech",
          "status": "queued", "url": "https://jobs.ashbyhq.com/initech/4f1c…"},
  "applicant": {"first_name": "Jordan", "...": "..."},
  "resume": {"name": "resume.pdf", "type": "application/pdf", "tailored": false},
  "answers": [{"question": "Notice period?", "answer": "Two weeks.", "company": "Globex",
               "title": "SRE", "applied_at": "2026-09-14"}],
  "can_tailor": true
}
```

- `job` is `null` when the page isn't for a job jobwatch can tell (then `/ext/submitted` adds it). Otherwise it carries
  `matched_by` (see above).
- `resume` is the one saved with this job's application package if there is one (`tailored: true`), else the
  watchlist's `resume:`; `null` when there's neither.
- `can_tailor` is true when jobwatch knows the job and resume-kit is set up: `/ext/tailor` can make one.
- `answers` are the form answers kept from earlier applications, newest first, each in full.

### `GET /ext/resume?url=<the page's address>&company=&title=`

The resume file `context` named, as bytes, with its `Content-Type` and a `Content-Disposition` filename.
404 when there's none.

### `POST /ext/tailor`

`{"url": "<the page's address>", "company": "", "title": ""}` (`company` and `title` optional): tailors a resume to that page's job with resume-kit (a minute or two) and
keeps it with the job's application, so `/ext/resume` gives that one from now on. Answers what jobwatch's own
Tailor resume does (`version`, `new`, `pages`, `ok`: resume-kit's checks passed, `problems`), plus `resume`:
`{"name", "type", "tailored": true}`. 404 when jobwatch doesn't track the job; 400 when resume-kit isn't set
up or fails.

### `POST /ext/draft`

```json
{"url": "<the page's address>", "company": "", "title": "", "question": "Why do you want to work here?", "words": 150,
 "others": [{"question": "Tell us about a project you led.", "answer": "…"}]}
```

→ `{"answer": "…", "model": "claude-sonnet-5-5"}`. Drafted by the watchlist's chat model from the resume, the
stories file and the posting (when the job is known). `words` is a rough length (default 150). `others`, optional,
are the form's other written answers so far (drafted, past or typed): the draft won't retell their stories. A model that
isn't set up answers `400 {"error": "..."}` saying what to set up. Drafts are for the person to review: the
extension never ticks one by default.

### `POST /ext/ats`

`{"url": "<the page's address>", "company": "", "title": ""}`: the ATS check of the job's resume (the tailored one
kept with the job, else the watchlist's `resume:`), the same check as `jobwatch ats` and the Prepare button on a queued
job's card. A local keyword check with no model; nothing is sent anywhere and nothing is changed.

```json
{"key": "ashby:initech/4f1c…", "company": "Initech", "title": "Platform Engineer", "file": "resume.pdf",
 "tailored": false, "read_with": "pdftotext", "chars": 2400, "score": 50,
 "found": [{"term": "Python", "kind": "must", "count": 3}],
 "missing": [{"term": "Terraform", "kind": "must", "count": 2}, {"term": "Kafka", "kind": "nice", "count": 1}],
 "checks": [], "matched_by": "link", "can_tailor": true}
```

`score` is 0 to 100 (must-have terms count double), `null` when the posting names no keywords. `missing` is what a
screener would miss; `checks` are formatting problems a parser would trip on. `can_tailor` is true when resume-kit is
set up (`/ext/tailor`). `404` when jobwatch doesn't track the job (see above); `400 {"error": "…"}`, in words for the
panel, when the job has no posting text (press **Save this posting to jobwatch**) or there is no resume or no way to
read it. Only shown when `/ext/ping`'s `features` has `ats`.

### `POST /ext/cover`

`{"url": "<the page's address>", "company": "", "title": "", "tone": "direct", "emphasis": "my deploy work"}`
(`tone`: direct, warm, formal or concise; `emphasis`, optional, what to lean on): drafts a cover letter for the job
with `cover.draft`, the same function as `jobwatch cover` and the Prepare button's last step, and keeps it with the job
as its next version (`covers/<job>/vN.md`).

```json
{"key": "ashby:initech/4f1c…", "company": "Initech", "title": "Platform Engineer", "tone": "direct", "emphasis": "",
 "letter": "Hello Initech team, …", "warnings": [], "model": "local model", "local": true, "drafted": true,
 "version": 1, "matched_by": "link"}
```

Like `/ext/reply`, it is written by the shared local model only, so the posting, the resume and the stories stay on the
computer; the watchlist's `reply: {backend: chat}` makes the chat's model write it instead, and then `local` is `false`
and `model` names it. A model that isn't running, or a resume with no text, answers `drafted: false`, `letter: ""` and
the why in `warnings`. `warnings` also lists what the code found in a letter (a figure the resume doesn't show, a stock
opener). An unknown tone, or a job with no posting text: `400`; no such job: `404`. A slow local model can take a
minute or two, so the extension waits up to 120 seconds. Only shown when `/ext/ping`'s `features` has `cover`. The
extension puts the letter in the form's cover letter box only when the person presses **Fill the cover letter box** (an
empty textarea; replacing text is a separate press) and never presses Submit.

### `POST /ext/reply`

```json
{"thread": "Dana Whitfield, Nov 12, 9:41 AM\nHi Jordan, …", "sender": "Dana Whitfield", "company": "Northwind Talent"}
```

`thread` is the text of the one open message thread, as read from the page (`sender` and `company` are optional: what
the page showed). → `{"reply": "…", "notes": ["…"], "warnings": ["…"], "company": "Initech", "model": "local model",
"local": true, "drafted": true}`. By default the reply is written by the shared local model server only (never Claude,
whatever the chat is set to), so the thread stays on the computer. It reads the thread, the resume, the stories and
what's tracked at that company (its applications, notes and pay lines kept with `comp`), under fixed reply rules.
`notes` are one to three things to check before sending, `warnings` are what the code found: an application or
referral in flight at that company (the reply itself says nothing about it), a figure in the draft that isn't in the
thread or the pay lines, or a stock opener. A thread that asks for no AI gets `reply: ""`, `drafted: false` and a
warning instead of a draft, and so does a model that isn't running. The thread isn't kept. Only shown when
`/ext/ping`'s `features` has `reply`. An empty thread: `400`. The extension types `reply` into the message box and
never presses Send.

**Opt-in to a bigger model:** the watchlist's `reply: {backend: chat}` makes the chat's backend and model write the
draft instead (`chat.backend: claude`: Anthropic's model, through the API key the chat already uses; jobwatch adds
no other way to pay or sign in). Then the thread, the resume's text and the tracker's lines for that company leave
the computer for Anthropic; `local` is `false` and `model` names the model, so the panel can say so. `reply:
{backend: local}` (the default) keeps everything local.

### `POST /ext/answers`

Sent the moment the person presses the form's Submit (the form's `submit` event, or a click on its submit button),
from the service worker, so a page that navigates away loses nothing.

```json
{"url": "<the page's address>", "answers": [{"question": "Notice period?", "answer": "Two weeks."}]}
```

→ `{"saved": true, "key": "ashby:initech/4f1c…", "status": "queued", "count": 1}`. The answers, as they stood
(the person's own edits included), replace the answers in the job's package; pressing Submit again (after a
validation error, say) updates the same package. The job's status is **not** changed: only a confirmation page
(`/ext/submitted`) records an application. A page jobwatch doesn't know gets `{"saved": false, "why": "…"}`.

### `POST /ext/submitted`

Sent after the person submits the form.

```json
{"url": "<the page's address>", "company": "Initech", "title": "Platform Engineer",
 "answers": [{"question": "Notice period?", "answer": "Two weeks."}], "resume": "resume.pdf"}
```

→ `{"key": "ashby:initech/4f1c…", "status": "applied", "added": false}`. The job is marked applied (an
application already further along keeps its stage), the answers are kept in its package, and the resume it
named is attached to the package. A page jobwatch doesn't know yet is added from its link, with `company` and
`title` from the page when the link can't be read; `added` says so.

### `POST /ext/import-list`

Sent when the person presses **Read the jobs on this list** on a LinkedIn, Indeed or Ladders list of jobs (only shown when
`/ext/ping`'s `features` has `import-list`, and for Ladders `list-ladders` too). The extension reads the list's cards with
`job-lists.js`, page after page (up to ten), and sends them all at once:

```json
{"records": [{"source": "linkedin", "id": "4100000001", "title": "Platform Engineer", "company": "Initech",
              "location": "Boulder, CO (Hybrid)", "pay": "$120K/yr - $180K/yr", "posted": "2 days ago"}]}
```

A Ladders record (`source: "ladders"`, `id`: the number ending the job's path) also has `url`, the job's page on Ladders. It
is a reference, kept in the job's note and never as where to apply (the jobs are the companies' own); the `pay` is Ladders'
own estimate, so it goes in the note too, not in the job's pay.

jobwatch counts the jobs it already tracks and looks for each new one on the company's own board (see
`jobwatch import-list`); that can take a few minutes for a long list. → the counts overall and per site
(`seen`, `tracked`, `earlier`, `added`, `unplaced`, `coverage` from 0 to 1: tracked over seen, `note`: "Same list as before: nothing new" when most was imported earlier, `by_source`), `summary` (the text
`jobwatch import-list` prints), and `added` and `unplaced`: the jobs, each with `company`, `title`, `location`, `key`
and, for unplaced ones, `why`. No records: `400`.

### `POST /ext/posting`

Sent when the person opened a company's posting from a LinkedIn job, or presses **Save this posting to jobwatch**.
Nothing is taken from LinkedIn's pages: `linkedin` is the job's address or number only.

```json
{"linkedin": "https://www.linkedin.com/jobs/view/3900000123/", "page_url": "https://jobs.lever.co/globex/aaaa-1111",
 "company": "Globex", "title": "Machine Learning Engineer", "text": "<the company page's visible job text>"}
```

Every field is optional but one of `linkedin`, `indeed`, `page_url` or `company` with `title` is needed. `indeed` is an
Indeed job's key (the `jk` of its address), sent by Read posting (`read-posting.js`) with the page's description as `text`,
and `closed: true` when LinkedIn says the posting takes no more applications (kept as a note, nothing is closed). The job is
found by its LinkedIn number (its link, or the note saying where it was found) or Indeed key (its link), else by
`page_url`, else by company and title. It is
filled in, keeping its key, status and notes: from `page_url` when that is a posting on a supported board (read as for
a link added by hand), else from `text`. No job found: one is added. → `{"key": "…", "company": "Globex",
"title": "…", "added": false, "has_text": true, "where": "queue", "said": "Filled in from Lever; scoring now"}`;
`where` is the tab of jobwatch's page the job is on. A page jobwatch can't read, sent with no `text`, answers `400`
saying to use **Save this posting to jobwatch** on it.

`auto: true` (new, with feature `auto-read`) marks a read the extension started by itself (auto-read, below). jobwatch
refuses it with `400` unless Settings has Read postings automatically on, saves the text exactly as for a pressed Read
posting, logs "Read <title> at <company> from linkedin.com" (or `indeed.com`) in Activity, and does not start a score
(`scoring: false`): only the usual automatic-scoring rules and caps apply.

### `GET /ext/read-queue?linkedin=<n>&indeed=<n>&limit=<n>`

Sent by auto-read (`auto-reader.js`) before each read. `linkedin` and `indeed` are how many reads the extension has left
today for each site; a site with none gets no job. `limit` is at most 5. → `{"enabled": true, "limits": {"per_day": 25,
"daily_max": 50, "pause_min": 120, "pause_max": 180}, "waiting": 12, "jobs": [{"key": "…", "site":
"linkedin", "url": "https://www.linkedin.com/jobs/view/3900000123/", "title": "…", "company": "…"}]}`. jobwatch chooses:
jobs that pass the title, place, pay and fit filters Today applies, with no text, not closed, a duplicate, snoozed or
skipped, not tried in the last 3 days, and at a company with no own board it watches, best first. With the setting off:
`enabled: false` and no jobs. The extension clamps `limits` to its own ceilings (25 a site by default, 50 in all, a
pause never under 60 s) whatever this says.

### `POST /ext/read-report`

Tells jobwatch what auto-read did, for Activity (and so a job that gave no text is not handed over again at once).
Either `{"outcome": "no_text" | "trouble" | "cancelled", "key": "…", "site": "linkedin", "reason": "…"}` (logged "Couldn't
read <title> at <company> from linkedin.com: <reason>") or `{"event": "paused" | "resumed" | "off" | "on", "reason":
"…"}`; a `paused` with a reason is a stop for the day, logged as worth a look. → `{"ok": true}`; anything else `400`.
