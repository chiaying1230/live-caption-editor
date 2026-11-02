const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('caption/static/pcm-worklet.js','utf8');

for (const rate of [8000, 16000, 44100, 48000]) {
  test(`worklet ${rate} Hz: duration, PCM range and final flush`, () => {
    const frames = [];
    class Base { constructor() {this.port = {postMessage: value => frames.push(value)};} }
    let Processor;
    vm.runInNewContext(code, {sampleRate:rate,AudioWorkletProcessor:Base,Int16Array,Math,
      registerProcessor: (name, cls) => {Processor=cls;}});
    const processor = new Processor();
    const total = Math.round(rate * 1.05);
    for (let offset=0;offset<total;offset+=128) {
      processor.process([[new Float32Array(Math.min(128,total-offset)).fill(.5)]]);
    }
    processor.port.onmessage({data:'flush'});
    assert.equal(frames.at(-1),'flushed');
    const pcm = frames.slice(0,-1).flatMap(buffer => Array.from(new Int16Array(buffer)));
    assert.equal(pcm.length,17600); // 10 full frames + padded half-frame.
    assert.ok(pcm.slice(0,16800).every(value => Math.abs(value-16384)<=1));
    assert.ok(pcm.slice(16800).every(value => value===0));
  });
}
