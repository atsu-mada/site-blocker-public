'use strict';
(function () {
  const original = location.hash.slice(1);
  let host = '';
  try {
    host = new URL(original).hostname.replace(/^www\./, '');
  } catch (error) {
    host = '';
  }
  // Fill both tapes; the text is doubled so the sideways run loops without a gap.
  const tape = '⚠ 立入禁止　KEEP OUT　'.repeat(14);
  document.querySelectorAll('.run').forEach((run) => { run.textContent = tape + tape; });
  if (host) {
    document.getElementById('site').textContent = host;
    document.getElementById('site').classList.toggle('long', host.length > 24);
    document.title = `${host} はブロック中`;
  }
  document.getElementById('back').addEventListener('click', () => {
    if (history.length > 1) history.back();
    else location.replace('about:blank');
  });
  document.getElementById('close').addEventListener('click', () => {
    // tabs.getCurrent and tabs.remove need no permission for the extension's own tab.
    chrome.tabs.getCurrent((tab) => {
      if (tab && tab.id !== undefined) chrome.tabs.remove(tab.id);
      else window.close();
    });
  });
})();
