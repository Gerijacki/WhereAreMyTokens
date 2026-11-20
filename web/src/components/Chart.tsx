import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
  SVGRenderer,
]);

export interface Theme {
  series: string[];
  text: string;
  textSecondary: string;
  muted: string;
  grid: string;
  surface: string;
  surface2: string;
  border: string;
}

function readTheme(): Theme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    series: Array.from({ length: 8 }, (_, i) => v(`--series-${i + 1}`)),
    text: v("--text-primary"),
    textSecondary: v("--text-secondary"),
    muted: v("--text-muted"),
    grid: v("--grid"),
    surface: v("--surface-1"),
    surface2: v("--surface-2"),
    border: v("--border"),
  };
}

/** Shared axis/tooltip styling so every chart reads as one system. */
export function baseOption(t: Theme): EChartsCoreOption {
  return {
    animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    animationDuration: 300,
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: t.textSecondary },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: "border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);",
    },
    legend: {
      top: 0,
      left: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: t.textSecondary, fontSize: 12 },
    },
  };
}

export function axisStyle(t: Theme) {
  return {
    axisLine: { lineStyle: { color: t.grid } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid } },
  };
}

interface DataTable {
  head: string[];
  rows: (string | number)[][];
}

type Loose = Record<string, unknown>;
const asArray = (v: unknown): Loose[] => (Array.isArray(v) ? (v as Loose[]) : v ? [v as Loose] : []);
const categories = (axis: unknown): string[] | null => {
  const a = asArray(axis).find((x) => x.type === "category" && Array.isArray(x.data));
  return a ? (a.data as unknown[]).map(String) : null;
};
const round = (n: unknown) => (typeof n === "number" ? Math.round(n * 1e4) / 1e4 : String(n ?? ""));

/** Charts are hover-only, so the same numbers are also offered as a table for screen readers. */
export function optionToTable(option: EChartsCoreOption): DataTable | null {
  const o = option as Loose;
  const xs = categories(o.xAxis);
  const ys = categories(o.yAxis);
  const series = asArray(o.series);
  if (series.length === 0) return null;
  const heat = series.find((s) => s.type === "heatmap");
  if (heat && xs && ys) {
    const rows = (heat.data as unknown[]).map((d) => {
      const [x, y, v] = d as number[];
      return [ys[y], xs[x], round(v)];
    });
    return { head: ["Row", "Column", "Value"], rows };
  }
  const cats = ys ?? xs;
  if (!cats) return null;
  const value = (d: unknown) => (d && typeof d === "object" && !Array.isArray(d) ? (d as Loose).value : d);
  const cols = series.map((s, i) => ({ name: String(s.name ?? `Series ${i + 1}`), data: (s.data as unknown[]) ?? [] }));
  return {
    head: ["", ...cols.map((c) => c.name)],
    rows: cats.map((c, i) => [c, ...cols.map((col) => round(value(col.data[i])))]),
  };
}

export function Chart({ build, height = 280, ariaLabel }: {
  build: (t: Theme) => EChartsCoreOption;
  height?: number;
  ariaLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(readTheme());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTheme(readTheme());
    mq.addEventListener("change", onChange);
    const obs = new MutationObserver(onChange);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", onChange);
      obs.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (theme && chart.current) chart.current.setOption(build(theme), true);
  }, [build, theme]);

  const table = useMemo(() => (theme ? optionToTable(build(theme)) : null), [build, theme]);

  return (
    <>
      <div ref={ref} role="img" aria-label={ariaLabel} style={{ height, width: "100%" }} />
      {table && (
        <table className="sr-only">
          <caption>{ariaLabel}</caption>
          <thead>
            <tr>{table.head.map((h, i) => <th key={i} scope="col">{h}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j}>{c}</td>))}</tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
