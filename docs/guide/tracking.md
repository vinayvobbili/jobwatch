# Tracking applications

[← jobwatch guide](README.md)

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

Every `.html` sheet whose name starts with the company's name shows as a button on its interviews and in its
details, newest first. A sheet opens in a new tab from that folder, so the stylesheet, images and
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
