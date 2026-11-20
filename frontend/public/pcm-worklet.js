class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new DataView(new ArrayBuffer(8000));
    this.index = 0;
    this.port.onmessage = () => {
      this.finished = true;
      this.flush();
      this.port.postMessage(null);
    };
  }

  flush() {
    if (!this.index) return;
    const chunk = this.frame.buffer.slice(0, this.index * 2);
    this.port.postMessage(chunk, [chunk]);
    this.index = 0;
  }

  process(inputs) {
    if (this.finished) return false;
    for (const sample of inputs[0]?.[0] ?? []) {
      this.frame.setInt16(this.index++ * 2,
        Math.round(Math.max(-1, Math.min(1, sample)) * 32767), true);
      if (this.index === 4000) this.flush();
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
