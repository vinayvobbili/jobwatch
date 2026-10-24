---
name: jobwatch
description: Run a job search from your agent with the jobwatch MCP server. It watches company job boards (Greenhouse, Lever, Ashby, Workday and more), ranks the new roles into a daily digest, queues the ones to apply to, tracks every application through to an offer, and builds interview prep from what you sent. Use when the user wants to find jobs at companies they name, see what's new, decide what to apply to, record an application or its status, read recruiter or status emails, or get ready for an interview.
---

# jobwatch

jobwatch is an open-source job-board watcher and application tracker (MIT, on PyPI). Its MCP server keeps a
watchlist of companies, checks their boards, and remembers every job, application and status in a local file
on the user's computer. Nothing is sent anywhere except the job boards it reads.

## Setup (once)

If the `jobwatch` tools aren't available, set it up:

```
pipx install 'jobwatch[mcp]'      # or: pip install 'jobwatch[mcp]'
jobwatch init                     # writes an example watchlist, jobwatch.yaml
claude mcp add jobwatch -s user -e JOBWATCH_CONFIG=~/jobwatch.yaml -- jobwatch-mcp
```

Other agents take the same command (`jobwatch-mcp`) with `JOBWATCH_CONFIG` pointing at the watchlist. Without
installing first: `uvx --with 'mcp>=2.2' jobwatch mcp`.

## The daily loop

1. **Build the watchlist.** For each company the user names, call `find_board` (a name, a job link or a
   careers page), then `add_board` with the entry it found. `list_suggested_boards` names companies whose jobs
   keep arriving while their board isn't watched.
2. **Check for new jobs.** `fetch_jobs` reads every board. If the user gets job-alert emails (LinkedIn,
   Indeed, Built In), fetch them with a mail connector and pass them to `import_job_alerts`.
3. **Show what's new.** `get_digest` ranks the new matches. Show the top few, not the whole list, each with
   why it fits and anything to check first (pay, location).
4. **Queue and apply.** `mark_job` with `queued` for the ones the user picks; `list_queued_jobs` lists them
   with people the user knows there (a referral is worth asking for before applying). `get_job` gives a
   posting's full text for tailoring a resume.
5. **Record what happened.** After the user submits, `mark_job` with `applied`, and
   `save_application_package` with the resume and answers they sent. Later stages are `screening`,
   `interviewing`, `offer`, `rejected` (they said no) and `withdrawn` (the user ended it, or it went quiet).

## Status emails

Search the user's mail for their applications' companies and phrases like "thank you for applying" or
"interview", and pass the messages to `read_status_emails`. It only proposes changes: show the proposals and
call `mark_job` only for the ones the user confirms.

## Before an interview

`get_interview_prep` puts the posting, the resume and what was sent on one sheet, with `story_gaps`: questions
a story from the user's own past would answer. Ask the user about one, and keep what they confirm with
`save_story`. `get_application_package` reads back exactly what was sent.

## Other tools

- `list_applications`: where every application stands, with follow-ups due and ones gone quiet.
- `get_company`: everything tracked at one company, closed postings too.
- `get_comps`: the live opportunities (or any jobs and companies you name) side by side, with a rule-based
  suggestion; explain its reasons and say what is missing. `set_comp` keeps what a recruiter said about pay
  (base, bonus, equity, asked, offered) as the user tells you, and the job's `role` (`product` builds the company's
  own product, `customer` is forward-deployed or customer-facing, `internal` builds internal tools) with a
  career note (with the company's kind, they set the suggestion's career part). `set_company_health` keeps a
  company's funding, layoffs and rating that you looked up on the web (jobwatch fetches none of it): record the
  source links and the day, and leave out what you couldn't find. It also takes the company's `kind` (`tech`,
  `consulting`, or `enterprise`: a non-tech business whose IT builds for itself). Health older than 90 days is stale: look it up again.
- `find_past_answers`: what the user answered before to a form question ("notice period", "reason for
  leaving"), newest first: reuse it before writing a new answer.
- `rate_contact`: record whom the user wants asked for a referral first (`use`) or never (`skip`, e.g. someone
  who doesn't check messages), with a short note; `clear` undoes it. Call it when the user says so about a
  person in a "you know" list.
- `read_profile`: the roles on a LinkedIn experience page, from page text the user copied or you got from their
  browser (never a link: jobwatch doesn't fetch linkedin.com). Use it for who an interviewer is.
- `check_postings`: whether queued jobs and open applications are still posted.
- `list_jobs`: jobs by status. `find_duplicates`: the same opening tracked twice.
- `add_application`: an application found elsewhere, from its link or pasted text.
- `list_skill_gaps`: what the matching jobs ask for that the resume doesn't show, with courses to close it.
- `list_boards`, `remove_board`, `dismiss_suggested_board`: manage the watchlist.

## Rules

- **Never apply for the user.** Fill in what you can, then stop for them to review and submit. Use `applied`
  only after they say they submitted.
- **Check for duplicates first.** Before a referral request or an application, check `get_job`'s
  `duplicate_of` and the warnings in `list_queued_jobs`: a strong match means it was already applied to.
- **Only confirmed facts.** Don't put anything on a resume, form or saved story that the user hasn't confirmed.
- **Keep it private.** The tracker holds pay, notes and recruiter names: don't paste them anywhere public.
