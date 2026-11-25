# jobwatch for Chrome: privacy policy

**What it reads:** apart from passive mode below, only the tab where you click the jobwatch icon, and only after you press **Fill this application**
in the side panel that opens. The side panel itself shows only what the extension read from that tab.
It reads the form's questions, their answer options and the values already in the fields, the page's address, and the
company and job title shown on the page.

**LinkedIn and Indeed job lists:** only when you press **Read the jobs on this list** on a LinkedIn or Indeed list of jobs (a
search, "Jobs based on your preferences", "Jobs for you"), it reads each job card on that list: the job's number on the
site, its title, company, place, pay and how long ago it was posted. It scrolls the list to its end and presses its
Next button (or opens its next page), at a human pace with random pauses of a few seconds, up to the number of pages
you set in the panel (4 by default, at most 10), and sends those cards to your own jobwatch. Nothing else on those
pages is read, and nothing is sent anywhere else.

**Passive mode (off by default; you turn it on with a checkbox in the side panel):** on LinkedIn and Indeed, a small script
runs in the pages you browse there. When the address is a list of jobs, it notes the job cards the page has already
drawn, with no scrolling, clicking or opening of anything by the extension: the same fields as above (the job's number
on the site, title, company, place, pay and how long ago it was posted), and nothing else from the page. It keeps them,
once per job, in the extension's storage in Chrome on this computer, up to 1000 jobs. They stay there and are sent
nowhere until you press **Import** in the side panel ("N jobs seen while browsing"); then they go to your own jobwatch,
the same as an imported list, and are deleted from the extension. With the checkbox off (the default), the script reads and stores nothing.
Removing the extension deletes what it kept.

**LinkedIn job pages:** apart from a list you import, passive mode's job cards, a job page jobwatch's Read posting button opened (next paragraphs), or the one conversation you ask a reply for (below), it reads nothing from LinkedIn's pages: no title, company,
description or page data. From a LinkedIn tab it takes only the address, for the job's number. When you press **Open the company's posting**, it presses
LinkedIn's Apply button (the one that opens the company's own site, never Easy Apply or anything that submits), and
then gives the address of the tab that opens, with the job's number, to your own jobwatch. For that it uses the `tabs`
permission, to see the address of that one new tab (opened within two minutes of the press) and of the active tab.
On a company's page, **Save this posting to jobwatch** sends your jobwatch the page's address and the job text the page
shows, only when you press it.

**Read posting (LinkedIn and Indeed job pages):** a job jobwatch has from an alert email has no posting text, and those two
sites show a posting only to a signed-in browser. When you press **Read posting** on a job's card in your own jobwatch, jobwatch
opens that job's page in a new tab with `#jobwatch-read` added to its address. The extension reads a LinkedIn or Indeed page
only when its address ends that way, which only that button adds (on every other page of those sites the script does nothing).
On that page it reads the job's description (its text, without the rest of the page), the job's title and company as the
page shows them, and whether the site says the posting is closed (LinkedIn's "no longer accepting applications", Indeed's "expired"). It gives them, with the job's number from the
address, to your own jobwatch, shows a small banner on the page, and closes the tab. Nothing else on the page is read, nothing
is kept by the extension, and it never clicks anything. If the page asks you to sign in or shows a captcha, the banner says so and
nothing is sent.

**LinkedIn messages (Draft reply):** only when you press **Draft reply to this conversation** in the side panel, on a
LinkedIn conversation you have open, it reads that one conversation as it is on the screen: the other person's name as the
page shows it, and the text and times of the messages that are already there. It does not scroll, open another conversation,
read your message list, profiles or anything else on LinkedIn, and it keeps nothing: the text goes to your own jobwatch, which
writes a reply from it. The side panel shows the draft, jobwatch's warnings and what to check, and says whether the draft
was written on your computer. Only when you then press **Put in the message box** does the extension type the draft into
that conversation's message box (it asks first if the box already has text). It never presses Send, or any other button
on LinkedIn: you read it and send it yourself. By default jobwatch writes the reply with its model on your computer, and the
conversation goes nowhere else. If you turn on `reply: {backend: chat}` in jobwatch's watchlist, jobwatch asks its chat
model instead, and with the chat set to Claude the conversation (with your resume text and your tracked notes for that
company) is sent to Anthropic by jobwatch, not by the extension; the side panel then says the thread was sent off your
computer. That is a setting in jobwatch, off by default.

**ATS check and Cover letter:** only when you press **ATS check** or **Cover letter** in the side panel, on a job's page. The
extension sends your own jobwatch the page's address and the company and job title the page shows (taken from the page's
own title and headings, the same two values it already reads when you press Fill this application; on LinkedIn and Indeed
pages it sends only the address), so jobwatch can tell which job you mean.
jobwatch checks the job's resume against the posting's keywords on your computer, or has its model on your computer draft
a letter from the posting, your resume and your stories, and keeps the letter with the job. If you turn on
`reply: {backend: chat}` in jobwatch's watchlist, the chat model writes the letter instead, and the panel says so. To offer
**Fill the cover letter box**, the extension looks at the page's form fields for one labelled as a cover letter, and keeps
nothing; only whether such a box exists, and whether it is empty, leaves the page, and that goes only to the side panel. Only when you press **Fill the cover letter box**
does it type the letter into that box, if it is empty (replacing text is a separate press), and it never presses Submit or any
other button.

**What it receives, and writes into the form:** from your own jobwatch, your applicant details (name, email, phone,
address, links, work authorization, and the voluntary self-identification answers you have set there), your answers to
earlier applications, and the job's resume file. It writes the ones you tick into the form you are looking at, and
nothing else; the form's own site receives them only when you press its Submit button.

**Where what it reads goes:** only to your own jobwatch, which runs on your computer (`http://127.0.0.1`, or
`localhost`). The extension sends it the page's address, the text of a question you ask it to draft together with your
other written answers on that form (so a draft doesn't repeat them), and, when you press the form's Submit, the
questions and answers on the form as they stood (not your name, contact details or voluntary self-identification
answers), which jobwatch keeps in that job's application package; once the page shows it went through, also the
company and job title and the name of the resume file, so the application is recorded; and the job cards of a list you import; and, when you press Draft reply, the text of the open LinkedIn conversation and the other person's name; and, when you press Fill this application, ATS check or Cover letter, the company and job title the page shows (so jobwatch can tell which of your jobs the page is). What jobwatch does with a draft request, such as which language
model it asks, is set in jobwatch, not in the extension. The extension's authors run no server and receive nothing.

**What it stores:**
- **In Chrome, on this computer:** the server address and token you enter in the options page; the number of pages
  and the passive-mode choice you set in the panel; and the job cards passive mode noted, until you import them.
- **In the browser's session memory, until you close the tab or the browser:** the answers captured when you press
  Submit, until the application is recorded (they have already been sent to your own jobwatch by then).

**What it doesn't do:** it never submits a form for you, has no analytics, no tracking, no advertising, no sale or
transfer of data, and no reading of any other site (passive mode runs only on linkedin.com and indeed.com).

Questions or issues: <https://github.com/vinayvobbili/jobwatch/issues>
