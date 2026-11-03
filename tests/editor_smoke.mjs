/**
 * SkellyMotion browser-logic smoke test.
 * No browser, network, models or external npm dependencies are required.
 * Catches missing element IDs, dead startup handlers, and clip-editor regressions.
 */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const html = fs.readFileSync('static/index.html', 'utf8');
const script = fs.readFileSync('static/app.js', 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
assert.equal(new Set(ids).size, ids.length, 'HTML contains duplicate IDs');

function classList(initial = []) {
  const found = new Set(initial);
  return {
    add: name => found.add(name),
    remove: name => found.delete(name),
    contains: name => found.has(name),
    toggle(name, enabled = !found.has(name)) {
      if (enabled) found.add(name);
      else found.delete(name);
      return enabled;
    }
  };
}
function element(id) {
  const callbacks = Object.create(null);
  const node = {
    id, callbacks, dataset: {}, style: { setProperty(key, value) { this[key] = value; } },
    classList: classList(), clientWidth: 1000, clientHeight: 700,
    offsetWidth: 1400, offsetHeight: 950, width: 450, height: 800,
    disabled: false, textContent: '', children: [], files: [],
    addEventListener(type, fn) { (callbacks[type] ??= []).push(fn); },
    click() {
      for (const fn of callbacks.click ?? []) fn({ target: node, preventDefault() {} });
    },
    setAttribute(key, value) { this[key] = value; },
    getAttribute(key) { return this[key]; },
    removeAttribute(key) { delete this[key]; },
    appendChild(child) { this.children.push(child); },
    append(child) { this.children.push(child); },
    remove() {}, focus() {}, pause() {}, load() {},
    play() { return Promise.resolve(); },
    setPointerCapture() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getBoundingClientRect() {
      return { left: 0, top: 0, width: this.offsetWidth * .65, height: this.offsetHeight * .65 };
    },
    getContext() {
      return {
        clearRect() {}, fillRect() {}, strokeText() {}, fillText() {},
        measureText(text) { return { width: text.length * 9 }; },
        save() {}, restore() {}, translate() {}, scale() {},
        createLinearGradient() { return { addColorStop() {} }; },
        createRadialGradient() { return { addColorStop() {} }; }
      };
    }
  };
  return node;
}
const nodes = Object.fromEntries(ids.map(id => [id, element(id)]));
const groups = Object.create(null);
for (const match of html.matchAll(/<(?:button|div|nav)\b([^>]*)>/g)) {
  const attrs = match[1];
  const id = attrs.match(/\bid="([^"]+)"/)?.[1];
  const node = id ? nodes[id] : element('generated');
  const classes = attrs.match(/\bclass="([^"]+)"/)?.[1]?.split(/\s+/) ?? [];
  node.classList = classList(classes);
  for (const name of classes) (groups['.' + name] ??= []).push(node);
  for (const attr of attrs.matchAll(/\bdata-([\w-]+)="([^"]*)"/g)) {
    const key = attr[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    node.dataset[key] = attr[2];
    (groups['[data-' + attr[1] + ']'] ??= []).push(node);
  }
}
const doc = {
  hidden: false, body: element('body'), listeners: Object.create(null),
  getElementById(id) {
    assert.ok(nodes[id], 'Missing UI ID: ' + id);
    return nodes[id];
  },
  querySelectorAll(selector) { return groups[selector] ?? []; },
  createElement(tag) { return element(tag); },
  addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
};
const win = {
  listeners: Object.create(null),
  addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
};
const storage = new Map();
const localStorage = {
  getItem(key) { return storage.get(key) ?? null; },
  setItem(key, value) { storage.set(key, String(value)); },
  removeItem(key) { storage.delete(key); }
};
const context = {
  document: doc, window: win, localStorage,
  performance: { now() { return 0; } },
  crypto: { randomUUID() { return 'a1234567-2345-3456-4567-789123456789'; } },
  requestAnimationFrame() {},
  setTimeout() { return 1; }, clearTimeout() {},
  getComputedStyle(node) {
    return { getPropertyValue(key) { return node.style[key] || ''; } };
  },
  fetch() { return Promise.reject(Error('Network disabled during smoke test')); },
  Blob, URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
  console
};
vm.runInNewContext(script, context, { filename: 'static/app.js' });
nodes.demoBtn.click();
assert.equal(nodes.clipCount.textContent, '6 clips', 'Demo should load six lyric clips');

nodes.duplicateLineBtn.click();
assert.equal(nodes.clipCount.textContent, '7 clips', 'Duplicate must add one clip');
nodes.undoBtn.click();
assert.equal(nodes.clipCount.textContent, '6 clips', 'Undo must restore prior clip count');
nodes.redoBtn.click();
assert.equal(nodes.clipCount.textContent, '7 clips', 'Redo must restore duplicated clip');
nodes.splitLineBtn.click();
assert.equal(nodes.clipCount.textContent, '8 clips', 'Split must add one clip');
nodes.deleteLineBtn.click();
assert.equal(nodes.clipCount.textContent, '7 clips', 'Delete must remove one clip');

nodes.snapBtn.click();
assert.equal(nodes.snapBtn['aria-pressed'], 'true', 'Snap toggle should update accessible state');
nodes.snapBtn.click();
assert.equal(nodes.snapBtn['aria-pressed'], 'false', 'Snap should turn back off');

const mode = groups['[data-mode]']?.find(x => x.dataset.mode === 'karaoke');
assert.ok(mode, 'Karaoke mode button should exist');
mode.click();
assert.equal(mode.classList.contains('selected'), true, 'Mode should be selectable');

nodes.saveLookBtn.click();
assert.ok(storage.get('skellymotion-my-look-v1'), 'Personal style should be saved locally');
nodes.loadLookBtn.click();
nodes.resetLookBtn.click();
nodes.zoomFit.click();
nodes.prevClipBtn.click();
nodes.nextClipBtn.click();
nodes.shortcutsBtn.click();
assert.equal(nodes.shortcutsOverlay.classList.contains('hidden'), false);
nodes.closeShortcuts.click();
assert.equal(nodes.shortcutsOverlay.classList.contains('hidden'), true);
nodes.exportSrtBtn.click();

console.log('SkellyMotion editor smoke tests passed: load, edit, undo, redo, split, delete, snap, styles, layout tools, SRT.');
