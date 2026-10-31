# The apply queue

[← jobwatch guide](README.md)

**Tutorial: applying** (2 minutes): the queue, jobs found elsewhere, job-alert emails, status emails, companies
to watch.

https://github.com/user-attachments/assets/9d021676-85da-4ce1-8d42-f3808b4ae03b

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

## The same opening twice

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

## Who is interviewing you

Open someone's LinkedIn experience page (`linkedin.com/in/<name>/details/experience/`) in your own browser, copy
the page text into a file, and list their roles. jobwatch only parses the text you give it; it never fetches
linkedin.com, whose robots.txt disallows it.

```
jobwatch profile page.txt                  # --format json, or html for a <ul> to paste into a prep sheet
pbpaste | jobwatch profile -
```

## Jobs you found somewhere else

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

## Filling application forms

The jobwatch extension for Chrome fills an application form for you to review. It works alongside the autofill
you already use: let Simplify, Chrome's autofill or your password manager fill your name and contact details,
then the extension fills the rest from what `jobwatch ui` knows:

- **Answers you gave before.** A question asked on an earlier form ("Notice period?", "Why are you leaving?")
  gets the answer you sent then, with the question it came from beside it.
- **Drafted answers.** A new question can be drafted by your chat model from your resume, your stories and the
  posting. Drafts start unticked: read and edit them first.
- **The resume.** The one kept with that job's application, else the one in Settings.
- **The application recorded.** When you submit, the job is marked applied and the answers you sent are kept
  with it, ready for interview prep.

It fills only fields that are still empty, never submits for you, and talks only to jobwatch on your computer.

To set it up, copy the token from **Settings > Applying > Browser extension** into the extension's options.
**Your details** on the same tab (name, contact, links, work authorization; the voluntary self-identification
questions are "decline" unless you say otherwise) fill any of those fields your other autofill left empty. The
same details live in the watchlist:

```yaml
applicant:
  first_name: Jordan
  last_name: Rivera
  email: jordan@example.com
  work_authorized: yes
  needs_sponsorship: no
  # salary: left out, your pay target is used
```

A salary question is offered with that number but never ticked for you: tick it when you want the form to say it.

## Job-alert emails

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

## Status updates from application emails

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

## Companies to watch

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
