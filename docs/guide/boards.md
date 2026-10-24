# Why company boards

[← jobwatch guide](README.md)

Most tech companies post jobs through Greenhouse, Lever, Ashby or Workable, and most large employers through
Workday (some through Eightfold, Oracle Recruiting Cloud, SmartRecruiters or a Jibe careers site), and many
small companies through Rippling. Each publishes open roles as public JSON so anyone can build a careers page, with
no API key or scraping; Google publishes its own (with YouTube's and DeepMind's) as an XML feed for job sites,
Amazon's careers site (amazon.jobs, with AWS) answers its own search in JSON, and Avature careers portals
(company career sites on Avature) list every posting in a sitemap for search engines, iCIMS careers sites
(careers-<company>.icims.com) list theirs in plain pages, and Jobvite careers sites (jobs.jobvite.com/<company>)
list every open role on one page. Hundreds of startups post once a month
in Hacker News' "Ask HN: Who is hiring?" thread, which HN's search API serves whole.
jobwatch reads those feeds for the companies on your watchlist:

- **Complete and fresh:** a role appears as soon as the company posts it, not when an aggregator picks it up.
- **Pay ranges:** read from the board's structured fields where they exist (Lever, Ashby), otherwise from
  the posting text. An hourly wage counts as the yearly pay it comes to (2,080 hours), so `$75–$80/hr` is
  held to `min_salary` as $156K–$166K.
- **Polite:** one request per company per run on Greenhouse, Lever, Ashby and Workable (a Jibe site: one per 100
  roles). A Workday, Eightfold or Oracle board can
  list thousands of roles, most of them nothing like yours, so jobwatch searches it for your
  `filters.titles` words and reads a posting in full only when its title passes your title filters, once:
  after that, a run costs a few searches per company. Titles written as regexes can't be searched for, so
  keep a plain word or two ("engineer", "data platform") among them. A board that answers "too many
  requests" (HTTP 429) is asked again after a pause; a posting it still won't serve is kept without its text
  and read on the next run. Eightfold boards are read one request at a time; a posting's own "work site" line (days in the office, or
  how much is from home) decides whether it is remote, and up to 100 stored postings per board are re-read each
  run until they have it. Google's feed is every role it
  has, one request (about 20 MB) a run; jobwatch keeps the ones whose titles have your `filters.titles` words,
  in the US unless the board is `google/any`. Amazon is searched like a Workday board, newest roles first and
  100 a request, one request at a time; each result has the role's full text, so nothing more is read. It keeps
  US roles unless the board is `amazon/any`. A SmartRecruiters board is searched the same way, 24 titles a
  page, and each posting it reads is one page. An Avature portal's sitemap is one request a run; a posting
  whose title has your `filters.titles` words and passes your title filters is read from its page, once, two at
  a time. An iCIMS site's list is a page of 50 roles a request, and its postings are read the same way. A Jobvite site's whole list is one request. HN's Who is hiring is one request to find the thread and one to read it whole.
  `jobwatch fetch --reread <board>` reads a searched board's stored postings again, as after an update that
  reads its pages better.
- **Within the rules:** it reads public APIs meant for this, and follows robots.txt. SmartRecruiters' own API
  host asks crawlers to stay away, so jobwatch doesn't use it: it reads the company's public careers site
  (careers.smartrecruiters.com, and each posting's page on jobs.smartrecruiters.com), which robots.txt leaves
  open. On an Avature portal it reads only the public pages its robots.txt lets robots read (never a link with
  `qtvc=`, never anything behind a sign-in); on iCIMS, the list and job pages, never its sign-in, referral or
  candidate pages; on Jobvite, the list and job pages, never the apply form. It doesn't scrape LinkedIn or Indeed, which forbid it.
