(() => {
  'use strict';
  const tabs = [...document.querySelectorAll('[data-demo-target]')];
  if (tabs.length < 2) return;

  const select = (tab) => {
    for (const candidate of tabs) {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(candidate.dataset.demoTarget);
      if (!panel) continue;
      panel.hidden = !selected;
      if (!selected) panel.querySelector('video')?.pause();
    }
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  });
})();
