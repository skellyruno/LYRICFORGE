// Exercise the embedded lab's actual simulation and controls with a minimal DOM/canvas shim.
// This validates JS behavior, not browser layout or native WebView2 rendering.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../static/compressor_lab.html',import.meta.url),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes={};const canvas={beginPath(){},lineTo(){},moveTo(){},stroke(){},clearRect(){},fillText(){},arc(){},fill(){}};
for(const [id,value] of Object.entries({threshold:'-18',ratio:'4',attack:'30',release:'200',scope:'',thresholdOut:'',ratioOut:'',attackOut:'',releaseOut:'',inLevel:'',outLevel:'',grLevel:'',toggle:'',reset:''})) nodes[id]={value,textContent:'',addEventListener(){},getContext(){return canvas}};
let raf;
const context=vm.createContext({window:{},document:{getElementById:id=>nodes[id],querySelectorAll:()=>[],hidden:false},performance:{now:()=>0},requestAnimationFrame:cb=>{raf=cb}});
vm.runInContext(source,context);
assert.equal(context.window.demoSettings().threshold,-18);
let peak=vm.runInContext('Math.max(...Array.from({length:2000},()=>step(demoSettings())[2]))',context);
assert.ok(peak>7 && peak<10);
nodes.reset.onclick();nodes.ratio.value='1';
assert.equal(vm.runInContext('Math.max(...Array.from({length:2000},()=>step(demoSettings())[2]))',context),0);
nodes.reset.onclick();nodes.threshold.value='-24';nodes.ratio.value='8';
assert.ok(vm.runInContext('Math.max(...Array.from({length:2000},()=>step(demoSettings())[2]))',context)>peak+5);
raf(100);assert.match(nodes.grLevel.textContent,/dB$/);
nodes.toggle.onclick();assert.equal(nodes.toggle.textContent,'Resume');
const t=vm.runInContext('t',context);raf(200);assert.equal(vm.runInContext('t',context),t);
nodes.reset.onclick();assert.equal(context.window.demoSettings().ratio,4);
console.log('Interactive compressor lab: simulation, control direction, meters, pause and reset passed.');
