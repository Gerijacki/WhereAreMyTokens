import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import { shortModel, tokens, money } from "../format";
import { Card } from "./ui";

interface TelemetryData {
  active: boolean;
  live: boolean;
  last_event_at: string | null;
  by_source_model: { source: string; model: string | null; requests: number; cost_usd: number;
    output_tokens: number; cache_read: number }[];
}

/** Only rendered when Claude Code's OpenTelemetry export is pointed at WAMT. */
export function TelemetryCard({ days }: { days: number }) {
  const q = useQuery({ queryKey: ["telemetry", days], queryFn: () => get<TelemetryData>("/telemetry", { days }) });
  if (!q.data?.active) return null;
  return (
    <Card title="OpenTelemetry feed" subtitle={q.data.live ? "Receiving events now" : "Events received from Claude Code's native telemetry"}>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr><th>Source</th><th>Model</th><th className="r">Requests</th><th className="r">Output</th><th className="r">Cost (reported)</th></tr>
          </thead>
          <tbody>
            {q.data.by_source_model.map((r, i) => (
              <tr key={i}>
                <td>{r.source}</td>
                <td>{r.model ? shortModel(r.model) : "–"}</td>
                <td className="r num">{r.requests.toLocaleString()}</td>
                <td className="r num">{tokens(r.output_tokens)}</td>
                <td className="r num">{money(r.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
