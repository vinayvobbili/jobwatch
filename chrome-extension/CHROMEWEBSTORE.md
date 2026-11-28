# Chrome Web Store Listing: jobwatch: Application Filler

> Last Updated: 2026-11-28

Live: https://chromewebstore.google.com/detail/jobwatch-application-fill/abackmpdpfflgiaccgfkababjplgolfi
(item ID `abackmpdpfflgiaccgfkababjplgolfi`; the listing shows 0.12.0, updated 2026-11-18)

**In review: 0.13.0** (`dist/jobwatch-extension-0.13.0.zip`); 0.13.1 waits on it. **Prepared after both: 0.13.2**
(`dist/jobwatch-extension-0.13.2.zip`, built by `python chrome-extension/tools/package.py`): reading postings by itself, with
the new `alarms` and `idle` permissions. Its paste blocks (the full set, which includes 0.13.0's) are in "Paste blocks for
0.13.2" below, and the developer's manual-test checklist in "Manual test checklist for 0.13.2".

Everything the [Developer Dashboard](https://chrome.google.com/webstore/devconsole) asks for, in the order it asks.
This file is for the developer and is not packaged (`tools/package.py` leaves out `.md` files). Build the upload and
the images first:

```bash
python chrome-extension/tools/package.py        # dist/jobwatch-extension-<version>.zip
python chrome-extension/tools/store_assets.py   # dist/store/: screenshots, promo tiles, icon
```

## Store Listing

**Extension Name**

jobwatch: Application Filler

**Short Description**

Fills job application forms from your own details and earlier answers. You review every field and press Submit yourself.

(Comes from `manifest.json` "description"; it is under 132 characters.)

**Detailed Description**

Fill job applications from your own details and earlier answers, and review every field before it reaches the form. You press Submit yourself.

jobwatch for Chrome is the browser half of jobwatch, a free, open-source job search tracker that runs on your own computer. Open an application, click the jobwatch icon, and Chrome's side panel shows what it can fill, each field marked with where the value came from, before anything is written.

It needs the jobwatch app: install it (https://github.com/vinayvobbili/jobwatch) and run `jobwatch` on the same computer. Without it the extension does nothing.

How it works
• Click the jobwatch icon on an application page, then Fill this application.
• Each field is a row with a badge: Your details (name, email, phone, links, work authorization), Past answer (an answer you gave on an earlier application, with the question and company it came from), Draft (written by jobwatch for a question nothing matched, never filled until you tick it) or Resume (the file jobwatch keeps for that job).
• Edit any value, tick the rows you want, press Fill selected.
• Read the form and submit it yourself. The extension never clicks Submit, Next or any button that sends the form.
• When you press the form's own Submit, jobwatch keeps the answers as they stood (your edits included) in that job's application package, and the panel says so. That alone never marks the job applied: only a confirmation page does. Your answers are kept for the next form and for interview prep.
• On a LinkedIn job, press Open the company's posting and the extension presses LinkedIn's Apply button for you, so the company's own page opens. jobwatch reads the posting there. On a company page it can't read, press Save this posting to jobwatch.
• On a LinkedIn, Indeed or Ladders list of jobs, press Read the jobs on this list to send the list's job cards to your jobwatch. While you browse LinkedIn and Indeed, the job cards you see are also noted on your computer (not on Ladders), and nothing leaves it until you press Import. A checkbox in the side panel turns this off.
• When your jobwatch holds a LinkedIn or Indeed job with no posting text, its Read posting button opens that job in a tab behind the one you are on. The extension reads the job's description there, gives it to your jobwatch and closes the tab. It reads only a page your own jobwatch opened.
• On a LinkedIn conversation with a recruiter, press Draft reply to this conversation. The extension reads that one open conversation and gives it to your jobwatch, which writes a draft with the model on your computer. The panel shows the draft, warnings and what to check, and says where it was written. Put in the message box types it into LinkedIn's box. The extension never presses Send: you read it and send it yourself.
• On a job's page, press ATS check to see which of the posting's keywords the resume jobwatch keeps for that job doesn't show (checked by jobwatch on your computer, with no model, and nothing is changed). Press Cover letter to have jobwatch draft one with the model on your computer and keep it with the job. The panel shows the letter to edit and copy. Fill the cover letter box puts it in the form's own cover letter box only if that box is empty (Replace is a second, separate press) and never presses Submit.

Works with
• Greenhouse, Lever and Ashby application forms, including a Greenhouse form embedded in a company's own page.
• Other single-page application forms, on a best-effort basis.
• LinkedIn, Indeed and Ladders lists of jobs.
• Fields another tool (Chrome autofill, a password manager) already filled are left alone.

Privacy
• On application forms it reads only the tab where you click the icon, and only when you press Fill this application.
• Page content and your answers go only to the jobwatch on your own computer (127.0.0.1). The authors run no server and receive nothing.
• A draft is written by the model you chose in jobwatch's settings: one on your own computer, or a cloud API you set up with your own key.
• On LinkedIn, Indeed and Ladders it reads only the job cards of a list (job number, title, company, place, pay, how long ago it was posted, and on Ladders the job's page address), and on a LinkedIn job page only the address. It reads Ladders only on the tab where you click the icon. It presses LinkedIn's Apply button only when you ask, and never Easy Apply or Submit.
• Only when you press Draft reply, it reads the one LinkedIn conversation that is open (the messages already on screen, no scrolling, no other conversation) and gives it to your jobwatch. It never presses Send. If you set jobwatch to use a cloud model for replies, jobwatch (not the extension) sends the conversation to it, and the panel says so.
• When you press Fill this application, ATS check or Cover letter, the extension sends your jobwatch the page's address and the company and job title the page shows, so it can tell which job you mean. It reads nothing else for them; the page's fields are looked at for a cover letter box only to offer to fill it, and nothing from them is kept or sent.
• No analytics, tracking or advertising.

Support: https://github.com/vinayvobbili/jobwatch/issues

**Category**

Productivity › Workflow & Planning

**Single Purpose** (the dashboard wording is in "Paste blocks for 0.13.0" below)

Connect the user's browser to their own local jobwatch app for job applications: fill application forms with the user's details and earlier answers after they review each field, and send the jobs on a LinkedIn, Indeed or Ladders list they have open to that app.

**Primary Language**

English

## Graphics & Assets

| Asset | Dimensions | Status | Filename |
|-------|-----------|--------|----------|
| Store Icon | 128×128 PNG | ✅ Ready | `dist/store/icon128.png` |
| Screenshot 1 | 1280×800 | ✅ Ready | `dist/store/screenshot-1-review.png` |
| Screenshot 2 | 1280×800 | ✅ Ready | `dist/store/screenshot-2-filled.png` |
| Screenshot 3 | 1280×800 | ✅ Ready | `dist/store/screenshot-3-draft.png` |
| Screenshot 4 | 1280×800 | ✅ Ready | `dist/store/screenshot-4-pairing.png` |
| Screenshot 5 (0.10.0) | 1280×800 | ✅ Ready | `dist/store/screenshot-5-list-import.png` |
| Screenshot 6 (0.10.0) | 1280×800 | ✅ Ready | `dist/store/screenshot-6-imported.png` |
| Small Promo Tile | 440×280 | ✅ Ready | `dist/store/promo-small.png` |
| Marquee Promo Tile (optional, shown only if the store features the item) | 1400×560 | ✅ Ready | `dist/store/promo-marquee.png` |

YouTube promo: https://youtu.be/cILjM1IF4ZQ

Absolute paths: `/Users/vinayvobbili/PycharmProjects/jobwatch/dist/store/` (the files above). Regenerated
2026-11-17 from 0.12.0 (they show the redesigned panel and "paired 0.12.0"). The store takes at most five: upload
1, 2, 3, 5 and 6, and drop 4 (pairing). All data in the images is made up (the demo server's Jordan Rivera and Initech).

### Screenshot Notes

1. The review: each field with its source badge, before anything is written.
2. The same form after Fill selected.
3. A drafted answer, unticked until the user ticks it.
4. The pairing step on the options page (server address and token).
5. (0.10.0) A LinkedIn list of made-up jobs (Initech, Globex, Umbrella), with Read the jobs on this list, the pages
   setting, the passive-mode checkbox and "Read the 8 jobs seen while browsing".
6. (0.10.0) What the import did: jobs seen and coverage.

Regenerate with `python chrome-extension/tools/store_assets.py`. The demo list page is `demo/linkedin-jobs.html`.

Optional extra shots of the redesigned side panel (not in the 1280×800 set; the lead card is not shown in 1 to 6): the panel
leading with the page it is on. Capture them with `python chrome-extension/tools/panel_states.py --out DIR`, which makes
`panel-<form|thread|list|posting|idle>-<light|dark>-narrow.png`, the wide list panel, the not-paired state and the
settings page. Suggested store shots, composed with `store_assets.compose` beside the page: (a) the application-form
lead card with the Apply / Messages / Jobs tiles, (b) the LinkedIn conversation card with Draft reply, (c) the job-list
card with Pages to read, Note jobs while I browse and the seen-while-browsing badge, (d) the dark theme. Screenshots 1 to 6
were regenerated for 0.12.0. All data is made up (Jordan Rivera, Initech,
Dana Whitfield).

## Paste blocks for 0.13.2

One block per dashboard field (Privacy practices tab; the Package tab has no What's new field). Checked against `manifest.json`,
`passive.js`, `read-posting.js`, `page-bridge.js`, `auto-read.js`, `auto-reader.js`, `job-lists.js`, `reply.js`, `background.js`
and `sidepanel.js` on 2026-11-28. What is submitted is exactly `dist/jobwatch-extension-0.13.2.zip`
(`python chrome-extension/tools/package.py`). **Order of submissions:** 0.13.0 is in review; 0.13.1 waits on it (its own notes are
not in this file); 0.13.2 is built on top of both and is submitted only after 0.13.0 is approved, so these blocks are the full set
for the dashboard and their changes from the live 0.12.0 are 0.13.0's plus 0.13.2's. The developer's manual-test checklist for
0.13.2 is under "Manual test checklist for 0.13.2", after the blocks.

0.13.2 adds **Read postings automatically** (auto-read): off by default, opt-in in the user's own jobwatch Settings; the extension
reads LinkedIn and Indeed job pages by itself, slowly and a few a day, for jobs the user's jobwatch picks. Manifest changes from
0.13.0: the version, and two new permissions, `alarms` and `idle`. **No new host permission and no new content script** (it
reuses `read-posting.js` and `page-bridge.js`); a test guards the permissions list. Changed blocks: Single purpose, `alarms` and
`idle` (new), tabs, the host permission box, the content-script justification, What's new.

0.13.0's changes from the live 0.12.0 (already in review):
- Single purpose: adds Ladders lists, and ATS check / Cover letter (in the code since 0.12.0's release, never submitted).
- Justification: activeTab: adds the Ladders list (the one place the list reader runs on activeTab alone).
- Justification: scripting: adds the Ladders list reader, and the one in-page function that fills an empty cover letter box.
- Justification: tabs: adds the Ladders list tab moved to its next page, the tab Read posting opens behind the current one, and the panel's popup window.
- The host permission box, the content-script justification and the permissions table: Read posting (`read-posting.js`
  on LinkedIn and Indeed) and the local-page bridge (`page-bridge.js`, new content scripts since 0.12.0), and the Ladders sentence.
- Data types: unchanged (the same four ticks); the Website content row gains Ladders' job cards and, on LinkedIn and
  Indeed, a job's description (Read posting).
**Ladders is not a new host permission** (no `theladders.com` anywhere in the manifest; a test guards that). The manifest
changes from the live 0.12.0 besides 0.13.2's are the version, `read-posting.js` added to the LinkedIn/Indeed content-script entry
(same two hosts), and a second content-script entry, `page-bridge.js`, on `http://localhost/*`, `http://*.localhost/*`
and `http://127.0.0.1/*`: the first and third are already in `host_permissions`; `*.localhost` (jobwatch's own
`<app>.localhost` address) is a content-script match only. Expect the review to look at the content scripts, and
possibly an in-depth review, as with 0.10.0 and 0.12.0.

### Justification: alarms

Times the pause between two automatic reads of a job posting (a random 2 to 3 minutes) and a once-a-minute check that the feature is still on. A Manifest V3 service worker is stopped by Chrome after about 30 seconds idle, so a timer in the worker would be lost; alarms survive that. It reads nothing and is used only when the user has turned on Read postings automatically in their own jobwatch's Settings (off by default).

### Justification: idle

Tells the extension whether the user is at the computer, so automatic reading of a posting waits while the user is active on a LinkedIn or Indeed tab and only runs when they are away or on another site. It reads nothing about the user other than "active, idle or locked", and keeps nothing. Used only when the user has turned on Read postings automatically.

### What's new (0.13.2)

No dashboard field (see 0.13.0's note); for the GitHub release notes and the listing description:

New: Read postings automatically, off until you turn it on in jobwatch's Settings (Applying). For LinkedIn and Indeed jobs that came from an alert or a list with no posting text, the extension reads the posting for you the way the Read posting button does: one job at a time in a tab behind your others, a random 2 to 3 minutes apart, at most 25 a day for each site and 50 in all, and only while you are not on LinkedIn or Indeed. At the first sign of trouble (a sign-in or security page, an error, an account notice) it stops for the day and says why in the side panel and on jobwatch's Today. Pause, Resume and Off are in the side panel and on Today, and the options page has a switch. LinkedIn may restrict accounts that look automated; the limits keep reading slow and small. Two new permissions: alarms (the pause between reads) and idle (to read only when you are not busy on LinkedIn). It needs the newest jobwatch.

### Single purpose

Help with job applications by connecting the browser to the user's own jobwatch app, which runs on their computer. The extension fills job application forms from the user's saved details and earlier answers after the user reviews each field, and sends the job listings from a LinkedIn, Indeed or Ladders list the user has open to that same local app. When the user asks, it also drafts a reply to a recruiter's LinkedIn conversation the user has open (it reads that conversation, the local app writes the draft, and the user chooses whether it is typed into the message box; the user sends it), and checks the resume against a job's posting and drafts a cover letter with the local app, which the user may put in the form's cover letter box. If the user turns it on in their own jobwatch (off by default), it also reads the postings of LinkedIn and Indeed jobs the app picks that have no text, one at a time in a background tab, slowly and a few a day, and gives the text to that same local app.

### Justification: activeTab

Reads the application form's questions and fills the ticked fields, only on the tab where the user clicked the extension's icon and pressed Fill this application. It is also the only access to a Ladders list (theladders.com): Read the jobs on this list reads that list only on the tab where the user clicked the icon, and only after the user presses the button.

### Justification: scripting

Injects the script that finds a form's fields and writes the ticked values into the tab, only after the user presses Fill this application. Also injects the job-list reader into the user's LinkedIn, Indeed or Ladders tab when the user presses Read the jobs on this list, and the script that presses LinkedIn's Apply button when the user presses Open the company's posting. When the user presses Draft reply to this conversation, it injects the script that reads the open LinkedIn conversation, and, when the user presses Put in the message box, the script that types the draft into that conversation's message box (it clicks nothing and never presses Send). When the user presses Fill the cover letter box, it injects one function that writes the letter into an empty cover letter box (it never touches a file field and never presses Submit). All scripts ship inside the package; no remote code is loaded.

### Justification: storage

Keeps the jobwatch address and pairing token the user enters on the options page, the number of list pages to read, the passive-mode checkbox, and the job cards passive mode has noted (see the LinkedIn and Indeed justification) until the user imports or deletes them. Session memory holds an answer the user just submitted until the local jobwatch has recorded it.

### Justification: sidePanel

Shows the review (each field, where its value came from, and the Fill selected button) and the list-import results in Chrome's side panel beside the page, so nothing covers the page. One panel per tab.

### Justification: tabs

Reads the address and title of tabs so the panel offers the right buttons for the site the user is on; the one new tab that LinkedIn's Apply button opens (within two minutes of the press), whose address goes to the user's local jobwatch; and a form's tab after a scan, to notice that the page now looks like a submission confirmation so jobwatch can record the application. During a list import the user started (LinkedIn, Indeed or Ladders), it also moves that same list tab to the list's next page. When the user's own jobwatch asks to read a posting (its Read posting button), it opens that LinkedIn or Indeed job in a tab behind the current one, waits for it to load and closes it. If the user has turned on Read postings automatically in their own jobwatch (off by default), it does the same for the jobs jobwatch picks, one at a time, and reads which tab the user is on, only to wait while that is a LinkedIn or Indeed tab. For a window where Chrome has no side panel (an installed web app) it opens the same panel in a small popup window beside it.

### Host permission justification (the dashboard field; 1,000 characters at most)

The dashboard has one box for every match pattern, content-script sites included, capped at 1,000 characters. Paste this; the two longer blocks below are the full wording for a reviewer who asks.

Local app (http://127.0.0.1/*, http://localhost/*; a small script also runs on these and *.localhost, for jobwatch's own page): the only network destination is the jobwatch app on the user's own computer. It supplies the user's details, answers and resume and receives job cards and applications. Nothing goes to the developer or a third party.

LinkedIn and Indeed (https://www.linkedin.com/*, https://*.indeed.com/*): the script acts only on a list of jobs, or a job page jobwatch opened with #jobwatch-read (Read posting, or slow, capped automatic reading if the user turns it on in jobwatch; off by default) and reads its description. On a list it reads only the cards drawn (title, company, place, pay, date), never profiles or account data. Messages: only on Draft reply. Passive mode is off by default. Read the jobs on this list runs only when pressed.

Ladders (theladders.com): no host access; read through activeTab, on the tab where the user clicked the icon.

### Justification: host permissions (http://127.0.0.1/* and http://localhost/*)

These are the only network destinations the extension talks to: the jobwatch app the user runs on their own computer (default http://127.0.0.1:8765). It supplies the user's details, earlier answers and resume, drafts answers, receives imported job cards, and records applications. Nothing is sent to the developer or any third party; the developer runs no server.

### Justification: content script on LinkedIn and Indeed (https://www.linkedin.com/*, https://*.indeed.com/*)

A content script runs on LinkedIn and Indeed pages. It does nothing unless the address is a list of jobs (a search, "Jobs based on your preferences", "Jobs for you"), or a single job page whose address ends in #jobwatch-read, which only the user's own jobwatch adds (its Read posting button opens the job in a new tab that way). On a list it reads only the job cards the page has already drawn: the job number on the site, title, company, place, pay and how long ago it was posted. On a #jobwatch-read job page it reads that job's description, title and company, and whether the site says the posting is closed (LinkedIn's "no longer accepting applications", Indeed's "expired"), gives them to the user's local jobwatch (the job's number comes from the tab's address), shows a banner and closes the tab. Nothing else on either page is read: no profile or account data.

Draft reply (only when the user presses the button in the side panel; a script injected for that press, not the content script above): on a LinkedIn conversation the user has open, it reads the other person's name and the text and times of the messages already on screen in that one conversation. It does not scroll, open another conversation or read the message list, and keeps nothing: the text goes to the user's own local jobwatch, which writes a draft. When the user presses Put in the message box it types the draft into that conversation's message box and nothing else; it never clicks Send or any other button. If jobwatch is set to use a cloud model for replies, jobwatch (not the extension) sends the conversation to it, and the panel says so.

Reading postings automatically (new in 0.13.2; off by default; the user turns it on in their own jobwatch's Settings, which shows the limits and a warning that LinkedIn may restrict accounts that look automated): the extension's service worker asks the user's local jobwatch for the next job worth reading, opens that LinkedIn or Indeed job in a background tab with `#jobwatch-read` added (so the same `read-posting.js`, with the same reads, acts on it), and closes the tab once the text is copied to the local jobwatch. One job at a time, one page load per job, no scrolling, clicking or following links, a random 2 to 3 minute pause, at most 25 a day for each site and 50 a day in all (hard ceilings in the code that settings cannot raise), only while the user is not active on LinkedIn or Indeed. It stops for the rest of the day at the first sign of trouble (a sign-in or security page, HTTP 429, 999 or 403, an account notice, two pages in a row with no posting), shows a badge and a message, and the user can pause or turn it off in the side panel, in jobwatch or in the extension's options. It signs in to nothing and solves no check. Nothing is sent to the developer or a third party.

Passive mode (off by default; the user opts in with a checkbox in the side panel): once the user ticks it, as the user browses a list, the script notes those cards, with no scrolling, clicking or page-opening by the extension, and keeps them in the extension's local Chrome storage on the user's computer (up to 1000 jobs). Nothing is sent anywhere until the user presses Import in the side panel; then the jobs go only to the user's own local jobwatch and are deleted from the extension. With the checkbox off (the default), the script reads and stores nothing.

Read the jobs on this list (LinkedIn, Indeed and, new in 0.13.0, Ladders): only when the user presses this button, the extension scrolls the list the user has open and moves it to the list's next page, up to the number of pages the user sets (4 by default, at most 10), reads the same job cards, and sends them to the user's local jobwatch. It reads only pages of that list in the user's own tab and never opens other pages or crawls.

Ladders (theladders.com, new in 0.13.0): no content script and no host permission. When the user presses Read the jobs on this list on a Ladders list ("Recommended Jobs", a search), the extension injects the same job-list reader (activeTab: the tab where the user clicked the icon) and reads the same fields from the cards: the job's number, title, company, place, pay (Ladders' own estimate), how long ago it was posted and the address of the job's page on Ladders. The jobs go only to the user's local jobwatch, which keeps Ladders' page only as a reference note. Passive mode does not run on Ladders.

Content script on the user's own jobwatch page (http://localhost/*, http://*.localhost/*, http://127.0.0.1/*; `page-bridge.js`, new since 0.12.0): so that the Read posting button on the user's jobwatch page can open a posting in a background tab instead of taking the user away from the page. It passes the page's request (a LinkedIn or Indeed job address) to the extension's service worker and the answer back, and reads nothing else from the page. The service worker acts only for the address and port the extension is paired with, and refuses any other local page. It also tells the page what the extension can do (a `ping`, answered with a fixed list), so the page works with an older extension too. Nothing goes to the developer or any third party.

### Data use: data types to tick

Tick: Personally identifiable information, Health information, Personal communications (new with Draft reply), Website content.

Leave unticked: Financial and payment information, Authentication information, Location, Web history, User activity.

Why, if a reviewer asks: PII and Health come from the user's own jobwatch and are written into the form they are filling (Health: the voluntary self-identification answers, only when the user ticks that row). Website content is the form's questions, the job cards of a LinkedIn, Indeed or Ladders list, and (Read posting, and the opt-in automatic reading of 0.13.2, which reads the same things without a button press) the description of a LinkedIn or Indeed job page the user's own jobwatch picked or opened. The extension keeps in local storage only today's counts, its on, paused or off state and the keys of jobs it tried; nothing new leaves the computer. Personal communications is the text of the one LinkedIn conversation the user asks for a reply to, read only when they press Draft reply. All of it goes only to the user's own jobwatch on the same computer; none to the developer or a third party. The pairing token is the user's own credential for their own jobwatch, stored locally.

### Data use: certifications to tick

- [x] I do not sell or transfer user data to third parties, outside of the approved use cases.
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose.
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes.

### What's new (0.13.0)

The dashboard has no "What's new" field (checked 2026-11-17); this text is for the GitHub release notes and, if you want it, the listing description, not a paste block. It covers the live 0.12.0 and what has changed in the extension since (Read posting, ATS check and Cover letter, the popup panel, Draft reply fixes, Ladders). Only what a user of the extension sees:

New: Read the jobs on this list now works on Ladders ("Recommended Jobs" and searches on theladders.com), a page at a time like Indeed, up to the number of pages you set. It reads the same job cards (number, title, company, place, pay, how long ago it was posted, and the job's page address on Ladders, which your jobwatch keeps only as a reference: you apply on the company's own site). The extension reads Ladders only on the tab where you click its icon and only when you press the button, and "Note jobs while I browse" is not offered there. It needs the newest jobwatch (`pip install -U jobwatch`); with an older one the panel says so instead of offering the button.

New: Read posting. When jobwatch holds a LinkedIn or Indeed job with no posting text, its Read posting button opens the job in a tab behind the one you are on, the extension reads the job's description there and passes it to your jobwatch, and the tab closes. Only that job's card changes on jobwatch's page; your place stays. With an older extension the tab opens in front, and jobwatch says to update. It reads only a page your own jobwatch opened (its address ends in #jobwatch-read).

New: ATS check and Cover letter on a job's page: which of the posting's keywords your resume doesn't show, and a cover letter drafted by your own jobwatch's local model, which you can put in an empty cover letter box (never Submit).

Also: in an installed web app's window (where Chrome has no side panel) the same panel opens in a small window beside it; Draft reply finds a conversation open in LinkedIn's message bubble and in InMail threads. No new permission and no new host permission is requested (the two content scripts added since 0.12.0 run on the sites and local addresses the extension already covers, see the content-script justification).

### What's new (0.12.0, live), submitted with 0.11.0

The dashboard has no "What's new" field (checked 2026-11-17); this text is for the GitHub release notes and the listing description, not a paste block. It covers 0.11.0 too, which was never submitted:

New: Draft reply. On a LinkedIn conversation you have open, press "Draft reply to this conversation" in the side panel. The extension reads that one open conversation and gives it to your own jobwatch, which writes a draft with a model running on your own computer. The panel shows a spinner with the seconds elapsed, then the draft, warnings and what to check, and says where it was written. "Put in the message box" types it into LinkedIn's box; the extension never presses Send. The message text stays on your computer and goes only to your own jobwatch, at the address you entered. It reads nothing else from LinkedIn's messages. This adds Personal communications to the data the extension handles; the privacy policy is updated.

New look for the side panel: a card for the page you are on (an application form, a LinkedIn conversation, a list of jobs, a job posting) with the one action that suits it, then every action as a tile in three groups (Apply, Messages, Jobs). A System, Light or Dark theme choice is in Settings.

Fixes: reading a LinkedIn or Indeed list takes the visible job title (no more "Selected, ..." or doubled titles), shows how many jobs your jobwatch already had, and no longer stalls on long waits; it says what to do if jobwatch doesn't answer in time.

No new permission is requested.

### What's new, ATS check and Cover letter in full (shipped in 0.13.0; the longer wording)

New: ATS check and Cover letter, on a job's page. ATS check shows which of the posting's keywords the resume your jobwatch keeps for that job doesn't show, so you can see what a screener would miss; it is a keyword check on your own computer and changes nothing. Cover letter has your jobwatch draft a letter with the model on your computer, keeps it with the job, and shows it in the side panel to edit and copy. "Fill the cover letter box" puts it in the form's cover letter box when that box is empty (replacing text is a second press) and never presses Submit. For these two buttons the extension sends your own jobwatch, at the address you entered, the page's address and the company and job title it shows. No new permission is requested; the privacy policy is updated.

### What's new (0.10.0, live)

New: import the jobs from a LinkedIn or Indeed list into your own jobwatch. Press "Read the jobs on this list" on a list you have open, or tick "Note jobs while I browse" in the side panel (it is off by default) and import the jobs noted while you browsed. The jobs go only to the jobwatch on your own computer. Also: one side panel per tab, and list imports can run in several tabs at once. This version adds LinkedIn and Indeed (job-list pages) as a site the extension runs on; the privacy policy is updated.

## Manual test checklist for 0.13.2

For the developer, before submitting 0.13.2. An agent must never run auto-read against real LinkedIn or Indeed; its tests use
fake pages. Do this yourself, with an account you can afford to have a check shown on:
1. Build and load unpacked: `python chrome-extension/tools/package.py`, then load `chrome-extension/` in chrome://extensions; run this jobwatch (the branch or the release). Options > Test says "Connected to jobwatch".
2. In jobwatch Settings > Applying, find "Read postings automatically": it is **off**, the limits are in plain words and the risk note is shown. Set Reads a day to 3 and Save.
3. Open Today with the extension loaded: no auto-read line yet. Tick Read postings automatically, Save. Within a minute Today shows "Reading postings: 0 of N today · next in 2m" (N at most 3) with Pause and Off, and the side panel shows the same.
4. Stay on a LinkedIn tab: it must not read ("waiting until you leave LinkedIn or Indeed"). Switch to another site: after the countdown one tab opens behind, closes, and Activity shows "Read <title> at <company> from linkedin.com". Check the new job has its text and that the pause between two reads is 2 to 3 minutes.
5. Press Pause: the line says paused and nothing reads; Resume continues after a new pause; Off turns it off in this browser, Turn on brings it back.
6. After the third read the line says "done for today, back tomorrow".
7. Sign out of LinkedIn (or use a private window with the extension allowed) and let one read start: it must stop for the day with the badge "!" and "Auto-read paused: LinkedIn asked for a sign-in. Resumes tomorrow, or press Resume after you check LinkedIn." on Today, in the panel and in Activity; the tab stays open. Sign in again, press Resume.
8. The kill switch: untick the checkbox on the extension's options page: reading stops at once and Today shows "Auto-read is off in this browser."; untick Settings > Read postings automatically in jobwatch: the line disappears.
9. Check the extension's details page in chrome://extensions: only `alarms` and `idle` are new (alarms may show no warning at all) and the site access is unchanged.

## Permissions Justification (working notes)

Each entry matches what the code does (checked against `background.js`, `sidepanel.js`, `options.js`, `passive.js`,
`read-posting.js` and `page-bridge.js` on 2026-11-25; the permissions list is the same as 0.12.0's).

| Permission | Type | Justification |
|------------|------|---------------|
| `activeTab` | permissions | Reads the application form's questions, and fills the ticked fields, only on the tab where the user clicked the extension's icon. Also the only access to a Ladders list (0.13.0): Read the jobs on this list reads it on that tab, after the button is pressed. |
| `scripting` | permissions | Injects the script that finds the form's fields and writes the ticked values into that tab, only after the user clicks the icon and presses Fill this application. Also injects the list reader into a LinkedIn, Indeed or Ladders tab when the user presses Read the jobs on this list, the one function that fills an empty cover letter box when the user presses Fill the cover letter box, the script that presses LinkedIn's Apply button when the user presses Open the company's posting, and (Draft reply) the script that reads the one open LinkedIn conversation when the user presses Draft reply, and types the draft into its message box when the user presses Put in the message box. It clicks nothing there and never presses Send. |
| `storage` | permissions | Saves the jobwatch address and pairing token the user enters on the options page, the list-import page count and the passive-mode checkbox, the job cards passive mode noted until the user imports them, and (in session memory) an answer the user just submitted until jobwatch has recorded it. |
| `sidePanel` | permissions | Shows the review (each field, where its value came from, and the Fill selected button) in Chrome's side panel beside the form, so it never covers the page. |
| `alarms` | permissions | (0.13.2) Times the pause between two automatic reads of a job posting and a once-a-minute check that the feature is on, so they survive Chrome stopping the service worker. Reads nothing; used only when the user turned on Read postings automatically (off by default). |
| `idle` | permissions | (0.13.2) Tells whether the user is at the computer, so automatic reading waits while the user is active on a LinkedIn or Indeed tab. Reads nothing but "active, idle or locked", keeps nothing; used only when Read postings automatically is on. |
| `tabs` | permissions | Reads the address (and title) of tabs: the active tab, to choose the side panel's button and to know which site the user is on; the one new tab that LinkedIn's Apply button opens (within two minutes), whose address is given to the user's local jobwatch; and a form's tab after a scan, to notice that the page now looks like a submission confirmation so jobwatch can record the application. For a list import (LinkedIn, Indeed or Ladders) it also moves the user's own list tab to its next page; for Read posting it opens the job in a background tab for the user's own jobwatch and closes it, and for a window with no side panel it opens the panel in a popup window. |
| `http://127.0.0.1/*` | host_permissions | The extension's only network access: the jobwatch app the user runs on their own computer (default `http://127.0.0.1:8765`) supplies the user's details, earlier answers and resume, drafts answers, receives imported job cards and records the application. |
| `http://localhost/*` | host_permissions | Same, for a user whose jobwatch address is written as `localhost` instead of `127.0.0.1`. |
| Content script on `https://www.linkedin.com/*` and `https://*.indeed.com/*` | content_scripts matches (a host access, not in `host_permissions`) | Passive mode, off by default and opt-in with a side-panel checkbox: once the user ticks it, when the address is a list of jobs, a small script notes the job cards the page has already drawn (job number, title, company, place, pay, age) and keeps them in the extension's storage on this computer until the user presses Import. With the checkbox off (the default) it reads and stores nothing. It also lets the Read the jobs on this list button reach those two sites' lists, and (`read-posting.js`, 0.13.0) reads a job page's description only when its address ends in `#jobwatch-read`, which only the user's own jobwatch adds. |
| Content script on `http://localhost/*`, `http://*.localhost/*` and `http://127.0.0.1/*` | content_scripts matches (the first and last are already in `host_permissions`; `*.localhost` is a match only) | `page-bridge.js`, 0.13.0: lets the Read posting button on the user's own jobwatch page open the posting in a background tab and tells that page when it is read, and what the extension can do (a `ping`). It reads nothing from the page but that request; the service worker refuses any local page that is not the paired jobwatch's address and port. |
| Ladders (`https://www.theladders.com/*`) | none (activeTab only) | **Not in the manifest.** Read the jobs on this list reads a Ladders list only on the tab where the user clicked the icon (activeTab), by injecting the same list reader (`scripting`). No content script, no host permission, no passive mode there. |

No other host permissions are requested. On an application form the extension reads only the active tab after the
user clicks its icon.

**Remote code:** No. All JavaScript ships in the package. jobwatch returns JSON data and a resume file only.

### Permission audit (2026-11-12)

Every permission in `manifest.json` is used by the code. Points to watch in review:

- `tabs` is the broadest. The listing above names each use; `chrome.tabs.get`, `query`, `update`, `onCreated`,
  `onUpdated`, `onActivated` and `onRemoved` are all called.
- `activeTab` is partly overlapped by the LinkedIn/Indeed content-script host access and by `tabs`; it is still used
  for the icon-click case on any other site, so it stays.
- Version 0.9.0's justifications said the extension "cannot read any website except the active tab" and "reads
  nothing from LinkedIn's pages". Both are no longer true from 0.10.0 (passive mode and list import add the
  LinkedIn/Indeed content script). The Privacy policy (`PRIVACY.md`) already says so; keep the dashboard in step.

## Privacy & Data Use

### Data Collection

**Does the extension collect user data?** Yes. It handles it on the user's computer and sends it only to the user's
own jobwatch; the developer receives none of it.

Tick **Personally identifiable information**, **Health information**, **Personal communications** (Draft reply) and
**Website content**. Leave every other type unticked.

| Data Type | Collected? | Transmitted Off-Device? | Purpose | Shared with Third Parties? |
|-----------|-----------|------------------------|---------|---------------------------|
| Personally identifiable information | Yes | No (stays between the page and the user's own jobwatch on the same computer) | Receives the user's name, email, phone, address and other applicant details from jobwatch and writes them into the form; answers sent back after a submit can contain such details. | No |
| Health information | Yes | No | Voluntary self-identification answers (e.g. disability status, default "decline to answer") chosen in jobwatch and written into the form when the user ticks that row. Never sent back to jobwatch. | No |
| Financial info | No | | | |
| Authentication info | No | | The pairing token is the user's own credential for their own jobwatch, stored locally and never collected by the developer. | |
| Personal communications | Yes (Draft reply) | No (only to the user's own jobwatch; jobwatch's own setting, off by default, can send it to a cloud model, and the panel says so) | Only when the user presses Draft reply: the other person's name and the text and times of the messages in the one open LinkedIn conversation, given to the local jobwatch to write a draft reply. Not kept by the extension. | No |
| Location | No | | The city and state in the user's details are an address for the form, not the device's location. | |
| Web history | No | | Only the active tab's address, and the address of the one tab LinkedIn's Apply button opens, are used, only to give to the user's own jobwatch; nothing is kept as a history. | |
| User activity | No | | No clicks, keystrokes or mouse movement are recorded. After a scan it only notices that the form was submitted (the form's submit event, or a click on its Submit button), so it can send the answers as they stood to jobwatch. | |
| Website content | Yes | No (only to the user's own jobwatch) | Reads the form's questions, answer options, current values, the page address, and the company and job title shown on the page; on LinkedIn and Indeed lists, the job cards; with Save this posting to jobwatch, the job text a company's page shows. Sent to the local jobwatch to find earlier answers, draft an answer, import jobs, keep the answers when the user presses Submit, and record the application. With ATS check and Cover letter the page's company and job title go to the local jobwatch to tell which job it is. | No |

### Data Use Certification

- [x] I do not sell or transfer user data to third parties, outside of the approved use cases.
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose.
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes.

## Privacy Policy

**Privacy Policy URL**

https://github.com/vinayvobbili/jobwatch/blob/main/chrome-extension/PRIVACY.md

It covers each of the answers above: what the extension reads, what it receives from jobwatch and writes into the
form, what it sends to jobwatch, what it stores, and that the authors run no server.

## Distribution

**Payment**: Free.

**Visibility**: choose one in the dashboard: Public (anyone can find it), Unlisted (only people with the link) or
Private (a Google Workspace domain or named testers).

**Regions**: All regions.

**Mature content**: No.

## Developer Info

**Publisher Name**: already set up on the developer account that publishes attestq (the one-off US$5 fee, 2-Step
Verification, the verified contact email and the trader / non-trader declaration are done; nothing to repeat).

**Contact Email**: the account's verified contact email (set in the dashboard, shown publicly).

**Support URL**: https://github.com/vinayvobbili/jobwatch/issues

**Homepage URL**: https://github.com/vinayvobbili/jobwatch

## Test Instructions (Privacy practices > "Test instructions" for the reviewer)

The extension does nothing without the jobwatch app on the same computer, so the reviewer gets the steps to run it
(no account or sign-in is needed):

The extension fills job application forms from the jobwatch app, which runs on the same computer (free, open source). To try it:
1. Install Python 3.11 or later, then run: pip install jobwatch
2. Run: jobwatch init, then: jobwatch. It opens http://127.0.0.1:8765.
3. In jobwatch, open Settings > Applying and fill in a few applicant details (any made-up name, email and phone). Then open Settings > Browser extension and copy the token.
4. In the extension's options (right-click its icon > Options), paste the token and press Test. It says "Connected to jobwatch".
5. Open any Greenhouse, Lever or Ashby job's application page, for example a job from https://job-boards.greenhouse.io, click the jobwatch icon (the side panel opens) and press "Fill this application". Each field shows what would be filled; tick rows and press "Fill selected". The extension never submits the form; please don't submit it.
6. ATS check and Cover letter (optional): in jobwatch, queue a job (or press Save this posting to jobwatch on its page), set a resume in Settings, then open the job's page and press "ATS check" (a keyword check on the computer, no model) or "Cover letter" (needs a local model set up in jobwatch). "Fill the cover letter box" fills an empty cover letter box on a form, only when pressed, and never submits. The extension sends jobwatch only the page's address, company and job title for these two.
7. Draft reply (optional): it needs a LinkedIn account and an open message conversation, and a local model set up in jobwatch, so a reviewer can skip it. Nothing is read from LinkedIn unless Draft reply is pressed on an open conversation.

8. Job lists and Read posting (optional): they need an account on LinkedIn, Indeed or Ladders, so a reviewer can skip them. On a list of jobs (for example theladders.com/recommended after signing in), click the icon and press "Read the jobs on this list": the panel shows the job cards read and what jobwatch made of them. Nothing is read from the list until that press. "Read posting" is a button on a job's card in jobwatch itself (it needs a job that came from a LinkedIn or Indeed alert), and opens that job behind the current tab.

9. Read postings automatically (0.13.2, optional, needs a LinkedIn or Indeed account): in jobwatch, Settings > Applying > "Read postings automatically" is off by default and says, with the limits, that LinkedIn may restrict accounts that look automated. It only does anything once ticked and saved; then, for a LinkedIn or Indeed job that came from an alert and has no posting text, the extension opens that job in a background tab, copies the posting to jobwatch and closes the tab, one job at a time, 2 to 3 minutes apart, at most 25 a day for each site. The side panel shows the state ("Reading postings: 3 of 12 today · next in 2m") with Pause, Resume and Off, and the options page has a checkbox that turns it off in the browser. Reviewers can skip it: it never runs unless turned on, and the `alarms` and `idle` permissions serve only it.

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 0.13.2 | 2026-11-28 (prepared) | Upload: `dist/jobwatch-extension-0.13.2.zip` (after 0.13.0 is approved; 0.13.1 is separate). Read postings automatically (`auto-read.js` scheduler, `auto-reader.js` service-worker loop, `/ext/read-queue` and `/ext/read-report`, a status line with Pause / Resume / Off in the side panel and on jobwatch's Today, a kill switch on the options page; off by default, opt-in in jobwatch's Settings). **New permissions: `alarms`, `idle`.** No new host permission, no new content script. Limits: one job at a time, a random 2 to 3 minute pause, 25 a day per site and 50 in all, stops for the day at the first sign of trouble. Data types and certifications unchanged; `PRIVACY.md` has a new paragraph. Not yet tried against real LinkedIn or Indeed (the developer's manual checklist is in "Manual test checklist for 0.13.2"). | Prepared (not submitted; waits for 0.13.0) |
| 0.13.0 | 2026-11-25 (prepared) | Upload: `dist/jobwatch-extension-0.13.0.zip` (built with `python chrome-extension/tools/package.py`; 81,098 bytes, 21 files, nothing else is in it). Ladders lists for Read the jobs on this list (`job-lists.js` already read Ladders; the panel, `listMode` in `logic.js` and the service worker now offer it, reached through activeTab: **no new permission and no new host**, no `theladders.com` in the manifest; the panel offers it only to a jobwatch that lists `list-ladders` in `/ext/ping`). Also in this version, never submitted before: Read posting (`read-posting.js` on the LinkedIn/Indeed content-script entry, `page-bridge.js` on the local addresses, a background tab, the capability `ping`, and a fallback for an older extension), ATS check and Cover letter, the panel as a popup window for installed web apps, Draft reply (frames, shadow roots, InMail, message bubble). Permissions and `host_permissions` are the same as 0.12.0; the content scripts changed (see "Paste blocks for 0.13.0"). The privacy practices answers (data types, certifications) are unchanged; the privacy policy (`PRIVACY.md`) now names Ladders. | Ready to submit (not submitted) |
| 0.12.0 | 2026-11-17 (submitted), live 2026-11-18 | Covers 0.11.0 (below), which was never submitted. Upload: `dist/jobwatch-extension-0.12.0.zip` (65,245 bytes, 19 files). Side panel redesign: a lead card chosen from the tab's address and title (`pageContext` in `logic.js`) with the page's one action, every action as a dimmable tile in Apply / Messages / Jobs groups, a paired-status chip in the header, and a System / Light / Dark theme kept in `chrome.storage.local` and set on the options page (`look.js`). Same buttons, same messages to the service worker, no new permission (the `tabs` permission already gave the tab title; it is used only to read a company, role or conversation name for the card, and is never sent anywhere). Draft reply: reads the one open LinkedIn conversation when the user presses the button, shows jobwatch's draft with warnings and "check this" notes and whether it was written on this computer, and types it into the message box (never presses Send). Adds Personal communications to the data-use ticks and the privacy policy's LinkedIn messages paragraph. Also in 0.12.0: the side panel shows a spinner with elapsed seconds while a draft or import runs, and the project's fonts; Draft reply finds the open thread on the current LinkedIn page, says when your message is last and offers a follow-up; list-import fixes (the board lookups have a time budget, the extension keeps its worker alive and says what to do when jobwatch doesn't answer). No new permission. Built and tested against a demo page only (`demo/linkedin-messages.html`), not yet against the real LinkedIn. | Published (listing shows 0.12.0, updated 2026-11-18) |
| 0.11.0 | | Never submitted; folded into 0.12.0. List import reads the card's visible title, and drops LinkedIn's screen-reader text ("Selected, ...", the title said twice) from titles; the import summary shows jobwatch's own coverage and says when a list was imported before. Setup text (side panel, options page, README) says to run `jobwatch`, which now opens the app. | not submitted |
| 0.10.0 | | Passive mode and list import for LinkedIn and Indeed job lists (adds the LinkedIn/Indeed content script), one side panel per tab, list imports run in parallel (one per tab). LinkedIn/Indeed list import, passive mode off by default, one side panel per tab, parallel list imports. New promo video: https://youtu.be/cILjM1IF4ZQ. Upload: `dist/jobwatch-extension-0.10.0.zip`. Paste blocks and screenshots 5 and 6 ready; submitted for review 2026-11-14. | Published (live, nothing pending as of 2026-11-17) |
| 0.9.0 | 2026-11-10 | First submission: fills Greenhouse, Lever and Ashby forms from details and earlier answers, drafts, resume attach, records the application, LinkedIn Apply handoff. | Published |

Fill in the 0.10.0 date from the dashboard. The 0.9.0 date is the listing's "Updated" date.

## Review Notes

- 0.10.0 submitted for review 2026-11-14; live.
- 0.12.0 submitted for review 2026-11-17 (auto-publish when approved; the host-permission banner warned of an in-depth review); live 2026-11-18.
- 0.13.2 prepared 2026-11-28, to be submitted after 0.13.0 is approved (0.13.1 is separate). Notes to the reviewer: it adds two
  permissions, `alarms` and `idle`, and nothing else in the manifest (no host permission, no content script). The feature they
  serve, reading LinkedIn and Indeed postings by itself, is off by default, needs the user's own opt-in in their local jobwatch
  Settings (which shows the limits and a warning that LinkedIn may restrict accounts that look automated), is slow and capped
  (one job at a time, a random 2 to 3 minutes apart, 25 a day per site, 50 in all), stops for the day at the first sign of
  trouble and has a kill switch; text goes only to the user's local jobwatch. Test instructions step 9 shows where it is.
- 0.13.0 prepared 2026-11-25, not yet submitted. Notes to the reviewer, if the dashboard has a field for them (the test
  instructions above are the field for this): the extension's permissions and host permissions are unchanged; since 0.12.0
  it adds two content-script entries (`read-posting.js` on LinkedIn/Indeed, acting only on a page jobwatch opened with
  `#jobwatch-read`; `page-bridge.js` on local addresses, passing one request to the service worker, which refuses any
  page but the paired jobwatch) and reads Ladders lists on the tab where the user clicked the icon (activeTab).

### Known Issues / Limitations

- 0.13.0 (prepared, not submitted): ATS check and Cover letter. Two
  new tiles in the Apply group (`ats`, `cover`), shown only when jobwatch's `/ext/ping` lists those features. Pressing
  one sends the local jobwatch the page's address plus the company and title the page shows (`pageInfo` in
  `background.js`, read with the existing `page.js` on the page the user is on; LinkedIn and Indeed pages are not read),
  through the new `POST /ext/ats` and `POST /ext/cover` (documented in `API.md`); the other `/ext` calls that find a job
  (`context`, `resume`, `tailor`, `draft`) now send the same two fields, so jobwatch can match an alert job to the
  company's own site by company plus title when exactly one open job fits. ATS check is jobwatch's local keyword check
  (no model); the letter is written by jobwatch's local model (unless the person set `reply.backend: chat`, and the panel
  says which) and kept with the job as a version. Fill the cover letter box (`fillCover`, an in-page function injected
  only on that press with `logic.js` and `page.js`, the same pair Fill this application injects) writes into a textarea
  whose label says cover letter, only if it is empty unless the person presses Replace; it never touches a file input,
  never clicks anything and never submits. No new permission, host or content script. When submitting: the single
  purpose (adds "and, when asked, checks the resume against the job's posting and drafts a cover letter with the local
  app, which the user may put in the form's cover letter box"), the scripting justification (one more injected
  function, after the user presses Fill the cover letter box, that fills that one box), the Website content row (the
  company and title shown on the page go to the local jobwatch for these two buttons), the privacy policy
  (`PRIVACY.md`, updated) and the "What's new" text. Built and tested against made-up pages only
  (`demo/cover.html`, `demo/cover-file.html`, `tests/test_extension_e2e.py`), not yet against a real application form
  with the unpacked extension.

- 0.13.0 (prepared, not submitted): Read posting. jobwatch's Queue/Today card button opens a LinkedIn or Indeed job
  in a new tab with `#jobwatch-read` in its address; the new content script `read-posting.js` (added to the existing
  LinkedIn/Indeed content-script entry in `manifest.json`, so no new permission or host) reads that page's description only
  then, sends it to the local jobwatch through the service worker (`readPosting` in `background.js`, `POST /ext/posting`
  with `indeed` or `linkedin` + `text`) and closes the tab. This is the first time the extension reads a job's description
  on LinkedIn/Indeed: when submitting, update the dashboard's host-permission and content-script justifications (the two
  paragraphs above already carry the new wording; the 1,000-character box needs the first one), the Website content row
  of the data-use table (job descriptions on LinkedIn/Indeed), the privacy policy (updated in `PRIVACY.md`), and the
  "What's new" text. Built and tested against made-up pages only (`tests/test_read_posting.py`), not yet against a live
  sign-in with the unpacked extension.
  Read posting also (same unreleased version) opens that tab behind the one the person is on, and tells jobwatch's page
  when it is read so the page updates one card instead of reloading: a second, tiny content script `page-bridge.js`
  on `http://localhost/*`, `http://*.localhost/*` and `http://127.0.0.1/*` (the hosts `host_permissions` already
  covers, so no new install warning) passes the page's request (`readInBackground` in `background.js`, which refuses any
  page not on the paired jobwatch's local address and port, and opens only LinkedIn or Indeed job addresses, with
  `tabs.create({active: false})`) and the answer back. It reads nothing from the page. When submitting, add it to the
  content-script justification below ("a content script on the user's own local jobwatch page, so the Read posting
  button there can open the posting without taking the user away from the page").
  The bridge also asks the service worker a `ping` on load, which answers `capabilities: ['readInBackground']`, and
  writes that to the page (`<html data-jobwatch-caps>`), so jobwatch's page, which is served by the latest jobwatch and
  often newer than the Web Store build, reads in the background only with an extension that can; an older one (which
  answers "unknown message") gets the tab in front as before, with a one-time hint to update or reload the extension.
  No new permission, host or message beyond `ping`; nothing sensitive is in its answer.

- 0.12.0 does nothing when the toolbar icon is clicked in an installed web app's window (LinkedIn's PWA): Chrome offers
  no side panel there and `background.js` swallowed the error. Fixed in 0.13.0:
  the click now opens the same panel (`sidepanel.html?tab=<id>`) as a 420 px popup window beside the app window, one per
  tab, focused instead of duplicated, closed with its tab; ordinary windows keep the side panel. `panelHome` and
  `panelBounds` in `logic.js` decide; no new permission. Checked in a real PWA window (LinkedIn's) on 2026-11-19 after
  reloading the unpacked extension: the click opens the popup panel.
- 0.12.0's Draft reply answered "No conversation is open (0 editable boxes, 0 messages)" with a LinkedIn message bubble
  plainly open: LinkedIn now draws the bubble inside an open shadow root (`#interop-outlet`), which the page queries in
  `reply.js` stopped at. Fixed in 0.13.0: `reply.js` walks open shadow roots
  (`deepAll`, `closestDeep`, `holds`, `activeDeep`) to find the box, read the messages and fill the reply; the demo page
  has a `?shadow` shape and the e2e test covers it. Checked against the live feed page's `#interop-outlet` on 2026-11-20.

- 0.12.0's Draft reply answered "No conversation is open (0 editable boxes, 0 messages)" on an InMail thread in
  Messaging (2026-11-23). A fresh Messaging tab read fine with the 0.12.0 selectors (an InMail thread and an ordinary
  chat), so the failing read had looked at a document with no box at all. Hardened in 0.13.0:
  `draftReply` and `fillReply` in `background.js` now inject `reply.js`
  into every frame of the tab (`allFrames`, the same access `activeTab` already grants; `pickRead` and `pickFill` in
  `logic.js` take the frame that holds the conversation), look once more after 1.5 s when nothing shows yet, and
  `reply.js` falls back to structure when LinkedIn's class names are gone (a paragraph in a list item or log region
  outside every box and form; sender from the profile link in the message header). A failure now also says how many
  frames were looked at. No new permission, host or content script, so no new store wording. Demo page shapes
  `?inmail`, `?bare` and `?frame` and the e2e test cover them. The user reloads the unpacked extension at
  `chrome://extensions` (the reload button on jobwatch's card), then reloads the LinkedIn tab.

- 0.12.0 told a LinkedIn page that is not Messaging (the feed, a profile) "IDLE / Nothing to do on this page" even
  though Draft reply works from a conversation open in the message bubble. Fixed in 0.13.0:
  `pageContext` gives those pages a "LinkedIn" lead card (kind `bubble`) that says "Have a recruiter's
  message open in the bubble? Draft reply reads it." with the Draft reply tile lit. Panel text only; no new permission.

- 0.13.0, Ladders lists (`job-lists.js` reads Ladders; `listMode` in `logic.js` says when a tab is one; `importList` in
  `background.js` injects the reader and moves the tab to the next page like Indeed's): reached through `activeTab`
  only. Chrome keeps activeTab's grant across a same-site page load, so the next page can be read; if it is not, the
  panel says "Chrome stopped the reading on page N: click the jobwatch icon there and import again" and imports what
  was read. `/ext/ping`'s new feature `list-ladders` gates the button, so an older jobwatch (which would put Ladders'
  pay estimate in a job's pay) offers none. Built and tested against a made-up page only (`demo/ladders-jobs.html`,
  `tests/test_extension_e2e.py`); **not yet checked on a real signed-in Ladders list with the unpacked extension**:
  do that before submitting (click the icon on theladders.com/recommended, press Read the jobs on this list).
- The 0.10.0 content script on LinkedIn and Indeed is a new host access (adds a "broad host access" review and
  possible in-depth review). The paste blocks above are the 0.10.0 answers; the 0.9.0 claim "reads nothing from
  LinkedIn" is gone.
- Draft reply (0.12.0) reads message text, so the data-use form gains Personal communications and the "never
  messages" wording is gone from the justifications above (the single purpose, scripting, host permission and content
  script blocks all name Draft reply). Checked by hand on a real LinkedIn InMail thread on 2026-11-17: it finds the
  open thread (role, aria-label and `data-view-name` hooks, not generated class names), drafts on the local model, and
  says when the user's message is the last one.
- The store takes at most five screenshots; there are six. Upload 1, 2, 3, 5 and 6; drop 4 (pairing).
- A reviewer may ask why `tabs` and `scripting` are needed beyond `activeTab`: answered in the blocks above.

### Rejection History

None.
