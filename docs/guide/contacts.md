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

A digest lists each job once, the top `display.today` (10) of them, and ends with how many more match;
those stay new for the next digest. Use `digest --all` for every match, including jobs already shown,
`--limit N` for another number, or `--peek` to look without marking them shown. Roles that disappear from a
board are marked closed. The MCP `get_digest` returns the same top 10 by default, with today's pace.
