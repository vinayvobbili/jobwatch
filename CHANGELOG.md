# Changelog

## Unreleased

- Dates the page and the commands show for a posting closed, a job first seen or a status change are now your day,
  not UTC's. The store keeps its stamps in UTC and the page cut them to ten characters, so after 7 PM Eastern a
  posting found closed that evening read "closed" with tomorrow's date (and the company page showed "Nov NaN").
  One helper does it in the page (`localDay`) and one in Python (`jobwatch.localday.local_day`); the stored data is
  unchanged.
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
- Fix: `suggest`, `find` and the MCP `find_board` no longer abort with "'idna' codec can't encode characters: label
  too long" when a company name makes a host label over 63 characters; that guess now counts as no board found.
- MCP: `mark_job` with status `applied` asks for proof of submission through elicitation (confirmation page seen,
  confirmation email seen, or not yet) and records nothing on "not yet", decline or cancel; a client without
  elicitation gets the old behaviour plus a warning. `proof_seen=true` skips the question.
