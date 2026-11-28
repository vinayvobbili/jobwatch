"""The browser extension's thinking (chrome-extension/logic.js), run with node like the page's own script is."""
# ruff: noqa: E501  (the cases are tables of form text)

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def run_js(tmp_path, body: str):
    """Run `body` with `JW` (the extension's logic) in scope; it prints one JSON value."""
    js = tmp_path / "case.js"
    js.write_text(f"const JW = require({json.dumps(str(EXT / 'logic.js'))});\n{body}", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_every_script_parses():
    """A syntax error in a content script gives a panel that never opens, with no test failing elsewhere."""
    for name in ("logic.js", "page.js", "sidepanel.js", "background.js", "lib.js", "options.js", "look.js", "job-lists.js", "passive.js", "read-posting.js", "page-bridge.js", "reply.js", "auto-read.js", "auto-reader.js"):
        r = subprocess.run(["node", "--check", str(EXT / name)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_the_manifest_asks_for_little():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    # "tabs" only to see the address of the tab LinkedIn's Apply button opens (background.js, openCompany), and which tab
    # the person is on for auto-read; "alarms" and "idle" only for reading postings by itself (auto-reader.js): the pause
    # between two reads must survive the service worker stopping, and nothing is read while the person is busy on LinkedIn
    assert sorted(manifest["permissions"]) == ["activeTab", "alarms", "idle", "scripting", "sidePanel", "storage", "tabs"]
    assert sorted(manifest["host_permissions"]) == ["http://127.0.0.1/*", "http://localhost/*"]
    # the only things that run unprompted, on the two job sites and nowhere else: passive mode's card note-taker (off
    # unless ticked) and read-posting.js, which reads only a page whose address jobwatch's Read posting button added
    # #jobwatch-read to
    # and page-bridge.js on local addresses only (the ones the extension already has host access to): it passes jobwatch's
    # own page's Read posting request to the service worker, which refuses any page but the paired jobwatch
    assert [(c["matches"], c["js"]) for c in manifest["content_scripts"]] == [
        (["https://www.linkedin.com/*", "https://*.indeed.com/*"],
         ["logic.js", "job-lists.js", "passive.js", "read-posting.js"]),
        (["http://localhost/*", "http://*.localhost/*", "http://127.0.0.1/*"], ["page-bridge.js"])]
    # Ladders lists are read with activeTab (the icon click on that tab), like any other site: no host of its own
    assert "theladders" not in json.dumps(manifest)
    assert "default_popup" not in manifest["action"]  # the toolbar button opens the side panel instead
    for name in (manifest["background"]["service_worker"], manifest["side_panel"]["default_path"],
                 manifest["options_page"], *manifest["icons"].values()):
        assert (EXT / name).is_file(), name


@needs_node
def test_questions_are_told_apart(tmp_path):
    questions = {
        "First Name *": "first_name", "Last name": "last_name", "Preferred first name": "preferred_name",
        "Full name": "full_name", "Email address": "email", "E-mail": "email", "Mobile phone": "phone",
        "LinkedIn Profile": "linkedin", "GitHub URL": "github", "Link to portfolio": "website",
        "Zip code": "postal_code", "Country": "country", "State / Province": "state", "City": "city",
        "Current location": "location", "Where are you currently located?": "location",
        "What's the name you'd prefer us to use throughout the interview process?": "preferred_name",
        "Are you legally authorized to work in the United States?": "work_authorized",
        "Are you authorized to work in the US without sponsorship?": "work_authorized",
        "Will you now or in the future require visa sponsorship?": "needs_sponsorship",
        "Do you need sponsorship?": "needs_sponsorship",
        "Are you open to relocating?": "relocate",
        "What is your notice period?": "notice_period", "When can you start?": "notice_period",
        "Desired salary": "salary", "Salary expectations": "salary",
        "Gender": "gender", "Are you Hispanic/Latino?": "hispanic", "Race": "race", "Veteran Status": "veteran",
        "Disability Status": "disability",
        "Preferred pronouns": None, "Why do you want to work here?": None, "Company name": None,
        "How did you hear about this job?": None, "Cover letter": None,
    }
    got = run_js(tmp_path, f"const q = {json.dumps(list(questions))};"
                           "console.log(JSON.stringify(Object.fromEntries(q.map(t => [t, JW.classify(t)]))));")
    assert got == questions


@needs_node
def test_a_long_question_is_free_text_even_when_it_mentions_a_keyword(tmp_path):
    long = ("Describe your experience working with teams in different cities and how you would handle a disagreement "
            "about the location of a new office, the salary bands and the notice we give people.")
    got = run_js(tmp_path, f"""
const f = (question, kind, hint = '', type = '') => JW.classifyField({{ question, kind, hint, type, autocomplete: '' }});
console.log(JSON.stringify([f({json.dumps(long)}, 'text'), f('Tell us about your salary history in detail please', 'textarea'),
  f('', 'text', 'candidate location'), f('', 'text', 'x', 'email'), f('Your phone', 'text')]));""")
    assert got == [{"key": None, "sure": False}, {"key": None, "sure": False},
                   {"key": "location", "sure": False}, {"key": "email", "sure": True}, {"key": "phone", "sure": True}]


@needs_node
def test_values_come_from_the_applicants_details(tmp_path):
    got = run_js(tmp_path, """
const d = { first_name: 'Jordan', last_name: 'Rivera', city: 'Boulder', state: 'CO', work_authorized: 'yes',
  needs_sponsorship: 'no', gender: 'decline', salary: '180K-190K', phone: '' };
console.log(JSON.stringify(['full_name', 'location', 'work_authorized', 'needs_sponsorship', 'gender', 'salary', 'phone']
  .map(k => JW.valueFor(k, d))));""")
    assert got == ["Jordan Rivera", "Boulder, CO", "Yes", "No", "Decline to answer", "180K-190K", ""]


@needs_node
def test_the_option_that_says_it_is_picked(tmp_path):
    cases = [
        ["Yes", ["Select...", "Yes", "No"]], ["No", ["Yes, I am", "No, I am not"]],
        ["Yes", ["Not applicable", "No"]],  # "Not" is not "No", and there is no yes
        ["Decline to answer", ["Male", "Female", "Decline To Self Identify"]],
        ["Decline to answer", ["I am a veteran", "I don't wish to answer"]],
        ["Decline to answer", ["Yes, I have a disability", "No, I do not have a disability", "I do not want to answer"]],
        ["Decline to answer", ["Man", "Woman", "Prefer not to say"]],
        ["Decline to answer", ["Man", "Woman"]],
        ["United States", ["Canada", "United States of America"]], ["CO", ["Choose...", "Colorado", "Texas"]],
        ["Colorado", ["CO", "TX"]], ["Boulder, CO", ["Denver, CO", "Boulder, CO"]], ["Male", ["Female", "Male"]],
        ["Remote", ["Onsite", "Hybrid"]],
    ]
    got = run_js(tmp_path, f"const c = {json.dumps(cases)};console.log(JSON.stringify(c.map(([v, o]) => JW.optionIndex(v, o))));")
    assert got == [1, 1, -1, 2, 1, 2, 2, -1, 1, 1, 0, 1, 1, -1]


@needs_node
def test_a_past_answer_is_matched_by_its_question(tmp_path):
    answers = [
        {"question": "Why do you want to work at Globex?", "answer": "Small teams that own what they run.", "company": "Globex"},
        {"question": "Notice period?", "answer": "Two weeks."},
        {"question": "Describe a time you handled a production incident.", "answer": "I rolled back."},
        {"question": "Empty one", "answer": "  "},
    ]
    asks = ["What is your notice period?", "Why do you want to work at Initech?", "Why do you want to work at Initech",
            "Describe a time you handled a production incident", "What is your favorite color?", "How are you?"]
    got = run_js(tmp_path, f"""
const a = {json.dumps(answers)};
console.log(JSON.stringify({json.dumps(asks)}.map(q => {{ const m = JW.matchPastAnswer(q, a);
  return m ? [m.question, Math.round(m.score * 100)] : null; }})));""")
    assert got[0] == ["Notice period?", 100]
    assert got[1][0] == "Why do you want to work at Globex?" and 60 <= got[1][1] < 85  # a different company: offered, not ticked
    assert got[3] == ["Describe a time you handled a production incident.", 100]
    assert got[4] is None and got[5] is None


@needs_node
def test_the_review_rows_tick_only_what_is_sure(tmp_path):
    fields = [
        {"id": "1", "kind": "text", "question": "First name", "hint": "", "type": "text", "autocomplete": ""},
        {"id": "2", "kind": "text", "question": "Last name", "hint": "", "type": "text", "autocomplete": "", "filled": True,
         "current": "Rivera"},
        {"id": "3", "kind": "text", "question": "", "weak": True, "hint": "candidate location", "type": "text", "autocomplete": ""},
        {"id": "4", "kind": "textarea", "question": "Why do you want to work at Initech?", "hint": "", "type": "", "autocomplete": ""},
        {"id": "5", "kind": "textarea", "question": "Describe a time you handled a production incident.", "hint": "", "type": "", "autocomplete": ""},
        {"id": "6", "kind": "select", "question": "Gender", "hint": "", "type": "", "autocomplete": "", "options": ["Select...", "Male", "Decline"]},
        {"id": "7", "kind": "radio", "question": "Do you need visa sponsorship?", "hint": "", "type": "", "autocomplete": "", "options": ["Maybe"]},
        {"id": "8", "kind": "file", "question": "Resume/CV", "hint": "resume", "type": "file", "autocomplete": ""},
        {"id": "9", "kind": "file", "question": "Cover letter", "hint": "", "type": "file", "autocomplete": ""},
        {"id": "10", "kind": "text", "question": "Pet's name", "hint": "", "type": "text", "autocomplete": ""},
        {"id": "11", "kind": "text", "question": "Desired salary", "hint": "", "type": "text", "autocomplete": ""},
    ]
    details = {"first_name": "Jordan", "last_name": "Rivera", "city": "Boulder", "state": "CO", "needs_sponsorship": "no",
               "gender": "decline", "salary": "180000"}
    answers = [{"question": "Why do you want to work at Globex?", "answer": "Small teams.", "company": "Globex"},
               {"question": "Describe a time you handled a production incident.", "answer": "I rolled back."}]
    rows = run_js(tmp_path, f"""
const rows = JW.buildPlan({json.dumps(fields)}, {json.dumps(details)}, {json.dumps(answers)}, {{ resume: 'resume.pdf' }});
console.log(JSON.stringify(rows.map(r => [r.id, r.source, r.value, r.checked])));""")
    assert rows == [
        ["1", "details", "Jordan", True],
        ["2", "details", "Rivera", False],                      # the page already has it: left alone
        ["3", "details", "Boulder, CO", False],                 # a guess from the field's name
        ["4", "past", "Small teams.", False],                   # another company's question: offered, unticked
        ["5", "past", "I rolled back.", True],                  # the same question: ticked
        ["6", "details", "Decline to answer", True],
        ["7", "none", "", False],                               # no option says "No": not found, not forced
        ["8", "resume", "resume.pdf", True],
        ["9", "none", "", False],
        ["10", "none", "", False],
        ["11", "details", "180000", False],                     # pay: offered, never ticked for you
    ]


@needs_node
def test_a_finished_submission_reads_as_one(tmp_path):
    got = run_js(tmp_path, """
const done = ['Thank you for applying!', 'Application submitted! Thanks for applying to Initech.',
  'We have received your application for Platform Engineer.', "We've received your application.",
  'Your application has been successfully submitted.'];
const not = ['Apply for this job', 'Submit application', 'This field is required', 'Upload your resume'];
const labels = ['Submit', 'Submit application', 'Apply now', 'Next', 'Back', 'Add another', 'Upload resume'];
console.log(JSON.stringify([done.map(JW.looksSubmitted), not.map(JW.looksSubmitted), labels.map(JW.isSubmitLabel)]));""")
    assert got == [[True] * 5, [False] * 4, [True, True, True, False, False, False, False]]


@needs_node
def test_a_one_line_box_gets_spaces_for_line_breaks(tmp_path):
    """Ashby asks long questions in one-line boxes, which drop line breaks: "the first.The second" otherwise."""
    got = run_js(tmp_path, r"console.log(JSON.stringify(JW.oneLine('I build guardrails.\n\nThe tools are tagged. \r\n Done.\n')));")
    assert got == "I build guardrails. The tools are tagged. Done."


@needs_node
def test_who_you_are_is_not_kept_as_an_answer(tmp_path):
    """The recorded application keeps answers to questions, not who the person is or the voluntary ones."""
    got = run_js(tmp_path, "console.log(JSON.stringify(['email', 'gender', 'full_name', 'salary', 'notice_period'].map(k => JW.IDENTITY.has(k))));")
    assert got == [True, True, True, False, False]


@needs_node
def test_linkedin_addresses_and_what_the_posting_action_does_on_them(tmp_path):
    urls = {
        "https://www.linkedin.com/jobs/view/3900000123/": ("3900000123", "linkedin"),
        "https://www.linkedin.com/jobs/view/platform-engineer-at-initech-3900000123": ("3900000123", "linkedin"),
        "https://www.linkedin.com/jobs/search/?keywords=sre&currentJobId=3900000777": ("3900000777", "linkedin"),
        "https://www.linkedin.com/jobs/search/?currentJobId=abc": ("", "linkedin-none"),
        "https://www.linkedin.com/feed/": ("", "linkedin-none"),
        "https://jobs.lever.co/globex/aaaa-1111": ("", "site"),
        "http://127.0.0.1:8765/": ("", "none"),
        "chrome://extensions": ("", "none"),
        "": ("", "none"),
    }
    got = run_js(tmp_path, f"const urls = {json.dumps(list(urls))};\nconsole.log(JSON.stringify(urls.map(u => [JW.linkedinJobId(u), JW.postingMode(u)])));")
    assert got == [list(v) for v in urls.values()]


@needs_node
def test_the_job_lists_import_this_list_reads(tmp_path):
    urls = {
        "https://www.linkedin.com/jobs/collections/recommended/": "linkedin",
        "https://www.linkedin.com/jobs/search/?keywords=sre&currentJobId=3900000777": "linkedin",
        "https://www.linkedin.com/jobs/": "linkedin",
        "https://www.linkedin.com/jobs/view/3900000123/": "",
        "https://www.linkedin.com/feed/": "",
        "https://www.indeed.com/": "indeed",
        "https://www.indeed.com/jobs?q=engineer&l=Boulder%2C+CO": "indeed",
        "https://www.indeed.com/q-engineer-jobs.html": "indeed",
        "https://www.indeed.com/viewjob?jk=a1b2c3d4e5f60001": "",
        "https://www.theladders.com/recommended": "ladders",
        "https://www.theladders.com/recommended?page=2": "ladders",
        "https://www.theladders.com/jobs/search-jobs?title=engineer&location=Boulder%2C%20CO": "ladders",
        "https://theladders.com/jobs/engineer-jobs": "ladders",
        "https://www.theladders.com/job/staff-platform-engineer-initech-virtual-travel_90000001": "",
        "https://www.theladders.com/": "",
        "https://www.theladders.com/career-advice/resume": "",
        "https://www.notheladders.com/recommended": "",
        "https://jobs.lever.co/globex/aaaa-1111": "",
        "": "",
    }
    got = run_js(tmp_path, f"const urls = {json.dumps(list(urls))};\nconsole.log(JSON.stringify(urls.map(u => JW.listMode(u))));")
    assert got == list(urls.values())


@needs_node
def test_a_ladders_list_needs_a_jobwatch_that_keeps_its_pages_as_references(tmp_path):
    cases = [("linkedin", ["import-list"]), ("indeed", ["import-list"]), ("ladders", ["import-list"]),
             ("ladders", ["import-list", "list-ladders"]), ("ladders", ["list-ladders"]), ("linkedin", []), ("ladders", None)]
    got = run_js(tmp_path, f"console.log(JSON.stringify({json.dumps(cases)}.map(([s, f]) => JW.listSupported(s, f))));")
    assert got == [True, True, False, True, False, False, False]


@needs_node
def test_draft_reply_is_offered_on_linkedin_only(tmp_path):
    urls = {
        "https://www.linkedin.com/messaging/thread/2-abc123/": "messaging",
        "https://www.linkedin.com/messaging/": "messaging",
        "https://www.linkedin.com/feed/": "linkedin",  # a message bubble can be open on any LinkedIn page
        "https://www.linkedin.com/jobs/view/4101001/": "linkedin",
        "https://www.indeed.com/jobs?q=engineer": "",
        "https://example.com/messaging/": "",
        "https://notlinkedin.com/messaging/": "",
        "chrome://extensions": "",
        "": "",
    }
    got = run_js(tmp_path, f"const urls = {json.dumps(list(urls))};\nconsole.log(JSON.stringify(urls.map(u => JW.replyMode(u))));")
    assert got == list(urls.values())


@needs_node
def test_a_conversation_becomes_the_text_the_reply_call_takes(tmp_path):
    got = run_js(tmp_path, """
const messages = [
  { sender: 'Dana Whitfield', when: 'Nov 12, 9:41 AM', text: "Hi Jordan,\\n\\n\\n\\nI'm hiring.  " },
  { sender: 'Jordan Rivera', when: '', text: 'Thanks.' },
  { sender: 'Dana Whitfield', when: 'Nov 12, 11:02 AM', text: '   ' },
  { sender: '', when: '', text: 'No name on this one' },
];
const long = Array.from({ length: 10 }, (_, i) => ({ sender: 'Dana', when: `Nov ${i + 1}`, text: 'x'.repeat(100) + i }));
const cut = JW.formatThread(long, 400);
console.log(JSON.stringify({
  text: JW.formatThread(messages), none: JW.formatThread([]), nothing: JW.formatThread(null),
  cutBlocks: cut.split('\\n\\n').length, cutKeepsNewest: cut.endsWith('x9'), cutKeepsOldest: cut.includes('Nov 1\\n'),
  cutWhole: cut.split('\\n\\n').every((b) => /^Dana, Nov \\d+\\n/.test(b)),
}));""")
    assert got == {
        "text": "Dana Whitfield, Nov 12, 9:41 AM\nHi Jordan,\n\nI'm hiring.\n\nJordan Rivera\nThanks.\n\nUnknown\nNo name on this one",
        "none": "", "nothing": "", "cutBlocks": 3, "cutKeepsNewest": True, "cutKeepsOldest": False, "cutWhole": True,
    }


@needs_node
def test_the_frame_whose_thread_was_read_is_the_one_used(tmp_path):
    """read() and fill() run in every frame of the tab; a thread in a frame is found even though the top page has none."""
    got = run_js(tmp_path, """
const none = { ok: false, none: true, error: 'No conversation is open. (The page showed 0 editable boxes, 0 messages.)' };
const thread = { ok: true, thread: 'Dana, Nov 12\\nHi', count: 1 };
const many = { ok: false, none: false, error: 'More than one conversation is open here.' };
console.log(JSON.stringify({
  inFrame: JW.pickRead([none, null, thread]).thread,
  topFirst: JW.pickRead([{ ...thread, thread: 'top' }, thread]).thread,
  complaint: JW.pickRead([none, many]).error,
  noneInOne: JW.pickRead([none]).error,
  noneInThree: JW.pickRead([none, none, null]).error,
  nothing: JW.pickRead([null]).error,
  fillFrame: JW.pickFill([{ filled: false, reason: 'gone' }, { filled: true }]),
  refusal: JW.pickFill([{ filled: false, reason: 'gone' }, { filled: false, reason: 'has-text' }]).reason,
  noFill: JW.pickFill([]).reason,
}));""")
    assert got["inFrame"] == "Dana, Nov 12\nHi" and got["topFirst"] == "top"
    assert got["complaint"].startswith("More than one")
    assert got["noneInOne"].endswith("0 messages.)") and got["noneInThree"].endswith("(2 frames looked at.)")
    assert got["nothing"] == "Reload this page, then try again."
    assert got["fillFrame"] == {"filled": True} and got["refusal"] == "has-text" and got["noFill"] == "gone"


def test_the_reply_script_cannot_press_send():
    """reply.js reads one conversation and types into its box. It has no way to click, submit or press Enter, and it
    never scrolls or opens another conversation."""
    code = "\n".join(line.split("//")[0] for line in (EXT / "reply.js").read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith(("*", "/*")))
    for forbidden in (".click(", "requestSubmit", ".submit(", "MouseEvent", "KeyboardEvent", "scrollTo", "scrollIntoView", "scrollTop", "fetch(", "XMLHttpRequest", "sendMessage"):
        assert forbidden not in code, forbidden
    # and it is only ever injected by the button: not a content script
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert all("reply.js" not in c["js"] for c in manifest["content_scripts"])


@needs_node
def test_a_thread_fingerprint_changes_when_the_conversation_does(tmp_path):
    got = run_js(tmp_path, """
const a = 'Dana, Nov 12\\nHello', b = 'Dana, Nov 12\\nHello\\n\\nDana, Nov 12\\nAnd one more';
console.log(JSON.stringify([JW.fingerprint(a) === JW.fingerprint(a), JW.fingerprint(a) === JW.fingerprint(b), JW.fingerprint(''), typeof JW.fingerprint(null)]));""")
    assert got[:2] == [True, False] and got[2].startswith("0:") and got[3] == "string"


@needs_node
def test_the_cover_letter_box_is_a_textarea_asked_for_one(tmp_path):
    """Only a textarea is a place for a letter: a one-line box ("Cover letter link") isn't, and a file input is only
    reported, never filled."""
    got = run_js(tmp_path, """
const f = (kind, question, extra = {}) => ({ id: question, kind, question, hint: '', filled: false, ...extra });
const cases = [
  [f('textarea', 'Cover Letter')],
  [f('text', 'Name'), f('textarea', 'Anything else?'), f('textarea', 'Why do you want to work here? (cover letter)', { filled: true }), f('textarea', "Cover letter or note")],
  [f('textarea', 'Letter of interest')],
  [f('text', 'Cover letter link'), f('file', 'Resume')],
  [f('file', 'Cover letter'), f('file', 'Resume')],
  [f('file', 'Resume/CV'), f('textarea', 'Describe a project')],
  [f('textarea', 'Cover letter', { hint: '' }), f('file', 'Cover letter')],
  [], null,
];
console.log(JSON.stringify(cases.map(c => { const r = JW.coverField(c); return r && (r.field ? r.field.question : 'file'); })));""")
    assert got == ["Cover Letter", "Cover letter or note", "Letter of interest", None, "file", None, "Cover letter", None, None]


@needs_node
def test_elapsed_time_reads_as_seconds_then_minutes(tmp_path):
    got = run_js(tmp_path, """
console.log(JSON.stringify([0, 12, 12.9, 59, 60, 65, 3725, -3, null, 'x'].map(JW.elapsedLabel)));""")
    assert got == ["0s", "12s", "12s", "59s", "1m 00s", "1m 05s", "62m 05s", "0s", "0s", "0s"]


@needs_node
def test_each_tab_knows_only_its_own_import_and_progress(tmp_path):
    got = run_js(tmp_path, """
const running = [{ tabId: 7, source: 'linkedin' }, { tabId: 9, source: 'indeed' }];
const msg = (tabId) => ({ type: 'listProgress', tabId, text: 'Read page 1' });
console.log(JSON.stringify([JW.importOnTab(running, 7), JW.importOnTab(running, 9), JW.importOnTab(running, 3),
  JW.importOnTab([], 7), JW.importOnTab(null, 7),
  JW.progressIsMine(msg(7), 7), JW.progressIsMine(msg(9), 7), JW.progressIsMine(msg(7), null),
  JW.progressIsMine({ type: 'toast', tabId: 7 }, 7)]));""")
    assert got == [True, True, False, False, False, True, False, False, False]


def test_list_imports_run_one_per_tab_in_parallel():
    """Two tabs import at once; the same tab twice is refused; the hidden-tab note is sent while a read is under way."""
    src = (EXT / "background.js").read_text(encoding="utf-8")
    assert "const listImports = new Map()" in src and "let listImport " not in src
    assert "if (listImports.has(tabId)) throw new Expected(JW.IMPORT_RUNNING)" in src
    assert src.index("listImports.has(tabId)") < src.index("listImports.set(tabId, source)")
    assert "listImports.delete(tabId)" in src  # in the finally: a failed import frees its tab
    assert "case 'importState': return { running: [...listImports]" in src
    assert "listProgress(tabId, now ? JW.IMPORT_HIDDEN" in src and "document.visibilityState" in src
    assert "whileVisible(tabId, () => chrome.scripting.executeScript" in src
    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    assert "JW.progressIsMine(msg, importing)" in panel and "importOnOtherTab" not in panel + src


@needs_node
def test_the_hidden_tab_note_says_how_to_read_two_lists_at_once(tmp_path):
    got = run_js(tmp_path, "console.log(JSON.stringify([JW.IMPORT_HIDDEN, JW.IMPORT_RUNNING]));")
    assert "isn't visible" in got[0] and "own window" in got[0]
    assert "already running on this tab" in got[1]


def test_each_tab_gets_its_own_side_panel():
    """The toolbar click enables a panel pinned to its tab, before opening it in the same gesture; the default is off."""
    src = (EXT / "background.js").read_text(encoding="utf-8")
    assert "setOptions({ tabId: tab.id, path: `sidepanel.html?tab=${tab.id}`, enabled: true })" in src
    assert src.index("setOptions({ tabId: tab.id") < src.index("sidePanel.open({ tabId: tab.id })")
    assert "chrome.sidePanel.setOptions({ enabled: false })" in src
    assert "await chrome.sidePanel.setOptions" not in src  # awaiting would let the click's user gesture lapse


@needs_node
def test_only_the_offsite_apply_button_is_pressed(tmp_path):
    """Easy Apply applies on LinkedIn, and Save, Share and the rest aren't Apply: none of them is the button to press."""
    buttons = [
        {"label": "Apply on company website", "text": "Apply"}, {"label": "", "text": "Apply"},
        {"label": "Apply", "text": "Apply"}, {"label": "Easy Apply to this job", "text": "Easy Apply"},
        {"label": "", "text": "Easy Apply"}, {"label": "Apply on company website", "text": "Easy Apply"},
        {"label": "Save Platform Engineer at Initech", "text": "Save"}, {"label": "Submit application", "text": "Submit"},
        {"label": "", "text": "Apply now and relocate"}, {"label": "Applications", "text": ""},
    ]
    got = run_js(tmp_path, f"const b = {json.dumps(buttons)};\nconsole.log(JSON.stringify(b.map(x => [JW.isOffsiteApply(x), JW.isEasyApply(x)])));")
    assert got == [[True, False], [True, False], [True, False], [False, True], [False, True], [False, True],
                   [False, False], [False, False], [False, False], [False, False]]


@needs_node
def test_a_companys_name_matches_its_spellings(tmp_path):
    got = run_js(tmp_path, "console.log(JSON.stringify([['Initech, Inc.', 'Initech'], ['Initech Systems', 'initech'], ['Globex', 'Umbrella'], ['', 'Globex']].map(p => JW.sameCompany(...p))));")
    assert got == [True, True, False, False]


@needs_node
def test_a_postings_text_is_tidied(tmp_path):
    got = run_js(tmp_path, r"console.log(JSON.stringify(JW.tidyText('Platform Engineer \n\n\n\nShow more\nBuild  tools.\r\n')));")
    assert got == "Platform Engineer\n\nBuild tools."


@needs_node
def test_a_form_is_replaced_when_most_of_its_fields_are_gone(tmp_path):
    """A multi-step form swapping its step in place: most scanned fields gone. A follow-up question opening or
    closing is the same form."""
    got = run_js(tmp_path, "console.log(JSON.stringify([[8, 0], [8, 3], [8, 4], [8, 7], [8, 8], [0, 0]].map(p => JW.formReplaced(...p))));")
    assert got == [True, True, False, False, False, False]


BUBBLE_HINT = "Have a recruiter's message open in the bubble? Draft reply reads it."
CONTEXT_CASES = [
    # (address, tab title, kind, heading, detail, primary)
    ("https://job-boards.greenhouse.io/initech/jobs/4012345", "Job Application for Platform Engineer at Initech", "form", "Application form", "Initech: Platform Engineer", "scan"),
    ("https://job-boards.greenhouse.io/initech/jobs/4012345", "", "form", "Application form", "Initech", "scan"),
    ("https://boards.greenhouse.io/embed/job_app?for=globex&token=1", "", "form", "Application form", "Globex", "scan"),
    ("https://boards.greenhouse.io/embed/job_app", "", "form", "Application form", "", "scan"),
    ("https://jobs.lever.co/umbrella-corp/0a1b2c3d/apply", "", "form", "Application form", "Umbrella Corp", "scan"),
    ("https://jobs.ashbyhq.com/initech/0a1b2c3d/application", "", "form", "Application form", "Initech", "scan"),
    ("https://www.linkedin.com/messaging/thread/2-abc/", "(3) Dana Whitfield | LinkedIn", "thread", "Conversation with Dana Whitfield", "", "reply"),
    ("https://www.linkedin.com/messaging/thread/2-abc/", "Messaging | LinkedIn", "thread", "Conversation", "LinkedIn Messaging", "reply"),
    ("https://www.linkedin.com/jobs/collections/recommended", "Jobs | LinkedIn", "list", "Job list", "LinkedIn", "import-list"),
    ("https://www.indeed.com/jobs?q=platform", "", "list", "Job list", "Indeed", "import-list"),
    ("https://www.theladders.com/recommended", "Recommended Jobs | Ladders", "list", "Job list", "Ladders", "import-list"),
    ("https://www.linkedin.com/jobs/view/3912345678/", "Platform Engineer | Initech | LinkedIn", "posting", "Job posting", "Platform Engineer | Initech", "posting"),
    ("https://jobs.lever.co/initech/0a1b2c3d", "", "posting", "Job posting", "Initech", "posting"),
    ("https://careers.globex.example/jobs/senior-engineer", "", "posting", "Job posting", "", "posting"),
    ("https://www.example.com/", "Example", "idle", "Nothing to do on this page", "", ""),
    ("https://www.linkedin.com/feed/", "Feed | LinkedIn", "bubble", "LinkedIn", BUBBLE_HINT, ""),
    ("https://www.linkedin.com/in/dana-whitfield/", "Dana Whitfield | LinkedIn", "bubble", "LinkedIn", BUBBLE_HINT, ""),
    ("chrome://extensions", "", "idle", "Nothing to do on this page", "", ""),
    ("", "", "idle", "Nothing to do on this page", "", ""),
]


@needs_node
@pytest.mark.parametrize("url, title, kind, heading, detail, primary", CONTEXT_CASES)
def test_the_panel_leads_with_what_the_page_is(tmp_path, url, title, kind, heading, detail, primary):
    got = run_js(tmp_path, f"console.log(JSON.stringify(JW.pageContext({json.dumps(url)}, {json.dumps(title)})));")
    assert (got["kind"], got["heading"], got["detail"], got["primary"]) == (kind, heading, detail, primary)
    assert got["primary"] == "" or got["primary"] in got["matches"]  # the lead action is never one of the dimmed tiles


@needs_node
def test_the_tiles_that_suit_a_page_are_the_ones_left_lit(tmp_path):
    got = run_js(tmp_path, """console.log(JSON.stringify([
      'https://www.linkedin.com/jobs/search/?currentJobId=3912345678', 'https://www.linkedin.com/feed/', 'https://www.example.com/',
      'https://www.theladders.com/jobs/search-jobs?title=sre'
    ].map(u => JW.pageContext(u, '').matches)));""")
    # a list with a job open also offers the company's posting; any LinkedIn page can have a conversation in a bubble;
    # passive mode runs only where the content script does (LinkedIn, Indeed), so a Ladders list doesn't light it
    assert got == [["import-list", "passive-import", "reply", "posting"], ["reply"], [], ["import-list"]]


@needs_node
def test_a_conversation_name_is_read_only_when_the_title_has_one(tmp_path):
    titles = ["(12) Dana Whitfield | LinkedIn", "Dana Whitfield - LinkedIn", "Messaging | LinkedIn", "(1) Messaging | LinkedIn", "LinkedIn", "", None]
    got = run_js(tmp_path, f"console.log(JSON.stringify({json.dumps(titles)}.map(t => JW.threadName(t))));")
    assert got == ["Dana Whitfield", "Dana Whitfield", "", "", "", "", ""]


@needs_node
def test_a_job_site_title_names_the_role_and_company(tmp_path):
    titles = ["Job Application for Platform Engineer at Initech", "Careers at Globex", ""]
    got = run_js(tmp_path, f"console.log(JSON.stringify({json.dumps(titles)}.map(t => JW.titleJob(t))));")
    assert got == [{"role": "Platform Engineer", "company": "Initech"}, {"role": "", "company": ""}, {"role": "", "company": ""}]


@needs_node
def test_the_theme_choice_defaults_to_the_system(tmp_path):
    got = run_js(tmp_path, "console.log(JSON.stringify(['light', 'dark', 'system', 'purple', '', null, undefined].map(JW.themeChoice)));")
    assert got == ["light", "dark", "system", "system", "system", "system", "system"]


@needs_node
def test_the_panel_opens_in_the_side_panel_only_in_an_ordinary_window(tmp_path):
    got = run_js(tmp_path, "console.log(JSON.stringify(['normal', 'app', 'popup', 'devtools', '', null, undefined].map(JW.panelHome)));")
    assert got == ["sidepanel", "window", "window", "window", "window", "window", "window"]


@needs_node
def test_the_panel_popup_is_as_tall_as_the_app_window_and_against_its_right_edge(tmp_path):
    got = run_js(tmp_path, """console.log(JSON.stringify([
      JW.panelBounds({ left: 100, top: 40, width: 1200, height: 800.4, type: 'app' }),
      JW.panelBounds({ left: 0, top: 0, width: 300, height: 700 }),
      JW.panelBounds({ type: 'app' }),
      JW.panelBounds(null)]));""")
    assert got == [{"width": 420, "height": 800, "left": 880, "top": 40},
                   {"width": 420, "height": 700, "left": 0, "top": 0},
                   {"width": 420}, {"width": 420}]


def test_the_toolbar_click_falls_back_to_a_panel_window_and_does_not_swallow_the_open_error():
    source = (EXT / "background.js").read_text(encoding="utf-8")
    assert "JW.panelHome(" in source and "chrome.windows.create(" in source
    assert "sidePanel.open({ tabId: tab.id }).catch(() => {})" not in source


@needs_node
def test_a_call_that_times_out_says_what_to_do(tmp_path):
    """Chrome stops a service worker whose fetch has waited 30 s, and the panel then waits for ever (11/17, Read the
    jobs on this list): a long call pings an extension API meanwhile (lib.js), and one that times out tells the
    person where to look."""
    shutil.copy(EXT / "lib.js", tmp_path / "lib.mjs")
    js = tmp_path / "case.mjs"
    js.write_text("""
globalThis.chrome = { runtime: { getPlatformInfo: () => Promise.resolve({}) } };
globalThis.fetch = (url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('x'), { name: 'AbortError' }))));
const { api } = await import('./lib.mjs');
const settings = { serverUrl: 'http://127.0.0.1:1', token: 't' };
let error = '';
try { await api('/ext/import-list', { method: 'POST', body: {}, settings, timeout: 150, slow: 'Look in Today.' }); } catch (e) { error = e.message; }
console.log(JSON.stringify({ error }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"error": "jobwatch took too long to answer. Look in Today."}
