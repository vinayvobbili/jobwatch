# Changelog

## Unreleased

- `jobwatch grep COMPANY -t TERM...` lists a company's tracked jobs whose saved posting text holds any of the terms
  as whole words ("ITAR" is not found in "military"; a term in capitals matches in capitals only, so "EAR" is not
  "ear"; "U.S. Person" also finds "U.S. Persons"). Closed postings are left out (`--closed` adds them, `--open` keeps
  only those with no closed mark), jobs whose text was pruned are counted, and `--live` reads each posting from its
  own page now instead, saying whether the kept text had the term too, so a requirement added after the first
  look shows. Nothing is saved. `--format json` has the snippets and the pages that couldn't be read.

- A job being scored now shows a spinner instead of small print. When Read posting has read a posting, or the
  background scorer has the job, the card's score spot holds an animated ring in the card's colors (a pulsing dot when
  your system asks for less motion) and the "Posting read: scoring it now…" line under the buttons is gone;
  "Scoring…" is its tooltip and screen-reader name. The Score button already shows a spinner and stays off while it
  runs. The spinner clears when the score arrives or the scoring fails (the error shows as before).
- Rows from a source that doesn't name its client (Ladders, or a name ending in Staffing or Recruiting, on a job from
  an alert, a list or a link) are hidden from Today as "client not named", unless the posting names its client
  ("Client: Globex") or you name it (`jobwatch resolve --name KEY COMPANY`). They stay on the company page and in
  search. `jobwatch resolve` matches each such row to a named company's copy of the same opening (same title, pay
  range within 1% and remote setting, across companies, which `dupes` doesn't do) and prints the pairs
  (`--explain` says how the nearest same-title jobs differ for rows with no twin); `--apply` marks the
  unnamed copy skipped with a note naming its twin (the twin, queued and applied jobs are never touched). The staffing
  warning now also fires on "For our client, we are seeking ..." and "For our client, a leader in the X space", and
  `auto_watch` leaves Ladders alone like any agency.
- `jobwatch resolve --apply --only KEY [KEY ...]` applies just the pairs whose keys you name (the keys the dry run
  prints, either the unnamed copy's or its twin's); the other pairs stay as they are. A key that names no pair is an
  error and nothing is applied.
- A scorer out of quota or credit is paused on its own, on every path that scores (a card's Score button, the
  page's background scorer, Read posting, the ↻ rescore, `jobwatch score`, `jobwatch credit --test`). The pause is on
  the whole quota pool: `claude_api` (Claude's API), `agy_claude_gpt` (every agy Claude and GPT model),
  `agy_gemini` (every agy Gemini model), `local`, or a provider's own, so a second step on the same quota is skipped
  with no call. It lasts until the time the error names (agy's "Resets in 138h16m", "it refreshes in 5 days, 10
  hours", a 429's Retry-After, Google's retryDelay), or an hour when it names none (the reason says so); then one
  call tries again, and a step that scores clears its pool's pause. A run that scores some jobs and then hits the
  limit pauses it too, and a run stops calling once one job finds the step out. The Claude credit's daily cap pauses
  `claude_api` until midnight Eastern and its total cap until you resume it. Pauses live in the state file with an
  absolute UTC time, so they outlive a restart and end on the clock; a row with an unreadable time counts as none.
  `jobwatch scorers` opens with each pool as a flag (available: yes, or no and back at when, and why), and
  `--pause`/`--resume` take `--pool NAME` for a whole pool. Settings' AI & fit scores card shows the pools as green
  or amber dots with the time each is back, and a paused step's tag gives the date as well as the time.
- A stale score no longer hides its number. The amber "stale" badge was drawn over the ring and covered the score
  (85/100 read as the word "stale"). The ring now shows the number as usual with a small clock icon on its rim
  (amber for an older resume, rose for a score marked stale), and the tooltips are the same.
- The Queue card's button reads "Remove" instead of "Remove from queue" (the tooltip and screen-reader name keep the
  full words), which saves room beside I applied and Snooze.
- A company's page folds its skipped jobs and closed postings into one dimmed "Closed (N)" group under the live
  cards. It starts collapsed, a click opens it, and the browser remembers which. The tiles above still count them.
- `jobwatch scorers` lists each step of the scoring chain, active or paused until a time with why and whether a run
  or you set it, from the state file alone (no page token, no model call). `jobwatch scorers --pause STEP --until
  "YYYY-MM-DD HH:MM" [--reason TEXT]` holds a step by hand, for one you know is out of quota, so the chain skips it
  with no call and no failed batch first; `--resume STEP` ends the pause.

- A job that was never scored no longer gets a green "Queue it" on its pay. With only the pay to go on, the card's
  bottom line is an amber "Score it first (press Score on the card): the posted pay goes up to $195K, within your
  target" ("Read posting scores it" when the posting text isn't there yet), the Why row says "Score first: ...", and
  Queue stays available. A score coming in replaces it with the real advice; a stale score counts as a score. Skip
  reasons (under the pay floor, applied before, turned down, on-site elsewhere) and a contact you know there are
  unchanged. `jobwatch advice` counts these as "score first".
- A new resume no longer makes fit scores stale, hides them or asks for new ones. Every rebuilt resume used to give
  every job a new score key, so each card read "not scored yet", Today lost its scores and a re-score paid for the
  lot (two rebuilds one morning cost about $4). Now each job keeps its newest score whatever resume made it, shown
  with a small amber "stale" badge (hover: "scored under an older resume") when that resume is older. A stale score
  filters, ranks and advises like any other; "No score yet" is only for jobs that never had one; nothing is scored
  again on its own. A new shortlist-ai (its version, prompts or scoring code) no longer flags a score either.
- Staleness is a decision you make, with the number in front of you. Today says "N scores predate your resume"
  (Settings → AI & fit scores → Scores and your resume has it too) and **Decide…** offers **Keep scores** (the
  current resume becomes the baseline; nothing is scored or paid) or **Mark stale** for every score, those at the
  Fit minimum or 60+, the queued jobs', or both of those, with a reason. Marked scores show a rose badge ("marked
  stale on 2026-11-26: new summary") and are scored again by the background scorer (when on), the Score button,
  `jobwatch score --rescore` and `--batch-api`; each new score clears the mark. The shell has `jobwatch scores`
  (which resume made how many), `--keep`, `--stale [--min N] [--queued] --reason WHY`, `--unmark` and `--log`;
  every decision is logged. Existing scores migrate by themselves: the state file gains three small tables, no
  score row changes, and every score made under an earlier resume (today's) shows as stale-badged. The Score button
  on a stale card scores it again. `jobwatch score --rescore` now takes only marked scores and ones another model
  made (a score made under an older resume waits for the decision), and says how many predate the resume. The card's
  advice and bottom line read a stale score like any other and say so ("a strong fit (82/100, stale score)").
- Who to contact. A job card's "Who to contact" button (also `jobwatch contact KEY` and the `find_contact` tool) lists the
  people the posting names (hiring manager, recruiter, interviewers, team lead; read by a plain parser, no model), the
  ones your notes name at the company and the people you know there (Connections.csv), with four LinkedIn people
  searches for you to open (jobwatch never reads linkedin.com). A button beside each person drafts a note to them: a
  LinkedIn note of 300 characters or less and a short email, ending with an ask (a referral to this role for someone you
  know, a short chat or the right way to send a resume for a manager or recruiter). Claude writes it from an allowlist
  (company, title, stage, day applied, the first name, what the person is to the job); with `reply.followup: local`, no
  key or no Claude answer, the local model writes it from the resume's confirmed lines, else a fixed template. A
  warning lists a stock opener, a figure the tracker doesn't hold or pay talk. It says first when you've already
  applied to the job or its duplicate. Nothing is sent or saved.
- A morning digest. After the day's first scheduled check, jobwatch shows a macOS notification naming the best new
  matches (title, company, fit or pay) that pass your pay floor, places and filters and aren't applied, skipped or a
  duplicate, and keeps the list as a page that clicking the notification opens (with terminal-notifier installed; else
  the notice alone). Nothing new, nothing shown. `jobwatch digest --notify` does it by hand (`--dry-run` shows what it
  would say, `-o FILE` writes the page); `morning: {notify: off, top: 3}` in the watchlist turns it off or sets how
  many it names.

- A score made from a card's Score button, or by `jobwatch credit --test`, is now an Activity row like every other
  score. It was saved with no row, so `jobwatch activity --since today --kind score` and the Activity tab said nothing
  about those scores.

- Today's Fit score minimum (60+, 70+, 80+) now hides the jobs with no score yet. The "No score yet" switch turns to
  Hide when you pick one, so 80+ no longer lists unscored cards, and the Showing line counts them out. Pick Show by
  hand and it stays until the fit changes; back on Any, the switch is what this browser had kept (a choice made under
  a fit minimum isn't kept).
- A card's suggestion and bottom line now follow its score. A card drawn before its job was scored said "Queue it: the
  posted pay goes up to ..."; when the score (a 40, say) came in, only the rings changed, so a weak fit sat over a
  green Queue. The page now asks `/api/advice` for the card's lines again whenever a score arrives (the Score button,
  Read posting, Rescore).
- A job that is on-site only outside your places gets a skip reason, not a Queue. A board's remote flag over two or more
  other places (or over one, when the posting asks for office time) passed the place filter, and good pay made the
  advice green. The suggestion now says "Skip: on-site in Austin; Chicago, not Denver or remote" (the first of
  `filters.locations`), and the bottom line says to ask the recruiter about your area or remote first. Remote by
  arrangement doesn't count. `jobwatch advice KEY` shows one job's suggestion and bottom line as its card has them.
- A job that shows only because its company is in `filters.nearby_offices`, yet is on-site somewhere else, is no
  plain Queue either. The card's Why line says why it shows ("Initech has an office near Denver; role is on-site
  Austin, TX: ask if the Denver office is an option", in amber) and the bottom line reads "Queue it, ask first: ...".
  It still passes the place rules; `jobwatch advice` counts these as "ask first".
- Read posting now scores its job at once. When the extension saves a posting's text (or the company's board replaces
  it), that one job is scored in the background with the scoring chain (`scoring.backend`, then `scoring.fallback`,
  the dated Claude entry first, under its caps), whatever `scoring.auto` says: it only controls the bulk scorer. The
  card says "Posting read: scoring it now…" instead of "in line to score", and the score (or why it failed, as for
  Rescore) replaces it with no click on Score. A job with its text but no current score (or a stale one) is scored
  by a read too; one already being scored isn't scored twice, and the bulk scorer skips it.
- Pay alone no longer says "Queue it". The posted pay (or Levels.fyi's ask) reaching `pay.target` counts as a reason
  to queue only when the job's fit score is 60 or more, or it has none yet; a poor match that pays well now reads
  "Skip it: not a close match". The bottom line could also say a plain "Queue it: the posted pay goes up to ..." for
  a fair fit (it should say "it's a stretch"): the poll that fills in the expected pay read only the current fit
  score, so a job showing an older scorer's score (stale) looked unscored to it. It now reads the score the card shows.
- Dates the page and the commands show for a posting closed, a job first seen or a status change are now your day,
  not UTC's. The store keeps its stamps in UTC and the page cut them to ten characters, so after 7 PM Eastern a
  posting found closed that evening read "closed" with tomorrow's date (and the company page showed "Nov NaN").
  One helper does it in the page (`localDay`) and one in Python (`jobwatch.localday.local_day`); the stored data is
  unchanged.
- A weak fit with no must-haves no longer shows an empty Gaps row. A posting with only an "ideal candidate has" list
  has no must-haves, so its fit had no gaps to list next to a low score. The card now lists the requirements the
  score judged missing, then the partly shown, each marked a nice to have (or a must-have).
- A degree requirement your education already meets no longer shows as a gap. A fit score can lose a degree's level
  on the way ("MS in Computer Science" read as a subject with no level), so "Bachelor's degree in Computer Science
  or a related discipline" came back partly met. Where a gap is a plain degree requirement and the `education:` in
  your profile.yaml (next to the watchlist, else resume-kit's content folder) has a degree at that level or above in
  that field (or a related one, when the posting says "or related"), the gap leaves the card, counts as met in the
  must-haves, and the box and "Why this score" say it was reconciled with your profile. The score is not made
  again. PhD requirements, fields your profile lacks and lines that also ask for years, a certification or a
  clearance are left alone; with no education in the profile nothing changes.
- `mark --note` replaces the whole note, so it used to wipe an application's dated history without a word. It now
  keeps the replaced note (in the database), says how long it was, and `jobwatch notes KEY --undo` brings it back;
  `jobwatch notes KEY` lists the notes replaced. The MCP `mark_job` refuses `note` on a job that already has one
  (use `add_note`) unless `replace_note` is true, and the CLI help says `--note` replaces.
- `jobwatch notes KEY... --from-backup ARCHIVE` reads jobs' notes out of a backup (a file, or the day it was made)
  without touching the database; `--restore` writes the archived note back in front of the note there now, so
  nothing newer is lost (`--dry-run` shows it first).
- Requires Python 3.11 or newer (3.10 reached end of life in October 2026).
- `jobwatch company NAME --status STATUS` (repeatable) lists only the jobs in those statuses, every one of them (closed
  postings and the roles your filters leave out too, none cut), and `--keys` prints just their keys, one a line, for
  scripts. The MCP `get_company` takes `status`.
- `jobwatch mark STATUS --company NAME` gives every job at a company a status in one go, printing the keys changed:
  `--only-status` limits it to jobs now in a status, `--dry-run` shows what would change, and `--add-note`, `--note`,
  `--next`, `--follow-up` and `--on` apply to each. Jobs you applied to (applied or any later stage) are left alone and
  listed unless you give `--include-active`. New MCP tool `mark_company_jobs` (new, shown, queued or skipped).
- `jobwatch import-list --unplaced [--source SITE] [--since DAY]` lists the jobs the imports tracked from the list's
  text alone (not found on the company's board), newest first, with company, title, place, site, key and why (no
  board found under its name, or not on its board); `--format json` too. The reason is now stored with each import; for
  an older job it comes from the kept `import-list.jsonl` run or is guessed. New MCP tool `list_unplaced_jobs`.
- `jobwatch find --try-variants NAME` tries a name's variants in turn (without Inc, LLC, Corp, Ltd or Holding, split
  into words, cut to its first words) and says which one found a board, one call in place of several `find` calls;
  `--add` works on the board found. The MCP `find_board` takes `try_variants`.
- Today's Best fit order now marks a posting down for its age, so old postings stop outranking fresh ones: no
  penalty for the first 7 days, then 0.5 fit points a day off the rank score (a 30-day-old posting needs about 11
  points more fit than a fresh one), and a posting over 120 days old lists below every younger one; a posting with no
  date counts as 14 days old. The fit score and badge don't change, only the order, and `jobwatch digest` and the
  MCP `get_digest` use the same order. `display.age_decay: {grace_days, per_day, cutoff_days}` and Settings tune it
  (`per_day: 0` turns it off).
- Today opens on Posted within 7d (it was Any). A choice you make there, Any included, is kept in this browser, Clear
  filters goes back to 7d, and `display.today_defaults.posted` (or Settings) sets the default (0 is Any). The header
  says how many postings the chip hides, and an empty Today offers Widen to 14 days or Show any age.
- `import-list` (and the MCP `import_job_list`) takes Ladders lists ("Recommended Jobs", a search) as a third site,
  read in your own browser by the same extractor. Ladders shows the companies' own jobs, and you apply on the
  company's own site: the job's link is its board posting when found there, Ladders' page is kept only as a reference
  in the job's note (with its pay estimate), and a job not found on a board has no link and a note saying to apply on
  the company's own site.
- The browser extension's **Read the jobs on this list** now reads Ladders lists too ("Recommended Jobs", a search): a
  page at a time, like Indeed, following the list's Next link, up to the pages you set. It needs no new permission or
  site access: it reaches the Ladders tab only where you clicked the extension's icon, and "Note jobs while I browse"
  isn't offered there. `/ext/ping` lists a new feature, `list-ladders`; an extension paired with a jobwatch without it
  offers no button on Ladders (and says to update), so a Ladders pay estimate never lands in a job's pay. The extension
  is 0.13.0 for the Chrome Web Store ahead of this release: it also carries the unreleased Read posting fixes, ATS
  check and Cover letter, and the panel in a popup window for installed web apps.
- `chrome-extension/tools/package.py` (the Web Store zip) now only refuses an extension that is behind the package, and
  checks the manifest's content scripts are in the zip; `scripts/release.py` leaves a manifest already at the release's
  version, since the store's review takes days and the extension is submitted before the release is cut.
- Fix: a job with no link no longer reads as a repeat of the one before it when a list or alert is taken in.
- Today's **No pay clue** choice now starts on Hide: with a Top pay chip on ($175K+, say), jobs no source has a pay
  figure for stay out instead of listing after the ones with a figure. Show is one click away and, like Hide, is kept
  in the browser. A choice you already made (the page keeps only clicks, never its default) stays as it was.
- Fix: Read posting no longer fails with "unknown message readInBackground" when the extension is older than the page
  (the Web Store build lags, or an unpacked copy was not reloaded). The extension tells the page what it can do; with an
  older one the posting opens in a tab in front as before, the card still fills in when you come back (Today keeps its
  place), and a one-time toast says to update or reload the jobwatch extension.
- Fix: Read posting on a card no longer reloads Today from the top or pulls you to the new tab. With the extension
  (it adds a small script on your own localhost pages, which only your paired jobwatch may use), the posting opens in a
  tab behind the one you are on, is read there, and only that card changes (its text, closed badge and state); the
  scroll position and the card you were on stay put. Without the extension's new version the tab still opens in front,
  but coming back redraws Today where you were.
- Fix: the extension's Read posting now marks a job closed (the card's closed badge, a note, and the on-page banner in
  amber) when the LinkedIn or Indeed page says the posting is closed. It was dropped when jobwatch already had the
  posting's text, when the job was added by that read, and when the job was skipped; the banner line is also found with
  a stray space, icon text or a closing dot around it.
- Fix: the tab Read posting opens now closes itself reliably once the posting is read. The page's own `window.close()`
  is ignored by Chrome for a tab with LinkedIn's redirects in its history, so the extension's service worker closes it
  (`chrome.tabs.remove`, no new permission), and only a LinkedIn or Indeed job tab whose posting it has just given to
  jobwatch; a tab that showed a sign-in wall or a captcha stays open for you. The page's `window.close()` remains as
  the fallback.
- Fix: Read posting no longer fails with "jobwatch took too long to answer" when jobwatch needs more than 20 seconds
  to fill a job in (it looks for the company's own board and scores the job first). The extension waits up to 90
  seconds for that call, and if jobwatch still hasn't answered says to look in Today and press Read posting again.
- Fix: `suggest`, `find` and the MCP `find_board` no longer abort with "'idna' codec can't encode characters: label
  too long" when a company name makes a host label over 63 characters; that guess now counts as no board found.
- MCP: `mark_job` with status `applied` asks for proof of submission through elicitation (confirmation page seen,
  confirmation email seen, or not yet) and records nothing on "not yet", decline or cancel; a client without
  elicitation gets the old behaviour plus a warning. `proof_seen=true` skips the question.
