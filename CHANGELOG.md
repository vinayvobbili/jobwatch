# Changelog

## Unreleased

- Requires Python 3.11 or newer (3.10 reached end of life in October 2026).
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
  the company's own site. The extension's button doesn't offer Ladders yet.
- Fix: a job with no link no longer reads as a repeat of the one before it when a list or alert is taken in.
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
