/**
 * The theme, for the side panel and the settings page: System (the default, follows the computer), Light or Dark.
 * The choice is kept in chrome.storage.local ("theme"), changed on the settings page, and applied here to both pages,
 * including a page that is already open when it changes. An earlier version kept it in the page's localStorage; that
 * choice is carried over once.
 */
(function () {
  'use strict';
  const root = document.documentElement;
  const apply = (value) => {
    const theme = globalThis.JW.themeChoice(value);
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
  };

  chrome.storage.local.get('theme').then(({ theme }) => {
    if (theme === undefined) {
      try {
        theme = localStorage.getItem('theme') || undefined;
        if (theme) chrome.storage.local.set({ theme });
      } catch {
        /* no old choice to carry over */
      }
    }
    apply(theme);
  }, () => {});
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.theme) apply(changes.theme.newValue);
  });
})();
