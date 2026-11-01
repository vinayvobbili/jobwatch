# jobwatch for Chrome: privacy policy

**What it reads:** only the tab where you click the jobwatch icon, and only after you press **Fill this application**
in the side panel that opens. The side panel itself shows only what the extension read from that tab.
It reads the form's questions, their answer options and the values already in the fields, the page's address, and the
company and job title shown on the page.

**LinkedIn:** it reads nothing from LinkedIn's pages: no title, company, description or page data. From a LinkedIn
tab it takes only the address, for the job's number. When you press **Open the company's posting**, it presses
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
company and job title, and the name of the resume file. What jobwatch does with a draft request, such as which language
model it asks, is set in jobwatch, not in the extension. The extension's authors run no server and receive nothing.

**What it stores:**
- **In Chrome, on this computer:** the server address and token you enter in the options page.
- **In the browser's session memory, until you close the tab or the browser:** the answers captured when you press
  Submit, until the application is recorded.

**What it doesn't do:** it never submits a form for you, has no analytics, no tracking, no advertising, no sale or
transfer of data, and no reading of any other tab or site.

Questions or issues: <https://github.com/vinayvobbili/jobwatch/issues>
