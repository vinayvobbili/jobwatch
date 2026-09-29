# jobwatch

Watch the job boards of the companies you care about and get a short, ranked digest of **new** roles that
match you, optionally fit-scored against your resume. jobwatch finds and ranks. It never applies for you.

```
$ jobwatch run
Checked 48 board(s): 9,412 open roles, 37 new.

# jobwatch digest

6 matching job(s). Filtered out: 22 by location, 4 by pay, 5 by title.

### [Staff AI Engineer](https://jobs.ashbyhq.com/initech/c1)
Initech · Denver, CO, United States; Remote · $230K–$300K · posted today
**Fit 81/100**, must-haves 6/7. Gaps: 3+ years with Kubernetes in production
Keywords: Python, RAG, agents
`ashby:initech:c1`
...
```

## Why company boards

Most tech companies post jobs through Greenhouse, Lever or Ashby. All three publish open roles as public
JSON so anyone can build a careers page, with no API key or scraping. jobwatch reads those feeds for the
companies on your watchlist:

- **Complete and fresh:** a role appears as soon as the company posts it, not when an aggregator picks it up.
- **Pay ranges:** read from the board's structured fields where they exist (Lever, Ashby), otherwise from
  the posting text.
- **Polite:** one request per company per run.
- **Within the rules:** it reads public APIs meant for this. It doesn't scrape LinkedIn or Indeed, which
  forbid it.

## Install

```
pip install jobwatch                 # discovery, filters, digest
pip install 'jobwatch[score]'        # + fit scores with shortlist-ai (Claude API)
pip install 'jobwatch[local]'        # + fit scores on-device (Apple Silicon, MLX)
pip install 'jobwatch[mcp]'          # + MCP server for Claude and other assistants
```

## Quick start

### In your browser

```
pipx install jobwatch      # or: pip install jobwatch
jobwatch ui
```

A page opens on your computer. Add the companies you want to watch (type a name or paste a link to one of
their jobs), say what you're looking for, and press **Check for new jobs**. From there:

- **Today:** new matching jobs, with pay, how long ago they were posted, keywords, and who you know there.
  **Queue** the ones worth applying to, **Skip** the rest.
- **Queue:** your short list. Apply on the company's site, then press **I applied**.
- **Applications:** every job you applied to and where it stands (applied, screening, interviewing, offer,
  rejected, withdrawn), with the next step and a follow-up day. Those due come first. **Add an application**
  covers jobs you found elsewhere, such as a referral or a recruiter.
- **Settings:** companies, filters, keywords, your resume (for fit scores) and your LinkedIn connections.
- **Ask jobwatch:** a chat on Today (about all of today's jobs and your applications) and beside each job's
  details (about that posting). See [Chat](#chat).

The page only talks to jobwatch on your own machine. The one exception is a model you choose: with
`scoring.backend: claude`, fit scores and chat send the posting and your resume to Anthropic. It's the same
watchlist file and history as the command line, so you can switch between the two.

### On the command line

```
jobwatch init                         # writes an example jobwatch.yaml
jobwatch find "Anthropic" "Scale AI"  # find each company's board
jobwatch find https://jobs.lever.co/spotify/4f1c2a9e-...   # or paste any job link
```

`find` prints a line like `Anthropic: greenhouse:anthropic (627 open roles)`. Add those entries under
`companies:`, adjust the filters, then:

```
jobwatch run                          # fetch every board, then show the digest
```

Run it daily, for example from cron: `0 8 * * * jobwatch run -o ~/jobs-today.md`.

## The watchlist

```yaml
companies:
  - greenhouse:anthropic
  - lever:spotify
  - {source: ashby, board: openai, name: OpenAI}

filters:
  titles: ["engineer", "architect"]       # regexes; the title must match one
  exclude_titles: ["intern", "manager"]
  exclude_departments: ["sales"]
  locations: ["remote", "Denver", "Boulder, CO"]
  remote_country: US                      # remote roles must be open in the US ("any" to allow all)
  min_salary: 200000                      # the top of a listed range must reach this
  require_salary: false                   # true: drop postings without pay
  max_age_days: 30

keywords:                                 # relevance: title hits count double
  LLM: 3
  RAG: 3
  Python: 2
  "re:agent(s|ic)?": 2                    # "re:" prefix = regex

resume: ~/Documents/resume.pdf            # for fit scores
connections: ~/Downloads/linkedin.zip     # who you know at each company (see below)
scoring:
  backend: claude                         # or local
  top: 5                                  # score the 5 most relevant new jobs per digest
```

Relative paths are resolved from the watchlist's folder. State (which jobs you've seen, applied to or
skipped, and their scores) lives in one SQLite file, by default `~/.local/share/jobwatch/state.db`.

### How locations match

A posting can list several places (`London, UK; Remote-Friendly, United States; Austin, TX`), and each one
is checked:

- `remote` matches a place that says remote and is in `remote_country`, or says only "Remote". It also
  matches a posting whose own remote flag is set and that lists a US location.
- Any other entry matches as text, so `Denver` matches `Denver, CO, United States`.

## Fit scores

Keyword relevance is fast and explainable, but it can't tell "uses Kubernetes" from "5+ years running
Kubernetes in production". With `resume:` set and `scoring.top` (or `--score N`), the most relevant new
jobs are scored with [shortlist-ai](https://github.com/vinayvobbili/shortlist-ai):

1. It turns the posting into must-have and nice-to-have requirements.
2. It judges each requirement against your resume, with quotes it checks against the resume text.
3. It lists the must-haves the resume doesn't show.

Scores are stored per resume file content, so each job is scored once, and again only after you edit your
resume. The local backend takes minutes per job, so keep `top` small.

## Chat

Ask questions in plain words: "which three should I apply to first?", "what follow-ups are due?", "how well
do I fit this one, honestly?", "what will they ask in interviews?". The chat uses the model you set for fit
scores:

- `scoring.backend: local`: the same on-device model as scoring (`pip install 'jobwatch[local]'`). Nothing
  leaves your computer. The first answer waits for the model to load.
- `scoring.backend: claude`: Claude Sonnet via Anthropic's API (`ANTHROPIC_API_KEY`). Your question, your resume
  and the jobs it's about are sent to Anthropic.

It reads today's matching jobs and your applications, or one posting with its fit score and
[what you sent](#what-you-sent), plus your resume (the one you sent for that job, when it's kept).
It's told to use only your resume for facts about you and to treat posting text as data, not instructions.
It has no tools, so it can't change, apply for or send anything. The same thing works from the terminal:

```
jobwatch ask "What follow-ups are due this week?"
jobwatch ask --job c1 "What should my resume lead with for this one?"
```

## The apply queue

Pick the roles worth a tailored application from the digest and queue them. Work through the queue when
you have time:

```
jobwatch queue c1 aaaa-1111 --note "ask for a referral first"   # add (the posting id is enough)
jobwatch queue                             # what to apply to next, oldest first
jobwatch show aaaa-1111                    # full posting text: for tailoring a resume
jobwatch mark applied aaaa-1111 --note "referred by a friend"   # after you submit
jobwatch mark skipped greenhouse:acme:102
jobwatch list --status applied
```

Queued jobs leave the digest. The queue flags any posting that has since closed.

## Tracking applications

An application moves through stages: `applied`, `screening`, `interviewing`, `offer`, and then `rejected`
or `withdrawn`. Each can have a next step and a day to follow up. Jobs you found somewhere jobwatch doesn't
watch (a referral, a recruiter, LinkedIn) go in with `add`, so every application is in one list:

```
jobwatch add "Umbrella" "Principal Engineer" --url https://... --on 2026-09-14 --note "via a recruiter"
jobwatch mark screening c1 --next "technical round" --follow-up +7   # or a date: 2026-10-05
jobwatch mark rejected principal-engineer
jobwatch applications            # every application, follow-ups due first (alias: apps)
jobwatch applications --due      # only the ones to act on today
```

The day you applied is kept as an application moves through the stages. `--next ""` or `--follow-up ""`
clears a field.

### What you sent

Each application keeps what you submitted, as copies:
- the resume and cover letter exactly as uploaded;
- the answers you gave on the form (salary expectation, why this company, notice period...);
- the posting as it read the day you applied.

Tailored resumes get rebuilt and postings change or come down. When a recruiter calls three weeks later,
this is what they're looking at. The chat reads it too, so "prep me for the recruiter call" works from
what you actually told them.

In the browser, open an application's **Details** and drop files into **What you sent**. From the command
line:

```
jobwatch mark applied c1 --attach ~/Downloads/Resume_Initech.pdf
jobwatch attach c1 cover-letter.pdf --answers answers.yaml    # answers.yaml: "Why Initech?: ..." pairs
jobwatch package c1                                         # show it
```

Packages live in `packages/<job>/` next to the state file. Removing a file moves it to `.removed/` there
rather than deleting it.

## Who you know there

A referral gets read before an application does. Download your LinkedIn data (Settings → Data privacy →
Get a copy of your data) and upload the archive in `jobwatch ui`, or point `connections:` at the .zip or
at its Connections.csv. Each digest and queue entry then lists your connections who work there:

```
You know: Ana Li (Staff Engineer) [messaged 14×, last 2025-03-02]; Bo Chen (Recruiter)
```

With the full archive, people you actually talk to come first. jobwatch counts the messages you exchanged,
recommendations and endorsements, so a close colleague ranks above someone who only accepted a connection
request. Only those counts are kept, never your messages. When you know nobody at a company, the page links
to a LinkedIn search of your 2nd-degree network there, to find someone who can introduce you.

Companies are matched by name, ignoring suffixes like "Inc." and "Corporation". Your LinkedIn data is only
read on your machine.

A digest lists each job once. Use `digest --all` to include jobs already shown, or `--peek` to look without
marking them shown. Roles that disappear from a board are marked closed.

## MCP server

`jobwatch-mcp` offers `find_board`, `fetch_jobs`, `digest`, `job_details`, `mark_job`, `apply_queue`,
`add_application`, `applications`, `save_application_package`, `application_package` and `list_jobs` to Claude Code or any MCP client. The watchlist comes
from `JOBWATCH_CONFIG`:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp
```

With a resume tool alongside it (for example [resume-kit](https://github.com/vinayvobbili/resume-kit), whose
`resume draft` starts a tailored version from a posting), an assistant can work through your queue: read
the posting, tailor the resume from facts you've confirmed, check for a referral, and fill in the
application for you to review. You still press Submit.

## Why it doesn't auto-apply

Tools that auto-apply to hundreds of jobs make the process worse for everyone and rarely work for the
person using them:

- Recruiters recognize mass applications.
- Some companies cap how many roles one person can apply to.
- Application forms ask legal questions (work authorization, export control, signatures) that you answer
  yourself.

jobwatch's job is to make sure you never miss a role worth applying to, and to spend your time on those.

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev,mcp]'
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

Tests use canned board responses and never touch the network. To see how `jobwatch ui` looks after a change,
`scripts/screenshots.py` captures every tab in light and dark, at wide, desktop and phone widths, plus the
chat with a canned reply (it needs
`pip install playwright && python -m playwright install chromium`).

Releases publish to PyPI through Trusted
Publishing when a `v*` tag is pushed.

MIT licensed.
