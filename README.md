# jobwatch

<!-- mcp-name: io.github.vinayvobbili/jobwatch -->

[![M8ven Score](https://m8ven.ai/badge/mcp/vinayvobbili-jobwatch-1cvk7w?v=b3794e69984556a0e35f219ef71c5bca)](https://m8ven.ai/mcp/vinayvobbili-jobwatch-1cvk7w?s=readme)
[![vinayvobbili/jobwatch MCP server](https://glama.ai/mcp/servers/vinayvobbili/jobwatch/badges/score.svg)](https://glama.ai/mcp/servers/vinayvobbili/jobwatch)
[![Listed on mcpservers.org](https://mcpservers.org/badge.svg)](https://mcpservers.org/servers/vinayvobbili/jobwatch)
[![jobwatch on AI Agents Listing](https://aiagentslisting.com/jobwatch/badge.svg?claim=7ad06551a472272d8db3d80aa39a0895)](https://aiagentslisting.com/mcp/jobwatch)
[![jobwatch skill on Agensi](https://img.shields.io/badge/Agensi-skill-2563eb)](https://www.agensi.io/skills/jobwatch)

Watch the job boards of the companies you care about and get a short, ranked digest of **new** roles that
match you, optionally fit-scored against your resume. jobwatch finds and ranks. It never applies for you.

If jobwatch helps your search, a ⭐ on GitHub is how I know: jobwatch sends nothing home, so stars are the
only count of who uses it. If it landed you an interview, a [$1 coffee](https://ko-fi.com/vinayvobbili) says so too.

![jobwatch: watch boards, rank by fit, ask about your jobs, track applications, prep for interviews](https://raw.githubusercontent.com/vinayvobbili/jobwatch/main/docs/demo.gif)

[Watch it with sound](https://github.com/vinayvobbili/jobwatch/blob/main/docs/jobwatch-demo.mp4) (1½ minutes,
made from made-up data). Tutorials, under two minutes each:
[getting started](https://github.com/vinayvobbili/jobwatch/blob/main/docs/tutorials/jobwatch-01-getting-started.mp4),
[your daily routine](https://github.com/vinayvobbili/jobwatch/blob/main/docs/tutorials/jobwatch-02-daily-routine.mp4)
and [where the AI runs](https://github.com/vinayvobbili/jobwatch/blob/main/docs/tutorials/jobwatch-03-where-the-ai-runs.mp4).

```
$ jobwatch run
Checked 48 board(s): 9,412 open roles, 37 new.

# jobwatch digest

6 matching job(s). Filtered out: 22 by location, 4 by pay, 5 by title.
Applied today: 1 of 3. Good going.

### [Staff Data Engineer](https://jobs.ashbyhq.com/initech/c1)
Initech · Denver, CO, United States; Remote · $230K–$300K · posted today
**Fit 81/100**, must-haves 6/7. Gaps: 3+ years with Kubernetes in production
Keywords: Python, RAG, agents
`ashby:initech:c1`
...
```

## Why company boards

Most tech companies post jobs through Greenhouse, Lever, Ashby or Workable, and most large employers through
Workday (some through Eightfold, Oracle Recruiting Cloud, SmartRecruiters or a Jibe careers site), and many
small companies through Rippling. Each publishes open roles as public JSON so anyone can build a careers page, with
no API key or scraping; Google publishes its own (with YouTube's and DeepMind's) as an XML feed for job sites,
Amazon's careers site (amazon.jobs, with AWS) answers its own search in JSON, and Avature careers portals
(company career sites on Avature) list every posting in a sitemap for search engines, iCIMS careers sites
(careers-<company>.icims.com) list theirs in plain pages, and Jobvite careers sites (jobs.jobvite.com/<company>)
list every open role on one page. Hundreds of startups post once a month
in Hacker News' "Ask HN: Who is hiring?" thread, which HN's search API serves whole.
jobwatch reads those feeds for the companies on your watchlist:

- **Complete and fresh:** a role appears as soon as the company posts it, not when an aggregator picks it up.
- **Pay ranges:** read from the board's structured fields where they exist (Lever, Ashby), otherwise from
  the posting text. An hourly wage counts as the yearly pay it comes to (2,080 hours), so `$75–$80/hr` is
  held to `min_salary` as $156K–$166K.
- **Polite:** one request per company per run on Greenhouse, Lever, Ashby and Workable (a Jibe site: one per 100
  roles). A Workday, Eightfold or Oracle board can
  list thousands of roles, most of them nothing like yours, so jobwatch searches it for your
  `filters.titles` words and reads a posting in full only when its title passes your title filters, once:
  after that, a run costs a few searches per company. Titles written as regexes can't be searched for, so
  keep a plain word or two ("engineer", "data platform") among them. A board that answers "too many
  requests" (HTTP 429) is asked again after a pause; a posting it still won't serve is kept without its text
  and read on the next run. Eightfold boards are read one request at a time; a posting's own "work site" line (days in the office, or
  how much is from home) decides whether it is remote, and up to 100 stored postings per board are re-read each
  run until they have it. Google's feed is every role it
  has, one request (about 20 MB) a run; jobwatch keeps the ones whose titles have your `filters.titles` words,
  in the US unless the board is `google/any`. Amazon is searched like a Workday board, newest roles first and
  100 a request, one request at a time; each result has the role's full text, so nothing more is read. It keeps
  US roles unless the board is `amazon/any`. A SmartRecruiters board is searched the same way, 24 titles a
  page, and each posting it reads is one page. An Avature portal's sitemap is one request a run; a posting
  whose title has your `filters.titles` words and passes your title filters is read from its page, once, two at
  a time. An iCIMS site's list is a page of 50 roles a request, and its postings are read the same way. A Jobvite site's whole list is one request. HN's Who is hiring is one request to find the thread and one to read it whole.
  `jobwatch fetch --reread <board>` reads a searched board's stored postings again, as after an update that
  reads its pages better.
- **Within the rules:** it reads public APIs meant for this, and follows robots.txt. SmartRecruiters' own API
  host asks crawlers to stay away, so jobwatch doesn't use it: it reads the company's public careers site
  (careers.smartrecruiters.com, and each posting's page on jobs.smartrecruiters.com), which robots.txt leaves
  open. On an Avature portal it reads only the public pages its robots.txt lets robots read (never a link with
  `qtvc=`, never anything behind a sign-in); on iCIMS, the list and job pages, never its sign-in, referral or
  candidate pages; on Jobvite, the list and job pages, never the apply form. It doesn't scrape LinkedIn or Indeed, which forbid it.

## Install

```
pip install jobwatch                 # discovery, filters, digest
pip install 'jobwatch[score]'        # + fit scores with shortlist-ai (Claude API)
pip install 'jobwatch[local]'        # + fit scores on-device (Apple Silicon, MLX)
pip install 'jobwatch[mcp]'          # + MCP server for Claude and other assistants
pip install 'jobwatch[video]'        # + drill videos from prep sheets (Apple Silicon, on-device voices)
```

## Quick start

### In your browser

```
pipx install jobwatch      # or: pip install jobwatch
jobwatch ui
```

A page opens on your computer. The first time, it starts with **Tell me about yourself** and walks you through
four short steps, each saved as you go and each skippable:

1. **About you:** a box for who you are and what you want next, your resume (upload or paste), and plain
   questions about the kind of company, the kind of work, the track and how far ahead you're thinking. These
   become `goals:` in the watchlist.
2. **Jobs you want:** titles, places, remote, and a pay target. If a model is set up and you added a resume,
   **Suggest titles from my resume** offers titles and keywords, marked as suggestions; nothing is sent
   anywhere unless you press it, and nothing is added until you click it.
3. **Companies:** type a name or paste a link to one of their jobs; each board found is added with a click.
4. **The rest:** fit scoring and job-alert emails, both optional ("Later" leaves them for Settings).

It ends on Today; press **Check for new jobs** to look. Everything it asks is also in Settings. From there:

- **Today:** new matching jobs, with pay, how long ago they were posted, keywords, and who you know there.
  It leads with **today's picks**: the top 10 in the order you sort by (best fit, newest or top pay), since
  a few good applications a day beat a long list. **Show all** opens every match, and the search and
  company filter always look through all of them. A line says how many you've applied to today against your
  pace ("Applied today: 1 of 3"). **Queue** the ones worth applying to, **Skip** the rest. While the page is
  running it checks the boards by itself every 6 hours (`fetch_every` in the watchlist), and Today says when
  they were last checked. A job that disappears from its board drops off Today at the next check. **Companies
  to watch**, at the side, lists
  companies whose jobs keep coming in from alerts or Hacker News posts while you don't watch them (see
  [Companies to watch](#companies-to-watch)).
- **Queue:** your short list. Apply on the company's site, then press **I applied**. The pace line counts
  it: once you reach your 3 for the day it says so, and at 5 that the rest can wait until tomorrow. It's
  advice; nothing is ever blocked.
- Long lists come in pages (12, 24, 48 or 96 at a time, kept per browser).
- **Applications:** every job you applied to and where it stands (applied, screening, interviewing, offer,
  rejected, withdrawn), with the next step and a follow-up day. Those due come first. Filter by status with
  the chips over the list (or click the pipeline bar), and switch between **Cards** and a sortable **Table**.
  **Add an application** covers jobs you found elsewhere, such as a referral or a recruiter.
- **Settings:** the whole watchlist, one card per part, with a bar that jumps to each card and keeps Save in
  reach: the companies you watch (with each one's name and careers link) and how often to check them; filters
  (titles, places, departments, pay, age, minimum fit score, and warnings to flag in a posting); keywords;
  how many picks Today shows and your daily pace; your resume, where fit scores run, their model and the
  [prompt that scores fit](#the-fit-score-prompt); your LinkedIn connections; the [chat](#chat)'s model,
  reply length and instructions; [expected pay](#the-watchlist); [job-alert emails](#job-alert-emails) from
  a mailbox; [Companies to watch](#companies-to-watch) and [Skills to build](#skills-to-build); and the
  page's theme (system, light or dark) and width (standard, wide or full, for a big monitor). Each setting
  says in a line what it does, a blank one shows its default, and a bad value is refused with why, leaving
  the file as it was.
- **Ask jobwatch:** a chat on Today (about all of today's jobs and your applications) and beside each job's
  details (about that posting). See [Chat](#chat).

The page only talks to jobwatch on your own machine. The one exception is a model you choose: with
`scoring.backend: claude`, fit scores and chat send the posting and your resume to Anthropic (and
[drafted prep](#drafted-answers-from-your-stories), your stories too); with `agy`, fit scores send them to
Google through the Antigravity CLI. It's the same
watchlist file and history as the command line, so you can switch between the two.

To have the page always there, even after a restart, on a Mac:

```
jobwatch service install      # starts jobwatch ui when you log in, and again if it stops
jobwatch service status       # running? where's the log?
jobwatch service uninstall
```

Running like that, the page keeps Today fresh on its own: it checks every board when it starts (if the last
check, from the page or `jobwatch fetch`, is older than `fetch_every`) and again every 6 hours. For checks at
the same times every day, give times instead: `fetch_every: 8am, 2pm, 8pm` (this computer's clock). A time
missed while the computer slept or the page was down is caught up once, as soon as it's back. Each check asks
each board the same as pressing **Check for new jobs**, and pressing the button while a check runs waits for
that one rather than starting another.

The **Activity** tab shows what it has been doing, newest first: each check of the boards (what's new, what
failed), each read of your job-alert emails, each job scored (its score and which model made it, or why it
failed) and each lookup of expected pay, with what started it (the schedule, the button, the background
scorer), plus what's running right now. It shows one list at a time, **Job Boards**, **Gmail** or **Scored** (the
jobs scored, with the pay and logo lookups), so the many jobs scored don't bury the rest. It updates by itself while
it's open, and keeps the last 1,000 entries of each kind.

Each card shows the company's logo once it's known, else its initials. The logo is the icon on the company's own
site (no logo service is asked), found in the background the first time a company shows up: the site is the
domain its postings link to whose name is the company's, else its name plus .com when that home page names it.
It's kept in the state file, and a company with none found is looked at again after two weeks. Sites that refuse
jobwatch's requests keep their initials. `jobwatch logos` looks them all up at once (`--again` to refresh).

A login item doesn't see variables set in your shell profile, so with `scoring.backend: claude` the page's
chat and scores need the API key another way: keep it in the macOS keychain and name the item in
`scoring.keychain` (`security add-generic-password -s anthropic -a "$USER" -w`, then `keychain: anthropic`),
give `ANTHROPIC_API_KEY` to launchd (`launchctl setenv ANTHROPIC_API_KEY ...`), or run `jobwatch ui` from a
terminal instead. The local backend needs nothing.

### On the command line

```
jobwatch init                         # writes an example jobwatch.yaml
jobwatch find "Globex" "Scale AI"   # find each company's board
jobwatch find https://jobs.lever.co/spotify/4f1c2a9e-...   # or paste any job link
jobwatch find "Globex" --roles agent   # also list the board's open roles with "agent" in the title
```

`--roles` lists each matching role with its place, pay (read from the posting's text when the board has no pay
field) and posted day, without adding the board to your watchlist.

`find` prints a line like `Globex: greenhouse:globex (627 open roles)`. For a Workday company it tries
the usual site names; if that finds nothing, paste a job link from their careers site (it has
`myworkdayjobs.com` in it) and `find` reads the board from it: `workday:nvidia.wd5/NVIDIAExternalCareerSite`.
An Oracle Recruiting Cloud site is found the same way, from a job link with `oraclecloud.com/hcmUI/CandidateExperience`
in it: `oracle:eeho.fa.us2/CX_45001`.
A company's own careers page works too (`jobwatch find https://careers.acme.com/jobs`): `find` reads it for
links to a board, which is how a board under a name nobody would guess turns up. Add those
entries under `companies:`, adjust the filters, then:

```
jobwatch run                          # fetch every board, then show the digest
```

Run it daily, for example from cron: `0 8 * * * jobwatch run -o ~/jobs-today.md`.

## The watchlist

```yaml
companies:
  - greenhouse:globex
  - lever:spotify
  - {source: ashby, board: initech, name: Initech}
  - {board: ashby:acme, careers: https://acme.example/careers}  # job links go to its own site (see below)
  - workable:acme                                       # apply.workable.com/acme
  - {source: workday, board: nvidia.wd5/NVIDIAExternalCareerSite, name: NVIDIA}  # tenant.wdN/site
  - {source: eightfold, board: acme, name: Acme}      # tenant (or tenant/domain), from a link
  - {source: jibe, board: careers.acme.com, name: Acme}  # a Jibe site's host (job links: /careers-home/jobs/...)
  - rippling:acme                                       # ats.rippling.com/acme/jobs
  - google:google                                       # Google, YouTube, DeepMind in the US (google/any: all)
  - amazon:amazon                                       # Amazon and AWS in the US (amazon/any: all)
  - {source: oracle, board: eeho.fa.us2/CX_45001, name: Oracle}  # pod.fa.region/site, from a job link
  - smartrecruiters:Initech                             # careers.smartrecruiters.com/Initech
  - {source: avature, board: careers.initech.example/careers, name: Initech}  # an Avature portal: host/portal
  - icims:initech                                       # careers-initech.icims.com (jobs-initech.icims.com: the host)
  - jobvite:initech                                     # jobs.jobvite.com/initech
  - hn:whoishiring                                      # HN's Who is hiring thread (whoishiring/3: last 3 months')

filters:
  titles: ["engineer", "architect"]       # regexes; the title must match one
  exclude_titles: ["intern", "manager"]
  exclude_text: ["penetration test\\w*|red team"]   # regexes on the posting's text; a match rejects the job (a job
                                          # listed without its description passes: only text that's there counts)
  exclude_departments: ["sales"]
  locations: ["remote", "Denver", "Boulder, CO"]
  remote_country: US                      # remote roles must be open in the US ("any" to allow all)
  home_state: CO                          # leave out remote roles open only in other states (or "Colorado")
  min_salary: 200000                      # the top of a listed range must reach this
  require_salary: false                   # true: drop postings without pay
  max_age_days: 30
  min_fit: 70                             # hide jobs whose fit score is below this; unscored jobs still show
  flags:                                  # not filters: a warning on queued jobs whose posting says this
    "active (TS|top secret)": clearance
    "on-?site 5 days": on-site

keywords:                                 # relevance: title hits count double
  LLM: 3
  RAG: 3
  Python: 2
  "re:agent(s|ic)?": 2                    # "re:" prefix = regex

resume: ~/Documents/resume.pdf            # for fit scores
connections: ~/Downloads/linkedin.zip     # who you know at each company (see below)
scoring:
  backend: claude                         # or local (the default), or agy (Google's Antigravity CLI)
  # model: ...                            # the model fit scores use; default: shortlist-ai's for the backend
  top: 5                                  # score the 5 most relevant new jobs per digest
  auto: true                              # the page scores every new match in the background
  # batch: 10                             # ...this many jobs in a row, then a rest (0: no rests)
  # rest: 10                              # ...of this many minutes
  # unload_after: 5                       # minutes idle before the local model leaves memory (0: keep it)
chat:                                     # Ask jobwatch; leave any of these out for its default
  backend: local                          # claude or local; default: scoring.backend
  claude_model: claude-sonnet-5-5
  local_model: mlx-community/Qwen3.5-9B-MLX-4bit
  max_tokens: 1500                        # the longest reply
  max_turns: 24                           # the latest messages of a conversation sent with each question
  # prompt: ...                           # its instructions (Settings > Chat); must keep {today} and {context}
stories: ~/Documents/stories.yaml         # your projects, for drafted prep answers (see Prep sheets)
prep:                                     # drafted prep (`jobwatch prep KEY --draft`), with the chat's model
  max_tokens: 4000                        # the longest draft
  # prompt: ...                           # its instructions; must keep {context}
pay:                                      # expected pay from Levels.fyi: off unless levels is true (below)
  levels: true
  years: 12                               # your years, for a title with no seniority word
  # region: new-york-city-area            # a Levels.fyi location, for remote jobs and ones near you
  ask_over: 10                            # ask this many percent over the level's median base
  round: 5000                             # rounded up to this (0: not rounded)
  today: 15                               # how many of Today's jobs get looked up
  target: 180000                          # your target base, for prep sheets (or a range: 180000-210000)
  floor: 150000                           # your private floor: your own sheet only, never sent to Claude
suggestions:                              # Companies to watch
  half_life: 30                           # days: a job this old counts half as much as today's
  limit: 10                               # how many companies are listed
learning:                                 # Skills to build
  timeline: quarter
  jobs: 5                                 # example jobs listed with each skill
display:                                  # the browser page
  theme: system                           # system, light or dark
  width: standard                         # standard, wide or full
  today: 10                               # Today's picks, and the digest's length; 0 shows every match
  company: matches                        # a company's page: the open roles your filters pass, or all
pace:                                     # applications a day: counted on Today and the queue, never enforced
  daily: 3                                # 0 turns it off, for when job hunting is your full-time job
  max: 5                                  # from this many on, the rest can wait until tomorrow
fetch_every: 6h                           # the page checks the boards this often (90m, 1d; off to stop),
                                          # or at set times: 8am, 2pm, 8pm
```

Relative paths are resolved from the watchlist's folder. State (which jobs you've seen, applied to or
skipped, and their scores) lives in one SQLite file, by default `~/.local/share/jobwatch/state.db`. Settings
shows where it and the cache are; change them in the file (a new state path starts an empty history).

`pay: {levels: true, years: 12}` (off by default) adds an estimate of a queued or viewed job's level and pay from
the company's public salary pages on Levels.fyi, with a link to the page. The ask it suggests is
`pay.ask_over` percent over the level's median base, rounded up to `pay.round`, kept within a posted range. It's meant for personal use: you're
responsible for checking Levels.fyi's terms. What's read stays in the state file and is never put in a digest.
If Levels.fyi refuses jobwatch's requests (HTTP 403), jobwatch says so on the job and asks nothing for a day.
Data: [Levels.fyi](https://www.levels.fyi).

`fetch_every` (6 hours unless set, at least 1 hour) is how often the browser page checks the boards while it's
open; `off` (or `0`) leaves it to you and `jobwatch fetch`.

### When a company's job pages are offline

Some companies keep listing jobs on their Ashby board while Ashby's own job pages for them say "Page not
found" (they've moved applying to their own site). jobwatch looks at the board's Ashby page once a day while
it fetches. If it's offline, `jobwatch fetch` warns about that board, and each of its jobs says to apply
through the company's own careers site (on Today, in a job's details, in `jobwatch show` and to an AI
assistant). Add the company's careers site to the board, `{board: ashby:acme, careers:
https://acme.example/careers}`, and its jobs link there instead. If the page can't be read, nothing changes.

### Filters for one board

A board can have filters of its own, for jobs your usual ones would hide: a college's adjunct openings, say,
with other titles and hourly pay (which counts as $35 × 2,080 a year against `min_salary`). Each setting under
the board's `filters:` replaces the watchlist's for that board's jobs only; the ones it leaves out stay the
watchlist's. A YAML anchor lets several boards share them:

```yaml
teaching: &teaching                       # any name; only the boards that use it count
  titles: [adjunct, instructor, lecturer, faculty]
  min_salary: 0
companies:
  - greenhouse:globex                     # the watchlist's filters
  - {board: workday:initech.wd1/Careers, name: Initech College, filters: *teaching}
  - board: icims:globexu
    filters: *teaching
```

They count wherever a job is judged: what a searched board is searched for and which postings are read in full,
Today, the digest, the queue's warnings, a company's page, Referrals and job-alert emails (a job an email links
to on one of these boards). A job from a board that isn't watched is judged by the watchlist's filters, or a
track's. The page's Settings keeps them as written; they're changed in the file.

A **track** does the same for a kind of job, by its title, wherever it comes from: a job-alert email's, one added
by link, a watched board's. A job whose title matches one of a track's `titles` (regexes) is judged by the
watchlist's filters with the track's `filters:` replacing them one by one; the first track that matches counts,
and a board's own filters come before any track.

```yaml
tracks:
  - name: teaching                        # optional, for you
    titles: ['\b(adjunct|instructor|lecturer)\b']
    filters:
      titles: [cyber, security, computer, information technology]
      min_salary: 0
```

### Hacker News' Who is hiring

`hn:whoishiring` watches the latest monthly "Ask HN: Who is hiring?" thread; `hn:whoishiring/3` the last three
(up to 12). It's read from HN's search API (hn.algolia.com), which robots.txt allows: one request finds the
threads and one reads each whole, so a run never asks for a post at a time. Each company's post is one job, named
after its company, with every role its first line names in the title ("Senior Engineer, Designer"; roles
listed further on when the first line has none). The place, remote and pay come from that first line
(`Acme | Senior Engineer | Remote (US) | $180k-$220k | link`), and the post's text is the description. The job
links to the company's own job page when the post has one (a posting on a board jobwatch reads first, then that
board, then a careers page), else to the post on HN. Boards it links to are noted with the job, not read: a
company whose post passes your filters shows up under [Companies to watch](#companies-to-watch), with the board
its post links to when there is one. A post that's deleted or flagged is gone from the thread, so its job closes;
an edited one is read again. Replies, remarks and job seekers' posts aren't jobs. The first line is free text,
so a post written in sentences may come out as "Open roles (see the post)". Posts aren't fit-scored: one lists
several roles, places and links, which a score would read as one job's must-haves; watch the company's board to
score each role.

### How locations match

A posting can list several places (`London, UK; Remote-Friendly, United States; Austin, TX`), and each one
is checked:

- `remote` matches a place that says remote and is in `remote_country`, or says only "Remote". It also
  matches a posting whose own remote flag is set and that lists a US location.
- With `home_state` set, a remote role open only in some states is left out unless yours is one of them,
  and one open only in your state ("Remote - Colorado") counts as remote. The states come from the
  posting's places ("Remote - Texas", or a remote posting that lists only states) and its text ("Remote
  locations: California, USA; Nevada, USA", "remote in CA, NV, OR or WA", "must reside in one of the
  following states: ..."). Today's filter bar says why: "remote only in CA, NV, OR, WA".
- Any other entry matches as text, so `Denver` matches `Denver, CO, United States`.

## Fit scores

Keyword relevance is fast and explainable, but it can't tell "uses Kubernetes" from "5+ years running
Kubernetes in production". With `resume:` set and `scoring.top` (or `--score N`), the most relevant new
jobs are scored with [shortlist-ai](https://github.com/vinayvobbili/shortlist-ai):

1. It turns the posting into must-have and nice-to-have requirements.
2. It judges each requirement against your resume, with quotes it checks against the resume text.
3. It lists the must-haves the resume doesn't show.

Scores are stored per resume file content, so each job is scored once, and again only after you edit your
resume. The local backend takes a minute or two per job, so keep `top` small. On the page, a tag under each
score says who made it: "Claude API", "local model", or "local, for now" when the local model stood in for
Claude (over `scoring.daily`, or Claude failed) and Claude will score it again.

While `jobwatch ui` runs, it scores every matching job in the background, one at a time: the jobs you've
queued first (they're the ones you're about to apply to), then Today's, most relevant first. It runs when
the page starts, after each "Check for new jobs", when you queue a job, and after you add a new resume. Today shows
how many are left, and a button brings in the new scores when you're ready (the cards don't move on their
own). A chat reply or a "Score fit" click goes first; background scoring waits for it. It's on by default
with `scoring.backend: local`. With `claude` every score is a paid API call, so turn it on with
`scoring.auto: true`. `jobwatch score [--limit N]` does the same in the terminal.

The page is meant to sit close to idle. With nothing left to score it runs no scoring thread and doesn't load
the model; the on-device model (several GB) loads when a job needs it and leaves memory after
`scoring.unload_after` minutes unused (default 5; 0 keeps it loaded). A long line of jobs is scored in batches:
`scoring.batch` jobs in a row (default 10; 0 for no rests), then a rest of `scoring.rest` minutes (default 10)
before the next batch; a new check for jobs or resume starts the next batch at once. `jobwatch service install`
runs the page at a lower priority (nice 10, low-priority disk), so scoring stays out of your way; run it again
to apply that to a service installed earlier.

A job the scorer failed on (no reply, a bad answer) isn't tried again for 3 days, so a down model doesn't make
every pass start with the same failures; that is remembered across restarts, and a change to the resume, the
prompts or the model tries it at once. Its card shows the error.

A card with no score says why: in line to score (and where), no posting text, the same role scored before
this posting came in, or a failure. A job from an alert email may have only its title: "Add the posting"
takes a link to the company's posting (read when it's on a board jobwatch reads) or the pasted text, and so
does `jobwatch mark <key> --url <link>`. `jobwatch unscored` lists them all.

Each score keeps its reasons: every requirement, its verdict (met, partly, missing) and the resume's words
behind it. They're under "Why this score" in a job's details, at the end of `jobwatch show <key>`, and in
the MCP `get_job` result. Scores saved before jobwatch kept these have only the summary.

`filters.min_fit` (the Fit slider on Today's filter bar, and in Settings next to how many picks Today shows)
hides jobs scored below it, counted as "fit" in the hidden roles. Jobs not scored yet still show, since
scoring catches up in the background.

Each score says which model made it (on the ring's tooltip, and in `jobwatch show <key>`). `jobwatch score
--backend claude --model claude-sonnet-5-5` scores with another backend or model for that run only, the
watchlist keeping its own; its scores sit next to the others, so check first that the two grade alike:
`jobwatch score --compare 10 --backend claude` scores 10 already-scored jobs again, from the lowest score to
the highest, and shows each old and new score, the mean difference and which ones land on the other side of
`min_fit`. It saves nothing. With Claude every score is a paid API call.

`scoring.backend: agy` scores with Google's Antigravity CLI (`agy`) on your own subscription login: no API key,
text only, about 35 seconds a call, so up to three run at once. `scoring.model` picks its model (an id from
`agy models`; default `claude-sonnet-5-5-medium`). Each call runs sandboxed in an empty temporary directory, and
it uses your subscription's quota. `agy` can't run the chat, which stays on `claude` or `local`
(`chat.backend`).

To score with Claude and keep other backends for when it can't, set `scoring.fallback: local`, or a list tried
in order, `scoring.fallback: [agy, local]` (Claude, then agy, then the local model; `scoring.agy_model` is the
model agy uses as a fallback). Without a key, out of credit or with the API down, the next backend scores the
job, and a backend that fails moves it on to the one after. The score says so ("fallback", and which backend
made it) and gets scored again by Claude later (after 3 days for a failure), or by `jobwatch score --rescore`. `scoring.daily: 40` caps the jobs the
page scores with Claude a day; past it the fallback scores them (or, with no fallback, they wait for
tomorrow), and Claude takes them up the next day. A fallback score never hides a job from scoring by
`min_fit`. The cap holds back background scoring only: `jobwatch score` scores what you ask, and counts it.
After switching backend or model, `jobwatch score --rescore 50` scores Today's and queued jobs again, best
first, where another model made the score and it's at least 50.

A new shortlist-ai (a release, or its prompts or scoring code changed) is another scorer: its scores start
afresh, and until a job is scored again its old score shows as "old score, rescoring". When the change doesn't
change what a score means (a prompt reordered for caching, say), `jobwatch score --keep-old` keeps the scores
of the scorer in use just before as current instead (`--keep-old ID` names another), so only new jobs are
scored by the new scorer. Scores from scorers replaced before that stay set aside and are scored again. If
the change turns out to move scores after all (`--compare` shows it), `jobwatch score --redo-kept --batch-api`
scores the kept ones again with the new scorer, at half price.

When the model gives no verdict for some of a job's requirements, each would count as not met (a good fit
scoring 5/100), so that run counts as a failure, like an error, and is tried again later. `jobwatch score
--incomplete` scores again the jobs whose saved score is like that, from before.

Claude scores `scoring.workers` jobs at once (4 by default; the on-device model takes one at a time), so
`jobwatch score` goes through a backlog about that many times faster at the same cost. For a big run nobody is
waiting on (a new resume, a backlog, a `--rescore`), `jobwatch score --batch-api` sends it all through Claude's
Message Batches API at half the price. The scoring steps depend on each other, so it goes in rounds of one
batch each (about three); each batch takes minutes, at most a day. Stopping is safe: the next run collects what
was sent instead of paying for it again. The page never batches: a score you ask for there is wanted now.

To tighten the prompts for the on-device model without losing paid scores (an edited prompt sets every score
aside), try them in a comparison first: `jobwatch score --compare 20 --stored-by claude --backend local
--prompts tight.yaml` scores 20 of the jobs Claude scored with the local model and the prompts in
tight.yaml (name: text, as `--show-prompts` names them), next to Claude's scores, with the mean size of the
difference to aim down. Nothing is kept, the prompts included: put them in Settings when they're ready.

### The fit score prompt

Settings → **Fit score prompt** shows what the model is told: each of shortlist-ai's prompts (reading the
resume, turning a posting into requirements, judging each requirement, counting years), each in a box you can
edit, with "Reset to default". Only the edited ones are saved, as `scoring.prompts` in the watchlist. The two
request templates must keep their `{placeholders}`; saving says so if one is missing. An edited prompt
changes scores from then on: scores made with other prompts are set aside and Today's jobs are scored again,
and putting the prompts back brings the old scores back. `jobwatch score --show-prompts` prints them.
Editing needs a shortlist-ai that takes edited prompts; with an older one they show read-only.

## Chat

Ask questions in plain words: "which three should I apply to first?", "what follow-ups are due?", "how well
do I fit this one, honestly?", "what will they ask in interviews?". The chat runs where fit scores do,
unless `chat.backend` says otherwise:

- `local`: the same on-device model as scoring (`pip install 'jobwatch[local]'`). Nothing leaves your
  computer. The first answer waits for the model to load.
- `claude`: Claude Sonnet via Anthropic's API (`ANTHROPIC_API_KEY`, or the keychain item `scoring.keychain`
  names). Your question, your resume and the jobs it's about are sent to Anthropic.

Settings → **Chat** sets the model for each (`chat.claude_model`, `chat.local_model`), the longest reply
(`chat.max_tokens`) and how many of a conversation's latest messages go with each question
(`chat.max_turns`). Its instructions are there too, folded like the fit score prompts: edit them, or "Reset
to default". Only an edited one is saved (`chat.prompt`), and it must keep `{today}` and `{context}`, where
the date and the jobs it reads go.

It reads today's matching jobs and your applications, or one posting with its fit score and
[what you sent](#what-you-sent), plus your resume (the one you sent for that job, when it's kept).
It's told to use only your resume for facts about you and to treat posting text as data, not instructions.
It has no tools, so it can't change, apply for or send anything.

Under each reply are a copy button and what it took: seconds (and any wait for a background fit score to
finish), tokens in and out, and on this computer tokens per second and peak memory. While a reply is on its
way, a timer shows how long it's been against how long recent replies took. The download button in the chat's
header saves the conversation as Markdown. The same thing works from the terminal:

```
jobwatch ask "What follow-ups are due this week?"
jobwatch ask --job c1 "What should my resume lead with for this one?"
```

## Skills to build

Which skills do the jobs you're going after ask for that your resume doesn't show, and where can you learn
them in the time you have?

```
jobwatch skills                     # gaps across today's matches and your applications
jobwatch skills --timeline month    # week, month, quarter (default) or any
jobwatch skills --all               # also the skills your resume already shows
```

The Skills tab in `jobwatch ui` shows the same, with a timeline switch, and each job's details link to it
from the gaps it lists.

Skills are ranked by demand: how many of your matching jobs mention one, with a must-have that a fit score
found missing counting three times. Each comes with:
- curated courses and certifications from the official pages (AWS, Linux Foundation, DeepLearning.AI,
  Hugging Face, OWASP...), each with a rough time and marked if it's longer than your timeline;
- searches on LinkedIn Learning, Coursera, edX and, for AI skills, DeepLearning.AI;
- with a timeline of a quarter or more, certificate programs at colleges near you.

Fit-score gaps no course closes (a clearance, citizenship, a degree, travel) are listed apart, and so are
must-haves asking for years of something: a course gives you something concrete to point to, not the years.

```yaml
learning:
  timeline: quarter       # week, month, quarter or any
  near: Denver            # for colleges nearby; default: the first city in filters.locations
  jobs: 5                 # example jobs listed with each skill
```

The chat knows the top gaps too ("what should I learn this month?"), and a job's details list the skills
that posting asks for that your resume doesn't show.

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

Each card on the page suggests queuing or skipping a job, and why, from a few fixed rules (no model call).
Skip wins: the same opening already applied to, two or more applications at that company in the past
week, pay under `pay.floor`, or fewer than half the must-haves met. Otherwise queue: posted pay (or Levels.fyi's
ask) reaching `pay.target`, a fit score of 75 or more, or someone you know there. A rejection for one role
there doesn't count against another. It's only a suggestion: nothing is hidden or marked for it.
`jobwatch advice` counts how often each rule fires across Today's jobs.

Queued jobs leave the digest. The queue flags any posting that has since closed, and what to check before
applying: pay below `min_salary`, a place your filters don't want (a job queued by hand never passed them),
and anything your `filters.flags` patterns find in the posting. Every fetch notices a watched board's
postings closing; `jobwatch check` also checks queued jobs and open applications from boards you don't
watch (a LinkedIn job can't be checked: LinkedIn's robots.txt doesn't allow reading its postings). A req
that's taken down often comes back under a new one: when a closed job's board lists the same title under
another id, `check` says "reposted as <id>: <link>", keeps the new posting (read in full) for you to queue,
and notes it on the old job, so the new one shows as a repost of what you applied to (see below). A board
can post one title many times, one per opening: postings tracked since before yours closed don't count (they
were open alongside it), and when several are left, `check` lists them for you to tell which, if any, it is,
and notes nothing:

```
jobwatch check                             # closed (or back) since the last check; --all lists the open ones too
```

### The same opening twice

One opening can reach you more than once: from its board and a job-alert email, under a new title, or
reposted under a new req after you applied. Every job a fetch, an alert import or `jobwatch add` brings in
is compared with the ones you've queued, applied to (or got further with) and skipped, at the same company:

- **The same opening:** the two share a req or posting id: in the title or posting text ("Req ID: R-0123456",
  "(482913)"), in the posting's link, or in your note on the other job (its link, "req 482913", or a note
  that it was reposted as another posting). The job is shown with "Already applied 2026-03-02", or
  "Reposted: you applied 2026-03-02 (old req …)" when your note says it was reposted.
- **Possibly the same:** only the title matches, setting aside dashes, a req in the title, "(Remote)" and a
  seniority word only one of them has. It's shown with "Possible duplicate of your 2026-03-02 application:
  check it's a different opening". Two postings on one board, two different reqs, or "Senior" against
  "Staff" are never matched by title.

Nothing is hidden: the job stays in the digest and the queue, with the badge in the browser and the warning
first among the queue's checks, in `jobwatch show`, and when you queue it (it's queued all the same). To
list every pair you track, without changing anything:

```
jobwatch dupes                             # --strong: only the ones sharing an id
```

Skip the one you don't need with `jobwatch mark skipped <key>`.

### Who is interviewing you

Open someone's LinkedIn experience page (`linkedin.com/in/<name>/details/experience/`) in your own browser, copy
the page text into a file, and list their roles. jobwatch only parses the text you give it; it never fetches
linkedin.com, whose robots.txt disallows it.

```
jobwatch profile page.txt                  # --format json, or html for a <ul> to paste into a prep sheet
pbpaste | jobwatch profile -
```

### Jobs you found somewhere else

A job from LinkedIn, a job-alert email or a friend goes in the queue with its link. When the link is to a
posting on Greenhouse, Lever, Ashby, Workable, Workday, Rippling, Google Careers, amazon.jobs, Oracle Recruiting
Cloud, SmartRecruiters, iCIMS, Jobvite or an Avature portal, jobwatch reads the posting from there, so it
can be fit-scored and prepped for like any other, even if you don't watch that company. jobwatch never reads
LinkedIn (its robots.txt disallows every page), so a LinkedIn job link needs the company and title too; the
same job is looked for on the company's own board: found, that's what is tracked, since it's where the
application goes; not found, the job is kept with the LinkedIn link and the text you paste. For anything else
(a company's own site), give the company and title and paste the posting's text:

```
jobwatch add https://apply.workable.com/acme/j/A1B2C3D4E5/ --status queued
jobwatch add "Umbrella" "Staff Engineer" --url https://www.linkedin.com/jobs/view/... --text posting.txt --status queued
pbpaste | jobwatch add "Umbrella" "Staff Engineer" --text - --status queued     # the posting from the clipboard
```

In the browser, press **Add a job** on the Queue page. Many job sites (LinkedIn's "Apply on company
website", job-alert emails) link through to the company's own board: that link is the one to use.

### Job-alert emails

The job alerts LinkedIn, Built In, Indeed and other job sites email you can go straight in. Save them from
your mail app (a `.eml` file each, a folder of them, or an `.mbox` export) and give them to `jobwatch alerts`:

```
jobwatch alerts ~/Downloads/alerts/ --dry-run      # what's in them, nothing recorded
jobwatch alerts ~/Downloads/alerts/                # track the new ones
pbpaste | jobwatch alerts -                        # one message's source, from the clipboard
```

Each job's title, company, place, pay and link are read from the email, with the tracking taken off the link.
LinkedIn, Built In and Indeed alerts each have their own reader; any other sender's is read by its job links.
A job that fails your filters on what the email says is kept as it is, so it's known next time, and nothing
more is read for it. For the rest, jobwatch looks for the job where the application goes:

- **A link to a company's board** (Greenhouse, Lever, Workday and the rest) is read from there.
- **A job site's link** is read only if the site's robots.txt allows it. Built In's job pages are allowed, and
  their full posting is used. LinkedIn's and Indeed's postings aren't (robots.txt disallows them), so they
  aren't read: the email's details are used.
- **Then the company's own board** is looked for: one you watch, or one found by name, as `find_board` would.
  If the same job is posted there, that's what is tracked, with the alert's link kept in its notes.

Jobs already tracked are left as they are: the same link, or the same company and title, from a board you
watch or an earlier alert. Each new one remembers where it came from (`via linkedin-alert`), passes through
your filters, and is in the next digest. Sponsored listings in Indeed alerts have no job id and are skipped.
`--no-follow` reads no links at all; `--all` lists every new job, filtered out or not; `--format json` is for
scripts. In Claude, `import_job_alerts` takes the messages (their source, or just the HTML) the same way.

jobwatch never asks for your email password. To read alerts straight from your mailbox instead, give it an
IMAP account in the watchlist, with the password in an environment variable or the macOS keychain. It's off
unless you set it. The mailbox is opened read-only, and messages are read without being marked read:

```yaml
alerts:
  imap:
    host: imap.gmail.com           # Gmail needs an app password (full mail access: see below)
    user: you@gmail.com
    keychain: jobwatch-imap        # security add-generic-password -s jobwatch-imap -a you@gmail.com -w
    # password_env: JOBWATCH_IMAP_PASSWORD   # or this, instead of keychain
    # folder: INBOX
    # days: 3                      # alerts from the last 3 days
    # senders: [jobalerts-noreply@linkedin.com, builtin.com, jobalert.indeed.com]
```

```
jobwatch alerts --imap
```

With a mailbox set, every check for new jobs reads it too (the page's schedule and its "Check for new jobs"
button, `jobwatch fetch` and `run`, and the MCP's `fetch_jobs`), so jobs from your alerts come in with the
boards'. A mailbox it can't read (no password yet, or a login it refuses) shows as a failed check, and the boards
are still checked. `jobwatch hidden --since 6h --source manual` lists the alert jobs that came in but that your
filters keep off Today, and why.

A Gmail app password isn't limited to reading: it can read, send and delete all of the account's mail. jobwatch
only opens the folder read-only, but that's jobwatch's doing, not the password's. Keep it in the keychain (run
the `security` command in a terminal: it asks for the password, so it never lands in your shell history), and
delete it in your Google account if you stop using jobwatch or think it got out.

### Status updates from application emails

The emails that tell you how an application is going (a "thank you for applying" confirmation, a rejection, an
interview invitation or scheduling link, a take-home assignment, an offer, a recruiter's reply) can be read for
you. Save them the way you would alerts and give them to `jobwatch inbox`. It proposes; you decide:

```
jobwatch inbox ~/Downloads/replies/                # what each email says, nothing recorded
jobwatch inbox ~/Downloads/replies/ --apply        # ask y/n about each proposal
jobwatch inbox ~/Downloads/replies/ --yes          # record them all
pbpaste | jobwatch inbox -                         # one message's source, from the clipboard
```

Each email is sorted into a confirmation, rejection, interview or scheduling email, assessment (take-home, coding
test), offer, or other (a recruiter's reply), by the phrasings and senders of the common applicant-tracking
systems in `jobwatch/data/inbox.yaml`. It's matched to the application by the sender's domain or name, how the
body names the company, the requisition or posting id and the job's title. A proposal gives the application,
its status now and the one suggested, a dated note quoting the decisive phrase, the email's date, sender and
subject, and how sure the match is and why. Recording one sets the status and adds the note, as `jobwatch mark`
does; a rejection also clears the next step and follow-up day, and an interview, assessment or offer sets a next
step when there's none.

A status only moves forward. A confirmation that arrives after you're interviewing isn't a proposal, and an email
about an application that has ended is a note at most. Emails that match no application (or several, with
nothing to tell them apart) are listed with the company they seem to be from, so you can `jobwatch add` it.
`--format json` is for scripts. In Claude, `read_status_emails` takes the messages the same way and returns the
proposals, each with the `mark_job` arguments that record it; the assistant shows them to you, and calls
`mark_job` only for the ones you confirm. jobwatch never asks for your mail password and reads no network.

### Companies to watch

jobwatch only checks the boards on your watchlist, so a company you never added is never checked, however good
its jobs. Alerts show which ones you're missing. Each job that comes in from an alert or `jobwatch add`, from a
company whose board you don't watch, is noted with its company; so is each new Hacker News post that passes your
filters, when you watch the Who is hiring thread. `jobwatch suggest` lists those companies, the
ones with the most jobs that pass your filters first (a job from last week counts more than one from last
season: one `suggestions.half_life` days old, 30 unless set, counts half), `suggestions.limit` of them (10
unless set; `--limit 0` lists all), with a few of their titles and their board. A company where you have an
application in flight (applied, and no no yet) comes first whatever your filters say of its jobs, with "you
applied to: ...": watching its board is what catches the job reposted under a new req.

```
jobwatch suggest                       # companies to watch, and the board to add for each
jobwatch suggest --add Umbrella        # put its board on the watchlist
jobwatch suggest --dismiss Hooli       # don't suggest it again
```

After changing your filters, or for HN posts fetched before they were noted, `jobwatch suggest --rescan` notes
the companies of the open posts already in the state file first (nothing is read from the web; running it again
counts nothing twice).

The board is the one a job was found on when the alert import matched it there (or the one an HN post links
to), else one found under the
company's name the way `jobwatch find` looks (check its titles: a guessed name can belong to another company).
Each company is looked for once, and what's found, or that nothing was, is kept in the state file. `--no-lookup`
lists what's known without looking. When no board turns up, give `jobwatch find` a link to its careers page.
`--add` rewrites the watchlist the way Settings does, keeping the old one as `.bak` (comments in a hand-written
file aren't kept). On the page, the same list is on Today with **Add** and **Dismiss**; in Claude,
`list_suggested_boards` gives each company's `add_board` arguments, and `dismiss_suggested_board` drops one.

## Tracking applications

An application moves through stages: `applied`, `screening`, `interviewing`, `offer`, and then `rejected`
or `withdrawn`. Each can have a next step and a day to follow up. Jobs you found somewhere jobwatch doesn't
watch (a referral, a recruiter, LinkedIn) go in with `add`, so every application is in one list:

```
jobwatch add "Umbrella" "Principal Engineer" --url https://... --on 2026-09-14 --note "via a recruiter"
jobwatch add https://job-boards.greenhouse.io/acme/jobs/101 --on 2026-09-20   # read from the link
jobwatch mark screening c1 --next "technical round" --follow-up +7   # or a date: 2026-10-05
jobwatch mark rejected principal-engineer
jobwatch mark umbrella interviewing   # the company is enough when you applied there once
jobwatch mark withdrawn c1 --add-note "recruiter says onsite only"   # adds a dated line; --note replaces
jobwatch mark c1 --add-note "interview Friday 10:30" --follow-up 2026-10-08   # no stage: it stays as it is
jobwatch mark principal-engineer --text posting.txt   # its posting, found later, for scoring and prep
jobwatch applications            # every application, follow-ups due first (alias: apps)
jobwatch applications --due      # only the ones to act on today
```

The day you applied is kept as an application moves through the stages. `--next ""` or `--follow-up ""`
clears a field. An application added by hand with only a company and a title can get its posting's text
later with `--text` (a copy from a job board, or `-` to paste it), so it can be scored and `jobwatch prep`
has something to work from; the posting kept with the application is replaced with it.

### Applications that go quiet

Many applications never get a reply, and their follow-up days pile up in the past. An application with no news
(a stage change or a note) for a few weeks has **gone quiet**: 21 days at `applied`, 14 at `screening`, 10 at
`interviewing`; one still at `applied` counts from the day you applied. Set your own in the watchlist (0 never
counts that stage):

```yaml
quiet:
  applied: 21
  screening: 14
  interviewing: 10
  long: 45        # quiet this long, a follow-up due sorts below the fresh ones and is only counted
```

```
jobwatch quiet                  # each one: days quiet, whether its posting is still up, and what to do next
jobwatch snooze c1 --days 7     # push the follow-up out, keeping the stage; noted in its history
jobwatch apps --due             # the fresh follow-ups, then "2 more due, quiet for 45+ days"
```

The suggestion is a short check-in to the recruiter or a contact (people you know there are listed, see
[Who you know there](#who-you-know-there)), or, when the posting has closed (`jobwatch check` records that) or
it has been quiet for `long` days, "likely closed: mark it rejected or withdrawn". jobwatch only suggests: it
never changes a status. A snooze isn't news, so a snoozed application stays quiet until you hear something. On
the Applications page they sit under **Gone quiet** with one-click Snooze 7 days, Mark withdrawn, Mark rejected
and Add note; the MCP `list_applications` gives each a `quiet` field.

Every company on Workday has its own careers site with its own sign-in, so after a few applications it's hard
to remember where each one lives. For a Workday application, `jobwatch show`, `jobwatch applications` and
the job's **Details** link that company's candidate page (`.../userHome`), where you sign in to see its
status. jobwatch keeps only the link, never a login or password: your password manager saves each company's
login under that company's own address. For one you added by hand whose posting has since come down, give
it the company's careers site (`jobwatch mark <key> --url https://acme.wd1.myworkdayjobs.com/Careers`)
and the page link follows.

### On your calendar

Follow-up days and interviews can show up in Apple Calendar, Google Calendar, Outlook or any other calendar
app, without giving jobwatch access to it: jobwatch writes an iCalendar (`.ics`) feed, and your calendar app
reads it.

```
jobwatch calendar -o jobwatch.ics   # import this file (or print it to stdout without -o)
```

Every open application's follow-up day is an all-day event, "Follow up: Acme Robotics — Staff Engineer", with
the next step, a link to the posting and the application's jobwatch key in its description. When the next step
names an interview or call with a date and a time, that is a timed event too: `Panel interview Tue 3/10 10:00
AM ET`, `call Wed 3/11 2:15-3:00 PM ET`, `intro call 2026-03-12T09:30:00-07:00`. Times can be in ET, PT, CT, MT
(daylight saving applied), EST, EDT, CST, CDT, MST, MDT, PST, PDT, UTC or GMT, and without a zone they stay the
same clock time wherever you are; an event with no end lasts an hour. When the text isn't clear (no time, a bare
`10:00` with no am/pm, two dates, a weekday that isn't that date's) there is no timed event, only the follow-up.
Rejected and withdrawn applications are left out. Each event keeps the same id, so importing the file again, or
a subscription refreshing, updates events instead of adding copies.

To subscribe instead of importing, press **Add to calendar** in the Applications tab of `jobwatch ui`. It opens
`http://127.0.0.1:<port>/calendar/<secret>.ics` in your calendar app (as a `webcal://` link), which refreshes it
by itself. The secret is made once, kept in the state file, and is what lets your calendar app in (it can't send
the page's token); the address works only on this computer, and nobody else can read the feed. The calendar app
needs jobwatch to be running (`jobwatch service install` keeps it so) to refresh.

For a reminder before interviews and calls (not follow-up days), set the minutes in the watchlist:

```yaml
calendar:
  remind: 30    # 0 (the default): no reminder
```

### Interviews

The **Interviews** tab in `jobwatch ui` lists the interviews and calls coming up: today's first (the tab shows
how many), then the next two weeks, soonest first. It reads them from next steps the same way the calendar feed
does, so `Interview with Sam Tue 3/10 2:00 PM ET` is on it. A next step that names a meeting with no time it can
read ("onsite loop, recruiter to schedule") is listed as not scheduled yet while its follow-up day is ahead, once
the application is past applied. Clicking a card opens everything about that application: the interview's time,
the whole note, what you sent, the people you know there, the posting, and your prep sheets.

Prep sheets you write yourself can be linked too. Put them in one folder and name each one for its company
(`acme-onsite.html`, `acme-recruiter-screen.html`), then point the watchlist at the folder:

```yaml
prep:
  sheets: prep    # next to the watchlist, or a full path
```

Every `.html` sheet whose name starts with the company's name shows as a button on its interviews and in its
details, newest first. A sheet opens in a new tab from that folder, so the stylesheet, images and
[drill video](#drill-video) beside it show as they do from disk (a video can be skipped through). The page
serves the folder at an address with a secret in it, like the calendar feed, only to this computer, and
sandboxed: a sheet can't run scripts.

### Looking up a company

Today only shows new roles on the boards you watch, so a company you added by hand, or one you're already
talking to, isn't there. In the browser, press `/` (or click the search box at the top) on any tab and type a
name: the matching companies come up, and one opens its page. A tab whose own search finds nothing says when
a tracked job at a matching company is elsewhere, with a link to it. On the command line:

```
jobwatch company acme                # a name, part of one, or a domain: acme.com; --format json
jobwatch company acme --all          # also the open roles your filters leave out
```

It finds the company under any status (new, queued, applied, interviewing, rejected, skipped...), open or
closed postings, and shows each job with its dates, next step, follow-up and note, whether a package was
saved, a duplicate warning, people you know there, and, when its board isn't on your watchlist, what to run
to add it. Open roles you haven't acted on are listed only when your filters pass them (title, text, place,
pay and fit, but not age: an older role still open is worth seeing), and the rest are counted by filter;
"Show them" on the page, or `--all`, lists them too, and Settings → Display → Company page (`display.company:
all`) lists every role each time. Jobs you queued, applied to or skipped are always listed. A long note shows as its latest dated entry, cut to about 200 characters (the page folds it until
clicked); `--format json` and `jobwatch show KEY` have all of it. The MCP tool is `get_company`.

To find a job by something you wrote or were told rather than by company, search the notes:

```
jobwatch search anthony              # which application did recruiter Anthony call about?
jobwatch search "$101/hr"            # --format json
```

It looks in every job's note, next step, where it was found (the recruiter or alert), title and company, at any
status, closed postings too, and shows each the way `jobwatch company` does.

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

To reuse what you answered before, search the answers across every package:

```
jobwatch answers "notice period"     # questions with all these words, newest application first; --format json
jobwatch answers                     # each distinct question once, with its latest answer
```

The MCP tool is `find_past_answers`.

### Prep sheets

Before a recruiter call or an interview, open the application's **Details** and press **Prep sheet** (or run
`jobwatch prep c1`). One page, ready to print, with:
- the stage, next step and your notes;
- each requirement and responsibility in the posting, next to the line on your resume closest to it (the
  resume you sent, if you kept it), or a plain "nothing close" so you can prepare a story or an honest answer;
- skills they ask for that your resume doesn't show, with the fit score's missing must-haves;
- a company brief: what the posting says about the company in its own words, its place and team, your notes
  on the job and who you know there. It's drawn from the posting and your notes only (nothing is looked up
  on the web) and says so;
- pay: the posted range, your target (`pay.target`, a number or a range) and your floor (`pay.floor`), with how each sits against the
  range. The floor is marked private: it is on your own sheet and nowhere else (see below);
- what you sent;
- questions to expect and questions to ask, for a screen or for interviews.

**Questions for this role.** `jobwatch prep c1 --questions` (or **Write questions for this role** on the page)
has the chat's model write the questions this role is likely to bring up from the posting's asks, each probing
one of them. Only the posting goes to the model (no resume, no stories, nothing of yours), and a question with a
number the posting doesn't contain is dropped. They're kept per job and posting text, so opening the sheet again
doesn't call the model, and a changed posting asks afresh. With no model, or nothing usable, the generic screen
or interview questions stand and the sheet says why. `prep.role_questions(cfg, store, key)` returns them for
anything else that wants them (such as a mock interview).

**Your pay floor stays on your computer.** Set `pay.target` and `pay.floor` (a yearly base, in the posting's
currency) in the watchlist; the target may be a range (`target: 180000-210000`, or `target_max: 210000`), and
the sheet says whether it sits below, inside, across or above the posted range. The sheet shows the floor labelled private. It is never put in a prompt for Claude:
with `chat.backend: claude` the posted range and your target may go in the questions prompt, the floor is left
out, and the sheet says so. The on-device model may see it. `get_interview_prep` over MCP leaves it out too
(`pay.floor_withheld`), since the client may be a cloud assistant.

**Open as page** (or `jobwatch prep c1 --open`) shows it as a standalone HTML page that prints cleanly on Letter
paper; `--format html -o prep.html` saves that page, and the default `--format md` prints Markdown.

Nothing on it is written for you: it quotes the posting and your resume. For an application you added by hand,
jobwatch looks for the posting on your watched boards by the requisition id in its title (`R0123456`,
`REQ-4711`, `Job 20769`), so a Workday posting fetched later fills in the sheet.

### Drafted answers from your stories

`jobwatch prep c1 --draft` adds the one part that is written for you, and only from what you've written
yourself: 6 to 10 questions this role is likely to bring up, each with the requirement it probes, and an
answer outline built from your stories and your resume, naming the stories it used. A question none of them
answers says "no story yet", with one honest line: what's closest, and how you'd ramp up.

Your stories are a YAML file you write once and point the watchlist at (`stories: ~/Documents/stories.yaml`).
Each is a project you'd talk about on a call:

```yaml
- id: alert-dedupe                    # what answers cite it by
  title: Cut duplicate on-call alerts
  did: Built a Python service that groups alerts about the same incident before they page anyone.
  hard: The teams named the same hosts three different ways.
  result: Pages per week went from 120 to 35 in two months.
  skills: [Python, Kafka]             # optional
  avoid: [the vendor's name]          # optional: details you're not sure of, or don't want said
```

[examples/stories.yaml](examples/stories.yaml) has a few more, made up. You don't have to write them by hand:
[Find a story](#find-a-story) interviews you and adds one for you. After editing it by hand, `jobwatch stories`
checks it and lists what's there. A mistake in the file (a missing
`result`, two stories with the same id) is reported with the story and what to fix.

The model is told never to invent experience, numbers, employers or credentials, and its answer is checked
anyway before it reaches the sheet:
- an answer citing a story you don't have is dropped;
- a point with a number that's in neither the stories it cites nor your resume is dropped (a number is what
  you'd repeat word for word, so it isn't just flagged);
- a point that says one of a story's `avoid` details is dropped too;
- an answer left with no story becomes "no story yet";
- it's cut to length, and a reply that isn't the JSON asked for gives no drafts.
The sheet says what was taken out. With no model, an error or nothing usable, it keeps the usual questions:
prep never fails because the model did.

It uses the chat's model (`chat.backend`): `local` keeps everything on your computer; with `claude` the
posting, your resume and your stories go to Anthropic. A draft takes a while, so it's kept in the state file
and opening the sheet again reads it; a change to the posting, resume, stories, stage, model or instructions
drafts afresh. Its instructions are `drafts.PROMPT`, or your own in `prep.prompt` (keep `{context}`, where the
posting, resume and stories go); `prep.max_tokens` (4000) is the longest draft. MCP clients ask for it with
`get_interview_prep`'s `draft_answers`, and for role questions `role_questions`; the sheet it returns has
`brief`, `pay` and `role_questions` as fields of their own.

### Mock interview

`jobwatch ask --job c1 --mock` (or **Mock interview** at the top of the prep sheet in `jobwatch ui`) practises
the call one question at a time. The questions come from the prep sheet: one for each requirement and
responsibility in the posting first, then the usual ones for the stage (and the drafted ones, when you've
drafted them). Type your answer, or `skip`, `repeat` or `quit`; a summary closes the session.

Each answer gets short feedback from the chat's model: what landed, what's missing against the posting's asks,
and a tightened version. The model is told to use only facts from your answer, your stories and your resume,
never to invent experience, numbers, employers or tools, and to write "[add a real example of X]" where
something is missing. The code checks the numbers too: a tightened answer with one that's in none of those isn't
offered, and neither is one that says a story's `avoid` detail you didn't say yourself. Saving it is your call (`y/N`, or **Save to the prep sheet**): saved answers are kept with the job's
package, one per question, and show on its prep sheet under **Practised answers**, and in MCP's
`get_interview_prep` as `practised`. It runs on the chat's backend like the rest (`local` stays on your
computer; with `claude` the posting, your resume and your stories go to Anthropic); with none available it says
what to install, before asking anything.

### Drill video

`jobwatch prep c1 --drill drill.mp4` turns the prep sheet into a video to rehearse with. Each question is asked in
one voice, then the screen says **Answer out loud** and holds for 75 seconds (`--pause 60` to change it), then
the answer's cue words come up while a second voice gives the full answer. `--no-pause` drops the hold, for a
quick review.

The answers are only ones the sheet already has: practised answers from mock interviews, then drafted outlines
told with the stories they cite (so run `--draft` first, or practise with `--mock`). A question with no answer is
left out, never filled in. The key can also be a prep sheet you wrote yourself, as HTML: every table with a
"Question" column and an "Answer" column gives one question a row, and so does every question heading
(`<h3 class="q">`) with a "say" block under it (`<div class="say">`), its paragraphs read as one answer. Text in
`class="muted"` (sources, asides) isn't spoken, nor is a paragraph with a `class="fill"` blank you haven't filled
in, nor a follow-up line like `If they push: "…"`:

```
jobwatch prep ~/prep/acme-sheet.html --drill ~/prep/acme-drill.mp4 --no-pause
```

It needs `pip install 'jobwatch[video]'`, which brings [slidecast](https://pypi.org/project/slidecast/) with
Kokoro voices that run on your Mac (Apple Silicon), and a browser to draw the slides (Chrome, or slidecast's
Playwright extra). Nothing is sent anywhere. The first run fetches the voice model and a small English language
model once.

### Find a story

A prep sheet shows where you're thin: an ask with nothing close on your resume, a drafted question with "no story
yet". Often there is a story; you just haven't remembered it. **Find a story** (at the top of the prep sheet, or
beside any of those lines) has the chat's model interview you about one of them, and writes what you tell it up
as a story for your story file. From the command line: `jobwatch ask --job c1 --story` lists the gaps to pick
from, or name your own (`jobwatch ask --job c1 --story "running a migration"`).

It asks one question at a time, starting broad: have you done anything like it, even partly, as a participant,
long ago? When you don't remember the details, it may offer what usually happens in a case like yours, under
**Common patterns, not your case**, for you to confirm or not. It's told never to present one as what you did,
to keep your real role (taking part isn't leading, a prototype isn't production), and to leave out what's
unsafe to say aloud: internal system names, people's names, the country of the people involved. With nothing
close, it says so and suggests one honest line instead.

When it has what you did, the hard part and how it ended (or you press **Write it up**), it proposes the story.
The code checks it before you see it: one with a number you never typed isn't offered, and neither is one that
says a detail it listed under `avoid`. You then check every line in the card, edit any of it, and press **Save
to my stories** (`y` on the command line). Nothing is saved before that. It's added to the end of your story file
with comments and the rest left as they were (the old file is kept as `.bak`); with no `stories:` set, it starts
`stories.yaml` beside the watchlist and names it there. Drafted answers and mock interviews use it from then on.

It runs on the chat's backend like the rest: `local` stays on your computer; with `claude` the posting, your
resume, your stories and what you type go to Anthropic. An assistant connected over MCP can run the same
interview itself: `get_interview_prep` returns `story_gaps`, and `save_story` keeps what you confirm.

## Comparing opportunities

The **Comps** tab (and `jobwatch comps`) puts your live opportunities, the applications at screening,
interviewing or offer, side by side as columns: stage, applied day, next step, pay as posted, place, fit score
with must-haves and top gaps, and the people you know there. Pick anything else to compare, any tracked job or
any company by name (even one you haven't applied to), with the box on the tab or `jobwatch comps KEY
--company NAME`; the choice is remembered in your browser. The highest value in a row (pay, base, offered, fit)
is starred.

What a recruiter tells you about pay is kept per job, and what you know of a company per company. jobwatch looks
none of it up: you type it in, or an assistant over MCP searches the web and records it with its source links.

```
jobwatch comp acme --base 170-200K --bonus "10% target" --equity "40K RSUs over 4 years" --signon 15K \
    --asked 215-250K --offered 190K --note "200K most likely their max" \
    --role product --career-note "agentic SOC product, principal IC"
jobwatch health "Acme" --kind tech --listing private --stage "Series B, $50M, 2025" --raised "$80M" --revenue "2x YoY" \
    --headcount growing --layoffs none --rating "4.1 Glassdoor" --risk "one big customer" \
    --sources "https://example.com/acme" --as-of 2026-10-20
```

A field you leave out stays; `''` clears it; `--clear` forgets all of a job's or company's. Health older than
90 days (or with no date) is marked stale. Over MCP the tools are `set_comp`, `set_company_health` and
`get_comps`.

The suggestion at the top ranks the opportunities by plain rules, no model. Its default weights are career value
(25%), pay against your `pay.target` (30%; at target is 80, 10% over 100, 10% under 50), fit score (20%), how far
along it is (10%: offer 100, interviewing 70, screening 40, applied 15) and company health (15%: 70 to start, public +10, layoffs -25, shrinking headcount
-10, rating of 4.0+ +10 or under 3.3 -10, a private company with under $20M raised -15, a risk note -10; growing
headcount +10). Pay uses what they offered, else the base they gave, else the posted range: the middle of the
range, since a nationwide band's top isn't what anyone is paid. Career value
starts from the company's `--kind` (`tech` 80, `consulting` 55, `enterprise` 40: a non-tech business whose IT
builds for itself, like a bank or insurer) and adds the job's `--role` (`product` +15 for building the company's
own product, `customer` +5 for forward-deployed or customer-facing engineering, `internal` -5 for internal tools),
kept between 0 and 100; `--career-note` is a few words of your own, shown but not scored. A part with nothing
to go on counts as 50. Those numbers are one person's goals; say yours with `goals:` (below) and the career part
follows them. Change the weights in the
watchlist; any numbers 0 or more, scaled to add up to 1 (a part you leave out keeps its default, so give all five
to be exact):

```yaml
comps:
  weights: {career: 40, pay: 30, fit: 15, progress: 5, health: 10}
```

Each opportunity shows its score, every part with the input it came from, and a sentence
on why.

**Your goals.** Say what you want next, and the career part scores against it instead of the fixed numbers
above (Settings → Your goals, or the watchlist):

```yaml
goals:
  about: "Staff engineer, ten years in security tooling, ready to build product again."
  company_kinds: [tech, consulting, enterprise]   # best first; or: any
  roles: [product, customer, internal]            # what the job builds, best first; or: any
  stages: [growth, startup, public]               # seed to Series B, Series C+, listed; or: any
  track: ic                                       # ic, manager or either
  horizon: "take risks for the next 3-5 years"
```

`company_kinds` and `roles` are in order of preference: a kind scores 90, 65 or 40 (first choice best) and a role
adds +10, 0 or -10; one you leave off the list ranks last, and `any` is neutral (65 and 0). Name only one of the
two and the other keeps its fixed rule. Without either, nothing changes from the numbers above. `stages` adds +10,
0 or -10 the same way, for a company whose Company health says how far along it is: public when it's listed, a
startup through Series B, growth stage from Series C on. A company with no stage kept gets nothing either way, and
without `stages` its stage counts for nothing. The suggestion's
input says which choice of yours a job is ("tech company (your 1st choice)"). `about`, `track` and `horizon` are in
your own words and change no score; `about` and the rest are read only if you ask for title suggestions when
setting up. Settings → Your goals also has `pay.target`, a private `pay.floor` (never shown elsewhere) and the
five weights as sliders.

**Worth it.** Today and the apply queue can also be ordered by the same score, with the **Worth it** button (kept
per browser). Each card then shows `worth N`, and hovering it lists the parts. A job isn't applied to yet, so the
progress part is left out and the other weights are scaled up to add to 1; pay is the middle of the posted range
(or what a recruiter told you, if kept), career and health come from the company's kept `kind` and health, and
anything unknown counts as 50. Only the order changes: fit scores and `filters.min_fit` work as before.

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

Someone you'd never ask for a referral can be left out, by name or profile link:

```yaml
connections_skip: [Jane Doe, https://www.linkedin.com/in/example-john]
```

Or say so as you go. The **Referrals** tab lists the people you know at companies with a new, queued or open
job, closest ties first, with the jobs they're at. **Use** puts someone ahead of closer ties; **Don't use**
stops suggesting them (they wait in a fold, to restore); a note keeps a few words with the name ("doesn't check
LinkedIn; reach on WhatsApp") and shows beside it on the job cards, where a small **Don't use** does the same.
People in `connections_skip` are listed there too, read-only. The same from the terminal, and for an assistant:

```
jobwatch referrals                                  # the same rows
jobwatch referrals --use "Ana Li" --note "answers fast"
jobwatch referrals --skip "Bo Chen" --note "doesn't check LinkedIn"
jobwatch referrals --clear "Bo Chen"                # NAME is a full name or a linkedin.com/in/ link
```

The MCP tool is `rate_contact` (who, verdict `use`, `skip` or `clear`, note). What you say is kept in the
state file next to your jobs, keyed by profile link (or name when there is none).

A digest lists each job once, the top `display.today` (10) of them, and ends with how many more match;
those stay new for the next digest. Use `digest --all` for every match, including jobs already shown,
`--limit N` for another number, or `--peek` to look without marking them shown. Roles that disappear from a
board are marked closed. The MCP `get_digest` returns the same top 10 by default, with today's pace.

## MCP server

`jobwatch-mcp` offers these tools to Claude Code or any MCP client:

- **Watchlist:** `find_board`, `list_boards`, `add_board`, `remove_board`, `list_suggested_boards`,
  `dismiss_suggested_board`
- **New jobs:** `fetch_jobs`, `import_job_alerts`, `get_digest`, `get_job`, `list_jobs`, `list_skill_gaps`
- **Applying:** `mark_job`, `list_queued_jobs`, `check_postings`, `add_application`, `list_applications`,
  `find_duplicates` (`get_job` and `list_queued_jobs` give each job's `duplicate_of`), `get_company`,
  `rate_contact`, `read_profile` (the roles on a LinkedIn experience page whose text you pasted: who the
  interviewer is; it never fetches linkedin.com)
- **What was sent:** `save_application_package`, `get_application_package`, `find_past_answers`,
  `get_interview_prep`, `save_story`

(0.3.0 renamed them to verb_noun: `digest` is now `get_digest`, `job_details` is `get_job`, `apply_queue` is
`list_queued_jobs`, `applications` is `list_applications`, `application_package` is `get_application_package`,
`interview_prep` is `get_interview_prep` and `skill_gaps` is `list_skill_gaps`.) The watchlist comes from
`JOBWATCH_CONFIG`:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp
```

`jobwatch mcp` runs the same server. Without installing anything first,
[uv](https://docs.astral.sh/uv/) can fetch and run it:

```
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- uvx --with 'mcp>=2.2' jobwatch mcp
```

It's listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.vinayvobbili/jobwatch`.

[skills/jobwatch/SKILL.md](skills/jobwatch/SKILL.md) is an agent skill that tells an assistant when and how to
use these tools (setup, the daily loop, status emails, interview prep, and what never to do for you). Copy the
folder into `~/.claude/skills/`, or zip it for a skills marketplace: `cd skills && python -m zipfile -c
jobwatch-skill.zip jobwatch`.

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

## Getting more interviews

What moves an application from the pile to a recruiter's call, and where jobwatch helps:

- **Apply early.** Recruiters read the first applications to a role, and many stop once they have enough to
  interview. Run jobwatch daily so you see a role the day it's posted, not a week later on an aggregator.
- **Ask for a referral first.** A referral gets read before an application does. Before you apply, check
  [who you know there](#who-you-know-there) and ask someone who knows your work, not a stranger who
  accepted a connection request.
- **Fewer, better applications.** A resume tailored to the posting, with its must-haves where a screener
  looks for them, beats ten generic ones. Use the [fit score](#fit-scores) and its gaps to pick the roles
  worth that work, and the daily pace to keep it a few a day.
- **Close real gaps, don't paper over them.** A claim you can't back up ends the interview it got you.
  [Skills to build](#skills-to-build) lists what your matches keep asking for; build one and point to it.
- **Be findable.** Recruiters search too. Public work they can look at (a GitHub with real projects, a write-up
  of something you built, a post now and then about what you're learning) gets you messages for roles you
  never applied to.
- **Follow up, then move on.** A short note to the recruiter or hiring manager a week or two after applying
  is fine; [quiet applications](#applications-that-go-quiet) tells you when. Don't apply to the same opening
  twice ([the same opening twice](#the-same-opening-twice) catches reposts), and mind companies that cap how
  many roles you apply to.
- **Answer fast.** When a recruiter writes, reply the same day. Keep what you sent and
  [prep sheets](#prep-sheets) ready, so a screen next week isn't a scramble.

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev,mcp]'
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

CI tests on Python 3.10 and 3.13. `scripts/check` runs the same checks on both locally (it needs
[uv](https://docs.astral.sh/uv/), which fetches each Python). `git config core.hooksPath .githooks` runs it before
every push.

Tests use canned board responses and never touch the network, except the check that every curated course
link still resolves: `JOBWATCH_LINK_TESTS=1 pytest tests/test_learn.py`. To see how `jobwatch ui` looks after a change,
`scripts/screenshots.py` captures every tab in light and dark, at wide, desktop and phone widths, plus the
chat with a canned reply (it needs
`pip install playwright && python -m playwright install chromium`).
`scripts/demo/make-video` rebuilds the demo video from made-up data: see
`scripts/demo/README.md`.

Releases publish to PyPI through Trusted Publishing when a `v*` tag is pushed, and then to the MCP Registry
from `server.json` (keep its two versions in step with the package; a test checks).
`scripts/release.py 0.2.3 -m "what's in it"` does the whole release: it bumps all three versions, runs
`scripts/check`, commits, tags, pushes, and waits until PyPI and the registry show the new version
(`--dry-run` shows the bump first).

MIT licensed.
