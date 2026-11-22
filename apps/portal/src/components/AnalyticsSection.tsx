import {
  formatPercent,
  formatSignedInteger,
  formatSignedNumber,
  formatSignedPercent,
  formatTimestamp,
} from "../../legacy/formatters.js";
import { TrendChart } from "./TrendChart";
import type { ComparisonPayload, EvaluationItem, SnapshotItem, TrendPayload } from "../types";

type AnalyticsSectionProps = {
  className?: string;
  analyticsStatusText: string;
  analyticsLabelInput: string;
  analyticsPolicyInput: string;
  analyticsPromptInput: string;
  baselineSnapshotId: string;
  candidateSnapshotId: string;
  driftScoreThreshold: string;
  driftOverrideThreshold: string;
  analyticsSnapshots: SnapshotItem[];
  analyticsEvaluations: EvaluationItem[];
  analyticsTrend: TrendPayload | null;
  analyticsComparison: ComparisonPayload | null;
  isRefreshingAnalytics: boolean;
  isCreatingSnapshot: boolean;
  isRunningSyncJob: boolean;
  isComparing: boolean;
  isRunningDrift: boolean;
  setAnalyticsLabelInput: (value: string) => void;
  setAnalyticsPolicyInput: (value: string) => void;
  setAnalyticsPromptInput: (value: string) => void;
  setBaselineSnapshotId: (value: string) => void;
  setCandidateSnapshotId: (value: string) => void;
  setDriftScoreThreshold: (value: string) => void;
  setDriftOverrideThreshold: (value: string) => void;
  onRefreshAnalytics: () => Promise<void>;
  onCreateSnapshot: () => Promise<void>;
  onRunSnapshotSyncJob: () => Promise<void>;
  onCompareSnapshots: () => Promise<void>;
  onRunDriftCheck: () => Promise<void>;
};

export function AnalyticsSection(props: AnalyticsSectionProps) {
  const {
    className,
    analyticsStatusText,
    analyticsLabelInput,
    analyticsPolicyInput,
    analyticsPromptInput,
    baselineSnapshotId,
    candidateSnapshotId,
    driftScoreThreshold,
    driftOverrideThreshold,
    analyticsSnapshots,
    analyticsEvaluations,
    analyticsTrend,
    analyticsComparison,
    isRefreshingAnalytics,
    isCreatingSnapshot,
    isRunningSyncJob,
    isComparing,
    isRunningDrift,
    setAnalyticsLabelInput,
    setAnalyticsPolicyInput,
    setAnalyticsPromptInput,
    setBaselineSnapshotId,
    setCandidateSnapshotId,
    setDriftScoreThreshold,
    setDriftOverrideThreshold,
    onRefreshAnalytics,
    onCreateSnapshot,
    onRunSnapshotSyncJob,
    onCompareSnapshots,
    onRunDriftCheck,
  } = props;

  const routeBucketCount = Object.keys(analyticsComparison?.route_distribution_delta || {}).length;
  const fairnessSlices = analyticsComparison?.fairness_slice_deltas || [];
  const recommendations = analyticsComparison?.recommendations || [];

  return (
    <section className={`card analytics-card ${className ?? ""}`}>
      <div className="panel-head">
        <div>
          <p className="eyebrow small">Phase 7 analytics</p>
          <h2>Snapshot registry and comparison</h2>
        </div>
        <button
          id="refresh-analytics-btn"
          type="button"
          className="secondary"
          onClick={() => void onRefreshAnalytics()}
          disabled={isRefreshingAnalytics}
        >
          Refresh snapshots
        </button>
      </div>

      <details className="analytics-help">
        <summary aria-label="Snapshot and drift check information"><span aria-hidden="true">i</span> How snapshots and drift checks work</summary>
        <div className="analytics-help-content">
          <p><strong>Snapshot:</strong> A saved point-in-time summary of the interview data currently in the system, including scored turns, routes and reviewer decisions. It is not a single candidate interview. Each snapshot uses the available history, so later snapshots can include earlier interviews too.</p>
          <p><strong>Generate snapshot:</strong> Enter an optional label and click Generate snapshot. The policy and prompt version fields are labels for tracking; entering a value does not change the active policy or prompt. Take another snapshot later, after more interviews or a system change.</p>
          <p><strong>Run sync job:</strong> Also creates a snapshot and records a sync job. If the optional lakehouse integration is enabled, it additionally exports the snapshot there.</p>
          <p><strong>Compare snapshots:</strong> Select an earlier reference as Baseline and a later snapshot as Candidate, then click Compare snapshots. Candidate means the snapshot being compared, not a job applicant. Deltas are candidate minus baseline. Use representative data: an empty or very small sample can be misleading.</p>
          <p><strong>Run drift check:</strong> Compares the selected snapshots against the limits below and additional fixed fairness-slice limits. It saves an OK or alert result in Evaluation history; an alert is a signal to investigate, not proof of a problem or a hiring decision.</p>
          <p><strong>Score drop threshold:</strong> The alert triggers when the average answer score falls by more than this amount. For example, 0.03 means a drop greater than 0.03 on the 0–1 score scale; an exact drop of 0.03 does not trigger this alert.</p>
          <p><strong>Override increase threshold:</strong> An override is a reviewer decision marked as overridden. The alert triggers when the proportion of reviews marked overridden rises by more than this amount. For example, 0.05 means an increase greater than 5 percentage points, not 5% relative growth.</p>
        </div>
      </details>

      <div className="analytics-actions">
        <input
          id="analytics-label-input"
          type="text"
          placeholder="Snapshot label (optional)"
          value={analyticsLabelInput}
          onChange={(event) => setAnalyticsLabelInput(event.target.value)}
        />
        <input
          id="analytics-policy-input"
          type="text"
          placeholder="adaptive-policy.v1"
          value={analyticsPolicyInput}
          onChange={(event) => setAnalyticsPolicyInput(event.target.value)}
        />
        <input
          id="analytics-prompt-input"
          type="text"
          placeholder="interviewer-prompt.v1"
          value={analyticsPromptInput}
          onChange={(event) => setAnalyticsPromptInput(event.target.value)}
        />
        <button id="create-snapshot-btn" type="button" onClick={() => void onCreateSnapshot()} disabled={isCreatingSnapshot}>
          Generate snapshot
        </button>
        <button
          id="run-sync-job-btn"
          type="button"
          className="secondary"
          onClick={() => void onRunSnapshotSyncJob()}
          disabled={isRunningSyncJob}
        >
          Run sync job
        </button>
      </div>

      <p id="analytics-status-text" className="status">
        {analyticsStatusText}
      </p>

      <div className="analytics-compare-grid">
        <label>
          Baseline snapshot
          <select
            id="baseline-snapshot-select"
            value={baselineSnapshotId}
            onChange={(event) => setBaselineSnapshotId(event.target.value)}
          >
            {!analyticsSnapshots.length ? (
              <option value="">No snapshots</option>
            ) : (
              analyticsSnapshots.map((item) => (
                <option key={`baseline-${item.snapshot_id}`} value={String(item.snapshot_id)}>
                  #{item.snapshot_id} {item.label || "(unlabeled)"}
                </option>
              ))
            )}
          </select>
        </label>
        <label>
          Candidate snapshot
          <select
            id="candidate-snapshot-select"
            value={candidateSnapshotId}
            onChange={(event) => setCandidateSnapshotId(event.target.value)}
          >
            {!analyticsSnapshots.length ? (
              <option value="">No snapshots</option>
            ) : (
              analyticsSnapshots.map((item) => (
                <option key={`candidate-${item.snapshot_id}`} value={String(item.snapshot_id)}>
                  #{item.snapshot_id} {item.label || "(unlabeled)"}
                </option>
              ))
            )}
          </select>
        </label>
        <button id="compare-snapshots-btn" type="button" onClick={() => void onCompareSnapshots()} disabled={isComparing}>
          Compare snapshots
        </button>
      </div>

      {analyticsComparison ? (
        <div id="analytics-summary-grid" className="summary-grid analytics-summary-grid">
          <article className="stat card">
            <span className="stat-label">Average Score Delta</span>
            <strong id="analytics-score-delta">{formatSignedNumber(analyticsComparison.average_score_delta, 4)}</strong>
            <p id="analytics-completed-delta">
              Completed runs delta: {formatSignedInteger(analyticsComparison.completed_run_delta)}
            </p>
          </article>
          <article className="stat card">
            <span className="stat-label">Override Rate Delta</span>
            <strong id="analytics-override-delta">
              {formatSignedNumber(analyticsComparison.reviewer_override_rate_delta, 4)}
            </strong>
            <p id="analytics-route-delta-note">{routeBucketCount} route bucket(s) changed</p>
          </article>
          <article className="stat card">
            <span className="stat-label">Fairness Slice Deltas</span>
            <strong id="analytics-fairness-count">{fairnessSlices.length} slices</strong>
            <p id="analytics-recommendation-count">{recommendations.length} recommendation(s)</p>
          </article>
        </div>
      ) : (
        <div id="analytics-summary-grid" className="summary-grid analytics-summary-grid hidden"></div>
      )}

      {analyticsComparison ? (
        <div id="analytics-comparison-body" className="analytics-comparison">
          <article className="analytics-block">
            <h3>Route distribution delta</h3>
            <pre id="analytics-route-delta-json">
              {JSON.stringify(analyticsComparison.route_distribution_delta || {}, null, 2)}
            </pre>
          </article>
          <article className="analytics-block">
            <h3>Fairness slice deltas</h3>
            <pre id="analytics-fairness-json">{JSON.stringify(fairnessSlices, null, 2)}</pre>
          </article>
          <article className="analytics-block">
            <h3>Recommendations</h3>
            <ul id="analytics-recommendations-list">
              {recommendations.length ? (
                recommendations.map((recommendation) => <li key={recommendation}>{recommendation}</li>)
              ) : (
                <li>No recommendations for this comparison.</li>
              )}
            </ul>
          </article>
        </div>
      ) : (
        <div id="analytics-comparison-body" className="analytics-comparison hidden"></div>
      )}

      <div className="analytics-compare-grid analytics-drift-grid">
        <label>
          Score drop threshold
          <input
            id="drift-score-threshold-input"
            type="number"
            min="0"
            step="0.01"
            value={driftScoreThreshold}
            onChange={(event) => setDriftScoreThreshold(event.target.value)}
          />
        </label>
        <label>
          Override increase threshold
          <input
            id="drift-override-threshold-input"
            type="number"
            min="0"
            step="0.01"
            value={driftOverrideThreshold}
            onChange={(event) => setDriftOverrideThreshold(event.target.value)}
          />
        </label>
        <button id="run-drift-check-btn" type="button" onClick={() => void onRunDriftCheck()} disabled={isRunningDrift}>
          Run drift check
        </button>
      </div>

      <div className="analytics-block">
        <h3>Evaluation history</h3>
        <ul id="analytics-evaluation-list" className="queue-list">
          {analyticsEvaluations.length ? (
            analyticsEvaluations.map((item) => (
              <li key={item.evaluation_id} className="queue-item">
                <strong>
                  Evaluation #{item.evaluation_id} · {item.status}
                </strong>
                <span>
                  baseline #{item.baseline_snapshot_id ?? "-"} vs candidate #{item.candidate_snapshot_id ?? "-"}
                </span>
                <small>Created {formatTimestamp(item.created_at)}</small>
              </li>
            ))
          ) : (
            <li className="empty-state">No drift evaluations have been recorded.</li>
          )}
        </ul>
      </div>

      <div className="analytics-block">
        <h3>LLM fallback trend</h3>
        <div className="analytics-trend-grid">
          <article className="trend-stat">
            <span className="stat-label">Avg candidate fallback</span>
            <strong id="analytics-trend-candidate-rate">
              {formatPercent(analyticsTrend?.average_candidate_fallback_rate || 0)}
            </strong>
          </article>
          <article className="trend-stat">
            <span className="stat-label">Avg delta</span>
            <strong id="analytics-trend-delta-rate">
              {formatSignedPercent(analyticsTrend?.average_fallback_rate_delta || 0)}
            </strong>
          </article>
          <article className="trend-stat">
            <span className="stat-label">Max candidate fallback</span>
            <strong id="analytics-trend-max-rate">
              {formatPercent(analyticsTrend?.max_candidate_fallback_rate || 0)}
            </strong>
          </article>
        </div>

        <div id="analytics-trend-chart" className="analytics-trend-chart" aria-label="LLM fallback trend chart">
          <TrendChart points={analyticsTrend?.points || []} />
        </div>

        <div className="analytics-trend-legend" aria-hidden="true">
          <span className="trend-legend-item">
            <span className="trend-legend-swatch trend-legend-swatch-candidate"></span>
            Candidate
          </span>
          <span className="trend-legend-item">
            <span className="trend-legend-swatch trend-legend-swatch-baseline"></span>
            Baseline
          </span>
        </div>

        <ul id="analytics-trend-list" className="queue-list">
          {analyticsTrend && analyticsTrend.points.length ? (
            analyticsTrend.points.map((point) => (
              <li key={point.evaluation_id} className="queue-item">
                <strong>
                  Evaluation #{point.evaluation_id} · {point.status}
                </strong>
                <span>
                  candidate {formatPercent(point.candidate_fallback_rate)} vs baseline {formatPercent(point.baseline_fallback_rate)}
                </span>
                <small>
                  {formatTimestamp(point.created_at)} · delta {formatSignedPercent(point.fallback_rate_delta)} · turns{" "}
                  {formatSignedInteger(point.observed_turn_count_delta)}
                </small>
              </li>
            ))
          ) : (
            <li className="empty-state">No drift evaluations with LLM trace rollups have been recorded.</li>
          )}
        </ul>
      </div>

      <div className="analytics-block">
        <h3>Snapshot registry</h3>
        <ul id="analytics-snapshot-list" className="queue-list">
          {analyticsSnapshots.length ? (
            analyticsSnapshots.map((item) => (
              <li key={item.snapshot_id} className="queue-item">
                <strong>
                  #{item.snapshot_id} {item.label || "(unlabeled)"}
                </strong>
                <span>
                  policy {item.policy_version} / prompt {item.prompt_version}
                </span>
                <small>Created {formatTimestamp(item.created_at)}</small>
              </li>
            ))
          ) : (
            <li className="empty-state">No persisted snapshots yet.</li>
          )}
        </ul>
      </div>
    </section>
  );
}
