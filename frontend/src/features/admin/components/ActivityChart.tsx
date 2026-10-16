import { useId } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../../../lib/i18n";

interface Point {
  bucket: string;
  value: number;
}

interface ActivityChartProps {
  title: string;
  points: Point[];
  hourly: boolean;
}

const WIDTH = 600;
const HEIGHT = 120;
const GAP = 2;

function label(iso: string, hourly: boolean): string {
  const options: Intl.DateTimeFormatOptions = hourly
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { month: "short", day: "numeric" };
  return new Intl.DateTimeFormat(i18n.language, options).format(new Date(iso));
}

/**
 * Single-series bar chart drawn with SVG attributes (the CSP forbids inline styles). Each bar
 * has a hover title; the same numbers are available as a table for assistive technology.
 */
export function ActivityChart({ title, points, hourly }: ActivityChartProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const max = Math.max(1, ...points.map((point) => point.value));
  const slot = WIDTH / Math.max(1, points.length);
  const total = points.reduce((sum, point) => sum + point.value, 0);
  const first = points[0];
  const last = points.at(-1);

  return (
    <figure className="space-y-2 rounded-lg border border-border p-4">
      <figcaption id={titleId} className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{title}</span>
        <span className="text-text-muted">{t("adminDashboard.total", { count: total })}</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        preserveAspectRatio="none"
        className="h-28 w-full"
        role="img"
        aria-labelledby={titleId}
      >
        <line
          x1={0}
          x2={WIDTH}
          y1={HEIGHT - 0.5}
          y2={HEIGHT - 0.5}
          className="stroke-border"
          strokeWidth={1}
        />
        {points.map((point, index) => {
          const height = point.value === 0 ? 0 : Math.max(2, (point.value / max) * (HEIGHT - 4));
          return (
            <g key={point.bucket}>
              <rect
                x={index * slot}
                y={0}
                width={slot}
                height={HEIGHT}
                className="fill-transparent hover:fill-surface-muted"
              >
                <title>{`${label(point.bucket, hourly)}: ${String(point.value)}`}</title>
              </rect>
              <rect
                x={index * slot + GAP / 2}
                y={HEIGHT - height}
                width={Math.max(1, slot - GAP)}
                height={height}
                rx={Math.min(4, slot / 4)}
                className="pointer-events-none fill-primary"
              />
            </g>
          );
        })}
      </svg>
      {first !== undefined && last !== undefined && (
        <div aria-hidden className="flex justify-between text-xs text-text-muted">
          <span>{label(first.bucket, hourly)}</span>
          <span>{label(last.bucket, hourly)}</span>
        </div>
      )}
      <table className="sr-only">
        <caption>{title}</caption>
        <tbody>
          {points.map((point) => (
            <tr key={point.bucket}>
              <th scope="row">{label(point.bucket, hourly)}</th>
              <td>{point.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
