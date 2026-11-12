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
`posting` (`POST /ext/posting`), so an older jobwatch, which sends no `features`, gets no button that would fail.

### `GET /ext/context?url=<the page's address>`

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

- `job` is `null` when the page isn't for a job jobwatch can tell (then `/ext/submitted` adds it).
- `resume` is the one saved with this job's application package if there is one (`tailored: true`), else the
  watchlist's `resume:`; `null` when there's neither.
- `can_tailor` is true when jobwatch knows the job and resume-kit is set up: `/ext/tailor` can make one.
- `answers` are the form answers kept from earlier applications, newest first, each in full.

### `GET /ext/resume?url=<the page's address>`

The resume file `context` named, as bytes, with its `Content-Type` and a `Content-Disposition` filename.
404 when there's none.

### `POST /ext/tailor`

`{"url": "<the page's address>"}`: tailors a resume to that page's job with resume-kit (a minute or two) and
keeps it with the job's application, so `/ext/resume` gives that one from now on. Answers what jobwatch's own
Tailor resume does (`version`, `new`, `pages`, `ok`: resume-kit's checks passed, `problems`), plus `resume`:
`{"name", "type", "tailored": true}`. 404 when jobwatch doesn't track the job; 400 when resume-kit isn't set
up or fails.

### `POST /ext/draft`

```json
{"url": "<the page's address>", "question": "Why do you want to work here?", "words": 150,
 "others": [{"question": "Tell us about a project you led.", "answer": "…"}]}
```

→ `{"answer": "…", "model": "claude-sonnet-5-5"}`. Drafted by the watchlist's chat model from the resume, the
stories file and the posting (when the job is known). `words` is a rough length (default 150). `others`, optional,
are the form's other written answers so far (drafted, past or typed): the draft won't retell their stories. A model that
isn't set up answers `400 {"error": "..."}` saying what to set up. Drafts are for the person to review: the
extension never ticks one by default.

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

Sent when the person presses **Import this list** on a LinkedIn or Indeed list of jobs (only shown when `/ext/ping`'s
`features` has `import-list`). The extension reads the list's cards with `job-lists.js`, page after page (up to ten),
and sends them all at once:

```json
{"records": [{"source": "linkedin", "id": "4100000001", "title": "Platform Engineer", "company": "Initech",
              "location": "Boulder, CO (Hybrid)", "pay": "$120K/yr - $180K/yr", "posted": "2 days ago"}]}
```

jobwatch counts the jobs it already tracks and looks for each new one on the company's own board (see
`jobwatch import-list`); that can take a few minutes for a long list. → the counts overall and per site
(`seen`, `tracked`, `earlier`, `added`, `unplaced`, `coverage` from 0 to 1, `by_source`), `summary` (the text
`jobwatch import-list` prints), and `added` and `unplaced`: the jobs, each with `company`, `title`, `location`, `key`
and, for unplaced ones, `why`. No records: `400`.

### `POST /ext/posting`

Sent when the person opened a company's posting from a LinkedIn job, or presses **Save this posting to jobwatch**.
Nothing is taken from LinkedIn's pages: `linkedin` is the job's address or number only.

```json
{"linkedin": "https://www.linkedin.com/jobs/view/3900000123/", "page_url": "https://jobs.lever.co/globex/aaaa-1111",
 "company": "Globex", "title": "Machine Learning Engineer", "text": "<the company page's visible job text>"}
```

Every field is optional but one of `linkedin`, `page_url` or `company` with `title` is needed. The job is found by its
LinkedIn number (its link, or the note saying where it was found), else by `page_url`, else by company and title. It is
filled in, keeping its key, status and notes: from `page_url` when that is a posting on a supported board (read as for
a link added by hand), else from `text`. No job found: one is added. → `{"key": "…", "company": "Globex",
"title": "…", "added": false, "has_text": true, "where": "queue", "said": "Filled in from Lever; scoring now"}`;
`where` is the tab of jobwatch's page the job is on. A page jobwatch can't read, sent with no `text`, answers `400`
saying to use **Save this posting to jobwatch** on it.
