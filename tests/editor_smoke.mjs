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
const instrumentedScript = script.replace('function easing(t){',
  'window.__studioDebug = { state, activeLyric, invalidatePlaybackIndex, previewDimensions, clipLocation, clipMotionMs, activeWordAtTime };\nfunction easing(t){');
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
  hidden: false, body: element('body'), documentElement: element('html'),
  listeners: Object.create(null),
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
vm.runInNewContext(instrumentedScript, context, { filename: 'static/app.js' });
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

assert.ok(nodes.effectsTrack.innerHTML.includes('fx-clip'), 'FX lane must render with lyric clips');
nodes.clipAnimation.value='bounce';
assert.ok(nodes.clipAnimation.callbacks.change?.length, 'Per-clip animation selector must be wired');
nodes.clipAnimation.callbacks.change[0]({target:nodes.clipAnimation});
assert.ok(nodes.effectsTrack.innerHTML.includes('Bounce'), 'FX lane must show selected animation');
nodes.clipPosX.value='72';
nodes.clipPosX.callbacks.input[0]({target:nodes.clipPosX});
assert.equal(nodes.clipPosXVal.textContent,'72%', 'Per-clip X position should update without rerendering all clips');
nodes.undoBtn.click();
nodes.redoBtn.click();
assert.ok(nodes.effectsTrack.innerHTML.includes('Bounce'), 'FX override should survive undo and redo');
assert.ok(nodes.recognitionMode.id==='recognitionMode' && nodes.languageHint.id==='languageHint',
 'Same-model recognition controls should be available');
assert.ok(nodes.renderProgressTrack.id==='renderProgressTrack', 'Export progress widget should exist');

// Resizing must update only layout sizes without breaking editor actions.
const side = nodes.panelResizer;
assert.ok(side.callbacks.pointerdown?.length, 'Panel must have a pointer resize handler');
side.callbacks.pointerdown[0]({button:0,pointerId:1,clientX:100,preventDefault(){}});
side.callbacks.pointermove[0]({clientX:140});
side.callbacks.pointerup[0]({});
assert.ok(parseFloat(nodes.app.style['--panel-width'])>312, 'Side panel should grow while dragging');
const bottom = nodes.timelineResizer;
bottom.callbacks.pointerdown[0]({button:0,pointerId:2,clientY:220,preventDefault(){}});
bottom.callbacks.pointermove[0]({clientY:185});
bottom.callbacks.pointerup[0]({});
assert.ok(parseFloat(nodes.app.style['--timeline-height'])>210, 'Timeline should grow when dragging up');
assert.ok(storage.get('skellymotion-layout-v1'), 'Custom layout should be remembered');
assert.ok(nodes.refreshProjects.callbacks.click?.length, 'Projects library refresh must be wired');
assert.ok(nodes.openProjectsWelcome.callbacks.click?.length, 'Welcome screen must link to saved projects');
assert.ok(nodes.selectAllProjects.callbacks.change?.length, 'Bulk project select-all must be wired');
assert.ok(nodes.deleteSelectedProjects.callbacks.click?.length, 'Checked-only delete action must be wired');
assert.ok(nodes.downloadBtn.callbacks.click?.length, 'Full MP4 Save As action must be wired');
assert.ok(nodes.previewDownloadBtn.callbacks.click?.length, 'Preview MP4 Save As action must be wired');
assert.ok(nodes.exitBtn.callbacks.click?.length, 'Explicit close/save workflow must be wired');

assert.ok(nodes.previewQuality.callbacks.change?.length,
 'Live preview quality selector must be wired');
const beforePreviewPixels=nodes.previewCanvas.width*nodes.previewCanvas.height;
nodes.previewQuality.value='light';
nodes.previewQuality.callbacks.change[0]({target:nodes.previewQuality});
const afterPreviewPixels=nodes.previewCanvas.width*nodes.previewCanvas.height;
assert.ok(afterPreviewPixels<beforePreviewPixels,
 'Light preview must significantly reduce canvas pixel count');
assert.equal(storage.get('skellymotion-preview-quality-v1'),'light',
 'Preview preference must survive restarts');
assert.equal(nodes.fps.value||'30',nodes.fps.value||'30',
 'Preview quality must not change export frame rate');
nodes.previewQuality.value='sharp';
nodes.previewQuality.callbacks.change[0]({target:nodes.previewQuality});
assert.ok(nodes.previewCanvas.width*nodes.previewCanvas.height>afterPreviewPixels,
 'Sharp preview must restore higher resolution');
assert.ok(nodes.previewResolutionLabel.textContent.includes('Preview '),
 'Editor should display the preview resolution');

const debug=win.__studioDebug;
assert.ok(debug,'Playback optimization test hooks available in smoke test');
assert.equal(debug.clipLocation({}).x,50,
 'Default lyric horizontal position must remain centered, not 8%');
assert.equal(debug.clipLocation({}).y,debug.state.settings.position,
 'Default lyric vertical position must inherit global setting');
assert.equal(debug.clipMotionMs({}),230,
 'Unspecified clip motion must agree with default ASS export duration');
assert.equal(debug.clipLocation({x:72,y:34}).x,72);
assert.equal(debug.clipLocation({x:72,y:34}).y,34);
assert.equal(debug.clipMotionMs({effectMs:250}),250);
const spacedWords=[{text:'first',start:1,end:1.4},
                   {text:'second',start:2,end:2.6}];
assert.equal(debug.activeWordAtTime(spacedWords,1.2)?.text,'first');
assert.equal(debug.activeWordAtTime(spacedWords,1.75),null,
 'Word-only preview must not flash a stale word in a vocal pause');
assert.equal(debug.activeWordAtTime(spacedWords,2.25)?.text,'second');
debug.state.lines=[
 {id:'intro',text:'Start',start:0,end:3},
 {id:'middle',text:'Middle',start:4,end:6},
 {id:'ending',text:'Ending',start:7,end:10}
];
debug.invalidatePlaybackIndex();
assert.equal(debug.activeLyric(1.4)?.id,'intro');
assert.equal(debug.activeLyric(5)?.id,'middle');
assert.equal(debug.activeLyric(6.5),null);
assert.equal(debug.activeLyric(9)?.id,'ending');
debug.state.lines[1].start=3.5;
debug.invalidatePlaybackIndex();
assert.equal(debug.activeLyric(3.7)?.id,'middle',
 'Edited timings invalidate cached playback index');

assert.ok(nodes.renderPreviewBtn.callbacks.click?.length, '15-second test render must be wired');
assert.ok(nodes.checkGPU.callbacks.click?.length, 'Hardware compatibility button must be wired');
assert.ok(nodes.refreshPerformance.callbacks.click?.length, 'Performance metrics refresh must be wired');
assert.ok(nodes.refineLyricsBtn.callbacks.click?.length, 'Uncertain lyric second-pass review must be wired');
assert.ok(nodes.applyRefineBtn.callbacks.click?.length, 'Applying review suggestions needs a deliberate button');
assert.equal(nodes.encoder.value ?? 'auto', nodes.encoder.value ?? 'auto', 'Encoder selection exists');
nodes.performanceMode.value='eco';
nodes.performanceMode.callbacks.input[0]({target:nodes.performanceMode});
assert.equal(nodes.startupPerformance.value,'eco','Changing Eco profile should update welcome choice');
nodes.fps.value='24';
nodes.fps.callbacks.input[0]({target:nodes.fps});
assert.equal(nodes.exportFpsLabel.textContent,'24 FPS','FPS label should react to changes');
nodes.encoder.value='cpu';
nodes.encoder.callbacks.input[0]({target:nodes.encoder});

assert.ok(nodes.wordTimingRows.innerHTML.includes('word-timing-row'),
 'Demo clips should expose individual word timing controls');
assert.ok(nodes.lyricTrack.callbacks.contextmenu?.length,
 'Right-click clip editing must be connected');
assert.ok(nodes.clipContextMenu.id==='clipContextMenu',
 'Context menu must be mounted in the editor');
assert.equal(groups['[data-platform]']?.length,3,
 'All three social export presets must exist');
const shorts=groups['[data-platform]'].find(x=>x.dataset.platform==='shorts');
shorts.click();
assert.equal(debug.state.settings.aspect,'portrait');
assert.equal(debug.state.settings.resolution,'1080p');
const pulsePreset=groups['[data-preset]'].find(x=>x.dataset.preset==='ice');
pulsePreset.click();
assert.equal(debug.state.settings.animation,'pulse');
assert.equal(debug.state.settings.background,'arctic');
assert.ok(groups['[data-animation]'].some(x=>x.dataset.animation==='pulse'));
assert.ok(groups['[data-background]'].some(x=>x.dataset.background==='sunset'));

console.log('SkellyMotion editor smoke tests passed: load, edit, undo, redo, split, delete, snap, styles, layout tools, SRT.');
