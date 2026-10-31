# The extension's API (jobwatch side)

The browser extension fills job application forms. On its own it fills the basics from details kept in the
browser. Paired with `jobwatch ui` on the same computer, it also gets the job the page is for, the resume to
attach, answers given on earlier applications, drafted answers to new questions, and it records the application
when the person submits it.

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

One flat object, the same shape in the extension's own storage and in jobwatch (the watchlist's `applicant:`
section). Every field is text; an empty string means "not set, leave the form's field alone".

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
| `salary` | `180000` or `180K-200K` | jobwatch fills it from `pay.target` (and `pay.target_max`) when unset. |
| `gender`, `race`, `hispanic`, `veteran`, `disability` | `decline` | Voluntary self-identification. `decline` picks the form's "I don't wish to answer" choice. jobwatch defaults each to `decline`. |

## Endpoints

### `GET /ext/ping`

`{"ok": true, "version": "0.9.0"}`. Used by the options page to test pairing.

### `GET /ext/context?url=<the page's address>`

What jobwatch knows for the application on that page.

```json
{
  "job": {"key": "ashby:initech/4f1c…", "title": "Platform Engineer", "company": "Initech",
          "status": "queued", "url": "https://jobs.ashbyhq.com/initech/4f1c…"},
  "applicant": {"first_name": "Jordan", "...": "..."},
  "resume": {"name": "resume.pdf", "type": "application/pdf"},
  "answers": [{"question": "Notice period?", "answer": "Two weeks.", "company": "Globex",
               "title": "SRE", "applied_at": "2026-09-14"}]
}
```

- `job` is `null` when the page isn't for a job jobwatch can tell (then `/ext/submitted` adds it).
- `resume` is the one saved with this job's application package if there is one, else the watchlist's
  `resume:`; `null` when there's neither.
- `answers` are the form answers kept from earlier applications, newest first, each in full.

### `GET /ext/resume?url=<the page's address>`

The resume file `context` named, as bytes, with its `Content-Type` and a `Content-Disposition` filename.
404 when there's none.

### `POST /ext/draft`

```json
{"url": "<the page's address>", "question": "Why do you want to work here?", "words": 150}
```

→ `{"answer": "…", "model": "claude-sonnet-5-5"}`. Drafted by the watchlist's chat model from the resume, the
stories file and the posting (when the job is known). `words` is a rough length (default 150). A model that
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
