import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const extensionRoot = path.join(repositoryRoot, 'src/extension');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`globalThis = this; ${await readFile(path.join(extensionRoot, 'core.js'), 'utf8')}`, sandbox);
const C = sandbox.SiteBlockerCore;
const manifest = JSON.parse(await readFile(path.join(extensionRoot, 'manifest.json'), 'utf8'));
const defaults = JSON.parse(await readFile(path.join(extensionRoot, 'default-sites.json'), 'utf8'));

const blocked = (entries, url) => Boolean(C.matchingEntry(C.uniqueEntries(entries), url));

test('entries normalize scheme, www, case, and trailing slash', () => {
  assert.equal(C.normalizeEntry('https://www.LinkedIn.com/').text, 'linkedin.com');
  assert.equal(C.normalizeEntry('mail.google.com/chat/').text, 'mail.google.com/chat');
  assert.equal(C.normalizeEntry('*.slack.com').wildcard, true);
  assert.equal(C.normalizeEntry('not a site'), null);
  assert.equal(C.normalizeEntry('localhost'), null);
});

test('a plain entry blocks the host and www only', () => {
  assert.ok(blocked(['linkedin.com'], 'https://www.linkedin.com/feed/'));
  assert.ok(blocked(['linkedin.com'], 'https://linkedin.com'));
  assert.ok(blocked(['amazon.co.jp'], 'https://www.amazon.co.jp/?tag=x'));
  assert.ok(!blocked(['amazon.co.jp'], 'https://read.amazon.co.jp/kindle-library'));
  assert.ok(!blocked(['x.com'], 'https://box.com/'));
  assert.ok(!blocked(['x.com'], 'https://example.com/?next=https://x.com/home'));
  assert.ok(!blocked(['slack.com'], 'https://app.slack.com/client'));
});

test('a wildcard entry blocks every subdomain and a path entry only that path', () => {
  assert.ok(blocked(['*.slack.com'], 'https://app.slack.com/client'));
  assert.ok(blocked(['*.slack.com'], 'https://slack.com/'));
  assert.ok(blocked(['mail.google.com/chat'], 'https://mail.google.com/chat/u/0/'));
  assert.ok(!blocked(['mail.google.com/chat'], 'https://mail.google.com/mail/u/0/'));
  assert.ok(!blocked(['mail.google.com/chat'], 'https://mail.google.com/chatter'));
});

test('rules redirect the main frame to the extension block page with the original URL', () => {
  const rules = C.buildRules(C.uniqueEntries(['linkedin.com', 'linkedin.com', 'example.org']), 'abc');
  assert.equal(rules.length, 2);
  assert.equal(rules.map((r) => r.id).join(','), '1,2');
  assert.equal(rules[0].action.redirect.regexSubstitution, 'chrome-extension://abc/blocked.html#\\0');
  assert.equal(JSON.stringify(rules[0].condition.resourceTypes), '["main_frame"]');
  assert.equal(rules[0].condition.isUrlFilterCaseSensitive, false);
});

test('the bundled fallback list is short and every entry parses', () => {
  assert.ok(defaults.length > 0 && defaults.length <= 50);
  assert.equal(C.uniqueEntries(defaults).length, defaults.length);
});

test('the manifest has no pinned key and asks only for what it uses', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.key, undefined);
  assert.deepEqual([...manifest.permissions].sort(),
    ['alarms', 'declarativeNetRequest', 'nativeMessaging', 'storage', 'webNavigation']);
  assert.ok(!manifest.permissions.includes('tabs'));
});

test('the manifest points at icons that exist, and the worker switches on/off icons', async () => {
  const { access } = await import('node:fs/promises');
  for (const file of Object.values(manifest.icons)) await access(path.join(extensionRoot, file));
  for (const size of [16, 32, 48, 128]) {
    for (const state of ['on', 'off']) await access(path.join(extensionRoot, `icons/${state}-${size}.png`));
  }
  const worker = await readFile(path.join(extensionRoot, 'background.js'), 'utf8');
  assert.match(worker, /chrome\.action\.setIcon/);
  assert.match(worker, /icons\/\$\{state\}-16\.png/);
});

test('the control page and the popup take ?for= only for 10, 20, or 30 minutes', () => {
  assert.equal(C.pauseFromQuery('?for=10'), 10);
  assert.equal(C.pauseFromQuery('?for=30'), 30);
  assert.equal(C.pauseFromQuery(''), 20);
  assert.equal(C.pauseFromQuery('?for=60'), 20);
  assert.equal(C.pauseFromQuery('?for=abc'), 20);
});

test('popup and control page share one panel, and the control page cannot be framed by web pages', async () => {
  const ids = (html) => [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]).filter((id) => id !== 'open-control');
  const popup = await readFile(path.join(extensionRoot, 'popup.html'), 'utf8');
  const control = await readFile(path.join(extensionRoot, 'control.html'), 'utf8');
  assert.equal(ids(popup).join(','), ids(control).join(','));
  for (const html of [popup, control]) assert.ok(html.includes('src="control.js"'));
  assert.equal(manifest.omnibox.keyword, 'sb');
  const exposed = manifest.web_accessible_resources.flatMap((entry) => entry.resources);
  assert.ok(exposed.includes('blocked.html'));
  assert.ok(!exposed.some((file) => file.startsWith('control') || file.startsWith('popup')));
  const blocked = await readFile(path.join(extensionRoot, 'blocked.html'), 'utf8');
  assert.ok(!/pause|resume|オフ/.test(blocked), 'the block page has no way to unblock');
});
