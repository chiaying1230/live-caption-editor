// AudioWorklet owns sample-rate conversion, so no main-thread audio callbacks.
// Integrate source samples over each 1/16000 s interval; supports 44.1/48 kHz.
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.remaining = this.ratio;
    this.sum = 0;
    this.frame = new Int16Array(1600);
    this.position = 0;
    this.stopped = false;
    this.port.onmessage = ({data}) => {
      if (data === 'flush') {
        this.stopped = true;
        if (this.position) {
          this.frame.fill(0, this.position);
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
        }
        this.port.postMessage('flushed');
      }
    };
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input || this.stopped) return true;
    for (let i = 0; i < input.length; i++) {
      let available = 1;
      while (available > 1e-8) {
        const used = Math.min(available, this.remaining);
        this.sum += input[i] * used;
        this.remaining -= used;
        available -= used;
        if (this.remaining < 1e-8) {
          const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.frame[this.position++] = Math.round(value * (value < 0 ? 32768 : 32767));
          this.sum = 0;
          this.remaining = this.ratio;
          if (this.position === 1600) {
            this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
            this.frame = new Int16Array(1600);
            this.position = 0;
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMProcessor);
