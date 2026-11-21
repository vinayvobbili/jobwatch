/**
 * Content script for "Draft reply", injected into the tab when the person presses the button (never on its own).
 *
 *   read()  reads the one conversation that is open and showing: its messages as they are on screen. It does not
 *           scroll, open another conversation or look at any other part of LinkedIn.
 *   fill()  puts the drafted reply in that conversation's message box, and nothing else. It never clicks anything:
 *           Send is the person's to press.
 *
 * LinkedIn's class names change, so the page is found by its structure first: the message box is a contenteditable
 * textbox, and its conversation is the nearest ancestor that holds message bodies. The class fragments below
 * (msg-s-...) are only the names of the parts inside it, matched by `[class*=...]` so a renamed prefix still works.
 * They were checked against the live thread page (Nov 2026); tests/test_extension_e2e.py runs this against
 * demo/linkedin-messages.html, which imitates it (?live is the current shape). When no box can be tied to the messages,
 * the one thread whose messages are showing is read anyway.
 *
 * Needs logic.js loaded first (formatThread, fingerprint).
 */
(function () {
  'use strict';
  // No "already loaded" guard: the button injects this fresh each press, and a copy left in the tab's script world by
  // an older version of the extension (reloaded at chrome://extensions) must not keep answering in place of this one.
  const JW = globalThis.JW;

  // Any editable box counts when it is a textbox by role, or says it is for writing a message (aria-label/placeholder)
  // or sits in a form: LinkedIn has dropped the role or the exact contenteditable value before.
  const EDITABLE = '[contenteditable]:not([contenteditable="false"])';
  const BODY = '[class*="event-listitem__body"], [data-event-urn] p, [data-view-name="message-list-item"] p';
  // Wrappers LinkedIn gives a whole thread, used when no message box can be tied to the messages.
  const THREAD = '[class*="msg-thread"], [class*="msg-convo"], [class*="message-list-container"], [data-view-name*="thread"]';
  const NAME = '[class*="message-group__name"]';
  const STAMP = 'time, [class*="message-group__timestamp"], [class*="time-heading"]';
  const HEADER = '[class*="msg-entity-lockup__entity-title"], [class*="msg-overlay-bubble-header__title"], ' +
    '[class*="msg-thread__link-to-profile"], [class*="thread-header"] h2';

  const TOO_MANY = 'More than one conversation is open here. Click into the message box of the one you want a reply for, then try again.';
  const NONE = 'No conversation is open. Open the recruiter\'s message (its message box must be showing) and try again.';
  const UNREADABLE = "Couldn't read the messages in this conversation. LinkedIn may have changed its page: copy the message into jobwatch's draft-reply command instead.";

  const text = (el) => String(el.textContent || '').replace(/[​​\s]+/g, ' ').trim();
  const shown = (el) => el.getClientRects().length > 0;

  // LinkedIn draws its message bubble inside an open shadow root (#interop-outlet), which querySelectorAll, closest,
  // contains and parentElement all stop at. These walk through the roots, in document order.
  /** Every element under `root` (the document, a shadow root or an element) that matches, shadow roots included. */
  function deepAll(selector, root) {
    const out = [];
    (function walk(node) {
      for (const el of node.children) {
        if (el.matches(selector)) out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
        walk(el);
      }
    })(root || document);
    return out;
  }
  /** The parent, stepping from a shadow root out to its host. */
  const upFrom = (el) => el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null);
  /** `el` itself or its nearest ancestor matching, crossing shadow roots. */
  function closestDeep(el, selector) {
    for (let e = el; e; e = upFrom(e)) if (e.matches(selector)) return e;
    return null;
  }
  /** Whether `inner` sits inside `outer`, crossing shadow roots. */
  function holds(outer, inner) {
    for (let e = inner; e; e = upFrom(e)) if (e === outer) return true;
    return false;
  }
  /** The element with the cursor, looking inside shadow roots. */
  function activeDeep() {
    let a = document.activeElement;
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    return a;
  }

  /** Climb from a message box to the conversation around it: the nearest ancestor with message bodies in it and no other message box. */
  function conversationOf(composer, composers) {
    for (let el = upFrom(composer); el && el !== document.body; el = upFrom(el)) {
      if (composers.some((c) => c !== composer && holds(el, c))) return null;
      if (deepAll(BODY, el).length) return el;
    }
    return null;
  }

  const isComposer = (el) => el.getAttribute('role') === 'textbox' ||
    /message|reply|write/i.test(`${el.getAttribute('aria-label') || ''} ${el.getAttribute('data-placeholder') || ''}`) ||
    !!closestDeep(el, 'form');

  /** The message boxes drawn on the page; when none reports a size (a layout that hides it from measuring), every box. */
  function composersShown() {
    const all = deepAll(EDITABLE).filter(isComposer);
    const drawn = all.filter(shown);
    return drawn.length ? drawn : all;
  }

  /** What the page showed, for the error: so a failure on a layout nobody has seen says what was there. */
  function census() {
    return `${deepAll(EDITABLE).length} editable boxes, ${deepAll(BODY).length} messages`;
  }

  /**
   * No message box could be tied to the messages (a box LinkedIn built another way, or one that isn't drawn yet): when
   * exactly one thread's messages are showing, read those. The box is then missing, so fill() will refuse.
   */
  function threadWithoutBox() {
    const all = deepAll(BODY);
    const bodies = all.filter(shown).length ? all.filter(shown) : all;
    if (!bodies.length) return null;
    const groups = new Map();
    for (const b of bodies) {
      const box = closestDeep(b, THREAD) || closestDeep(b, 'main') || closestDeep(b, 'ul, ol') || upFrom(b);
      groups.set(box, (groups.get(box) || 0) + 1);
    }
    if (groups.size > 1) return null;
    return { composer: null, box: [...groups.keys()][0] };
  }

  /** The conversation to use: the only one showing, or the one whose box has the person's cursor. */
  function find() {
    const composers = composersShown();
    const found = composers.map((composer) => ({ composer, box: conversationOf(composer, composers) })).filter((c) => c.box);
    if (!found.length) return threadWithoutBox() || { error: `${NONE} (The page showed ${census()}.)` };
    if (found.length === 1) return found[0];
    const active = activeDeep();
    const focused = found.find((c) => holds(c.composer, active) || holds(c.box, active));
    return focused || { error: TOO_MANY };
  }

  /** Who the conversation is with: the name in its header, else the sender of its last message. */
  function counterpart(box, composers, last) {
    let up = box;
    for (let i = 0; i < 4 && up; i++, up = upFrom(up)) {
      if (composers.some((c) => holds(up, c) && !holds(box, c))) break;
      const header = deepAll(HEADER, up)[0];
      if (header && text(header)) return text(header);
    }
    return last || '';
  }

  /** The messages in document order, each with the sender and the time LinkedIn showed above it. */
  function messagesIn(box) {
    const out = [];
    let sender = '', date = '', stamp = '';
    for (const el of deepAll(`${NAME}, ${STAMP}, ${BODY}`, box)) {
      if (el.matches(NAME)) {
        sender = text(el);
        stamp = '';
      } else if (el.matches(BODY)) {
        out.push({ sender, when: [date, stamp].filter(Boolean).join(', '), text: el.innerText || el.textContent });
      } else if (el.matches('[class*="time-heading"]') || !/\d{1,2}:\d{2}/.test(text(el))) {
        date = text(el);
      } else {
        stamp = text(el);
      }
    }
    return out;
  }

  function read() {
    const hit = find();
    if (hit.error) return { ok: false, error: hit.error };
    const messages = messagesIn(hit.box);
    const thread = JW.formatThread(messages);
    if (!thread) return { ok: false, error: UNREADABLE };
    const last = messages.length ? messages[messages.length - 1].sender : '';
    const composers = composersShown();
    return { ok: true, thread, count: messages.length, last, sender: counterpart(hit.box, composers, last), fingerprint: JW.fingerprint(thread) };
  }

  /**
   * Put `reply` in the open conversation's message box. Refused (filled: false, with a reason) when another conversation
   * is open now (`fingerprint` is the one read()), or when the box already has text and the person didn't say to replace it.
   * Typing is imitated with the editor's own insertText, so LinkedIn's editor sees real input and enables its Send button;
   * nothing is clicked.
   */
  function fill(reply, opts) {
    const o = opts || {};
    const hit = find();
    if (hit.error) return { filled: false, reason: 'gone', error: hit.error };
    if (o.fingerprint && JW.fingerprint(JW.formatThread(messagesIn(hit.box))) !== o.fingerprint) {
      return { filled: false, reason: 'changed', error: 'This conversation has changed since the draft was written. Draft the reply again.' };
    }
    const box = hit.composer;
    if (!box) return { filled: false, reason: 'gone', error: "The message box isn't showing. Open it, then try again." };
    if (text(box) && !o.replace) return { filled: false, reason: 'has-text', error: 'The message box already has text in it.' };
    box.focus();
    const range = document.createRange();
    range.selectNodeContents(box);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    let done = false;
    try {
      done = document.execCommand('insertText', false, reply);
    } catch {
      /* fall through to the manual way */
    }
    if (!done || text(box) === '') {
      box.replaceChildren(...String(reply).split('\n').map((line) => {
        const p = document.createElement('p');
        p.textContent = line;
        return p;
      }));
      box.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: reply }));
    }
    return text(box) ? { filled: true } : { filled: false, reason: 'failed', error: "Couldn't put the reply in the message box. Copy it from the panel." };
  }

  globalThis.JWReply = { read, fill };
})();
