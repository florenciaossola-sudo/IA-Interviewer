import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { formatTimestamp } from "../legacy/formatters.js";
import { AuditReviewSection } from "./components/AuditReviewSection";
import { useAudit } from "./hooks/useAudit";

function ReviewerScreen({ audit }: { audit: ReturnType<typeof useAudit> }) {
  const [roleFilter, setRoleFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const roles = [...new Set(audit.queueItems.map((item) => item.role))].sort();
  const visibleQueueItems = audit.queueItems.filter((item) =>
    (roleFilter === "all" || item.role === roleFilter) &&
    (priorityFilter === "all" || item.priority_band === priorityFilter),
  );

  return (
    <>
      <section className="hero card reviewer-portal-section">
        <div>
          <p className="eyebrow">Reviewer portal</p>
          <h1>Audit a run without opening the candidate view.</h1>
          <p className="lede">
            Load a run ID to inspect the persisted run record, event stream, and checkpoints stored in SQLite.
          </p>
        </div>

        <div className="lookup-panel">
          <label htmlFor="run-id-input">Run ID</label>
          <div className="lookup-row">
            <input
              id="run-id-input"
              type="text"
              placeholder="iv_ab12cd"
              autoComplete="off"
              value={audit.runIdInput}
              onChange={(event) => audit.setRunIdInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void audit.loadAudit();
                }
              }}
            />
            <button
              id="load-run-btn"
              type="button"
              onClick={() => void audit.loadAudit()}
              disabled={audit.isLoadingAudit}
            >
              Load audit
            </button>
          </div>
          <p id="status-text" className="status">
            {audit.statusText}
          </p>
        </div>
      </section>

      <section className="card queue-card">
        <div className="panel-head">
          <div>
            <p className="eyebrow small">Human gate</p>
            <h2>Review queue</h2>
          </div>
          <button
            id="refresh-queue-btn"
            type="button"
            className="secondary"
            onClick={() => void audit.refreshQueue()}
            disabled={audit.isRefreshingQueue}
          >
            Refresh queue
          </button>
        </div>
        <p className="queue-help">
          Ordered by review priority derived from AAI; it is not a probability or an automated decision.
        </p>
        <div className="queue-filters">
          <label>
            Role
            <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
              <option value="all">All roles</option>
              {roles.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>
          <label>
            Priority
            <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
              <option value="all">All priorities</option>
              <option value="high">High</option>
              <option value="elevated">Elevated</option>
              <option value="low">Low</option>
              <option value="none">None</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
        </div>

        {!visibleQueueItems.length ? (
          <div id="queue-empty" className="empty-state">
            {audit.queueError || (audit.queueItems.length ? "No runs match these filters." : "No runs are waiting for review.")}
          </div>
        ) : (
          <div id="queue-empty" className="empty-state hidden">
            No runs are waiting for review.
          </div>
        )}

        <div className="review-queue-scroll">
          <ul id="queue-list" className="queue-list">
            {visibleQueueItems.map((item) => (
              <li key={item.run_id}>
                <button
                  type="button"
                  className="queue-item"
                  onClick={() => {
                    audit.setRunIdInput(item.run_id);
                    void audit.loadAudit(item.run_id);
                  }}
                >
                  <strong>{item.run_id}</strong>
                  <span>
                    {item.role} / {item.doc_type}
                  </span>
                  <small>Updated {formatTimestamp(item.updated_at)}</small>
                  {item.assigned_reviewer ? <small>Assigned reviewer: {item.assigned_reviewer}</small> : null}
                  <small>
                    Priority: {item.priority_band} ({item.review_priority_score ?? "unknown"}/100)
                    {item.aai_index !== null ? ` · AAI ${item.aai_index}` : ""}
                  </small>
                  {item.priority_reasons.length > 0 && <small>Signals: {item.priority_reasons.join(", ")}</small>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <AuditReviewSection
        auditBundle={audit.auditBundle}
        reviewerName={audit.reviewerName}
        decision={audit.decision}
        rationale={audit.rationale}
        reviewStatusText={audit.reviewStatusText}
        isSubmittingReview={audit.isSubmittingReview}
        setReviewerName={audit.setReviewerName}
        setDecision={audit.setDecision}
        setRationale={audit.setRationale}
        onSubmitReview={audit.onSubmitReview}
      />

    </>
  );
}

function ReviewerAuthGate({ children }: { children: ReactNode }) {
  const [configured, setConfigured] = useState(false);
  const [reviewer, setReviewer] = useState(() => window.localStorage.getItem("ai_interviewer_reviewer") || "");
  const [accessKey, setAccessKey] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void fetch("http://127.0.0.1:8081/review/auth/status")
      .then((response) => response.json() as Promise<{ configured: boolean }>)
      .then((payload) => setConfigured(payload.configured))
      .catch(() => setConfigured(false));
  }, []);

  if (!configured || window.localStorage.getItem("ai_interviewer_reviewer_token")) {
    return <>{children}</>;
  }

  async function login() {
    setError("");
    const response = await fetch("http://127.0.0.1:8081/review/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer, access_key: accessKey }),
    });
    const payload = await response.json() as { token?: string; detail?: string };
    if (!response.ok || !payload.token) {
      setError(payload.detail ?? "Could not authenticate reviewer.");
      return;
    }
    window.localStorage.setItem("ai_interviewer_reviewer", reviewer.trim());
    window.localStorage.setItem("ai_interviewer_reviewer_token", payload.token);
    window.location.reload();
  }

  return (
    <main className="shell">
      <section className="card reviewer-auth-panel">
        <p className="eyebrow">Reviewer authentication</p>
        <h1>Sign in to review assigned runs</h1>
        <label>Reviewer identity<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
        <label>Access key<input type="password" value={accessKey} onChange={(event) => setAccessKey(event.target.value)} /></label>
        <button type="button" onClick={() => void login()} disabled={!reviewer.trim() || !accessKey}>Sign in</button>
        <p className="status">{error}</p>
      </section>
    </main>
  );
}

export function App() {
  const audit = useAudit();

  return (
    <ReviewerAuthGate>
      <main className="shell">
        <ReviewerScreen audit={audit} />
      </main>
    </ReviewerAuthGate>
  );
}
