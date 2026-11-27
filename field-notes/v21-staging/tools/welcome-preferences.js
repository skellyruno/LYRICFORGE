/* Welcome preferences are local UI only, never saved in a project or export. */
(() => {
  'use strict';
  const key = 'skellymotion-welcome-appearance-v1';
  const root = document.documentElement;
  const theme = document.getElementById('welcomeAppearance');
  const art = document.getElementById('welcomeArtwork');
  if (!theme || !art) return;
  const normalize = value => ({
    theme: value?.theme === 'clean' ? 'clean' : 'skelly',
    artwork: value?.artwork !== false
  });
  let value = normalize(null);
  try { value = normalize(JSON.parse(localStorage.getItem(key))); } catch {}
  const apply = next => {
    value = normalize(next);
    root.dataset.welcomeAppearance = value.theme;
    root.dataset.welcomeArtwork = value.artwork ? 'show' : 'hide';
    theme.value = value.theme;
    art.checked = value.artwork;
  };
  const save = () => {
    apply({theme: theme.value, artwork: art.checked});
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  };
  theme.addEventListener('change', save);
  art.addEventListener('change', save);
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    try { apply(JSON.parse(event.newValue)); } catch { apply(null); }
  });
  apply(value);
})();
