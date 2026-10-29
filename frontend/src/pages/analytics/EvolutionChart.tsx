import { useEffect, useState } from "react";
import { getPublicationAnalytics } from "../../api.ts";
import type { MetricSeries, PublicationAnalytics } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import Field from "../../ui/Field.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { formatDate, toApiError } from "../../utils.ts";
import { CONCEPT_LABELS, NUMBER, PERCENT } from "./copy.ts";

const WIDTH = 600;
const HEIGHT = 200;
const PAD = { top: 16, right: 16, bottom: 24, left: 16 };

function seriesLabel(series: MetricSeries): string {
  if (series.derived) return "Engagement (calculated)";
  const common = series.concept ? CONCEPT_LABELS[series.concept] : null;
  return `${common ?? series.label} (${series.name})`;
}

function formatValue(series: MetricSeries, value: number): string {
  return series.derived ? PERCENT.format(value) : NUMBER.format(value);
}

interface ChartProps {
  series: MetricSeries;
  /** Every reading's time, so readings without this metric show as gaps. */
  readings: string[];
}

/**
 * Real readings as dots on a time axis. A straight line only joins two
 * consecutive readings that both have the metric: it is a visual link, not a
 * measurement. A reading without the metric breaks the line (a tick, no dot).
 */
function Chart({ series, readings }: ChartProps) {
  const times = readings.map((value) => new Date(value).getTime());
  const first = Math.min(...times);
  const span = Math.max(...times) - first;
  const x = (time: number) =>
    span === 0
      ? WIDTH / 2
      : PAD.left + ((time - first) / span) * (WIDTH - PAD.left - PAD.right);
  const max = Math.max(...series.points.map((point) => point.value), 0);
  const y = (value: number) =>
    HEIGHT -
    PAD.bottom -
    (max === 0 ? 0 : (value / max) * (HEIGHT - PAD.top - PAD.bottom));
  const dots = series.points.map((point) => ({
    ...point,
    cx: x(new Date(point.captured_at).getTime()),
    cy: y(point.value),
  }));
  const segments = dots.slice(1).flatMap((dot, index) => {
    const previous = dots[index];
    return dot.reading === previous.reading + 1 ? [[previous, dot]] : [];
  });
  const baseline = HEIGHT - PAD.bottom;
  return (
    <svg
      className="ap-analytics__chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`${seriesLabel(series)}: ${series.points.length} real ${
        series.points.length === 1 ? "reading" : "readings"
      }. Exact values are in the table below.`}
    >
      <line
        className="ap-analytics__chart-axis"
        x1={PAD.left}
        x2={WIDTH - PAD.right}
        y1={baseline}
        y2={baseline}
      />
      {times.map((time, index) => (
        <line
          key={index}
          className="ap-analytics__chart-tick"
          data-reading={index}
          x1={x(time)}
          x2={x(time)}
          y1={baseline}
          y2={baseline + 6}
        />
      ))}
      {segments.map(([from, to]) => (
        <line
          key={`${from.snapshot_id}-${to.snapshot_id}`}
          className="ap-analytics__chart-link"
          x1={from.cx}
          y1={from.cy}
          x2={to.cx}
          y2={to.cy}
        />
      ))}
      {dots.map((dot) => (
        <circle
          key={dot.snapshot_id}
          className="ap-analytics__chart-dot"
          data-reading={dot.reading}
          cx={dot.cx}
          cy={dot.cy}
          r={5}
        >
          <title>
            {`${formatValue(series, dot.value)} · ${formatDate(dot.captured_at)}`}
          </title>
        </circle>
      ))}
      <text className="ap-analytics__chart-label" x={PAD.left} y={PAD.top - 4}>
        {formatValue(series, max)}
      </text>
    </svg>
  );
}

interface EvolutionChartProps {
  analytics: PublicationAnalytics;
}

/**
 * How one post's metrics changed across its real readings (FR-023). Only
 * metrics seen at least once can be chosen; nothing is filled, interpolated,
 * smoothed or predicted, and every value is listed with its exact time.
 */
export function EvolutionChart({ analytics }: EvolutionChartProps) {
  const { history, series } = analytics;
  const [selected, setSelected] = useState(series[0]?.name ?? "");
  if (history.length === 0 || series.length === 0) {
    return (
      <p className="ap-meta">
        No readings yet. The evolution appears here once AutoPublisher reads
        this post&apos;s metrics.
      </p>
    );
  }
  const current = series.find((item) => item.name === selected) ?? series[0];
  const readings = history.map((snapshot) => snapshot.captured_at);
  return (
    <div className="ap-analytics__evolution">
      <Field label="Metric">
        {(control) => (
          <select
            {...control}
            value={current.name}
            onChange={(event) => setSelected(event.target.value)}
          >
            {series.map((item) => (
              <option key={item.name} value={item.name}>
                {seriesLabel(item)}
              </option>
            ))}
          </select>
        )}
      </Field>
      {current.definition && (
        <p className="ap-analytics__formula">{current.definition}</p>
      )}
      <p className="ap-meta">
        {current.points.length} of {history.length}{" "}
        {history.length === 1 ? "reading has" : "readings have"} this metric.
        Dots are real readings; lines only connect consecutive readings and are
        not measurements in between.
      </p>
      {history.length === 1 && (
        <p className="ap-meta">
          Only one reading so far: there isn&apos;t enough history to see a
          change yet.
        </p>
      )}
      <Chart series={current} readings={readings} />
      <table className="ap-analytics__readings">
        <caption className="ap-visually-hidden">
          {seriesLabel(current)}, real readings oldest first
        </caption>
        <thead>
          <tr>
            <th scope="col">Read at</th>
            <th scope="col">{current.derived ? "Engagement" : current.name}</th>
          </tr>
        </thead>
        <tbody>
          {current.points.map((point) => (
            <tr key={point.snapshot_id}>
              <td>{formatDate(point.captured_at)}</td>
              <td>{formatValue(current, point.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Loads one post's history when opened (the posts list carries none). */
function EvolutionPanel({ publicationId }: { publicationId: number }) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "loaded"; analytics: PublicationAnalytics }
  >({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    getPublicationAnalytics(publicationId)
      .then((analytics) => {
        if (current) setState({ status: "loaded", analytics });
      })
      .catch((caught: unknown) => {
        if (current) {
          setState({ status: "error", message: toApiError(caught).message });
        }
      });
    return () => {
      current = false;
    };
  }, [publicationId, attempt]);

  if (state.status === "loading") {
    return <Skeleton lines={3} label="Loading the evolution…" />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        title="Couldn't load the evolution"
        message={state.message}
        onRetry={() => {
          setState({ status: "loading" });
          setAttempt((value) => value + 1);
        }}
      />
    );
  }
  return <EvolutionChart analytics={state.analytics} />;
}

export default EvolutionPanel;
