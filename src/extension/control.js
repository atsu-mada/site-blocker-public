'use strict';
// Shared by the toolbar popup (popup.html) and the control page (control.html, also opened by typing `sb` in the
// address bar). A hand-made pause waits 10 seconds before it takes effect and lasts at most 30 minutes,
// so turning blocking off on impulse takes a moment of thought. `blockctl` has no wait.
(function () {
  const C = globalThis.SiteBlockerCore;
  const CONFIRM_SECONDS = 10;
  const $ = (id) => document.getElementById(id);
  let timer = null;

  function clock(ms) {
    return new Date(ms).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  }

  function chosenMinutes() {
    return Number($('minutes').value) || C.DEFAULT_PAUSE;
  }

  function labelPause() {
    $('pause').textContent = `${chosenMinutes()}分だけオフにする`;
  }

  function render(status) {
    if (!status || status.error) {
      $('state').textContent = '状態を読めません';
      return;
    }
    const enabled = status.enabled;
    $('panel').classList.toggle('off', !enabled);
    if (enabled) {
      $('state').textContent = 'ブロック中 ⚠';
      $('detail').textContent = '';
      $('sites').textContent = `いま ${status.sites} サイトを止めています。`;
    } else {
      const left = Math.max(1, Math.ceil((status.offUntil - Date.now()) / 60000));
      $('state').textContent = 'オフ';
      $('detail').textContent = `あと ${left} 分（${clock(status.offUntil)} に自動でオン）`;
    }
    $('detail').hidden = enabled;
    if (!enabled) $('sites').textContent = `オンに戻ると ${status.sites} サイトを止めます。`;
    $('off-controls').hidden = !enabled;
    $('on-controls').hidden = enabled;
    if (!enabled) stopCountdown();
    const warnings = [];
    if (!status.hostConnected) warnings.push('ホスト（blockctl と一覧ファイルを扱うローカルのプログラム）につながっていません（一覧の更新と blockctl が止まっています）。');
    if (enabled && status.activeRules !== status.expectedRules) {
      warnings.push(`効いている規則が ${status.activeRules} 件で、一覧の ${status.expectedRules} 件と合いません。`);
    }
    if (status.listErrors && status.listErrors.length) warnings.push(`一覧の読み取りで問題: ${status.listErrors[0]}`);
    $('warning').hidden = warnings.length === 0;
    $('warning').textContent = warnings.join(' ');
    document.title = document.body.classList.contains('page')
      ? `${enabled ? 'ブロック中' : 'オフ'} - Site Blocker` : document.title;
  }

  async function refresh() {
    try {
      render(await chrome.runtime.sendMessage({ cmd: 'status' }));
    } catch (error) {
      render({ error: String(error) });
    }
  }

  function stopCountdown() {
    clearInterval(timer);
    timer = null;
    $('confirm').hidden = true;
    $('pause').hidden = false;
    $('minutes').disabled = false;
  }

  function startCountdown() {
    const minutes = chosenMinutes();
    let left = CONFIRM_SECONDS;
    const show = () => { $('countdown').textContent = `あと ${left} 秒で ${minutes}分オフ`; };
    $('pause').hidden = true;
    $('confirm').hidden = false;
    $('minutes').disabled = true;
    show();
    $('cancel').focus();
    timer = setInterval(async () => {
      left -= 1;
      if (left > 0) return show();
      stopCountdown();
      render(await chrome.runtime.sendMessage({ cmd: 'pause', minutes }));
    }, 1000);
  }

  const preset = C.pauseFromQuery(location.search);
  $('minutes').value = String(preset);
  $('minutes').addEventListener('change', labelPause);
  labelPause();

  $('pause').addEventListener('click', startCountdown);
  $('cancel').addEventListener('click', stopCountdown);
  $('resume').addEventListener('click', async () => {
    render(await chrome.runtime.sendMessage({ cmd: 'resume' }));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && timer) stopCountdown();
  });

  // Follow changes made elsewhere (blockctl, another tab, the timer running out).
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && (changes.offUntil || changes.lastStatus || changes.sites)) refresh();
  });
  setInterval(refresh, 15000);
  refresh();
})();
