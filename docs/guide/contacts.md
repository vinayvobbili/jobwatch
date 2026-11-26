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

Or say so as you go. The **Referrals** tab lists the people you know at companies with a new, queued or open
job, closest ties first, with the jobs they're at. **Use** puts someone ahead of closer ties; **Don't use**
stops suggesting them (they wait in a fold, to restore); a note keeps a few words with the name ("doesn't check
LinkedIn; reach on WhatsApp") and shows beside it on the job cards, where a small **Don't use** does the same.
People in `connections_skip` are listed there too, read-only. The same from the terminal, and for an assistant:

```
jobwatch referrals                                  # the same rows
jobwatch referrals --use "Ana Li" --note "answers fast"
jobwatch referrals --skip "Bo Chen" --note "doesn't check LinkedIn"
jobwatch referrals --clear "Bo Chen"                # NAME is a full name or a linkedin.com/in/ link
```

The MCP tool is `rate_contact` (who, verdict `use`, `skip` or `clear`, note). What you say is kept in the
state file next to your jobs, keyed by profile link (or name when there is none).

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
