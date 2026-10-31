/**
 * Content script, injected into every frame of the tab when the person clicks "Fill this application".
 * It reads the form (scan), puts values in it (fill), reads company and title off the page (info) and
 * watches for the person's own submit. It never clicks Submit, Next or any button that sends the form.
 *
 * The React fallbacks (reactProps and where it is used) follow job_app_filler's approach to Greenhouse's
 * boards; see THIRD_PARTY_NOTICES. Field names to expect on Greenhouse and Lever (candidate-location,
 * hispanic_ethnicity, urls[LinkedIn], eeo[gender]) come from reading Autofill-Jobs.
 *
 * Needs logic.js loaded first. The panel (panel.js, top frame only) and the service worker drive it
 * through chrome.scripting.executeScript calls to `globalThis.JWPage`.
 */
(function () {
  'use strict';
  if (globalThis.JWPage) return;
  const JW = globalThis.JW;

  const registry = new Map(); // field id -> {kind, els, ...} from the last scan
  let counter = 0;

  // --- one object per supported system: how to read its title and where its field labels sit --------

  const ADAPTERS = [
    { name: 'greenhouse', match: (h) => /(^|\.)greenhouse\.io$/.test(h),
      wrapper: '.field, .select, .text-input-wrapper, [class*="field-wrapper" i], [class*="question" i]',
      label: 'label, .label, [class*="label" i]',
      title: () => pick('.app-title, .job__title h1, h1.section-header, h1'),
      company: () => pick('.company-name', /^at\s+/i) },
    { name: 'lever', match: (h) => h === 'jobs.lever.co',
      wrapper: '.application-question',
      label: '.application-label, label',
      title: () => pick('.posting-header h2, .posting-headline h2'),
      company: () => (document.title.match(/^(.+?)\s+-\s+/) || [])[1] || '' },
    { name: 'ashby', match: (h) => h === 'jobs.ashbyhq.com',
      wrapper: '.ashby-application-form-field-entry, [class*="fieldEntry" i]',
      label: '.ashby-application-form-question-title, label, [class*="label" i]',
      title: () => (document.title.match(/^(.+?)\s+@\s+/) || [])[1] || pick('h1'),
      company: () => (document.title.match(/\s+@\s+(.+)$/) || [])[1] || '' },
  ];
  const adapter = () => ADAPTERS.find((a) => a.match(location.hostname)) || {};

  function pick(selector, strip) {
    const el = document.querySelector(selector);
    const t = el ? clean(el.textContent) : '';
    return strip ? t.replace(strip, '') : t;
  }

  function info() {
    const a = adapter();
    const og = (p) => (document.querySelector(`meta[property="${p}"]`) || {}).content || '';
    let title = (a.title && a.title()) || '';
    let company = (a.company && a.company()) || '';
    // og:title is often the job title alone (Greenhouse's new boards); the page's own title names the company
    for (const pageTitle of [clean(og('og:title')), clean(document.title)]) {
      if (title && company) break;
      const m = pageTitle.replace(/^job application for\s+/i, '').match(/^(.+?)\s+(?:at|@|-|\||–)\s+(.+)$/i);
      if (m) { title = title || m[1]; company = company || m[2]; }
    }
    company = company || clean(og('og:site_name'));
    return { system: a.name || 'other', title, company };
  }

  // --- reading the form ---------------------------------------------------------------------------

  const clean = (s) => String(s || '').replace(/\s+/g, ' ').replace(/[*✱]/g, '').replace(/\s*\(?required\)?$/i, '').trim();
  const textOf = (el) => clean(el.textContent);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function waitFor(test, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (test()) return true;
      await wait(40);
    }
    return !!test();
  }

  function visible(el) {
    if (!el.isConnected || !el.getClientRects().length) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  }

  const CONTROLS = 'input, select, textarea, button, [role="listbox"], [role="combobox"]';

  /**
   * A label's text as the person sees it: without the form controls inside it, and without hidden helper text
   * (Lever keeps a "No location found" note and the EEO definitions inside its labels).
   */
  function labelText(label) {
    let shown = '';
    const walk = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const p = n.parentElement;
      const control = p.closest(CONTROLS);
      if ((control && label.contains(control)) || !p.getClientRects().length || getComputedStyle(p).visibility === 'hidden') continue;
      shown += n.textContent;
    }
    if (clean(shown)) return clean(shown);
    const c = label.cloneNode(true); // a visually hidden label (for screen readers) still names its field
    c.querySelectorAll(CONTROLS).forEach((x) => x.remove());
    return clean(c.textContent);
  }

  /** react-select's hidden "required" input, or any other stand-in next to a custom dropdown. */
  function comboStandIn(el) {
    if (el.getAttribute('aria-hidden') === 'true') return true;
    const box = el.parentElement && el.parentElement.closest('[class*="select" i], [class*="combobox" i]');
    return !!box && box.querySelectorAll('input, select, textarea').length <= 3 &&
      [...box.querySelectorAll('[role="combobox"]')].some((c) => c !== el);
  }

  function byIds(ids) {
    return clean(String(ids).split(/\s+/).map((i) => document.getElementById(i)).filter(Boolean).map((n) => n.textContent).join(' '));
  }

  /** The nearest label-looking text that comes before `el` in a wrapper holding only this one field. */
  function nearby(el) {
    const a = adapter();
    const wrapper = a.wrapper && el.closest(a.wrapper);
    const labelSel = (wrapper && a.label) || 'legend, label, h1, h2, h3, h4, [class*="label" i], [class*="title" i], [class*="question" i]';
    const tryIn = (box) => {
      for (const l of box.querySelectorAll(labelSel)) {
        if (l.contains(el) || l.querySelector('input, select, textarea')) continue;
        if (!(l.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
        const t = labelText(l);
        if (t.length > 1 && t.length < 400) return t;
      }
      return '';
    };
    if (wrapper) return tryIn(wrapper);
    let box = el.parentElement;
    for (let i = 0; box && i < 5; i++, box = box.parentElement) {
      const names = new Set([...box.querySelectorAll('input, select, textarea')].filter((n) => n.type !== 'hidden')
        .map((n) => n.name || n.id || Math.random()));
      if (names.size > 1) break;
      const t = tryIn(box);
      if (t) return t;
    }
    return '';
  }

  function questionOf(el) {
    if (el.getAttribute('aria-labelledby')) {
      const t = byIds(el.getAttribute('aria-labelledby'));
      if (t) return t;
    }
    for (const l of el.labels || []) {
      const t = labelText(l);
      if (t) return t;
    }
    const wrap = el.closest('label');
    if (wrap && labelText(wrap)) return labelText(wrap);
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    return nearby(el) || precedingText(el);
  }

  /** Plain text just before the field, with no label element around it ("Your city<br><input>"). */
  function precedingText(el) {
    let node = el;
    for (let up = 0; node && up < 3; up++, node = node.parentElement) {
      for (let n = node.previousSibling; n; n = n.previousSibling) {
        const t = clean(n.nodeType === 3 ? n.textContent : n.tagName === 'BR' ? '' : n.querySelector && n.querySelector('input, select, textarea') ? '' : n.textContent);
        if (t && t.length < 200) return t;
        if (n.nodeType === 1 && n.tagName !== 'BR') break;
      }
      if (!node.parentElement || node.parentElement.querySelectorAll('input, select, textarea').length > 1) break;
    }
    return '';
  }

  function groupQuestion(first) {
    const fs = first.closest('fieldset');
    const legend = fs && fs.querySelector('legend');
    if (legend && textOf(legend)) return textOf(legend);
    const g = first.closest('[role="group"], [role="radiogroup"]');
    if (g) {
      if (g.getAttribute('aria-labelledby') && byIds(g.getAttribute('aria-labelledby'))) return byIds(g.getAttribute('aria-labelledby'));
      if (g.getAttribute('aria-label')) return clean(g.getAttribute('aria-label'));
    }
    return nearby(first);
  }

  function optionLabel(input) {
    const own = [...(input.labels || [])].map(labelText).find(Boolean);
    if (own) return own;
    const wrap = input.closest('label');
    if (wrap && labelText(wrap)) return labelText(wrap);
    if (input.getAttribute('aria-label')) return clean(input.getAttribute('aria-label'));
    const next = input.nextSibling && clean(input.nextSibling.textContent || '');
    return next || input.value || '';
  }

  const hintOf = (el) => [el.name, el.id, el.getAttribute('placeholder'), el.getAttribute('data-qa'),
    el.getAttribute('aria-label')].filter(Boolean).join(' ').replace(/[_\-[\]]+/g, ' ');

  function comboControl(el) {
    return el.closest('[class*="control" i]') || el.closest('[class*="select" i]') || el.parentElement;
  }

  function comboValue(el) {
    const box = (el.parentElement && el.parentElement.closest('[class*="select" i], [class*="combobox" i]')) || el.parentElement;
    const v = box && box.querySelector('[class*="single-value" i], [class*="singleValue" i], [class*="selected" i]');
    if (v && textOf(v)) return textOf(v);
    return el.tagName === 'INPUT' ? el.value : textOf(el);
  }

  function comboListbox(el) {
    const id = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
    const box = id && document.getElementById(id);
    if (box && box.isConnected) return box;
    return [...document.querySelectorAll('[role="listbox"], [class*="menu" i]')].find(visible) || null;
  }

  function comboOptions(el) {
    const box = comboListbox(el);
    if (!box) return [];
    const o = [...box.querySelectorAll('[role="option"]')];
    return o.length ? o : [...box.querySelectorAll('[class*="option" i]')];
  }

  const key = (el, type, init) => el.dispatchEvent(new KeyboardEvent(type, { key: init, code: init, bubbles: true, cancelable: true }));

  async function openCombo(el) {
    if (comboOptions(el).length) return;
    el.focus();
    const c = comboControl(el);
    const mouse = (t) => c.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, button: 0, view: window }));
    mouse('mousedown');
    if (!(await waitFor(() => comboOptions(el).length, 150))) {
      mouse('mouseup');
      mouse('click');
    }
    if (!(await waitFor(() => comboOptions(el).length, 150))) key(el, 'keydown', 'ArrowDown');
    if (!(await waitFor(() => comboOptions(el).length, 300))) {
      // Greenhouse's boards open the menu from a plain div's React handler (job_app_filler's trick).
      const shell = el.closest('[class*="select-shell" i]');
      const trigger = (shell && [...shell.children].find((n) => !n.attributes.length)) || c;
      const props = reactProps(trigger) || reactProps(c);
      const ev = { defaultPrevented: false, button: 0, preventDefault() {}, stopPropagation() {} };
      if (props && props.onMouseDown) props.onMouseDown(ev);
      if (props && props.onMouseUp && !comboOptions(el).length) props.onMouseUp(ev);
    }
    await waitFor(() => comboOptions(el).length, 500);
  }

  function closeCombo(el) {
    key(el, 'keydown', 'Escape');
    el.blur();
    el.dispatchEvent(new Event('blur'));
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  }

  /** Every fillable field on the page, with what it says now. Sync, so a submit handler can use it. */
  function gather() {
    registry.clear();
    counter = 0;
    const fields = [];
    const seen = new Set();
    const add = (f, reg) => {
      f.id = `f${++counter}`;
      registry.set(f.id, reg);
      fields.push(f);
    };
    for (const el of document.querySelectorAll('input, textarea, select, [role="combobox"]')) {
      if (seen.has(el) || el.closest('#jobwatch-panel')) continue;
      const type = (el.type || '').toLowerCase();
      const tag = el.tagName;
      if (tag === 'INPUT' && ['hidden', 'submit', 'button', 'image', 'reset', 'search', 'range', 'color'].includes(type)) continue;
      if (el.disabled || /captcha|honeypot/i.test(`${el.name} ${el.id} ${el.className}`)) continue;
      const combo = el.getAttribute('role') === 'combobox';
      if (type !== 'file' && !visible(el)) continue;
      if (tag === 'INPUT' && el.readOnly && !combo) continue;
      if (!combo && type !== 'file' && comboStandIn(el)) continue;
      const base = { type, autocomplete: el.getAttribute('autocomplete') || '', hint: hintOf(el), required: el.required || el.getAttribute('aria-required') === 'true' };

      if (type === 'radio' || type === 'checkbox') {
        const same = el.name ? [...document.querySelectorAll(`input[type="${type}"]`)].filter((n) => n.name === el.name && visible(n)) : [el];
        same.forEach((n) => seen.add(n));
        if (type === 'checkbox' && same.length === 1) {
          add({ ...base, kind: 'checkbox', question: optionLabel(el) || questionOf(el), options: [], filled: false, current: el.checked ? 'Yes' : '' }, { els: [el] });
          continue;
        }
        const labels = same.map(optionLabel);
        const checked = same.filter((n) => n.checked).map(optionLabel);
        add({ ...base, kind: type === 'radio' ? 'radio' : 'checkboxes', question: groupQuestion(same[0]), options: labels,
          filled: checked.length > 0, current: checked.join(', '), hint: hintOf(same[0]) }, { els: same });
        continue;
      }
      if (type === 'file') {
        add({ ...base, kind: 'file', question: questionOf(el) || hintOf(el), options: [], filled: !!(el.files && el.files.length),
          current: el.files && el.files[0] ? el.files[0].name : '' }, { els: [el] });
        continue;
      }
      if (combo) {
        const cur = comboValue(el);
        add({ ...base, kind: 'combobox', question: questionOf(el), options: [], filled: !!cur && !/^select/i.test(cur), current: cur }, { els: [el] });
        continue;
      }
      if (tag === 'SELECT') {
        const opts = [...el.options].map((o) => clean(o.textContent));
        const sel = el.selectedOptions[0];
        const filled = !!(sel && sel.value !== '' && !/^(select|choose|please)/i.test(clean(sel.textContent)));
        add({ ...base, kind: 'select', question: questionOf(el), options: opts, filled, current: filled ? clean(sel.textContent) : '' }, { els: [el] });
        continue;
      }
      add({ ...base, kind: tag === 'TEXTAREA' ? 'textarea' : 'text', question: questionOf(el), options: [], filled: !!el.value.trim(), current: el.value }, { els: [el] });
    }
    // yes/no button pairs (Ashby's): two plain buttons reading Yes and No inside one wrapper
    const done = new Set();
    for (const b of document.querySelectorAll('button')) {
      const p = b.parentElement;
      if (!p || done.has(p) || b.closest('#jobwatch-panel')) continue;
      const btns = [...p.children].filter((n) => n.tagName === 'BUTTON');
      const texts = btns.map((n) => JW.normalize(n.textContent));
      if (btns.length !== 2 || !(texts.includes('yes') && texts.includes('no')) || btns.some((n) => n.type === 'submit')) continue;
      done.add(p);
      const on = btns.find((n) => n.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(n.className));
      add({ kind: 'buttons', type: '', autocomplete: '', hint: '', required: false, question: nearby(btns[0]) || groupQuestion(btns[0]),
        options: btns.map(textOf), filled: !!on, current: on ? textOf(on) : '' }, { els: btns });
    }
    return fields;
  }

  /** gather(), plus the choices of each custom dropdown, read by opening it and closing it again. */
  async function scan() {
    const fields = gather();
    for (const f of fields) {
      if (f.kind !== 'combobox') continue;
      const el = registry.get(f.id).els[0];
      try {
        await openCombo(el);
        f.options = [...new Set(comboOptions(el).map(textOf))].slice(0, 300);
        closeCombo(el);
      } catch {
        f.options = [];
      }
    }
    for (const f of fields) f.weak = !f.question;
    for (const f of fields) f.question = f.question || clean(registry.get(f.id).els[0].getAttribute('placeholder') || f.hint);
    return { info: info(), fields, frame: location.href };
  }

  // --- filling -------------------------------------------------------------------------------

  function setNative(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  }

  function settle(el) {
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.blur();
    el.dispatchEvent(new Event('blur'));
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  }

  /** The props React keeps on a DOM node (`__reactProps$...`), or null on a page that doesn't use React. */
  function reactProps(el) {
    for (const k in el) if (k.startsWith('__reactProps')) return el[k];
    return null;
  }

  function typeInto(el, value) {
    el.focus();
    setNative(el, value);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    // React put the old value back: hand it the change directly
    const props = reactProps(el);
    if (el.value !== value && props && props.onChange) {
      setNative(el, value);
      props.onChange({ target: el, currentTarget: el, preventDefault() {} });
    }
  }

  const press = (el) => {
    if (el.tagName === 'BUTTON' && el.type === 'submit') throw new Error('refusing to click a submit button');
    ['mousedown', 'mouseup'].forEach((t) => el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
    el.click();
  };

  async function fillCombo(el, value) {
    await openCombo(el);
    let opts = comboOptions(el);
    let i = JW.optionIndex(value, opts.map(textOf));
    if (i < 0 && el.tagName === 'INPUT') {
      typeInto(el, value);
      await waitFor(() => comboOptions(el).length, 700);
      opts = comboOptions(el);
      i = JW.optionIndex(value, opts.map(textOf));
    }
    if (i < 0) {
      closeCombo(el);
      return { ok: false, error: 'No matching option' };
    }
    const picked = textOf(opts[i]);
    press(opts[i]);
    await wait(60);
    if (comboOptions(el).length) closeCombo(el);
    return { ok: true, picked };
  }

  async function attachFile(el, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    el.files = dt.files;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    // Greenhouse's React upload shows the name in .file-upload__filename; when it doesn't, call its handler (job_app_filler's trick)
    const box = el.closest('[class*="file-upload" i]');
    const props = reactProps(el);
    if (box && props && props.onChange) {
      await wait(400);
      if (!box.querySelector('[class*="filename" i]')) props.onChange({ target: { files: [file] } });
    }
    const zone = el.closest('[class*="drop" i], [data-dropzone]') || (el.parentElement && el.parentElement.closest('[class*="drop" i]'));
    if (zone) {
      const d = new DataTransfer();
      d.items.add(file);
      for (const t of ['dragenter', 'dragover', 'drop']) zone.dispatchEvent(new DragEvent(t, { bubbles: true, cancelable: true, dataTransfer: d }));
    }
  }

  async function fillOne(item) {
    const reg = registry.get(item.id);
    if (!reg) return { id: item.id, ok: false, error: 'The page changed; scan again' };
    const els = reg.els;
    const value = String(item.value == null ? '' : item.value);
    try {
      if (item.kind === 'file') {
        if (!item.resume) return { id: item.id, ok: false, error: 'No file to attach' };
        const bytes = Uint8Array.from(atob(item.resume.b64), (c) => c.charCodeAt(0));
        await attachFile(els[0], new File([bytes], item.resume.name, { type: item.resume.type || 'application/octet-stream' }));
        return { id: item.id, ok: true, picked: item.resume.name };
      }
      if (item.kind === 'select') {
        const el = els[0];
        const i = JW.optionIndex(value, [...el.options].map((o) => clean(o.textContent)));
        if (i < 0) return { id: item.id, ok: false, error: 'No matching option' };
        el.focus();
        setNative(el, el.options[i].value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        settle(el);
        return { id: item.id, ok: true, picked: clean(el.options[i].textContent) };
      }
      if (item.kind === 'radio' || item.kind === 'checkboxes' || item.kind === 'buttons') {
        const i = JW.optionIndex(value, item.kind === 'buttons' ? els.map(textOf) : els.map(optionLabel));
        if (i < 0) return { id: item.id, ok: false, error: 'No matching option' };
        const el = els[i];
        if (item.kind === 'buttons') press(el);
        else if (!el.checked) el.click();
        return { id: item.id, ok: true, picked: item.kind === 'buttons' ? textOf(el) : optionLabel(el) };
      }
      if (item.kind === 'checkbox') {
        if (/^(yes|true|checked)/i.test(value) && !els[0].checked) els[0].click();
        return { id: item.id, ok: true };
      }
      if (item.kind === 'combobox') return { id: item.id, ...(await fillCombo(els[0], value)) };
      typeInto(els[0], value);
      settle(els[0]);
      return { id: item.id, ok: true };
    } catch (e) {
      return { id: item.id, ok: false, error: String((e && e.message) || e) };
    }
  }

  async function fill(items) {
    const out = [];
    for (const item of items) out.push(await fillOne(item));
    return out;
  }

  // --- the person's own submit --------------------------------------------------------------------

  let watching = false;
  let lastCapture = 0;

  function currentErrors() {
    return [...document.querySelectorAll('[aria-invalid="true"], [role="alert"], [class*="error" i]')]
      .some((n) => visible(n) && (n.getAttribute('aria-invalid') === 'true' || textOf(n).length > 0));
  }

  /** Question/answer pairs worth keeping: not who you are, not the voluntary questions, not files. */
  function collect() {
    const pairs = [];
    for (const f of gather()) {
      if (!f.current || f.kind === 'file' || f.kind === 'checkbox' || !f.question) continue;
      const k = JW.classifyField(f).key;
      if (k && JW.IDENTITY.has(k)) continue;
      pairs.push({ question: f.question, answer: f.current.trim() });
    }
    return pairs;
  }

  function capture() {
    const now = Date.now();
    if (now - lastCapture < 1500) return;
    lastCapture = now;
    const file = [...document.querySelectorAll('input[type="file"]')].map((i) => i.files && i.files[0]).find(Boolean);
    const before = JW.looksSubmitted(document.body.innerText);
    chrome.runtime.sendMessage({ type: 'captured', pairs: collect(), info: info(), resume: file ? file.name : '', frame: location.href });
    poll(before);
  }

  // A page that shows its thank-you in place (no navigation): watch for it after each submit, one watcher at a time.
  let polling = false;

  async function poll(before) {
    if (before || polling) return;
    polling = true;
    for (let i = 0; i < 120; i++) {
      await wait(1000);
      if (JW.looksSubmitted(document.body.innerText) && !currentErrors()) {
        chrome.runtime.sendMessage({ type: 'looksSubmitted' });
        break;
      }
    }
    polling = false;
  }

  function isSubmitControl(el) {
    const label = el.value && el.tagName === 'INPUT' ? el.value : el.textContent;
    if (JW.isSubmitLabel(label)) return true;
    return el.type === 'submit' && !/\b(next|continue|back|previous|upload|add|attach|save)\b/i.test(label);
  }

  function watch() {
    if (watching) return;
    watching = true;
    document.addEventListener('submit', capture, true);
    document.addEventListener('click', (e) => {
      const b = e.target.closest && e.target.closest('button, input[type="submit"], [role="button"]');
      if (b && !b.closest('#jobwatch-panel') && isSubmitControl(b)) capture();
    }, true);
  }

  globalThis.JWPage = { scan, fill, info, collect, watch, gather };
})();
