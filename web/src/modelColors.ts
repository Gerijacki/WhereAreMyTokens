import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { get, type Overview } from "./api";
import type { Theme } from "./components/Chart";

/**
 * Colour follows the model, never its rank in the current filter: slots are assigned
 * from the all-time model list (alphabetical), so changing the range never repaints a model.
 */
export function useModelColors() {
  const all = useQuery({
    queryKey: ["overview", 0, undefined],
    queryFn: () => get<Overview>("/overview", { days: 0 }),
    staleTime: 60_000,
  });
  const key = (all.data?.by_model.map((m) => m.model) ?? []).sort().join("|");
  return useCallback(
    (model: string, theme?: Theme) => {
      const i = key.split("|").indexOf(model);
      const slot = i >= 0 && i < 7 ? i : 7; // 8th slot doubles as "other"
      return theme ? theme.series[slot] : `var(--series-${slot + 1})`;
    },
    [key],
  );
}
