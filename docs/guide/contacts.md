# Who you know there

[← jobwatch guide](README.md)

**Tutorial: Comps and who you know** (2 minutes): pay, career value and company health side by side, the
weights, and the people you know at each company.

https://github.com/user-attachments/assets/42eb0edb-945e-4caf-95c0-3eeae6fdada6

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

Your colleagues where you work now are people you know, but not referrals for an internal move. Name your
employer and no one there is listed:

```yaml
employer: Initech        # or a list of its names
```

Or say so as you go, in the **Referrals** tab.

## The Referrals tab

Referrals answers one question: *who could refer me to a job I'm tracking?* It lists the people from your
LinkedIn connections who work at a company with a job you're tracking, so you can ask one of them before you apply.

**Getting started.** The tab needs two things. First your LinkedIn data (the steps are at the top of this page):
until you've uploaded it, the tab explains this in plain words and links to the upload under Settings → People &
pay. Second, tracked jobs: companies you watch (Settings → Your search) and jobs you added or queued. If you
have connections but nobody works at a company you track yet, the tab says so and points to where to add
companies. A person who isn't on LinkedIn can be added by hand (see below), with or without any LinkedIn data.
Nothing here assumes a particular setup: with no Fit
minimum set, a tracked company's jobs count as good fits from a fit score of 60, and a note under the search bar says so,
with a link to where you set your own.

**One card per company**, in a grid that fills the page (the Standard / Wide / Full width setting). A card is as tall
as its content needs, and the cards in a row are as tall as the tallest of them, so rows line up and a row of small
companies stays compact; no room is kept for what a company doesn't have. A card has:

- the company's logo and name (they open its page in the Company tab, as a company name on Today does), a
  "12 people you know" pill. The company's job board or careers page is not here: it is the **Careers ↗** chip in the
  Company tab's header (a new tab). Its link is the board jobwatch watches, else the company's own site its jobs link
  to (never LinkedIn's or another job site's), else the careers site your watchlist gives its board, or the website
  its logo was found at, else a web search for its careers page ("Search careers ↗"); only the company's name goes in
  that search;
- its jobs as what suits you, never a wall: "23 good fits" (a job you queued or applied to, or a fit score at or above
  your Fit minimum, `filters.min_fit`, else the fit chip Today opens on, else 60; never a job with no score yet, nor
  one whose title your title filters turn down), the best three of them ("+ 20 more"), and small grey text for the jobs not
  scored yet and the total open. A company with no good fit says so in that one line and sorts below those that have
  one;
- a slim row for each of the first three people you know there, the closest first (the ones you chose **Ask first**
  for, then who messaged or endorsed you, the latest first, then A-Z), with their title, how close you are, one **pill**
  for your choice and a note button;
- **The pill** is the whole choice, in three states. **Ask?** (grey outline) means nothing chosen: the people you have
  messaged most come first. **★ Ask first** (purple) means "ask this person for a referral first": they lead the "You
  know" lines everywhere and the referral drafts. **Skip** (muted, struck through) means never suggest them: they are
  hidden from "You know" lines and drafts and move to **Not suggested**, where you can bring them back. A one-line
  legend under the page's subtitle says so (dismiss it with **Got it**; it stays dismissed). A click on a pill opens
  the person's dialog on the editor; with the pill focused, **U** sets Ask first, **S** Skip and **N** no preference
  without opening anything. Setting Skip shows "Won't suggest Jane Doe. Undo" for 8 seconds, the same on a job card's
  "Don't use" on Today and the Company tab. People in `connections_skip` are listed under Not suggested too,
  read-only;
- two buttons: "See the 23 good fits" and "+ 8 more people".

**Click for the details.** Everything but the company's name and logo (which go to its Company tab) opens a large dialog (most of the window;
Esc or a click outside closes it; the arrow keys step to the next company or person, "3 of 12"). The "12 people you
know" pill opens the company's Overview: counts, what you're working there, its best fits, the people, and the company
health you kept in Comps. The buttons open its Good fits, Applied and queued, Not scored, All and People tabs, each
with a search. A job opens its details above the dialog, and Esc closes the details first, then the dialog. A person's
name, avatar, pill or note button opens their dialog. At the top is your choice as a large control of three: **Ask
first**, **No preference** and **Don't use**, each with a line saying what it does; a choice saves at once ("Saved")
and the pill behind updates, the arrow keys change it (they step between people only outside the control) and
**Clear** returns to No preference. Below it: a note to save ("doesn't check LinkedIn; reach on WhatsApp", shown on the
card in one line and beside the person on job cards), title, how close you are, their LinkedIn profile, the jobs there
and a draft referral request (see "Who to contact" below).

**Finding people.** The search box above the cards (press `/`) finds a person by name, company or title, in any
word order, ignoring accents; the company's card stays with just the people who matched, and Esc clears it. The sort is
Best fit first, Most good fits, Most people you know, Last messaged or A-Z; **Ask first** shows only the people you
set to Ask first and **Working a job** only companies where you queued or applied. A **Not suggested (3)** chip
appears when someone is set to Skip: it opens that section at the foot of the page and goes to it. A search finds
skipped people too: the section opens by itself with them, each with the Skip pill. **Hide companies with no good
fits** (the eye-off chip, remembered in your browser, off at first) hides the companies whose card reads "No good fit
yet" (the Fit minimum decides); one you have an application in flight at (queued, applied, screening, interviewing) or
a person you set to Ask first or added by hand at is never hidden. Nothing disappears silently: the count reads "3 of 6 companies · 7
people (3 hidden: no good fits)", a search that matches a hidden company says "1 match hidden by 'no good fits'" with a
**Show it** button, and when more than a quarter of your companies have no good fits the tab offers to hide them. A long list is not rendered at
once: 24 cards at a time with a "Show 24 more companies" button (hundreds of companies stay quick, and a search always
runs over all of them), and a dialog lists 100 rows at a time.

The same from the terminal, and for an assistant:

```
jobwatch referrals                                  # the same rows
jobwatch referrals --use "Ana Li" --note "answers fast"
jobwatch referrals --skip "Bo Chen" --note "doesn't check LinkedIn"
jobwatch referrals --clear "Bo Chen"                # NAME is a full name or a linkedin.com/in/ link
```

The MCP tool is `rate_contact` (who, verdict `use`, `skip` or `clear`, note). What you say is kept in the
state file next to your jobs, keyed by profile link (or name when there is none).

## People who aren't on LinkedIn

A friend, an ex-colleague or someone you met in person may not be one of your LinkedIn connections, or not on LinkedIn
at all. Add them by hand and jobwatch treats them like any connection: the Referrals tab, the "You know" lines on Today
and the queue, the Company tab's people, **Who to contact** and the drafts all list them, with the same **Ask? / Ask
first / Skip** choice and note.

- **In the page.** The **Add a person** button in the Referrals toolbar, or the **+** on a company's card (the Company
  tab has one too, with the company filled in), opens a large dialog (Esc closes it). Name and company are required;
  title, a few words on how you know them (up to 200 characters), a LinkedIn link, an email and a phone are optional.
  **How you reach them** is a quick pick: WhatsApp, Text, Email, Phone or In person. It shows beside their name, as
  "reach on WhatsApp". The company box suggests the companies you track and takes any text. If someone is already
  listed with that name at that company, the dialog says "Already in your connections" and does not save. Once saved,
  the person is on the company's card with the muted **Ask?** pill and an **added by hand** tag, and a toast says
  "Added Jane Doe at Globex" with **Undo** for 8 seconds. If no job you track is at that company yet, the toast says so:
  they show on its card as soon as one is.
- **Change or delete.** A person added by hand has an **Added by hand** section in their dialog with **Edit** (the same
  dialog) and **Delete** ("Removed Jane Doe", with **Undo** for 8 seconds, which puts back everything, even your choice).
  A person from your LinkedIn data cannot be deleted, only set to Skip.
- **From the terminal.**

```
jobwatch referrals --add "Jane Doe" --company "Globex" --title "Staff Engineer" --note "met at a meetup" --reach whatsapp
jobwatch referrals --add "Jane Doe" --company "Globex Corporation" --url linkedin.com/in/jane-doe --email jane@example.com --phone 555-0100
jobwatch referrals --remove "Jane Doe"       # only people added by hand; a connection can only be skipped
```

  Only the name and `--company` are needed. The list marks them `[added by hand]`. The MCP tools are `add_contact` and
  `remove_contact`.

Added people are kept in jobwatch's own state file (next to your jobs), not in the LinkedIn file or the watchlist, so
uploading a new LinkedIn export or replacing Connections.csv never drops them. They match a company the way
connections do: "Globex", "Globex Corporation" and "globex" are one company. Your choice for them (Ask first or Skip)
is kept with them, and a person you change to another name or LinkedIn link keeps it.

**How close they rank.** Someone you added on purpose is a close tie: they rank like someone you exchanged five messages
with, above a connection who only accepted a request or endorsed you, and below your real correspondents (people you
have messaged often) and anyone you chose **Ask first** for, who always lead. If your LinkedIn archive also has messages
with them, whichever is closer counts. "Added by hand" is the reason shown, in place of "messaged 5×".

## Who to contact, and what to say

A referral isn't the only way in: for one job, `jobwatch contact KEY` lists who to write to and drafts the note.
The **Who to contact** button on a job's card does the same, with the note beside a Copy button. People come only
from places that need no scraping and no login, and none is made up:

- **The posting.** Many postings name the hiring manager, the recruiter, the interviewers or the team lead
  ("Hiring Manager: Jane Okafor, Director of Security", "You will report to ..."). A fixed set of patterns reads
  them, not a model: a name needs a cue word before it, and a title, a team or a technology is never a name.
- **Your notes.** A recruiter's name you wrote in the notes or next step of any of your applications at the company.
- **People you know there.** Your LinkedIn connections at the company, as above: ones you marked **Use**, then the
  closest ties.
- **Anyone else.** LinkedIn people searches that jobwatch builds and **you** open: the company's heads of this kind
  of work, its recruiters, the people doing it, and who could introduce you. jobwatch never reads linkedin.com.

The note is a draft for one person: a LinkedIn connection note of 300 characters or less and a short email, in the
first person, ending with a short ask that fits them: a chat for a hiring manager, whether the role is open for a
recruiter, and for someone you know there, whether they would refer you for **this role** (with room to say no). It
leads with whether you already applied (or a copy of the job): check that first. It never mentions pay or adds a
pronoun line, and only uses what your resume and the posting hold. Nothing is sent or saved.

```
jobwatch contact KEY                       # the people and searches, and a note to the first person listed
jobwatch contact KEY --pick 2              # the note to the second person in the list
jobwatch contact KEY --to "Rae Quinn" --role recruiter   # someone you found with a search
jobwatch contact KEY --no-draft            # only the people and the searches
```

Like follow-up emails, the note is written by Claude from an allowlist only (the company, the job title, the stage
and day applied, the person's first name and what they are to the job: no resume, posting or notes), or, with
`reply: {followup: local}` or when Claude can't answer, by the local model, which also reads your resume's confirmed
lines and the start of the posting. With no model at all a fixed template stands in. Warnings under the draft list
what to check: a figure your resume and the posting don't hold, a stock opener, an exclamation mark, a word about
pay, a missing greeting. The MCP tool is `find_contact`.

A digest lists each job once, the top `display.today` (10) of them, and ends with how many more match;
those stay new for the next digest. Use `digest --all` for every match, including jobs already shown,
`--limit N` for another number, or `--peek` to look without marking them shown. Roles that disappear from a
board are marked closed. The MCP `get_digest` returns the same top 10 by default, with today's pace.
