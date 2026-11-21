import { NetworkGraph, type RecipientGraph } from "../soc/NetworkGraph";

export type InvestigatorData = {
  graph: RecipientGraph | null;
  capture: {
    duration_ms?: number;
    voiced_ms?: number;
    rms_dbfs?: number;
    clipped_ratio?: number;
    frame_ms?: number;
    levels_dbfs?: number[];
  } | null;
  voice_windows: { offset_ms: number; window_ms: number; score: number }[];
};

const seconds = (ms: number) => (ms / 1000).toFixed(2) + " s";

export function InvestigatorEvidence({ data, diagnostic }: { data?: InvestigatorData; diagnostic: boolean }) {
  const capture = data?.capture;
  const levels = capture?.levels_dbfs ?? [];
  const windows = data?.voice_windows ?? [];
  const duration = capture?.duration_ms ?? 0;
  const position = (ms: number) => Math.min(100, Math.max(0, ms / duration * 100));

  return <section className="aw-investigator" aria-label="Investigator visualizations">
    {data?.graph ? <NetworkGraph graph={data.graph} tz={Intl.DateTimeFormat().resolvedOptions().timeZone} />
      : <div><h3>Recipient network</h3><p className="aw-muted">No recipient graph was recorded.</p></div>}
    <figure className="aw-voice-chart" aria-labelledby="aw-voice-title">
      <h3 id="aw-voice-title">Voice timeline</h3>
      {duration > 0 ? <>
        <dl className="aw-voice-metrics">
          <div><dt>Capture</dt><dd>{seconds(duration)}</dd></div>
          {capture?.voiced_ms != null && <div><dt>Voiced</dt><dd>{seconds(capture.voiced_ms)}</dd></div>}
          {capture?.rms_dbfs != null && <div><dt>Average level</dt><dd>{capture.rms_dbfs} dBFS</dd></div>}
          {capture?.clipped_ratio != null && <div><dt>Clipped</dt><dd>{(capture.clipped_ratio * 100).toFixed(1)}%</dd></div>}
        </dl>
        <p className="aw-muted">Audio level · −80 to 0 dBFS</p>
        {levels.length > 0 ? <div className="aw-audio-levels" aria-hidden="true">
          {levels.map((level, index) => {
            const x = position(index * (capture?.frame_ms ?? duration / levels.length));
            return <span key={index} style={{
              left: `${x}%`,
              width: `${Math.min(100 - x, position(capture?.frame_ms ?? duration / levels.length))}%`,
              height: `${Math.min(100, Math.max(1, (level + 80) / 80 * 100))}%`,
            }} />;
          })}
        </div> : <p className="aw-muted">No frame levels were recorded.</p>}
        {windows.length > 0 && <div className="aw-voice-windows" aria-hidden="true">
          {windows.map(({ offset_ms, window_ms }, index) => <span key={index} style={{
            left: `${position(offset_ms)}%`, width: `${position(offset_ms + window_ms) - position(offset_ms)}%`,
          }} />)}
        </div>}
        <div className="aw-voice-axis" aria-hidden="true"><span>0 s</span><span>{seconds(duration)}</span></div>
      </> : <p className="aw-muted">No capture measurements were recorded.</p>}
      {windows.length > 0 ? <details>
        <summary>{diagnostic ? "Diagnostic score windows" : "Model score windows"} ({windows.length})
          {windows.length === 1 && ` · score ${windows[0].score}`}
        </summary>
        <ul>
          {windows.map(({ offset_ms, window_ms, score }, index) => <li key={index}>
            {seconds(offset_ms)} · {seconds(window_ms)} model window · score {score}
          </li>)}
        </ul>
      </details> : <p className="aw-muted">No timestamped model scores were recorded.</p>}
    </figure>
  </section>;
}
