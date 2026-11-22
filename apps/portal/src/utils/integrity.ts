import type { EventRecord, IntegrityState } from "../types";

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

export function groupIntegrityEvidence(evidence: string[]): Array<{ text: string; count: number }> {
  const counts = new Map<string, number>();
  for (const text of evidence) {
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  return Array.from(counts, ([text, count]) => ({ text, count }));
}

export function findIntegrityReport(events: EventRecord[]): IntegrityState | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const payload = asRecord(event.payload);
    if (!payload) {
      continue;
    }

    const integrity = asRecord(payload.integrity_state);
    if (!integrity) {
      continue;
    }

    return {
      aai_index: Number(integrity.aai_index ?? 0),
      disposition: String(integrity.disposition ?? "unknown"),
      signal_breakdown: Array.isArray(integrity.signal_breakdown)
        ? integrity.signal_breakdown.map((item) => {
            const row = asRecord(item);
            return {
              signal_family: String(row?.signal_family ?? "unknown"),
              event_count: Number(row?.event_count ?? 0),
              suppressed: Boolean(row?.suppressed),
              evidence: Array.isArray(row?.evidence) ? row.evidence.map((item) => String(item)) : [],
            };
          })
        : [],
      confounders: Array.isArray(integrity.confounders)
        ? integrity.confounders.map((item) => String(item))
        : [],
      baseline_available: Boolean(integrity.baseline_available),
      baseline_answer_length: typeof integrity.baseline_answer_length === "number" ? integrity.baseline_answer_length : null,
      current_answer_length: typeof integrity.current_answer_length === "number" ? integrity.current_answer_length : null,
      baseline_deviation_ratio: typeof integrity.baseline_deviation_ratio === "number" ? integrity.baseline_deviation_ratio : null,
    };
  }

  return null;
}
