import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const src=fs.readFileSync('static/app.js','utf8');
const start=src.indexOf('function previewInterval('),end=src.indexOf('const previewClock=',start);
assert.ok(start>=0&&end>start);
const {previewInterval,previewFrameDue}=vm.runInNewContext(src.slice(start,end)+'\n({previewInterval,previewFrameDue})');
for(const [mode,expected] of [['eco',15],['balanced',30],['turbo',60]]){
 for(const refresh of [60,120,144]){
  const clock={interval:0,next:NaN};let frames=0;
  for(let i=0;i<refresh*10;i++){
   const t=i*1000/refresh+(i%3===0?.12:-.12);
   if(previewFrameDue(clock,t,previewInterval(false,false,true,mode)))frames++;
  }
  assert.ok(Math.abs(frames-expected*10)<=1,mode+' '+refresh+' '+frames);
 }
}
const c={interval:0,next:NaN};
assert.ok(previewFrameDue(c,0,1000/60));
assert.ok(!previewFrameDue(c,4,1000/60));
assert.ok(previewFrameDue(c,750,1000/60));
assert.ok(!previewFrameDue(c,751,1000/60));
assert.ok(previewFrameDue(c,751,1000/60,true));
assert.equal(previewInterval(true,false,true,'turbo'),250);
assert.equal(previewInterval(false,true,true,'turbo'),250);
assert.equal(previewInterval(false,false,false,'turbo'),120);
console.log('Preview clock: 9 cadence matrices, missed-frame, forced redraw and idle gates passed');
