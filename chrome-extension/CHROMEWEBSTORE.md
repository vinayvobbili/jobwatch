# Chrome Web Store Listing: jobwatch: Application Filler

> Last Updated: 2026-11-14

Live: https://chromewebstore.google.com/detail/jobwatch-application-fill/abackmpdpfflgiaccgfkababjplgolfi
(item ID `abackmpdpfflgiaccgfkababjplgolfi`)

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

It needs the jobwatch app: install it (https://github.com/vinayvobbili/jobwatch) and run `jobwatch ui` on the same computer. Without it the extension does nothing.

How it works
• Click the jobwatch icon on an application page, then Fill this application.
• Each field is a row with a badge: Your details (name, email, phone, links, work authorization), Past answer (an answer you gave on an earlier application, with the question and company it came from), Draft (written by jobwatch for a question nothing matched, never filled until you tick it) or Resume (the file jobwatch keeps for that job).
• Edit any value, tick the rows you want, press Fill selected.
• Read the form and submit it yourself. The extension never clicks Submit, Next or any button that sends the form.
• When you press the form's own Submit, jobwatch keeps the answers as they stood (your edits included) in that job's application package, and the panel says so. That alone never marks the job applied: only a confirmation page does. Your answers are kept for the next form and for interview prep.
• On a LinkedIn job, press Open the company's posting and the extension presses LinkedIn's Apply button for you, so the company's own page opens. jobwatch reads the posting there. On a company page it can't read, press Save this posting to jobwatch.
• On a LinkedIn or Indeed list of jobs, press Read the jobs on this list to send the list's job cards to your jobwatch. While you browse those two sites, the job cards you see are also noted on your computer, and nothing leaves it until you press Import. A checkbox in the side panel turns this off.

Works with
• Greenhouse, Lever and Ashby application forms, including a Greenhouse form embedded in a company's own page.
• Other single-page application forms, on a best-effort basis.
• LinkedIn and Indeed lists of jobs.
• Fields another tool (Chrome autofill, a password manager) already filled are left alone.

Privacy
• On application forms it reads only the tab where you click the icon, and only when you press Fill this application.
• Page content and your answers go only to the jobwatch on your own computer (127.0.0.1). The authors run no server and receive nothing.
• A draft is written by the model you chose in jobwatch's settings: one on your own computer, or a cloud API you set up with your own key.
• On LinkedIn and Indeed it reads only the job cards of a list (job number, title, company, place, pay, how long ago it was posted), and on a LinkedIn job page only the address. It presses LinkedIn's Apply button only when you ask, and never Easy Apply or Submit.
• No analytics, tracking or advertising.

Support: https://github.com/vinayvobbili/jobwatch/issues

**Category**

Productivity › Workflow & Planning

**Single Purpose** (see "Paste blocks for 0.10.0" below for the 0.10.0 wording)

Connect the user's browser to their own local jobwatch app for job applications: fill application forms with the user's details and earlier answers after they review each field, and send the jobs on a LinkedIn or Indeed list they have open to that app.

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

YouTube promo: (pending re-upload)

Absolute paths: `/Users/vinayvobbili/PycharmProjects/jobwatch/dist/store/` (the files above; upload all six
screenshots, the store allows up to five, so drop screenshot 4 or 3 if the dashboard refuses a sixth). All data in the images is made up (the demo server's Jordan Rivera and Initech).

### Screenshot Notes

1. The review: each field with its source badge, before anything is written.
2. The same form after Fill selected.
3. A drafted answer, unticked until the user ticks it.
4. The pairing step on the options page (server address and token).
5. (0.10.0) A LinkedIn list of made-up jobs (Initech, Globex, Umbrella), with Read the jobs on this list, the pages
   setting, the passive-mode checkbox and "Read the 8 jobs seen while browsing".
6. (0.10.0) What the import did: jobs seen and coverage.

Regenerate with `python chrome-extension/tools/store_assets.py`. The demo list page is `demo/linkedin-jobs.html`.

## Paste blocks for 0.10.0

One block per dashboard field (Privacy practices tab, and Package > What's new). Checked against `manifest.json`,
`passive.js`, `job-lists.js`, `background.js` and `sidepanel.js` on 2026-11-14.

### Single purpose

Help with job applications by connecting the browser to the user's own jobwatch app, which runs on their computer. The extension fills job application forms from the user's saved details and earlier answers after the user reviews each field, and sends the job listings from a LinkedIn or Indeed list the user has open to that same local app.

### Justification: activeTab

Reads the application form's questions and fills the ticked fields, only on the tab where the user clicked the extension's icon and pressed Fill this application.

### Justification: scripting

Injects the script that finds a form's fields and writes the ticked values into the tab, only after the user presses Fill this application. Also injects the job-list reader into the user's LinkedIn or Indeed tab when the user presses Read the jobs on this list, and the script that presses LinkedIn's Apply button when the user presses Open the company's posting. All scripts ship inside the package; no remote code is loaded.

### Justification: storage

Keeps the jobwatch address and pairing token the user enters on the options page, the number of list pages to read, the passive-mode checkbox, and the job cards passive mode has noted (see the LinkedIn and Indeed justification) until the user imports or deletes them. Session memory holds an answer the user just submitted until the local jobwatch has recorded it.

### Justification: sidePanel

Shows the review (each field, where its value came from, and the Fill selected button) and the list-import results in Chrome's side panel beside the page, so nothing covers the page. One panel per tab.

### Justification: tabs

Reads the address and title of tabs so the panel offers the right buttons for the site the user is on; the one new tab that LinkedIn's Apply button opens (within two minutes of the press), whose address goes to the user's local jobwatch; and a form's tab after a scan, to notice that the page now looks like a submission confirmation so jobwatch can record the application. During a list import the user started, it also moves that same list tab to the list's next page.

### Justification: host permissions (http://127.0.0.1/* and http://localhost/*)

These are the only network destinations the extension talks to: the jobwatch app the user runs on their own computer (default http://127.0.0.1:8765). It supplies the user's details, earlier answers and resume, drafts answers, receives imported job cards, and records applications. Nothing is sent to the developer or any third party; the developer runs no server.

### Justification: content script on LinkedIn and Indeed (https://www.linkedin.com/*, https://*.indeed.com/*)

A content script runs on LinkedIn and Indeed pages. It does nothing unless the address is a list of jobs (a search, "Jobs based on your preferences", "Jobs for you"). On such a list it reads only the job cards the page has already drawn: the job number on the site, title, company, place, pay and how long ago it was posted. Nothing else on the page is read: no profile, messages, job descriptions or account data.

Passive mode (on by default, with a checkbox in the side panel to turn it off): as the user browses a list, the script notes those cards, with no scrolling, clicking or page-opening by the extension, and keeps them in the extension's local Chrome storage on the user's computer (up to 1000 jobs). Nothing is sent anywhere until the user presses Import in the side panel; then the jobs go only to the user's own local jobwatch and are deleted from the extension. With the checkbox off, the script reads nothing.

Read the jobs on this list: only when the user presses this button, the extension scrolls the list the user has open and moves it to the list's next page, up to the number of pages the user sets (4 by default, at most 10), reads the same job cards, and sends them to the user's local jobwatch. It reads only pages of that list in the user's own tab and never opens other pages or crawls. Nothing goes to the developer or any third party.

### Data use: data types to tick

Tick: Personally identifiable information, Health information, Website content.

Leave unticked: Financial and payment information, Authentication information, Personal communications, Location, Web history, User activity.

Why, if a reviewer asks: PII and Health come from the user's own jobwatch and are written into the form they are filling (Health: the voluntary self-identification answers, only when the user ticks that row). Website content is the form's questions and the job cards of a LinkedIn or Indeed list. All of it goes only to the user's own jobwatch on the same computer; none to the developer or a third party. The pairing token is the user's own credential for their own jobwatch, stored locally.

### Data use: certifications to tick

- [x] I do not sell or transfer user data to third parties, outside of the approved use cases.
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose.
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes.

### What's new (0.10.0)

New: import the jobs from a LinkedIn or Indeed list into your own jobwatch. Press "Read the jobs on this list" on a list you have open, or leave "Note jobs while I browse" on (it can be switched off in the side panel) and import the jobs noted while you browsed. The jobs go only to the jobwatch on your own computer. Also: one side panel per tab, and list imports can run in several tabs at once. This version adds LinkedIn and Indeed (job-list pages) as a site the extension runs on; the privacy policy is updated.

## Permissions Justification (working notes)

Each entry matches what the code does (checked against `background.js`, `sidepanel.js`, `options.js`, `passive.js`
on 2026-11-12).

| Permission | Type | Justification |
|------------|------|---------------|
| `activeTab` | permissions | Reads the application form's questions, and fills the ticked fields, only on the tab where the user clicked the extension's icon. |
| `scripting` | permissions | Injects the script that finds the form's fields and writes the ticked values into that tab, only after the user clicks the icon and presses Fill this application. Also injects the list reader into a LinkedIn or Indeed tab when the user presses Read the jobs on this list, and the script that presses LinkedIn's Apply button when the user presses Open the company's posting. |
| `storage` | permissions | Saves the jobwatch address and pairing token the user enters on the options page, the list-import page count and the passive-mode checkbox, the job cards passive mode noted until the user imports them, and (in session memory) an answer the user just submitted until jobwatch has recorded it. |
| `sidePanel` | permissions | Shows the review (each field, where its value came from, and the Fill selected button) in Chrome's side panel beside the form, so it never covers the page. |
| `tabs` | permissions | Reads the address (and title) of tabs: the active tab, to choose the side panel's button and to know which site the user is on; the one new tab that LinkedIn's Apply button opens (within two minutes), whose address is given to the user's local jobwatch; and a form's tab after a scan, to notice that the page now looks like a submission confirmation so jobwatch can record the application. For a list import it also moves the user's own list tab to its next page. |
| `http://127.0.0.1/*` | host_permissions | The extension's only network access: the jobwatch app the user runs on their own computer (default `http://127.0.0.1:8765`) supplies the user's details, earlier answers and resume, drafts answers, receives imported job cards and records the application. |
| `http://localhost/*` | host_permissions | Same, for a user whose jobwatch address is written as `localhost` instead of `127.0.0.1`. |
| Content script on `https://www.linkedin.com/*` and `https://*.indeed.com/*` | content_scripts matches (a host access, not in `host_permissions`) | Passive mode, on by default and switched off by a side-panel checkbox: when the address is a list of jobs, a small script notes the job cards the page has already drawn (job number, title, company, place, pay, age) and keeps them in the extension's storage on this computer until the user presses Import. With the checkbox off it reads nothing. It also lets the Read the jobs on this list button reach those two sites' lists. |

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

Tick **Personally identifiable information**, **Health information** and **Website content**. Leave every other type
unticked.

| Data Type | Collected? | Transmitted Off-Device? | Purpose | Shared with Third Parties? |
|-----------|-----------|------------------------|---------|---------------------------|
| Personally identifiable information | Yes | No (stays between the page and the user's own jobwatch on the same computer) | Receives the user's name, email, phone, address and other applicant details from jobwatch and writes them into the form; answers sent back after a submit can contain such details. | No |
| Health information | Yes | No | Voluntary self-identification answers (e.g. disability status, default "decline to answer") chosen in jobwatch and written into the form when the user ticks that row. Never sent back to jobwatch. | No |
| Financial info | No | | | |
| Authentication info | No | | The pairing token is the user's own credential for their own jobwatch, stored locally and never collected by the developer. | |
| Personal communications | No | | | |
| Location | No | | The city and state in the user's details are an address for the form, not the device's location. | |
| Web history | No | | Only the active tab's address, and the address of the one tab LinkedIn's Apply button opens, are used, only to give to the user's own jobwatch; nothing is kept as a history. | |
| User activity | No | | No clicks, keystrokes or mouse movement are recorded. After a scan it only notices that the form was submitted (the form's submit event, or a click on its Submit button), so it can send the answers as they stood to jobwatch. | |
| Website content | Yes | No (only to the user's own jobwatch) | Reads the form's questions, answer options, current values, the page address, and the company and job title shown on the page; on LinkedIn and Indeed lists, the job cards; with Save this posting to jobwatch, the job text a company's page shows. Sent to the local jobwatch to find earlier answers, draft an answer, import jobs, keep the answers when the user presses Submit, and record the application. | No |

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
1. Install Python 3.10 or later, then run: pip install jobwatch
2. Run: jobwatch init, then: jobwatch ui. It opens http://127.0.0.1:8765.
3. In jobwatch, open Settings > Applying and fill in a few applicant details (any made-up name, email and phone). Then open Settings > Browser extension and copy the token.
4. In the extension's options (right-click its icon > Options), paste the token and press Test. It says "Connected to jobwatch".
5. Open any Greenhouse, Lever or Ashby job's application page, for example a job from https://job-boards.greenhouse.io, click the jobwatch icon (the side panel opens) and press "Fill this application". Each field shows what would be filled; tick rows and press "Fill selected". The extension never submits the form; please don't submit it.

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 0.10.0 | | Passive mode and list import for LinkedIn and Indeed job lists (adds the LinkedIn/Indeed content script), one side panel per tab, list imports run in parallel (one per tab). Upload: `dist/jobwatch-extension-0.10.0.zip`. Paste blocks and screenshots 5 and 6 ready; not yet submitted. | Ready to submit |
| 0.9.0 | 2026-11-10 | First submission: fills Greenhouse, Lever and Ashby forms from details and earlier answers, drafts, resume attach, records the application, LinkedIn Apply handoff. | Published |

Fill in the 0.10.0 date from the dashboard. The 0.9.0 date is the listing's "Updated" date.

## Review Notes

### Known Issues / Limitations

- The 0.10.0 content script on LinkedIn and Indeed is a new host access (adds a "broad host access" review and
  possible in-depth review). The paste blocks above are the 0.10.0 answers; the 0.9.0 claim "reads nothing from
  LinkedIn" is gone.
- The store takes at most five screenshots; there are six. Drop one when uploading.
- A reviewer may ask why `tabs` and `scripting` are needed beyond `activeTab`: answered in the blocks above.

### Rejection History

None.
