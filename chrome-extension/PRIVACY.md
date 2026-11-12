# jobwatch for Chrome: privacy policy

**What it reads:** apart from passive mode below, only the tab where you click the jobwatch icon, and only after you press **Fill this application**
in the side panel that opens. The side panel itself shows only what the extension read from that tab.
It reads the form's questions, their answer options and the values already in the fields, the page's address, and the
company and job title shown on the page.

**LinkedIn and Indeed job lists:** only when you press **Import this list** on a LinkedIn or Indeed list of jobs (a
search, "Jobs based on your preferences", "Jobs for you"), it reads each job card on that list: the job's number on the
site, its title, company, place, pay and how long ago it was posted. It scrolls the list to its end and presses its
Next button (or opens its next page), at a human pace with random pauses of a few seconds, up to the number of pages
you set in the panel (4 by default, at most 10), and sends those cards to your own jobwatch. Nothing else on those
pages is read, and nothing is sent anywhere else.

**Passive mode (on by default; a checkbox in the side panel turns it off):** on LinkedIn and Indeed, a small script
runs in the pages you browse there. When the address is a list of jobs, it notes the job cards the page has already
drawn, with no scrolling, clicking or opening of anything by the extension: the same fields as above (the job's number
on the site, title, company, place, pay and how long ago it was posted), and nothing else from the page. It keeps them,
once per job, in the extension's storage in Chrome on this computer, up to 1000 jobs. They stay there and are sent
nowhere until you press **Import** in the side panel ("N jobs seen while browsing"); then they go to your own jobwatch,
the same as an imported list, and are deleted from the extension. With the checkbox off, the script reads nothing.
Removing the extension deletes what it kept.

**LinkedIn job pages:** apart from a list you import or passive mode's job cards, it reads nothing from LinkedIn's pages: no title, company,
description or page data. From a LinkedIn tab it takes only the address, for the job's number. When you press **Open the company's posting**, it presses
LinkedIn's Apply button (the one that opens the company's own site, never Easy Apply or anything that submits), and
then gives the address of the tab that opens, with the job's number, to your own jobwatch. For that it uses the `tabs`
permission, to see the address of that one new tab (opened within two minutes of the press) and of the active tab.
On a company's page, **Save this posting to jobwatch** sends your jobwatch the page's address and the job text the page
shows, only when you press it.

**What it receives, and writes into the form:** from your own jobwatch, your applicant details (name, email, phone,
address, links, work authorization, and the voluntary self-identification answers you have set there), your answers to
earlier applications, and the job's resume file. It writes the ones you tick into the form you are looking at, and
nothing else; the form's own site receives them only when you press its Submit button.

**Where what it reads goes:** only to your own jobwatch, which runs on your computer (`http://127.0.0.1`, or
`localhost`). The extension sends it the page's address, the text of a question you ask it to draft together with your
other written answers on that form (so a draft doesn't repeat them), and, after you submit an application, the
questions and answers on the form (not your name, contact details or voluntary self-identification answers), the
company and job title, and the name of the resume file; and the job cards of a list you import. What jobwatch does with a draft request, such as which language
model it asks, is set in jobwatch, not in the extension. The extension's authors run no server and receive nothing.

**What it stores:**
- **In Chrome, on this computer:** the server address and token you enter in the options page; the number of pages
  and the passive-mode choice you set in the panel; and the job cards passive mode noted, until you import them.
- **In the browser's session memory, until you close the tab or the browser:** the answers captured when you press
  Submit, until the application is recorded.

**What it doesn't do:** it never submits a form for you, has no analytics, no tracking, no advertising, no sale or
transfer of data, and no reading of any other site (passive mode runs only on linkedin.com and indeed.com).

Questions or issues: <https://github.com/vinayvobbili/jobwatch/issues>
