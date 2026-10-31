# jobwatch for Chrome: application filler

Fill the basics with Simplify or Chrome autofill, then jobwatch fills the rest.

The extension does what those tools don't, because it works with your jobwatch:

- **It reuses your earlier answers.** Every form question you answered on a past application is kept by jobwatch.
  On a new form, the extension finds the question that reads most like each one, shows you which earlier question it
  matched (and the company and date), and puts the answer in a box you can edit. Notice period, why this kind of
  role, a time you handled an incident: write it once.
- **It drafts the new ones.** A question nothing matches gets a **Draft with jobwatch** button. The draft comes from
  your resume, your stories and the posting, and it is never filled until you tick it.
- **It attaches the job's resume.** The one saved with that job's application package, or your default.
- **It records the application when you submit.** After you press Submit and the page shows it went through,
  jobwatch marks the job applied and keeps the answers you gave, ready for the next form.

It fills only what is still empty. A field Simplify, Chrome or a password manager already filled starts unticked and
marked "already filled". The basics (name, email, phone, links, work authorization, the voluntary
self-identification questions) come from the applicant details in jobwatch's Settings, as a fallback for what is left.

It never clicks Submit, Next or any button that sends the form. You review the panel, press **Fill selected**, read
the form, and submit it yourself.

## Set it up

1. Run `jobwatch ui` and open Settings, Browser extension. Copy the token.
2. In Chrome, open the extension's options (right-click its icon, Options) and paste the token. The server address is
   `http://127.0.0.1:8765` unless you started `jobwatch ui --port` differently. Press **Test**.
3. Open a job application, click the extension's icon, then **Fill this application**.

Without jobwatch running, the icon says so and does nothing else. The extension has no standalone mode.

## What you see

A panel opens on the right of the page. Each field of the form is a row:

| Badge | Meaning |
|---|---|
| Your details | From the applicant details in jobwatch. Ticked when the match is certain, except salary, which you tick yourself. |
| Past answer | From an earlier application. Ticked only when the old question reads almost the same; otherwise it is offered, not ticked. |
| Draft | Written by jobwatch on your request. Never ticked for you. |
| Resume | The file jobwatch has for this job. |
| Not found | Nothing to fill. Type an answer, or press Draft. |

For a dropdown or a group of radio buttons the row shows the option it will pick. Edit any value, tick the rows you
want, press **Fill selected**.

Works on Greenhouse (job-boards.greenhouse.io, boards.greenhouse.io and the form embedded in a company's own page),
Lever and Ashby, and tries its best on other single-page forms. Workday is not supported yet.

## Privacy

Nothing leaves your computer except to jobwatch, which runs on it. See [PRIVACY.md](PRIVACY.md).

## For developers

```
manifest.json       Manifest V3: activeTab, scripting, storage, and http://127.0.0.1 / localhost
background.js       service worker; the only code that talks to jobwatch (API.md); keeps pending submissions per tab
logic.js            classification, matching, option picking, the review plan; no DOM, tested with node
page.js             content script per frame: scan, fill, read company and title, watch for the person's submit
panel.js            the side panel (shadow DOM), top frame only
popup.*, options.*  the toolbar popup and the options page (server, token, theme and width)
demo/               fixture forms imitating Greenhouse, Lever and Ashby, and a generic one
tools/              make_icons.py, package.py (store zip), fake_server.py (API.md stand-in), harness.py (Playwright),
                    live_check.py (what the extension makes of a real form; reads only, never fills or submits)
API.md              the contract with jobwatch's local server
```

There is no build step and no dependency. Load it with chrome://extensions, Developer mode, Load unpacked.

Tests, from the repo root:

```
pip install -e ".[dev,browser]" && playwright install chromium
python -m pytest tests/test_extension_*.py -q
```

The end-to-end test loads the extension into Chromium, serves the demo forms under the addresses of the boards they
imitate, and runs a fake jobwatch. It skips when Playwright or Chromium is missing.

To see how a real board's form reads, `python chrome-extension/tools/live_check.py <application link>` prints one
line per field: what it is, where its value would come from, and whether it starts ticked. It fills nothing.

Add a system by adding an entry to `ADAPTERS` in `page.js` (how to match its host, where its field labels sit, how to
read the job title and company) and a fixture in `demo/`. Anything custom about filling goes in `fillOne`. Workday
would be the next one.

Store zip: `python chrome-extension/tools/package.py` writes `dist/jobwatch-extension-<version>.zip`. It refuses to
build when the manifest version differs from the jobwatch package's.

Parts of the React handling in `page.js` follow two open-source autofill extensions; see
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).
