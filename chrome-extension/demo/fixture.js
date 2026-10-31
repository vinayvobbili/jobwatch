/*
 * Behaviour the demo forms share, so they act like the real boards the extension meets: inputs that ignore a
 * plain `.value =` (React's value tracker), react-select style dropdowns, Yes/No buttons, drop zones, and a
 * submit that checks required fields and counts itself. window.__state / __submits are what the tests read.
 */
window.__state = {};
window.__submits = 0;

// Controlled inputs: a value set the plain way doesn't count, only a real input event does.
document.querySelectorAll('[data-controlled]').forEach((el) => {
  const proto = Object.getPrototypeOf(el);
  const native = Object.getOwnPropertyDescriptor(proto, 'value');
  let tracked = el.value;
  Object.defineProperty(el, 'value', {
    configurable: true,
    get: () => native.get.call(el),
    set: (v) => { tracked = String(v); native.set.call(el, v); },
  });
  el.addEventListener('input', () => {
    const now = native.get.call(el);
    if (now !== tracked) { tracked = now; window.__state[el.name || el.id] = now; }
  });
});

// react-select look-alike: the menu is built on mousedown or ArrowDown, an option is chosen on click.
document.querySelectorAll('.select__control').forEach((control) => {
  const input = control.querySelector('input');
  const options = (input.dataset.options || '').split('|');
  const holder = control.querySelector('.select__value-container');
  let menu = null;
  const close = () => { if (menu) menu.remove(); menu = null; input.setAttribute('aria-expanded', 'false'); };
  const open = () => {
    if (menu) return;
    menu = document.createElement('div');
    menu.className = 'select__menu';
    menu.setAttribute('role', 'listbox');
    menu.id = `${input.id}-listbox`;
    input.setAttribute('aria-controls', menu.id);
    input.setAttribute('aria-expanded', 'true');
    const draw = () => {
      menu.innerHTML = '';
      const typed = input.value.toLowerCase();
      options.filter((o) => o.toLowerCase().includes(typed)).forEach((o) => {
        const opt = document.createElement('div');
        opt.className = 'select__option';
        opt.setAttribute('role', 'option');
        opt.textContent = o;
        opt.addEventListener('click', () => {
          holder.querySelectorAll('.select__placeholder, .select__single-value').forEach((n) => n.remove());
          const v = document.createElement('div');
          v.className = 'select__single-value';
          v.textContent = o;
          holder.prepend(v);
          window.__state[input.id] = o;
          const required = control.parentElement.querySelector('.select__required'); // react-select keeps it in step
          if (required) required.value = o;
          input.value = '';
          close();
        });
        menu.append(opt);
      });
    };
    draw();
    input.addEventListener('input', draw);
    control.after(menu);
  };
  control.addEventListener('mousedown', (e) => { e.preventDefault(); input.focus(); menu ? close() : open(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') open();
    if (e.key === 'Escape') close();
  });
});

// Ashby's Yes/No buttons
document.querySelectorAll('._yesno_').forEach((box) => {
  box.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    box.querySelectorAll('button').forEach((n) => n.classList.remove('_active_'));
    b.classList.add('_active_');
    window.__state[box.dataset.name] = b.textContent.trim();
  }));
});

// Resume drop zones
document.querySelectorAll('.drop-zone').forEach((zone) => {
  const input = zone.querySelector('input[type="file"]');
  const show = (f) => { zone.querySelector('.file-name').textContent = f.name; window.__state.resume = f.name; };
  input.addEventListener('change', () => input.files[0] && show(input.files[0]));
  zone.addEventListener('dragover', (e) => e.preventDefault());
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    window.__state.dropped = true;
    if (e.dataTransfer.files[0]) show(e.dataTransfer.files[0]);
  });
});

// Submit: required fields first, then a thank-you (inline, or a page of its own when data-thanks says).
document.addEventListener('submit', (e) => {
  e.preventDefault();
  const form = e.target;
  let bad = false;
  form.querySelectorAll('.field-error').forEach((n) => n.remove());
  form.querySelectorAll('[aria-invalid]').forEach((n) => n.removeAttribute('aria-invalid'));
  form.querySelectorAll('[required]').forEach((el) => {
    if (el.type === 'file' || el.type === 'checkbox') return;
    const empty = el.type === 'radio' ? !form.querySelector(`[name="${el.name}"]:checked`) : !el.value.trim();
    if (!empty) return;
    bad = true;
    el.setAttribute('aria-invalid', 'true');
    const msg = document.createElement('div');
    msg.className = 'field-error';
    msg.textContent = 'This field is required';
    el.after(msg);
  });
  if (bad) return;
  window.__submits++;
  if (form.dataset.thanks) location.href = form.dataset.thanks;
  else document.querySelector('.confirmation').hidden = false;
});
