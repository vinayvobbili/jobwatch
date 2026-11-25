# The page and the command line

[← jobwatch guide](README.md)

**Tutorial: getting started** (1¾ minutes): install, `jobwatch`, the four onboarding steps, Today.

https://github.com/user-attachments/assets/f95f85df-406f-4ede-b84c-59569d1a586a

**Tutorial: your daily routine** (1½ minutes): today's picks, a job's details, the queue, "I applied",
Applications, the prep sheet.

https://github.com/user-attachments/assets/8653c4ca-a79d-4135-9be1-51ba3c9fccf6

## In your browser

```
curl -LsSf https://astral.sh/uv/install.sh | sh      # installs uv (other systems: brew install uv, or the docs below)
uv tool install jobwatch
```

Then run `jobwatch`. uv brings Python with it; install options for every system:
https://docs.astral.sh/uv/getting-started/installation/

Already have Python? `pipx install jobwatch` (or `pip install jobwatch`) works too.

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

It ends on Today; press **Check for new jobs** to look. Everything it asks is also in Settings. To keep it in
its own window with its own icon in the dock or taskbar, install it as an app: in Chrome or Edge, the install
icon at the end of the address bar (or ⋮ → Cast, save and share → Install page as app). From there:

- **Today:** new matching jobs, with pay, how long ago they were posted, keywords, and who you know there.
  It leads with **today's picks**: the top 10 in the order you sort by (best fit, newest or top pay), since
  a few good applications a day beat a long list. **Show all** opens every match, and the search and
  company filter always look through all of them. Today opens on **Posted within 7d**, so a posting older than
  a week stays out of the picks until you widen it (14d or Any; the header says how many it hides, and an empty
  Today offers the widening); a choice you make there is kept in this browser, **Clear filters** goes back to 7d,
  and `display.today_defaults.posted` in the watchlist changes the default. **Best fit** also marks a posting
  down for its age: its fit score and badge don't change, but its place in the order does. Nothing is marked
  down for the first 7 days, then 0.5 points a day come off, so a 30-day-old posting needs about 11 points
  more fit than a fresh one to rank above it, and a posting over 120 days old lists below every younger one;
  a posting with no date counts as 14 days old. `display.age_decay: {grace_days: 7, per_day: 0.5, cutoff_days:
  120}` sets these (`per_day: 0` turns it off; they're in Settings under Today & display too), and
  `jobwatch digest` and the MCP `get_digest` use the same order. A line says how many you've applied to today against your
  pace ("Applied today: 1 of 3"). **Queue** the ones worth applying to, **Skip** the rest. While the page is
  running it checks the boards by itself every 6 hours (`fetch_every` in the watchlist), and Today says when
  they were last checked. A job that disappears from its board drops off Today at the next check. **Companies
  to watch**, at the side, lists
  companies whose jobs keep coming in from alerts or Hacker News posts while you don't watch them (see
  [Companies to watch](applying.md#companies-to-watch)).
  The **Companies** list beside Today has a checkbox on each company: untick one to leave its jobs out from now on
  (it waits unticked at the bottom of the list, and each change has Undo). Its box filters the list as you type,
  and **All** and **None** tick or untick every company shown, or just the ones that match what you typed.
  **Details** on a job opens its full posting, whose **Stage** picker moves it to any stage (queued, applied,
  screening, interviewing, offer, rejected, withdrawn, closed by company, skipped or snoozed) with an Undo, so a rejection or a
  withdrawal is one pick away.
- **Queue:** your short list. Apply on the company's site, then press **I applied**. The pace line counts
  it: once you reach your 3 for the day it says so, and at 5 that the rest can wait until tomorrow. It's
  advice; nothing is ever blocked.
- Long lists come in pages (12, 24, 48 or 96 at a time, kept per browser).
- **Applications:** every job you applied to and where it stands (applied, screening, interviewing, offer,
  rejected, withdrawn, closed by company), with the next step and a follow-up day. Those due come first. Filter by status with
  the chips over the list (or click the pipeline bar), and switch between **Cards** and a sortable **Table**.
  **Add an application** covers jobs you found elsewhere, such as a referral or a recruiter. A posting that
  closed shows "posting closed Nov 17", an amber badge until you clear it, and a line in the **Closed postings**
  strip on top; [`jobwatch notify-closed`](tracking.md#closed-postings) pops that up on your Mac once a day.
- **Company:** everything tracked at one company, whatever its status, as the same cards with the buttons each
  status calls for. Find one with the box at the top (`/` from any tab), or click a company's name on a card.
  **Snooze** on a card sets a job aside while you have an application in progress at that company: it isn't a
  no, and it comes back to your Queue when that application ends, or after 3 weeks if there's no news. The Queue
  lists what's snoozed at the side, with **Queue now**.
- **Your data** is one folder on this computer (`~/.local/share/jobwatch`). `jobwatch backup` writes the database,
  what you sent with each application and the watchlist to a dated archive in a synced drive's folder (Google
  Drive, Dropbox or OneDrive, or `--dest`), keeping the newest 30; `jobwatch backup --install` runs it daily on a
  Mac, and Today says so in red if the newest archive is more than 2 days old. `--also PATH` keeps another file or
  folder in the archive, such as one your private repo ignores. `jobwatch backup --verify` unpacks the newest archive
  somewhere temporary and opens what's in it. To restore, stop the page and unpack the newest archive into that folder.
  `jobwatch prune` shrinks a big database: it lists old closed jobs nobody acted on (those it would delete) and
  old open ones (whose posting text it would drop), and `--apply` does it after copying the database first (`--days`
  sets how old, 30 by default). A job you queued, applied to, scored, noted or kept anything for is never touched.
- **Settings:** the whole watchlist, one card per part, with a bar that jumps to each card and keeps Save in
  reach: the companies you watch (with each one's name and careers link) and how often to check them; filters
  (titles, places, departments, pay, age, minimum fit score, and warnings to flag in a posting); keywords;
  how many picks Today shows and your daily pace; your resume, where fit scores run, their model and the
  [prompt that scores fit](fit-scores.md#the-fit-score-prompt); your LinkedIn connections; the [chat](chat.md)'s model,
  reply length and instructions; [expected pay](watchlist.md); [job-alert emails](applying.md#job-alert-emails) from
  a mailbox; [Companies to watch](applying.md#companies-to-watch) and [Skills to build](skills.md); and the
  page's theme (system, light or dark) and width (standard, wide or full, for a big monitor). Each setting
  says in a line what it does, a blank one shows its default, and a bad value is refused with why, leaving
  the file as it was.
- **Ask jobwatch:** a chat on Today (about all of today's jobs and your applications) and beside each job's
  details (about that posting). See [Chat](chat.md).

The page only talks to jobwatch on your own machine. The one exception is a model you choose: with
`scoring.backend: claude`, fit scores and chat send the posting and your resume to Anthropic (and
[drafted prep](interview-prep.md#drafted-answers-from-your-stories), your stories too); with `agy`, fit scores send them to
Google through the Antigravity CLI. It's the same
watchlist file and history as the command line, so you can switch between the two.

To have the page always there, even after a restart, on a Mac, Linux or Windows:

```
jobwatch service install      # starts jobwatch ui when you log in, and again if it stops
jobwatch service status       # running? where's the log?
jobwatch service uninstall
```

What it sets up depends on the system, and none of it needs administrator rights:

| System | What it makes | Log |
| --- | --- | --- |
| macOS | a launchd agent, `~/Library/LaunchAgents/io.github.jobwatch.ui.plist` | `~/Library/Logs/jobwatch-ui.log` |
| Linux | a systemd user unit, `~/.config/systemd/user/jobwatch-ui.service` | `~/.local/state/jobwatch/ui.log` |
| Windows | a Task Scheduler task named `jobwatch-ui` that runs when you log on, with no console window | `%LOCALAPPDATA%\jobwatch\ui.log` |

On Linux, run `loginctl enable-linger $USER` once if it should keep running while you're logged out. It needs
systemd: on a system without it (a container, or WSL without systemd), `jobwatch service install` says so, and
you start `jobwatch ui --no-browser` yourself from whatever starts things there. On Windows, `status` reads
Task Scheduler's English labels.

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

A row about a job links to it: the company and title in the line open that job's card (on Today, Queue or
Applications, scrolled to and highlighted for a moment) or, when it has no card there, its details; a row about several
jobs ("Found 3 postings taken down") folds out a list of them, and a button beside the row (it shows when you hover it
or tab to it) opens the card too. A prep sheet's row links to the application the sheet belongs to. Rows from before
jobwatch kept this are matched by the "Company: Title" they name, only when exactly one job has it.

Each card shows the company's logo once it's known, else its initials. The logo is the icon on the company's own
site (no logo service is asked), found in the background the first time a company shows up: the site is the
domain its postings link to whose name is the company's, else its name plus .com when that home page names it.
It's kept in the state file, and a company with none found is looked at again after two weeks. Sites that refuse
jobwatch's requests keep their initials. `jobwatch logos` looks them all up at once (`--again` to refresh).

A login item doesn't see variables set in your shell profile, so with `scoring.backend: claude` the page's
chat and scores need the API key another way: keep it in the macOS keychain and name the item in
`scoring.keychain` (`security add-generic-password -s anthropic -a "$USER" -w`, then `keychain: anthropic`),
give `ANTHROPIC_API_KEY` to launchd (`launchctl setenv ANTHROPIC_API_KEY ...`; on Linux an `Environment=` line
from `systemctl --user edit jobwatch-ui`; on Windows a user environment variable), or run `jobwatch ui` from a
terminal instead. The local backend needs nothing.

## On the command line

```
jobwatch init                         # writes an example jobwatch.yaml
jobwatch find "Globex" "Scale AI"   # find each company's board
jobwatch find https://jobs.lever.co/spotify/4f1c2a9e-...   # or paste any job link
jobwatch find "Globex" --roles agent   # also list the board's open roles with "agent" in the title
```

`--roles` lists each matching role with its place, pay (read from the posting's text when the board has no pay
field) and posted day, without adding the board to your watchlist.

A company's name as people write it ("Initech Holdings, Inc.") isn't always the one its board goes by.
`jobwatch find --try-variants "Initech Holdings, Inc."` tries the name as given, then without Inc, LLC, Corp, Ltd or
Holding (each in turn), a name written as one word split into words ("InitechSystems"), the first two words and the
first word, and stops at the first that finds a board with open roles, saying which one did (the joined and hyphenated
board names of each, `initechholdings` and `initech-holdings`, are tried for every variant). `--add` watches that
board, named as you gave it. The MCP `find_board` has `try_variants`.

`find` prints a line like `Globex: greenhouse:globex (627 open roles)`. For a Workday company it tries
the usual site names; if that finds nothing, paste a job link from their careers site (it has
`myworkdayjobs.com` in it) and `find` reads the board from it: `workday:initech.wd5/InitechCareers`.
An Oracle Recruiting Cloud site is found the same way, from a job link with `oraclecloud.com/hcmUI/CandidateExperience`
in it: `oracle:eeho.fa.us2/CX_45001`.
A company's own careers page works too (`jobwatch find https://careers.acme.com/jobs`): `find` reads it for
links to a board, which is how a board under a name nobody would guess turns up. Add those
entries under `companies:`, adjust the filters, then:

```
jobwatch run                          # fetch every board, then show the digest
```

Run it daily, for example from cron: `0 8 * * * jobwatch run -o ~/jobs-today.md`.
