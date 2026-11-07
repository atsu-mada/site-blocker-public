// Site Blocker service worker.
// The native host (local.site_blocker.host) sends the site list from the list file and the off/on
// state written by `blockctl`; this worker turns them into dynamic blocking rules and reports how many rules
// Chrome actually holds, so `blockctl status` reads the real state instead of a label.
importScripts('core.js');

const C = globalThis.SiteBlockerCore;
const HOST_NAME = 'local.site_blocker.host';
const POPUP_MAX_MINUTES = 30;
const DEFAULTS = { sites: [], offUntil: 0, listUpdatedAt: null, listErrors: [], hostError: null, hostErrorAt: null };

let port = null;

async function loadState() {
  return chrome.storage.local.get(DEFAULTS);
}

async function ensureSites() {
  const state = await loadState();
  if (state.sites.length) return;
  // First start without the host: use the list bundled at install time, so blocking is never empty by mistake.
  try {
    const response = await fetch(chrome.runtime.getURL('default-sites.json'));
    const sites = await response.json();
    if (Array.isArray(sites) && sites.length) await chrome.storage.local.set({ sites, listUpdatedAt: 'bundled' });
  } catch (error) {
    await chrome.storage.local.set({ listErrors: [`bundled list unreadable: ${error}`] });
  }
}

async function currentStatus(reason) {
  const state = await loadState();
  const rules = await chrome.declarativeNetRequest.getDynamicRules();
  const entries = C.uniqueEntries(state.sites);
  return {
    type: 'status',
    reason,
    enabled: !C.isOff(state.offUntil, Date.now()),
    offUntil: state.offUntil || 0,
    activeRules: rules.length,
    expectedRules: entries.length,
    sites: entries.length,
    listUpdatedAt: state.listUpdatedAt,
    listErrors: state.listErrors,
    hostConnected: Boolean(port),
    hostError: state.hostError,
    version: chrome.runtime.getManifest().version,
    at: Date.now()
  };
}

async function report(reason) {
  const status = await currentStatus(reason);
  await chrome.storage.local.set({ lastStatus: status });
  if (port) {
    try {
      port.postMessage(status);
    } catch (error) {
      port = null;
    }
  }
  return status;
}

async function apply(reason) {
  await ensureSites();
  const state = await loadState();
  const off = C.isOff(state.offUntil, Date.now());
  const existing = await chrome.declarativeNetRequest.getDynamicRules();
  const addRules = off ? [] : C.buildRules(C.uniqueEntries(state.sites), chrome.runtime.id);
  await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: existing.map((rule) => rule.id), addRules });
  if (off) {
    await chrome.alarms.create('reenable', { when: state.offUntil });
  } else {
    await chrome.alarms.clear('reenable');
  }
  await showState(off, state.offUntil);
  return report(reason);
}

// Toolbar icon: vermilion while blocking, grey while paused (icons built by src/tools/build_icons.py).
async function showState(off, offUntil) {
  const state = off ? 'off' : 'on';
  await chrome.action.setIcon({ path: { 16: `icons/${state}-16.png`, 32: `icons/${state}-32.png` } });
  const until = off ? new Date(offUntil).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
  await chrome.action.setTitle({ title: off ? `Site Blocker: オフ（${until} まで）` : 'Site Blocker: ブロック中' });
}

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (error) {
    port = null;
    chrome.storage.local.set({ hostError: String(error), hostErrorAt: Date.now() });
    return;
  }
  port.onMessage.addListener(async (message) => {
    if (!message || typeof message !== 'object') return;
    if (message.type === 'config') {
      const update = { offUntil: Number(message.offUntil) || 0, listErrors: message.listErrors || [], hostError: null };
      // An empty or unreadable list never replaces a working one.
      if (Array.isArray(message.sites) && C.uniqueEntries(message.sites).length) {
        update.sites = message.sites;
        update.listUpdatedAt = message.listUpdatedAt || null;
      }
      await chrome.storage.local.set(update);
      await apply('config');
    } else if (message.type === 'ping') {
      await report('ping');
    }
  });
  port.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError ? chrome.runtime.lastError.message : 'disconnected';
    port = null;
    chrome.storage.local.set({ hostError: reason, hostErrorAt: Date.now() });
  });
}

async function setOffUntil(offUntil, by) {
  await chrome.storage.local.set({ offUntil });
  if (port) {
    try {
      port.postMessage(offUntil ? { type: 'pause', until: offUntil, by } : { type: 'resume', by });
    } catch (error) {
      port = null;
    }
  }
  return apply(by);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (sender.id !== chrome.runtime.id) return sendResponse({ error: 'unknown sender' });
    if (message.cmd === 'status') return sendResponse(await currentStatus('popup'));
    if (message.cmd === 'pause') {
      const minutes = Math.min(Math.max(1, Math.floor(Number(message.minutes) || 0)), POPUP_MAX_MINUTES);
      return sendResponse(await setOffUntil(Date.now() + minutes * 60000, 'popup-pause'));
    }
    if (message.cmd === 'resume') return sendResponse(await setOffUntil(0, 'popup-resume'));
    return sendResponse({ error: 'unknown command' });
  })();
  return true;
});

// Typing `sb` and Enter in the address bar opens the control page; `sb 10` preselects 10 minutes.
chrome.omnibox.setDefaultSuggestion({ description: 'Site Blocker の操作ページを開く（sb 10 で10分を選んだ状態）' });
chrome.omnibox.onInputEntered.addListener((text, disposition) => {
  const minutes = String(text || '').trim().match(/^\d+/);
  const url = chrome.runtime.getURL(`control.html${minutes ? `?for=${minutes[0]}` : ''}`);
  if (disposition === 'currentTab') chrome.tabs.update({ url });
  else chrome.tabs.create({ url, active: disposition === 'newForegroundTab' });
});

// Safety net for pages a service worker serves without a network request (seen with x.com).
chrome.webNavigation.onCommitted.addListener(async (details) => {
  if (details.frameId !== 0 || !/^https?:/.test(details.url)) return;
  const state = await loadState();
  if (C.isOff(state.offUntil, Date.now())) return;
  if (C.matchingEntry(C.uniqueEntries(state.sites), details.url)) {
    await chrome.tabs.update(details.tabId, { url: `${chrome.runtime.getURL('blocked.html')}#${details.url}` });
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'reenable') {
    await apply('reenable');
    return;
  }
  connect();
  const state = await loadState();
  // Without the host, an expired pause still ends here.
  if (!port || (state.offUntil && !C.isOff(state.offUntil, Date.now()))) await apply('keepalive');
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('keepalive', { periodInMinutes: 1 });
  connect();
  apply('installed');
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create('keepalive', { periodInMinutes: 1 });
  connect();
  apply('startup');
});

connect();
