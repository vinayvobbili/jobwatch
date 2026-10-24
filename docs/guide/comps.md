# Comparing opportunities

[← jobwatch guide](README.md)

The **Comps** tab (and `jobwatch comps`) puts your live opportunities, the applications at screening,
interviewing or offer, side by side as columns: stage, applied day, next step, pay as posted, place, fit score
with must-haves and top gaps, and the people you know there. Pick anything else to compare, any tracked job or
any company by name (even one you haven't applied to), with the box on the tab or `jobwatch comps KEY
--company NAME`; the choice is remembered in your browser. The highest value in a row (pay, base, offered, fit)
is starred.

What a recruiter tells you about pay is kept per job, and what you know of a company per company. jobwatch looks
none of it up: you type it in, or an assistant over MCP searches the web and records it with its source links.

```
jobwatch comp acme --base 165-195K --bonus "10% target" --equity "40K RSUs over 4 years" --signon 15K \
    --asked 210-230K --offered 180K --note "195K most likely their max" \
    --role product --career-note "observability product, staff IC"
jobwatch health "Acme" --kind tech --listing private --stage "Series B, $50M, 2025" --raised "$80M" --revenue "2x YoY" \
    --headcount growing --layoffs none --rating "4.1 Glassdoor" --risk "one big customer" \
    --sources "https://example.com/acme" --as-of 2026-10-20
```

A field you leave out stays; `''` clears it; `--clear` forgets all of a job's or company's. Health older than
90 days (or with no date) is marked stale. Over MCP the tools are `set_comp`, `set_company_health` and
`get_comps`.

The suggestion at the top ranks the opportunities by plain rules, no model. Its default weights are career value
(25%), pay against your `pay.target` (30%; at target is 80, 10% over 100, 10% under 50), fit score (20%), how far
along it is (10%: offer 100, interviewing 70, screening 40, applied 15) and company health (15%: 70 to start, public +10, layoffs -25, shrinking headcount
-10, rating of 4.0+ +10 or under 3.3 -10, a private company with under $20M raised -15, a risk note -10; growing
headcount +10). Pay uses what they offered, else the base they gave, else the posted range: the middle of the
range, since a nationwide band's top isn't what anyone is paid. Career value
starts from the company's `--kind` (`tech` 80, `consulting` 55, `enterprise` 40: a non-tech business whose IT
builds for itself, like a bank or insurer) and adds the job's `--role` (`product` +15 for building the company's
own product, `customer` +5 for forward-deployed or customer-facing engineering, `internal` -5 for internal tools),
kept between 0 and 100; `--career-note` is a few words of your own, shown but not scored. A part with nothing
to go on counts as 50. Those numbers are one person's goals; say yours with `goals:` (below) and the career part
follows them. Change the weights in the
watchlist; any numbers 0 or more, scaled to add up to 1 (a part you leave out keeps its default, so give all five
to be exact):

```yaml
comps:
  weights: {career: 40, pay: 30, fit: 15, progress: 5, health: 10}
```

Each opportunity shows its score, every part with the input it came from, and a sentence
on why.

**Your goals.** Say what you want next, and the career part scores against it instead of the fixed numbers
above (Settings → Your goals, or the watchlist):

```yaml
goals:
  about: "Staff engineer, ten years in security tooling, ready to build product again."
  company_kinds: [tech, consulting, enterprise]   # best first; or: any
  roles: [product, customer, internal]            # what the job builds, best first; or: any
  stages: [growth, startup, public]               # seed to Series B, Series C+, listed; or: any
  track: ic                                       # ic, manager or either
  horizon: "take risks for the next 3-5 years"
```

`company_kinds` and `roles` are in order of preference: a kind scores 90, 65 or 40 (first choice best) and a role
adds +10, 0 or -10; one you leave off the list ranks last, and `any` is neutral (65 and 0). Name only one of the
two and the other keeps its fixed rule. Without either, nothing changes from the numbers above. `stages` adds +10,
0 or -10 the same way, for a company whose Company health says how far along it is: public when it's listed, a
startup through Series B, growth stage from Series C on. A company with no stage kept gets nothing either way, and
without `stages` its stage counts for nothing. The suggestion's
input says which choice of yours a job is ("tech company (your 1st choice)"). `about`, `track` and `horizon` are in
your own words and change no score; `about` and the rest are read only if you ask for title suggestions when
setting up. Settings → Your goals also has `pay.target`, a private `pay.floor` (never shown elsewhere) and the
five weights as sliders.

**Worth it.** Today and the apply queue can also be ordered by the same score, with the **Worth it** button (kept
per browser). Each card then shows `worth N`, and hovering it lists the parts. A job isn't applied to yet, so the
progress part is left out and the other weights are scaled up to add to 1; pay is the middle of the posted range
(or what a recruiter told you, if kept), career and health come from the company's kept `kind` and health, and
anything unknown counts as 50. Only the order changes: fit scores and `filters.min_fit` work as before.
