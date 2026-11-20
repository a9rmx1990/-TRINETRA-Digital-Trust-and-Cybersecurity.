// AudioWorklet: downsample the input channel to 16 kHz mono Int16 and post ~100 ms frames
// together with the measured RMS of those exact samples (used for the level meter).
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.out = new Int16Array(1600);
    this.n = 0;
    this.sumSq = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const v = Math.max(-1, Math.min(1, ch[i]));
        this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        this.sumSq += v * v;
        if (this.n === this.out.length) {
          const rms = Math.sqrt(this.sumSq / this.n);
          this.port.postMessage({ pcm: this.out.buffer, rms }, [this.out.buffer]);
          this.out = new Int16Array(1600);
          this.n = 0;
          this.sumSq = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PcmWorklet);
