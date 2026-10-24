# The watchlist

[← jobwatch guide](README.md)

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

## When a company's job pages are offline

Some companies keep listing jobs on their Ashby board while Ashby's own job pages for them say "Page not
found" (they've moved applying to their own site). jobwatch looks at the board's Ashby page once a day while
it fetches. If it's offline, `jobwatch fetch` warns about that board, and each of its jobs says to apply
through the company's own careers site (on Today, in a job's details, in `jobwatch show` and to an AI
assistant). Add the company's careers site to the board, `{board: ashby:acme, careers:
https://acme.example/careers}`, and its jobs link there instead. If the page can't be read, nothing changes.

## Filters for one board

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

## Hacker News' Who is hiring

`hn:whoishiring` watches the latest monthly "Ask HN: Who is hiring?" thread; `hn:whoishiring/3` the last three
(up to 12). It's read from HN's search API (hn.algolia.com), which robots.txt allows: one request finds the
threads and one reads each whole, so a run never asks for a post at a time. Each company's post is one job, named
after its company, with every role its first line names in the title ("Senior Engineer, Designer"; roles
listed further on when the first line has none). The place, remote and pay come from that first line
(`Acme | Senior Engineer | Remote (US) | $180k-$220k | link`), and the post's text is the description. The job
links to the company's own job page when the post has one (a posting on a board jobwatch reads first, then that
board, then a careers page), else to the post on HN. Boards it links to are noted with the job, not read: a
company whose post passes your filters shows up under [Companies to watch](applying.md#companies-to-watch), with the board
its post links to when there is one. A post that's deleted or flagged is gone from the thread, so its job closes;
an edited one is read again. Replies, remarks and job seekers' posts aren't jobs. The first line is free text,
so a post written in sentences may come out as "Open roles (see the post)". Posts aren't fit-scored: one lists
several roles, places and links, which a score would read as one job's must-haves; watch the company's board to
score each role.

## How locations match

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
