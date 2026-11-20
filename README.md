# jobwatch

<!-- mcp-name: io.github.vinayvobbili/jobwatch -->

[![CI](https://github.com/vinayvobbili/jobwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/vinayvobbili/jobwatch/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/jobwatch)](https://pypi.org/project/jobwatch/)
[Home page](https://vinayvobbili.github.io/jobwatch/)

Watch the job boards of the companies you care about and get a short, ranked digest of **new** roles that
match you, optionally fit-scored against your resume. jobwatch finds and ranks. It never applies for you.

![jobwatch: watch boards, rank by fit, ask about your jobs, track applications, prep for interviews](https://vinayvobbili.github.io/jobwatch/demo.gif)

With sound (1½ minutes, made from made-up data):

https://github.com/user-attachments/assets/71b048d0-d372-42fd-a247-c4a59c3ffd71

## Get started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), which brings Python with it, then jobwatch:

```
curl -LsSf https://astral.sh/uv/install.sh | sh      # Mac or Linux (or: brew install uv)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"      # Windows (or: winget install astral-sh.uv)

uv tool install jobwatch
jobwatch ui
```

Already have Python? `pipx install jobwatch` works too.

A page opens on your computer and walks you through four short steps: about you and your resume, the jobs you
want, the companies to watch, and (optionally) fit scores and job-alert emails. Then press **Check for new
jobs**. Install the page as an app from Chrome's address bar to keep it in its own window, or run
`jobwatch service install` to have it always running, on macOS, Linux or Windows (a launchd agent, a systemd user
unit or a Task Scheduler task).

**Or run it from Claude:**

- **Claude Code** (the Claude app's Code tab, the terminal, and Cowork): `/plugin marketplace add
  vinayvobbili/jobwatch`, then `/plugin install jobwatch@jobwatch` (or Settings → Plugins → Add marketplace). The
  [plugin](https://github.com/vinayvobbili/jobwatch/blob/main/plugin/README.md) brings the tools and a skill with
  the daily routine, and runs jobwatch with uv. Then ask Claude "watch Stripe for product designer roles".
- **Claude Desktop with Settings → Extensions**: [download the extension](https://github.com/vinayvobbili/jobwatch/releases/latest/download/jobwatch.mcpb)
  (`jobwatch.mcpb`, always the latest release), open it and press Install.
  Claude Desktop sets up everything it needs, uv included.

A chat on claude.ai, or in an app whose plugins run in the cloud, can't reach jobwatch on your computer.

Extras: `jobwatch[score]` (fit scores with the Claude API), `jobwatch[local]` (fit scores with a local model on any
OpenAI-compatible server, `LOCAL_LLM_URL` if it isn't at `http://127.0.0.1:8010/v1`), `jobwatch[mcp]` (an MCP server),
`jobwatch[video]` (drill videos) and `jobwatch[lca]` (H-1B wage filings as a second pay source). Prefer a terminal?
`jobwatch init`, `jobwatch find "Globex"`, then `jobwatch run` daily.
[More on the page and the command line →](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/the-page.md)

## Example

All of this is made-up data. A digest entry (the same text `jobwatch run` prints and `get_digest` returns):

```
# jobwatch digest

Top 2 of 9 matching job(s). Filtered out: 14 by location, 31 by title.
Scored 2 with shortlist-ai.

### [Senior Platform Engineer](https://jobs.ashbyhq.com/initech/7f3a1c)
Initech; Remote (US) · $180K–$220K · posted 1d ago
**Fit 78/100**, must-haves 4/6 (scored by Qwen3.5-9B · local). Gaps: Observability (metrics, tracing); Led an on-call rotation
Source: Initech's Ashby board
`ashby:initech:7f3a1c`
```

The card behind that score, from `jobwatch show ashby:initech:7f3a1c`, with the resume's own words per verdict:

```
Fit 78/100, must-haves 4/6 (scored by Qwen3.5-9B · local)
  met     [must] 5+ years running Kubernetes in production  "Ran 40-node Kubernetes clusters for 6 years at Globex"
  met     [must] Terraform or similar infrastructure as code  "Wrote the Terraform modules behind 120 services"
  met     [must] Python for tooling and automation  "Python: CLI tools, CI pipelines, internal APIs"
  partly  [must] Observability (metrics, tracing)  "Set up Prometheus dashboards for the payments team"
  met     [must] Incident response  "Cut mean time to recover from 90 to 25 minutes"
  missing [must] Led an on-call rotation
  met     [nice] Postgres operations  "Tuned Postgres replicas serving 5K queries per second"
```

## Why trust it

- About 2,400 tests in 121 modules, none of which touch the network (a fixture fails any test that tries).
- CI runs ruff and the whole suite on Python 3.10 and 3.13 for every push; the same checks run before every push.
- Fit scoring was checked on a small eval of 29 expected verdicts: the suggested 16 GB model (Qwen3.5-9B, 4-bit)
  agreed on 28, Gemma 4 12B on 29. Only the 16 GB row of the model table was tested.
  [Fit scores](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/fit-scores.md)

## Design in 5 lines

1. Poll each company's public board or API once per run, follow robots.txt, back off when asked.
2. Keep only new roles that pass your title, place and pay filters, ranked by keyword relevance.
3. Fit-score only the top few per digest (`scoring.top`, 5 in the example watchlist): your resume against the
   posting's must-haves and nice-to-haves.
4. Quote-verify: each verdict carries the resume's own words, checked against the resume text.
5. A job is scored once, and the score says which model made it, so a new model or an edited resume never triggers
   a surprise bill.

## Limits

- It reads the boards in the table below. A company on any other system isn't watched; add its jobs through
  job-alert emails, a link or pasted text. It doesn't scrape LinkedIn or Indeed.
- It finds and ranks. It never applies; you answer the forms and press Submit.
- Fit scores are an LLM's judgment, checked against your resume's text, not against how a recruiter reads it.
- The always-on service needs launchd, systemd or Task Scheduler; elsewhere run `jobwatch ui` when you want the page.

## What it does

| | |
|---|---|
| **Watches company boards** | Greenhouse, Lever, Ashby, Workable, Workday, Eightfold, Oracle, SmartRecruiters, Rippling, iCIMS, Jobvite, Comeet, Gem, Recruitee, Avature, Google, Amazon, careers sites with a job sitemap, HN's Who is hiring and VC portfolio job boards (one board, hundreds of companies). Fresh roles, real pay ranges, robots.txt respected. [Why boards](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/boards.md) · [the watchlist](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/watchlist.md) |
| **Scores fit** | Your resume against each posting: must-haves met, gaps, a score out of 100. On the Claude API, Antigravity, or this Mac. [Fit scores](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/fit-scores.md) |
| **Keeps a short queue** | Today's picks, a queue to apply from, job-alert emails and status emails read for you, reposts caught. [Applying](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/applying.md) |
| **Tailors a resume per job** | With [resume-kit](https://github.com/vinayvobbili/resume-kit) installed, one button on a queued job builds a resume from your confirmed facts and keeps it with the application for Apply and the extension to attach. [Tailoring](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/applying.md#tailoring-a-resume-to-a-job) |
| **Drafts the paperwork** | An ATS keyword check, cover letters, follow-up emails; a local model writes them and nothing is sent. [ATS](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/applying.md#checking-a-resume-for-ats-keywords) · [Cover letters](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/applying.md#drafting-a-cover-letter) · [Follow-ups](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/tracking.md#follow-up-and-thank-you-drafts) |
| **Fills forms for review** | A [Chrome extension](https://chromewebstore.google.com/detail/jobwatch-application-fill/abackmpdpfflgiaccgfkababjplgolfi) fills from your details and earlier answers; you press Submit. [Filling forms](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/applying.md#filling-application-forms) |
| **Tracks applications** | Every stage, the next step, follow-ups for the ones gone quiet, a calendar feed. [Tracking](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/tracking.md) |
| **Preps interviews** | A prep sheet per interview, answers drafted from your own stories, a mock interview, a drill video, ranked likely questions. [Interview prep](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/interview-prep.md) |
| **Compares offers** | Pay, career value and company health side by side, and an estimate where a posting lists no pay. [Comps](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/comps.md) |
| **Shows who you know** | Your LinkedIn connections at each company, the people you actually talk to first. [Who you know](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/contacts.md) |
| **Answers questions** | A chat about today's jobs and each posting, and the skills your matches keep asking for. [Chat](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/chat.md) · [Skills](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/skills.md) |
| **Works with assistants** | An MCP server and an agent skill, so Claude can run your search with you. [MCP server](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/mcp.md) |

Everything stays on your computer, except what a model you choose for fit scores and chat receives: the Claude API
or Antigravity get the posting and your resume (and your stories, for drafted answers). On-device models send nothing.

## Tutorials

Seven videos of two minutes or less, made from made-up data. If one stops early, reload the page.

- [Getting started](https://github.com/user-attachments/assets/f95f85df-406f-4ede-b84c-59569d1a586a): install, the four onboarding steps, Today.
- [Your daily routine](https://github.com/user-attachments/assets/8653c4ca-a79d-4135-9be1-51ba3c9fccf6): picks, a job's details, the queue, "I applied", the prep sheet.
- [Where the AI runs](https://github.com/user-attachments/assets/40e6f2cb-c201-4da9-ba21-77bdacc464b8): the Claude API, Antigravity or this Mac; what leaves your computer.
- [Applying](https://github.com/user-attachments/assets/9d021676-85da-4ce1-8d42-f3808b4ae03b): the queue, job-alert emails, status emails, companies to watch.
- [Tracking applications](https://github.com/user-attachments/assets/e2e43a54-83d2-4154-9229-a063fafefe44): stages, follow-ups, the calendar feed, Interviews.
- [Interview prep](https://github.com/user-attachments/assets/c8ac1030-700f-4cdd-823d-4b92cd411bf3): prep sheets, drafted answers, a mock interview, a drill video.
- [Comps and who you know](https://github.com/user-attachments/assets/42eb0edb-945e-4caf-95c0-3eeae6fdada6): pay, career value and company health side by side; the people you know there.

## Why it doesn't auto-apply

Tools that auto-apply to hundreds of jobs rarely work: recruiters recognize mass applications, some companies cap
how many roles one person can apply to, and forms ask legal questions (work authorization, export control,
signatures) that you answer yourself. jobwatch makes sure you never miss a role worth applying to.
[Getting more interviews](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/more-interviews.md)
has what moves an application from the pile to a recruiter's call.

## The guide

Everything else, from every watchlist setting to the drill video, is in
[the guide](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/README.md).
[Development](https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide/development.md) covers running the
tests and making a release. MIT licensed.

If jobwatch helps your search, a ⭐ on GitHub is how I know: jobwatch has no usage tracking, so stars are the
only count of who uses it. If it landed you an interview, a [$1 coffee](https://ko-fi.com/vinayvobbili) says so too.

<sub>Listed on:
[M8ven](https://m8ven.ai/mcp/vinayvobbili-jobwatch-1cvk7w?s=readme) ·
[Glama](https://glama.ai/mcp/servers/vinayvobbili/jobwatch) ·
[mcpservers.org](https://mcpservers.org/servers/vinayvobbili/jobwatch) ·
[AI Agents Listing](https://aiagentslisting.com/mcp/jobwatch) ·
[Agensi](https://www.agensi.io/skills/jobwatch)</sub>
