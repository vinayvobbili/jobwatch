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
    for name in ("logic.js", "page.js", "panel.js", "background.js", "lib.js", "options.js", "popup.js"):
        r = subprocess.run(["node", "--check", str(EXT / name)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_the_manifest_asks_for_little():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert sorted(manifest["permissions"]) == ["activeTab", "scripting", "storage"]
    assert sorted(manifest["host_permissions"]) == ["http://127.0.0.1/*", "http://localhost/*"]
    assert "content_scripts" not in manifest  # nothing runs on a page until the person clicks
    for name in (manifest["background"]["service_worker"], manifest["action"]["default_popup"],
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
  needs_sponsorship: 'no', gender: 'decline', salary: '180K-200K', phone: '' };
console.log(JSON.stringify(['full_name', 'location', 'work_authorized', 'needs_sponsorship', 'gender', 'salary', 'phone']
  .map(k => JW.valueFor(k, d))));""")
    assert got == ["Jordan Rivera", "Boulder, CO", "Yes", "No", "Decline to answer", "180K-200K", ""]


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
def test_who_you_are_is_not_kept_as_an_answer(tmp_path):
    """The recorded application keeps answers to questions, not who the person is or the voluntary ones."""
    got = run_js(tmp_path, "console.log(JSON.stringify(['email', 'gender', 'full_name', 'salary', 'notice_period'].map(k => JW.IDENTITY.has(k))));")
    assert got == [True, True, True, False, False]
