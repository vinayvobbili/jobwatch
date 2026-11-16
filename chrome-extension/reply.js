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
 * They were written from LinkedIn's markup as remembered, not checked against the live site: tests/test_extension_e2e.py
 * runs this against demo/linkedin-messages.html, which imitates it.
 *
 * Needs logic.js loaded first (formatThread, fingerprint).
 */
(function () {
  'use strict';
  if (globalThis.JWReply) return;
  const JW = globalThis.JW;

  const COMPOSER = '[role="textbox"][contenteditable="true"], [role="textbox"][contenteditable=""]';
  const BODY = '[class*="event-listitem__body"], [data-event-urn] p';
  const NAME = '[class*="message-group__name"]';
  const STAMP = 'time, [class*="message-group__timestamp"], [class*="time-heading"]';
  const HEADER = '[class*="msg-entity-lockup__entity-title"], [class*="msg-overlay-bubble-header__title"], ' +
    '[class*="msg-thread__link-to-profile"], [class*="thread-header"] h2';

  const TOO_MANY = 'More than one conversation is open here. Click into the message box of the one you want a reply for, then try again.';
  const NONE = 'No conversation is open. Open the recruiter\'s message (its message box must be showing) and try again.';
  const UNREADABLE = "Couldn't read the messages in this conversation. LinkedIn may have changed its page: copy the message into jobwatch's draft-reply command instead.";

  const text = (el) => String(el.textContent || '').replace(/[​​\s]+/g, ' ').trim();
  const shown = (el) => el.getClientRects().length > 0;

  /** Climb from a message box to the conversation around it: the nearest ancestor with message bodies in it and no other message box. */
  function conversationOf(composer, composers) {
    for (let el = composer.parentElement; el && el !== document.body; el = el.parentElement) {
      if (composers.some((c) => c !== composer && el.contains(c))) return null;
      if (el.querySelector(BODY)) return el;
    }
    return null;
  }

  /** The conversation to use: the only one showing, or the one whose box has the person's cursor. */
  function find() {
    const composers = [...document.querySelectorAll(COMPOSER)].filter(shown);
    const found = composers.map((composer) => ({ composer, box: conversationOf(composer, composers) })).filter((c) => c.box);
    if (!found.length) return { error: NONE };
    if (found.length === 1) return found[0];
    const focused = found.find((c) => c.composer.contains(document.activeElement) || c.box.contains(document.activeElement));
    return focused || { error: TOO_MANY };
  }

  /** Who the conversation is with: the name in its header, else the sender of its last message. */
  function counterpart(box, composers, last) {
    let up = box;
    for (let i = 0; i < 4 && up; i++, up = up.parentElement) {
      if (composers.some((c) => up.contains(c) && !box.contains(c))) break;
      const header = up.querySelector(HEADER);
      if (header && text(header)) return text(header);
    }
    return last || '';
  }

  /** The messages in document order, each with the sender and the time LinkedIn showed above it. */
  function messagesIn(box) {
    const out = [];
    let sender = '', date = '', stamp = '';
    for (const el of box.querySelectorAll(`${NAME}, ${STAMP}, ${BODY}`)) {
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
    const composers = [...document.querySelectorAll(COMPOSER)];
    return { ok: true, thread, count: messages.length, sender: counterpart(hit.box, composers, last), fingerprint: JW.fingerprint(thread) };
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
