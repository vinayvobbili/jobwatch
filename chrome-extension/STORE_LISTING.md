# Chrome Web Store listing

Everything the [Developer Dashboard](https://chrome.google.com/webstore/devconsole)
asks for, in the order it asks. Build the upload and the images first:

```bash
python chrome-extension/tools/package.py        # dist/jobwatch-extension-<version>.zip
python chrome-extension/tools/store_assets.py   # dist/store/: screenshots, promo tiles, icon
```

## Package

Upload `dist/jobwatch-extension-<version>.zip`. The name and the short
description come from `manifest.json`.

## Store listing

**Description**

> Fill job applications from your own details and earlier answers, and review
> every field before it reaches the form. You press Submit yourself.
>
> jobwatch for Chrome is the browser half of jobwatch, a free, open-source job
> search tracker that runs on your own computer. Open an application, click the
> jobwatch icon, and Chrome's side panel shows what it can fill, each field
> marked with where the value came from, before anything is written.
>
> It needs the jobwatch app: install it (https://github.com/vinayvobbili/jobwatch)
> and run `jobwatch ui` on the same computer. Without it the extension does
> nothing.
>
> How it works
> • Click the jobwatch icon on an application page, then Fill this application.
> • Each field is a row with a badge: Your details (name, email, phone,
>   links, work authorization), Past answer (an answer you gave on an earlier
>   application, with the question and company it came from), Draft (written by
>   jobwatch for a question nothing matched, never filled until you tick it) or
>   Resume (the file jobwatch keeps for that job).
> • Edit any value, tick the rows you want, press Fill selected.
> • Read the form and submit it yourself. The extension never clicks Submit,
>   Next or any button that sends the form.
> • After you submit, jobwatch records the application and keeps your answers
>   for the next form.
>
> Works with
> • Greenhouse, Lever and Ashby application forms, including a Greenhouse form
>   embedded in a company's own page.
> • Other single-page application forms, on a best-effort basis.
> • Fields another tool (Chrome autofill, a password manager) already filled are
>   left alone.
>
> Privacy
> • It reads only the tab where you click the icon, and only when you press
>   Fill this application.
> • Page content and your answers go only to the jobwatch on your own computer
>   (127.0.0.1). The authors run no server and receive nothing.
> • A draft is written by the model you chose in jobwatch's settings: one on
>   your own computer, or a cloud API you set up with your own key.
> • No analytics, tracking or advertising.

- **Category:** Productivity › Workflow & Planning
- **Language:** English
- **Store icon:** `dist/store/icon128.png`
- **Screenshots** (1280×800), in this order: `dist/store/screenshot-1-review.png`,
  `screenshot-2-filled.png`, `screenshot-3-draft.png`, `screenshot-4-pairing.png`
- **Small promo tile:** `dist/store/promo-small.png` (440×280)
- **Marquee promo tile** (optional; shown only if the store features the item):
  `dist/store/promo-marquee.png` (1400×560)
- **Global promo video:** none
- **Homepage URL:** https://github.com/vinayvobbili/jobwatch
- **Support URL:** https://github.com/vinayvobbili/jobwatch/issues
- **Mature content:** No

All data in the images is made up (the demo server's Jordan Rivera and Initech).

## Privacy practices

**Single purpose**

> Fill job application forms with the user's details and earlier answers kept
> by their own local jobwatch app, after the user reviews each field.

**Permission justifications**

| Permission | Justification |
|---|---|
| `activeTab` | Reads the application form's questions, and fills the ticked fields, only on the tab where the user clicked the extension's icon. |
| `scripting` | Injects the script that finds the form's fields and writes the ticked values into that tab. It runs only after the user clicks the icon and presses Fill this application. |
| `storage` | Saves the jobwatch address and the pairing token the user enters on the options page, and keeps an answer the user just submitted until jobwatch has recorded it. |
| `sidePanel` | Shows the review (each field, where its value came from, and the Fill selected button) in Chrome's side panel beside the form, so it never covers the page. |
| Host permission `http://127.0.0.1/*` | The extension's only network access: the jobwatch app the user runs on their own computer (default `http://127.0.0.1:8765`) supplies the user's details, earlier answers and resume, drafts answers, and records the application. |
| Host permission `http://localhost/*` | Same, for a user whose jobwatch address is written as `localhost` instead of `127.0.0.1`. |

No other host permissions are requested; the extension cannot read any website
except the active tab after the user clicks its icon.

**Remote code:** No, I am not using remote code. All JavaScript ships in the
package. jobwatch returns JSON data and a resume file only.

**Data usage.** Tick **Personally identifiable information** and **Website
content**. Leave every other type unticked.

- **Personally identifiable information:** ticked. The extension handles the
  user's name, email address, phone number, address and the other applicant
  details in their jobwatch: it receives them from jobwatch and writes them into
  the form. The answers it sends back to jobwatch after a submit can also
  contain such details. All of it stays between the page and the jobwatch on
  the user's own computer; the developer receives none of it. It is ticked
  because the item handles it, which is the cautious reading of "collects or
  transmits".
- **Website content:** ticked. It reads the form's questions, answer options,
  current field values, the page address, and the company and job title shown
  on the page, and sends them to the local jobwatch to find earlier answers,
  draft an answer and record the application.
- Not ticked:
  - health information: the voluntary self-identification answers (including
    disability status) are chosen by the user in jobwatch (default "decline") and
    only written into the form; they are never sent back to jobwatch or anywhere
    else;
  - financial and payment information;
  - authentication information: the pairing token is the user's own credential
    for their own jobwatch, stored locally, and never collected by the developer;
  - personal communications;
  - location: the city and state in the user's details are an address for the
    form, not the device's location;
  - web history: only the active tab's address is read, after the user clicks;
  - user activity: no clicks, keystrokes or mouse movement are recorded. After a
    scan it only notices that the form was submitted, so it can tell jobwatch.

Certify all three:
- I do not sell or transfer user data to third parties, outside of the approved
  use cases.
- I do not use or transfer user data for purposes that are unrelated to my
  item's single purpose.
- I do not use or transfer user data to determine creditworthiness or for
  lending purposes.

**Privacy policy URL:**
https://github.com/vinayvobbili/jobwatch/blob/main/chrome-extension/PRIVACY.md

It covers each of the answers above: what the extension reads, what it receives
from jobwatch and writes into the form, what it sends to jobwatch, what it
stores, and that the authors run no server.

## Distribution

- **Payment:** Free.
- **Visibility:** choose one:
  - **Public:** anyone can find it;
  - **Unlisted:** only people with the link can find it;
  - **Private:** limited to a Google Workspace domain or named testers.
- **Regions:** All regions.

## Account (one-time)

Already done for attestq, which uses the same developer account: the one-off
US$5 fee, 2-Step Verification, the verified contact email, the trader /
non-trader declaration and the publisher name. Nothing to repeat.

The first review usually takes from a few days to a couple of weeks. A reviewer
cannot use the item without the jobwatch app, so if the review asks how to try
it, point to the README's setup steps and the demo forms in `chrome-extension/demo/`.
