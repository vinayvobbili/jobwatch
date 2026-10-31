/**
 * The extension's thinking, with no DOM and no chrome.* in it, so node can test it
 * (tests/test_extension_logic.py): which applicant field a question is, which past
 * answer fits a new question, which option of a select to pick, whether a page
 * looks like a finished submission.
 *
 * A classic script on purpose: the content scripts are injected as files, and the
 * service worker and options page load it for the same `JW` object.
 */
(function (root) {
  'use strict';

  // [key, label, kind]: the applicant fields in API.md. jobwatch supplies them; they only fill what is still empty.
  const DETAIL_FIELDS = [
    ['first_name', 'First name', 'text'], ['last_name', 'Last name', 'text'], ['preferred_name', 'Preferred name', 'text'],
    ['email', 'Email', 'text'], ['phone', 'Phone', 'text'],
    ['city', 'City', 'text'], ['state', 'State', 'text'], ['country', 'Country', 'text'], ['postal_code', 'Postal code', 'text'],
    ['linkedin', 'LinkedIn', 'text'], ['github', 'GitHub', 'text'], ['website', 'Website', 'text'],
    ['work_authorized', 'Legally allowed to work in the job\'s country', 'yesno'],
    ['needs_sponsorship', 'Needs visa sponsorship, now or later', 'yesno'],
    ['relocate', 'Willing to relocate', 'yesno'],
    ['notice_period', 'Notice period', 'text'], ['salary', 'Salary expectation', 'text'],
    ['gender', 'Gender', 'eeo'], ['race', 'Race / ethnicity', 'eeo'], ['hispanic', 'Hispanic / Latino', 'eeo'],
    ['veteran', 'Veteran status', 'eeo'], ['disability', 'Disability', 'eeo'],
  ];
  const KEYS = DETAIL_FIELDS.map((f) => f[0]);
  const YESNO = new Set(DETAIL_FIELDS.filter((f) => f[2] === 'yesno').map((f) => f[0]));
  const EEO = new Set(DETAIL_FIELDS.filter((f) => f[2] === 'eeo').map((f) => f[0]));
  // Not kept as "answers" on a recorded application: who you are, and the voluntary questions.
  const IDENTITY = new Set(['first_name', 'last_name', 'preferred_name', 'full_name', 'email', 'phone', 'city', 'state',
    'country', 'postal_code', 'location', 'linkedin', 'github', 'website', ...EEO]);

  // Offered but never ticked for you: a pay number on a form is a negotiating move, so the person adds it on purpose.
  const ASK_FIRST = new Set(['salary']);

  const SHOW_MIN = 0.6; // a past question this alike is offered
  const HIGH = 0.85; // and one this alike starts ticked

  const STOP = new Set(('a an the is are was do does did you your yours to of in at for and or on with be will would can ' +
    'could have has what please we our us i my me this that it if as from by how any about').split(' '));

  function normalize(s) {
    return String(s == null ? '' : s).toLowerCase().replace(/[’']/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function stem(w) {
    if (w.length > 5 && w.endsWith('ing')) return w.slice(0, -3);
    if (w.length > 4 && w.endsWith('ed')) return w.slice(0, -2);
    if (w.length > 4 && w.endsWith('es')) return w.slice(0, -2);
    if (w.length > 3 && w.endsWith('s')) return w.slice(0, -1);
    return w;
  }

  function tokens(s) {
    const out = new Set();
    for (const w of normalize(s).split(' ')) if (w && !STOP.has(w)) out.add(stem(w));
    return out;
  }

  /** How alike two questions read, 0..1 (Dice on their meaningful words). */
  function similarity(a, b) {
    const x = tokens(a), y = tokens(b);
    if (!x.size || !y.size) return 0;
    let both = 0;
    for (const w of x) if (y.has(w)) both++;
    return (2 * both) / (x.size + y.size);
  }

  // --- which applicant field a question is ------------------------------------------------

  // First hit wins, so the narrow ones come first. A null key is a question to leave alone.
  const RULES = [
    { key: 'hispanic', re: /\b(hispanic|latino|latina|latinx)\b/ },
    { key: 'veteran', re: /\bveteran\b|military service/ },
    { key: 'disability', re: /\bdisabilit(y|ies)\b/ },
    { key: 'race', re: /\b(race|ethnic\w*)\b/ },
    { key: null, re: /\bpronouns?\b|\bsexual orientation\b|\btransgender\b/ },
    { key: 'gender', re: /\b(gender|sex)\b/ },
    { key: 'work_authorized', not: /\b(requir\w*|need)\b.*\b(sponsor\w*|visa)\b/,
      re: /\b(legally|lawfully)\b.*\bwork\b|\bauthori[sz]ed\b.*\bwork\b|\beligible to work\b|\bwork authori[sz]ation\b|\bright to work\b/ },
    { key: 'needs_sponsorship', re: /\bsponsor\w*|\bvisa\b/ },
    { key: 'relocate', re: /\brelocat\w*/ },
    { key: 'notice_period', re: /\bnotice\b|\bearliest\b.*\bstart\b|\bstart date\b|\bwhen (can|could) you (start|join)\b|\bavailable to start\b/ },
    { key: 'salary', re: /\b(salary|compensation|remuneration)\b/ },
    { key: 'preferred_name', re: /\bpreferred (first )?name\b|\bnickname\b|\bgo by\b|\bname (you|youd|you would) prefer\b/ },
    { key: 'first_name', re: /\b(first|given) name\b|\bforename\b/ },
    { key: 'last_name', re: /\b(last|family) name\b|\bsurname\b/ },
    { key: 'full_name', re: /^(your |full |legal |candidate )*name$/ },
    { key: 'email', re: /\be ?mail\b/ },
    { key: 'phone', re: /\b(phone|mobile|cell|telephone)\b/ },
    { key: 'linkedin', re: /\blinkedin\b/ },
    { key: 'github', re: /\bgithub\b/ },
    { key: 'website', re: /\b(website|portfolio|personal (site|url)|blog)\b|\bother (url|link)s?\b/ },
    { key: 'postal_code', re: /\b(zip|postal|postcode)\b/ },
    { key: 'country', re: /\bcountry\b/ },
    { key: 'state', re: /\b(state|province)\b/ },
    { key: 'city', re: /\bcity\b|\btown\b/ },
    { key: 'location', re: /\blocation\b|\bwhere (are |do )?you (currently )?(based|located|live)\b|\bcurrent address\b/ },
  ];

  const AUTOCOMPLETE = { 'given-name': 'first_name', 'family-name': 'last_name', name: 'full_name', email: 'email',
    tel: 'phone', 'postal-code': 'postal_code', 'address-level2': 'city', 'address-level1': 'state', 'country-name': 'country' };

  function classify(text) {
    const t = normalize(text);
    if (!t) return null;
    for (const r of RULES) if (r.re.test(t) && !(r.not && r.not.test(t))) return r.key;
    return null;
  }

  /**
   * {key, sure} for a scanned field. `sure` is true when the question's own text says it;
   * a guess from the field's name or placeholder is not sure. Long questions are free text.
   */
  function classifyField(f) {
    const q = f.weak ? '' : f.question;
    const words = normalize(q).split(' ').filter(Boolean).length;
    const limit = f.kind === 'textarea' ? 8 : 30;
    if (words && words <= limit) {
      const key = classify(q);
      if (key) return { key, sure: true };
      if (RULES.some((r) => r.key === null && r.re.test(normalize(q)))) return { key: null, sure: false };
    }
    if (AUTOCOMPLETE[f.autocomplete]) return { key: AUTOCOMPLETE[f.autocomplete], sure: true };
    if (f.type === 'email') return { key: 'email', sure: true };
    if (f.type === 'tel') return { key: 'phone', sure: true };
    if (f.kind !== 'textarea' && words <= limit) {
      const key = classify(f.hint);
      if (key) return { key, sure: false };
    }
    return { key: null, sure: false };
  }

  // --- values ----------------------------------------------------------------------------

  /** What to put in the form for an applicant field, or '' when the details don't say. */
  function valueFor(key, d) {
    d = d || {};
    const get = (k) => String(d[k] || '').trim();
    if (key === 'full_name') return [get('first_name'), get('last_name')].filter(Boolean).join(' ');
    if (key === 'location') return [get('city'), get('state')].filter(Boolean).join(', ');
    const v = get(key);
    if (!v) return '';
    if (YESNO.has(key)) return /^y/i.test(v) ? 'Yes' : /^n/i.test(v) ? 'No' : '';
    if (EEO.has(key) && /^decline/i.test(v)) return 'Decline to answer';
    return v;
  }

  // --- options ---------------------------------------------------------------------------

  const DECLINE = /\b(decline|dont wish|do not wish|prefer not|rather not|choose not|not want to (answer|say|disclose|identify|state)|not to (answer|say|disclose|identify|state))\b/;
  const PLACEHOLDER = /^(select\b|please select|choose\b|pick\b|none selected|)$/;
  const ALIAS = { us: 'united states', usa: 'united states', 'united states of america': 'united states', uk: 'united kingdom' };
  const STATES = ('AL Alabama|AK Alaska|AZ Arizona|AR Arkansas|CA California|CO Colorado|CT Connecticut|DE Delaware|FL Florida|' +
    'GA Georgia|HI Hawaii|ID Idaho|IL Illinois|IN Indiana|IA Iowa|KS Kansas|KY Kentucky|LA Louisiana|ME Maine|MD Maryland|' +
    'MA Massachusetts|MI Michigan|MN Minnesota|MS Mississippi|MO Missouri|MT Montana|NE Nebraska|NV Nevada|NH New Hampshire|' +
    'NJ New Jersey|NM New Mexico|NY New York|NC North Carolina|ND North Dakota|OH Ohio|OK Oklahoma|OR Oregon|PA Pennsylvania|' +
    'RI Rhode Island|SC South Carolina|SD South Dakota|TN Tennessee|TX Texas|UT Utah|VT Vermont|VA Virginia|WA Washington|' +
    'WV West Virginia|WI Wisconsin|WY Wyoming|DC District of Columbia').split('|')
    .map((s) => [s.slice(0, 2).toLowerCase(), s.slice(3).toLowerCase()]);

  function forms(v) {
    const out = new Set([v]);
    if (ALIAS[v]) out.add(ALIAS[v]);
    for (const [code, name] of STATES) {
      if (v === code) out.add(name);
      if (v === name) out.add(code);
    }
    return [...out];
  }

  /** Index of the option that says what `value` says, or -1. */
  function optionIndex(value, options) {
    const opts = options.map(normalize);
    const find = (test) => opts.findIndex((o) => !PLACEHOLDER.test(o) && test(o));
    const v = normalize(value);
    if (!v) return -1;
    if (/^(decline|prefer not|dont wish|do not wish|i do not wish)/.test(v)) return find((o) => DECLINE.test(o));
    const yn = v.match(/^(yes|no)\b/);
    if (yn) {
      const i = find((o) => new RegExp(`^${yn[1]}\\b`).test(o));
      if (i >= 0 || v === yn[1]) return i;
    }
    for (const f of forms(v)) {
      const i = find((o) => o === f);
      if (i >= 0) return i;
    }
    for (const f of forms(v)) {
      const re = new RegExp(`\\b${f}\\b`);
      const i = find((o) => re.test(o) && o.split(' ').length <= f.split(' ').length + 3);
      if (i >= 0) return i;
    }
    const want = [...tokens(v)];
    let best = -1, bestScore = 0.5;
    opts.forEach((o, i) => {
      if (PLACEHOLDER.test(o)) return;
      const s = similarity(v, o);
      if (s >= bestScore && want.every((w) => tokens(o).has(w))) { best = i; bestScore = s; }
    });
    return best;
  }

  // --- past answers ----------------------------------------------------------------------

  /** The earlier answer whose question reads most like `question`, or null. */
  function matchPastAnswer(question, answers) {
    let best = null;
    for (const a of answers || []) {
      if (!a || !a.question || !String(a.answer || '').trim()) continue;
      const score = similarity(question, a.question);
      if (score >= SHOW_MIN && (!best || score > best.score)) best = { ...a, score };
    }
    return best;
  }

  // --- the plan --------------------------------------------------------------------------

  const CHOICE = new Set(['select', 'radio', 'checkboxes', 'combobox', 'buttons']);
  const isChoice = (f) => CHOICE.has(f.kind) && f.options && f.options.length;

  function isResume(f) {
    const q = normalize(f.question);
    return f.kind === 'file' && /\b(resume|cv|curriculum)\b/.test(q + ' ' + normalize(f.hint)) && !/\bcover\b/.test(q);
  }

  /**
   * One review row per scanned field. Ticked at the start only when it's a sure applicant-detail
   * match, the resume, or a past answer whose question reads almost the same (HIGH), on a field the page
   * hasn't already filled. Weaker past answers, drafts and guesses start unticked.
   * `opts.resume` is the resume's file name when jobwatch has one.
   */
  function buildPlan(fields, details, answers, opts) {
    return fields.map((f) => {
      const item = { id: f.id, kind: f.kind, question: f.question, options: f.options || [], required: !!f.required,
        filled: !!f.filled, current: f.current || '', key: null, source: 'none', value: '', checked: false, matched: null };
      if (f.kind === 'file') {
        if (isResume(f) && opts && opts.resume) Object.assign(item, { source: 'resume', value: opts.resume, checked: !f.filled });
        return item;
      }
      const { key, sure } = classifyField(f);
      const value = key ? valueFor(key, details) : '';
      if (value && !(isChoice(f) && optionIndex(value, f.options) < 0)) {
        Object.assign(item, { key, source: 'details', value });
      } else if (f.kind !== 'checkbox' && !(key && EEO.has(key))) {
        const m = matchPastAnswer(f.question, answers);
        if (m && !(isChoice(f) && optionIndex(String(m.answer), f.options) < 0)) {
          Object.assign(item, { source: 'past', value: String(m.answer).trim(),
            matched: { question: m.question, company: m.company || '', title: m.title || '',
              applied_at: m.applied_at || '', score: m.score } });
        }
      }
      item.checked = !f.filled && !ASK_FIRST.has(key) &&
        ((item.source === 'details' && sure) || (item.source === 'past' && item.matched.score >= HIGH));
      return item;
    });
  }

  // --- a finished submission -------------------------------------------------------------

  const SUCCESS = new RegExp('\\b(thank you for (applying|your application|your interest|submitting)|thanks for applying|' +
    'application (has been |was )?(successfully )?(submitted|received|sent)|(we have|weve) received your application|' +
    'received your application|successfully submitted|application complete)\\b');

  function looksSubmitted(text) {
    return SUCCESS.test(normalize(text));
  }

  /** A button that would send the form (not Next, Back or Upload). */
  function isSubmitLabel(text) {
    return /^(submit( application)?|apply|send application|apply now|complete application)$/.test(normalize(text));
  }

  const JW = { DETAIL_FIELDS, KEYS, YESNO, EEO, IDENTITY, ASK_FIRST, SHOW_MIN, HIGH, normalize, tokens, similarity, classify, classifyField,
    valueFor, optionIndex, matchPastAnswer, buildPlan, isResume, looksSubmitted, isSubmitLabel };
  if (typeof module !== 'undefined' && module.exports) module.exports = JW;
  root.JW = JW;
})(typeof globalThis !== 'undefined' ? globalThis : this);
