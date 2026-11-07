// Shared logic of the Site Blocker extension: list entries, blocking rules, and URL matching.
// Loaded by the service worker (importScripts) and by the Node tests (vm), so it has no browser calls.
(function (root) {
  'use strict';

  // One list entry: "example.com", "*.example.com" (every subdomain), or "example.com/path".
  const ENTRY_RX = /^(\*\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(\/[^\s?#]*)?$/;
  const MAX_ENTRIES = 1000;

  function normalizeEntry(raw) {
    if (typeof raw !== 'string') return null;
    let text = raw.trim().toLowerCase();
    text = text.replace(/^https?:\/\//, '').replace(/^www\./, '');
    const match = ENTRY_RX.exec(text);
    if (!match) return null;
    const path = (match[3] || '').replace(/\/+$/, '');
    return { wildcard: Boolean(match[1]), host: match[2], path, text: (match[1] || '') + match[2] + path };
  }

  function escapeRegex(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function entryPattern(entry) {
    const host = escapeRegex(entry.host);
    const hostPart = entry.wildcard ? `([a-z0-9-]+\\.)*${host}` : `(www\\.)?${host}`;
    return `^https?://${hostPart}(:[0-9]+)?${escapeRegex(entry.path)}([/?#].*)?$`;
  }

  function uniqueEntries(rawList) {
    const seen = new Set();
    const out = [];
    for (const raw of rawList || []) {
      const entry = normalizeEntry(raw);
      if (!entry || seen.has(entry.text)) continue;
      seen.add(entry.text);
      out.push(entry);
      if (out.length >= MAX_ENTRIES) break;
    }
    return out;
  }

  function buildRules(entries, extensionId) {
    return entries.map((entry, index) => ({
      id: index + 1,
      priority: 1,
      action: {
        type: 'redirect',
        redirect: { regexSubstitution: `chrome-extension://${extensionId}/blocked.html#\\0` }
      },
      condition: {
        regexFilter: entryPattern(entry),
        isUrlFilterCaseSensitive: false,
        resourceTypes: ['main_frame']
      }
    }));
  }

  function matchingEntry(entries, url) {
    for (const entry of entries) {
      if (new RegExp(entryPattern(entry), 'i').test(url)) return entry;
    }
    return null;
  }

  function isOff(offUntil, now) {
    return typeof offUntil === 'number' && offUntil > now;
  }

  // Off durations a person can choose by hand (popup and control page); `?for=10` preselects one.
  const PAUSE_CHOICES = [10, 20, 30];
  const DEFAULT_PAUSE = 20;

  function pauseFromQuery(search) {
    const match = /[?&]for=(\d+)(?:&|$)/.exec(String(search || ''));
    const value = match ? Number(match[1]) : NaN;
    return PAUSE_CHOICES.includes(value) ? value : DEFAULT_PAUSE;
  }

  root.SiteBlockerCore = {
    normalizeEntry, entryPattern, uniqueEntries, buildRules, matchingEntry, isOff, pauseFromQuery,
    PAUSE_CHOICES, DEFAULT_PAUSE, MAX_ENTRIES
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
