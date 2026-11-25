# Tracking applications

[← jobwatch guide](README.md)

**Tutorial: tracking applications** (2 minutes): stages and follow-ups, applications that go quiet, the
calendar feed, Interviews, looking up a company, what you sent.

https://github.com/user-attachments/assets/e2e43a54-83d2-4154-9229-a063fafefe44

An application moves through stages: `applied`, `screening`, `interviewing`, `offer`, and then `rejected`,
`withdrawn` or `closed` ("Closed by company": they took the posting down; `jobwatch mark closed c1`). Each can have a next step and a day to follow up. Jobs you found somewhere jobwatch doesn't
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

`--add-note` is how to record news. `--note` replaces the whole note, history included, so it says how much it
replaced; the replaced note is kept, and `jobwatch notes KEY --undo` brings it back (`jobwatch notes KEY` lists the
notes replaced). A note lost before that, or longer ago, can be read from a backup without touching the database, and
written back in front of the note there now so nothing newer is lost:

```
jobwatch notes c1 c2 --from-backup 2026-11-24                    # the archived notes next to the ones now
jobwatch notes c1 c2 --from-backup 2026-11-24 --restore --dry-run   # what would be written
jobwatch notes c1 c2 --from-backup 2026-11-24 --restore
```

The day you applied is kept as an application moves through the stages. `--next ""` or `--follow-up ""`
clears a field.

To give every job at one company a status in one go (you've decided against the company, or want all its new roles
queued), use `--company`:

```
jobwatch mark skipped --company Initech --dry-run          # what would change, and nothing does
jobwatch mark skipped --company Initech                    # every job at Initech: the keys changed are printed
jobwatch mark skipped --company Initech --only-status new  # only the roles you haven't acted on
jobwatch mark queued --company Globex --only-status new --add-note "worth a look"
```

The company is its exact name, or a name that matches no other company (a short one that matches several is an
error). A job you applied to (`applied` or any later stage) is left alone and listed, unless you give
`--include-active`: a status like `skipped` would drop its applied day. A job already in the status isn't touched.
`--note`, `--add-note`, `--next`, `--follow-up` and `--on` apply to each job changed. The MCP tool is
`mark_company_jobs` (it sets `new`, `shown`, `queued` or `skipped`; an application's stage is marked one job at a
time with `mark_job`).

Say which interview the next step is with `--round`: `recruiter_screen`, `hiring_manager`, `technical`,
`system_design`, `panel` (onsite or loop), `executive` (VP, director, CXO), `hr`, `informal` (coffee,
in-person talk, referral chat) or `offer_call` (`--round ""` clears it; the `mark_job` tool and the edit
form on the Applications tab set it too). With a round the next step is a meeting whatever its words, and the
Interviews tab and the calendar feed label it with the round ("Tech interview", "VP / exec round", ...); the
time still comes from the next step's text (`--next "Fri 10/30 3:30 PM ET" --round informal`). Without a
round, jobwatch reads the words as before. An application added by hand with only a company and a title can get its posting's text
later with `--text` (a copy from a job board, or `-` to paste it), so it can be scored and `jobwatch prep`
has something to work from; the posting kept with the application is replaced with it.

## Applications that go quiet

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
[Who you know there](contacts.md#who-you-know-there)), or, when the posting has closed (`jobwatch check` records that) or
it has been quiet for `long` days, "likely closed: mark it rejected or withdrawn". jobwatch only suggests: it
never changes a status. A snooze isn't news, so a snoozed application stays quiet until you hear something. On
the Applications page they sit under **Gone quiet** with one-click Snooze 7 days, Mark withdrawn, Mark rejected
and Add note; the MCP `list_applications` gives each a `quiet` field.

## Follow-up and thank-you drafts

When the follow-up day comes, or after an interview, jobwatch drafts the email from a few things it already keeps for
the job: the company, the job title, its stage and round, the day you applied, the note's dated lines, and the first
name of the person to greet. That name comes from the next step or the note, after "call with", "interviewer:",
"met", "recruiter", "hiring manager", "HM", or a verb like "nudge", "ask", "ping", "email", "message", "contact" or
"reach out to" ("optionally nudge Dana Whitfield once" greets Dana), or from `--interviewer`, which wins:

```
jobwatch followup c1                                  # a follow-up on the application
jobwatch followup c1 --thanks --interviewer "Dana Lee"   # a thank-you after the call; --interviewer can repeat
```

It prints the draft and sends and saves nothing: you read it and send it yourself. Claude (`claude-haiku-5-5`) writes
it from that allowlist only, with the API key from your environment or macOS keychain as the chat uses it. A note
line about pay or compensation, your employer or leaving it, immigration, health, or one holding an email address,
phone number, link or ID number is left out whole, and so are the next step, the resume, the form answers, the cover
letter and your stories: none of it leaves this computer. With no key, or when the call fails, the local model writes
the draft from the very same lines, and the card and the command say which one wrote it ("Written by Claude" or
"Written by local model"). A line naming your current employer (`employer:` in the watchlist) or a word of
`reply: {deny: [...]}` stays home too. To keep drafts on this computer always, set `reply: {followup: local}`.
Under the draft, warnings list what to check: a figure the tracker doesn't hold, a stock opener ("hope this finds you
well"), an exclamation mark, a word about pay, a greeting without the named person, or a thank-you for an
application with no interview on record. A job that isn't applied to yet, or has ended, has no one to write to.

On the Applications page each open application has a **Draft follow-up** button (a thank-you for one in a
screening or interviewing stage) with the subject, an editable body, a Copy button and the same warnings. The MCP
`draft_followup` tool gives the same draft to your agent.

## Closed postings

A posting you cared about that gets taken down used to show only a gray "posting closed" chip. Now jobwatch keeps a
**notice** for each application (in any open stage) or queued job whose posting closed in the last two weeks, and
tells you in three places. Jobs on Today that you never acted on get none.

- **The card** says when: "posting closed Nov 17", and an amber **closed Nov 17** badge until you clear it (click it).
- **The Closed postings strip** at the top of Applications lists the notices you haven't cleared, applications
  first, each linking to its card, with a status chip, a small **live** marker on a screening or interviewing
  application (a closed posting there isn't a loss) and **Got it** / **Got it, all**. Clearing a notice only hides it:
  nothing is removed or changed in your applications. Beside **Got it**, an application that is only applied has
  **Closed by company** (and, in the header, **Closed by company, all applied**): it sets the status to *Closed by
  company*, an ended status like rejected and withdrawn that leaves the live lists and shows in the status chips, with
  the dated note "Posting closed Nov 17: closed by company". A queued job has **Skip** (status skipped, note "Posting
  closed Nov 17: skipped"). Each asks "Mark this application Closed by company? You can change the status back."
  inline first, then offers **Undo** for 8 seconds (status, note and notice all come back). Screening, interviewing
  and offer rows get no such button: a closed posting there usually only means they stopped advertising it.
- **A popup** on your Mac, once a day, through `jobwatch notify-closed`: "jobwatch: 2 postings closed" and up to three
  `Company: Title` lines, applications first, then "+N more". It first runs the daily posting check (a posting checked
  in the last 12 hours isn't checked again), looks at each posting once more, then tells each notice once.

A posting counts as closed only on positive evidence: a 404 or 410 at its link, a short page that says so ("this
position has been filled", "job not found", "no longer available"), an end date in its markup that has passed, or its
absence from a board's own listing that loaded and had jobs. A maintenance or "try again later" page, a challenge
page, a 403, 429 or 5xx, a redirect to the site's home page, or a board that lists no jobs at all says nothing: the
check calls the posting *unknown* and marks and notices nothing. Even a closed posting becomes a notice only after a
second look at least six hours after the first, and the popup looks a third time just before it speaks, so a one-off
blip never notifies. Until that second look a posting found closed once shows an amber **checking** badge (not the
red **closed 21 Nov**), keeps its Apply and Queue buttons, and has no "The posting is closed." verdict; once confirmed
a closed queued job also offers **Skip** (an inline question, then Undo for 8 seconds) beside Remove from queue. The
Queue, Today, company pages, Details, `jobwatch list` and the MCP tools all read the same state. A board that lists
only the roles matching your watchlist (Workday, a careers site's sitemap) never closes a job you follow by leaving
it out of a listing: only that job's own page can. `jobwatch notify-closed --recheck` looks again at every job marked closed now and reopens the
ones that are open or can't be told.

```
jobwatch notify-closed --dry-run      # print what the popup would say; check nothing, tell no one
jobwatch notify-closed --test         # pop up a sample
jobwatch notify-closed --install      # run it daily at 9:00 through launchd (io.github.jobwatch.notify-closed)
jobwatch notify-closed --uninstall    # stop the daily job
jobwatch notify-closed --recheck      # look again at every job marked closed; reopen the unproven
jobwatch notify-closed --clear        # clear every notice, as "Got it, all" does (--dismiss works too)
```

The popup uses `osascript` (nothing to install); the first time, macOS may ask to allow notifications from Script
Editor. The daily job's log is `~/Library/Logs/jobwatch-notify-closed.log`.

Every company on Workday has its own careers site with its own sign-in, so after a few applications it's hard
to remember where each one lives. For a Workday application, `jobwatch show`, `jobwatch applications` and
the job's **Details** link that company's candidate page (`.../userHome`), where you sign in to see its
status. jobwatch keeps only the link, never a login or password: your password manager saves each company's
login under that company's own address. For one you added by hand whose posting has since come down, give
it the company's careers site (`jobwatch mark <key> --url https://acme.wd1.myworkdayjobs.com/Careers`)
and the page link follows.

## On your calendar

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
Rejected, withdrawn and closed-by-company applications are left out. Each event keeps the same id, so importing the file again, or
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

## Follow-ups in Apple Reminders

On a Mac, jobwatch can keep each follow-up day in the Reminders app. It is off until you ask, in the watchlist:

```yaml
follow_ups: reminders    # off (the default), reminders or reminders-all; macOS only
```

An application then gets one reminder, "Follow up: Initech — Platform Engineer", due its follow-up day at 9:00 with an
alert, but only when there is something to do: its stage is live (screening, interviewing, offer; snoozed or not), or
it is applied and its next step (`jobwatch mark --next`, the Applications page, the MCP `mark_job`) is an action, not a
wait. A next step counts as waiting when it starts with wait, waiting, await, awaiting, passive, "no action" or
none, or says "hear back", "no action" or "passive" anywhere; "Wait for the recruiter" gets no reminder, "Follow up if no
reply" does. A snoozed applied one, or one with no next step, gets none. `follow_ups: reminders-all` makes one for every open application with a day, snoozed
ones too. The notes hold the next step, the posting's link and a line `jobwatch:<key>`, which is how jobwatch finds it
again. When the day changes (the `--follow-up` of `jobwatch mark`, `jobwatch snooze`, the Applications page, the MCP
`mark_job`) the reminder moves; when the day is cleared, the application is closed, snoozed or loses its next step, the
reminder is deleted. A reminder you complete yourself stays completed for that day. jobwatch never touches a reminder
without its `jobwatch:<key>` line.

```
jobwatch reminders sync    # make Reminders match every follow-up now (also done when `jobwatch ui` starts); safe to repeat
```

With this on, each application on the Applications page has a bell: it asks for a title (starting with the company),
a day and time and an optional note, and adds a one-off reminder with the posting's link. A sync leaves those alone.

The first time, macOS asks whether to let your terminal (or the app running jobwatch) control Reminders. If you
said no, turn it on under System Settings > Privacy & Security > Automation. A failure never stops what you were
doing: jobwatch prints one line saying so, once.

## Interviews

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

Each interview shows one sheet, the main one, as a "Start here" chip titled with the sheet's own `<title>` (so
name it for the interviewer or the round: "Acme: hiring manager call with Sam"). It is the sheet the application's
note or next step names by file name (`Prep sheet: prep/acme-hm-sam.html`; the last labelled one wins, else the first
named), else the company's newest sheet that doesn't name another posting's number. Companion pages are never the
chip: a page says what it is in `<meta name="jobwatch-prep-role" content="...">`, with `module` (one drill clip's
page), `playlist` and `rehearse` (the practice page `jobwatch rehearse` writes) kept off it, and a plain sheet
carrying no marker. Link the playlist and the practice page from the sheet itself. A sheet opens in a new tab from that folder, so the stylesheet, images and
[drill video](interview-prep.md#drill-video) beside it show as they do from disk (a video can be skipped through). The page
serves the folder at an address with a secret in it, like the calendar feed, only to this computer, and
sandboxed: a sheet can't run scripts.

## Looking up a company

Today only shows new roles on the boards you watch, so a company you added by hand, or one you're already
talking to, isn't there. In the browser, press `/` (or click the search box at the top) on any tab and type a
name: the matching companies come up, and one opens its page. A tab whose own search finds nothing says when
a tracked job at a matching company is elsewhere, with a link to it. On the command line:

```
jobwatch company acme                # a name, part of one, or a domain: acme.com; --format json
jobwatch company acme --all          # also the open roles your filters leave out
jobwatch company acme --status new --status queued   # only jobs in these statuses: every one, none cut
jobwatch company acme --status new --keys            # just their keys, one a line, for scripts
```

It finds the company under any status (new, queued, applied, interviewing, rejected, skipped...), open or
closed postings, and shows each job with its dates, next step, follow-up and note, whether a package was
saved, a duplicate warning, people you know there, and, when its board isn't on your watchlist, what to run
to add it. Open roles you haven't acted on are listed only when your filters pass them (title, text, place,
pay and fit, but not age: an older role still open is worth seeing), and the rest are counted by filter;
"Show them" on the page, or `--all`, lists them too, and Settings → Display → Company page (`display.company:
all`) lists every role each time. Jobs you queued, applied to or skipped are always listed. A long note shows as its latest dated entry, cut to about 200 characters (the page folds it until
clicked); `--format json` and `jobwatch show KEY` have all of it. `--status` (repeat it for more) lists only the jobs
in those statuses, every one of them, closed postings and the roles your filters leave out too; with `--keys` it
prints just their keys, one a line (a company that matches nothing is an error, a status with no jobs prints nothing),
the way to feed `jobwatch mark` or a script. The MCP tool is `get_company` (its `status` is the same).

To find a job by something you wrote or were told rather than by company, search the notes:

```
jobwatch search anthony              # which application did recruiter Anthony call about?
jobwatch search "$101/hr"            # --format json
```

It looks in every job's note, next step, where it was found (the recruiter or alert), title and company, at any
status, closed postings too, and shows each the way `jobwatch company` does.

## What you sent

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
