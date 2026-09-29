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

## Tracking

```
jobwatch show aaaa-1111                    # full posting text: for tailoring a resume
jobwatch mark applied aaaa-1111 --note "referred by a friend"
jobwatch mark skipped greenhouse:acme:102
jobwatch list --status applied
```

A digest lists each job once. Use `digest --all` to include jobs already shown, or `--peek` to look without
marking them shown. Roles that disappear from a board are marked closed.

## MCP server

`jobwatch-mcp` offers `find_board`, `fetch_jobs`, `digest`, `job_details`, `mark_job` and `list_jobs` to
Claude Code or any MCP client. The watchlist comes from `JOBWATCH_CONFIG`:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp
```

With a resume tool alongside it, an assistant can take you from "what's new today?" to a tailored resume
and a filled-in application for you to review. You still press Submit.

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

Tests use canned board responses and never touch the network. Releases publish to PyPI through Trusted
Publishing when a `v*` tag is pushed.

MIT licensed.
