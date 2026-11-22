import { useEffect, useMemo, useRef, useState } from "react";

import { formatTimestamp } from "../../legacy/formatters.js";
import { API_BASE_URL, downloadAssessmentHtml, generateRecommendationLetter, getFollowUp, reviewerAuthHeaders, saveFollowUp, updateFollowUp } from "../../legacy/api.js";
import type { AuditBundle, DecisionLogItem, FollowUp, GraphStateSnapshot, ReviewStateSnapshot } from "../types";
import { findIntegrityReport, groupIntegrityEvidence } from "../utils/integrity";

type AuditReviewSectionProps = {
  auditBundle: AuditBundle | null;
  reviewerName: string;
  decision: string;
  rationale: string;
  reviewStatusText: string;
  isSubmittingReview: boolean;
  setReviewerName: (value: string) => void;
  setDecision: (value: string) => void;
  setRationale: (value: string) => void;
  onSubmitReview: (overrideOutcome?: string) => Promise<void>;
};

export function AuditReviewSection(props: AuditReviewSectionProps) {
  const {
    auditBundle,
    reviewerName,
    decision,
    rationale,
    reviewStatusText,
    isSubmittingReview,
    setReviewerName,
    setDecision,
    setRationale,
    onSubmitReview,
  } = props;
  const [integrityDisposition, setIntegrityDisposition] = useState("inconclusive");
  const [integrityRationale, setIntegrityRationale] = useState("");
  const [integrityDispositionStatus, setIntegrityDispositionStatus] = useState("");
  const [isSavingIntegrityDisposition, setIsSavingIntegrityDisposition] = useState(false);
  const [showAaiInfo, setShowAaiInfo] = useState(false);
  const [followUp, setFollowUp] = useState<FollowUp | null>(null);
  const [followUpAction, setFollowUpAction] = useState("Request a focused follow-up interview.");
  const [followUpNote, setFollowUpNote] = useState("");
  const [followUpStatus, setFollowUpStatus] = useState("");
  const [isSavingFollowUp, setIsSavingFollowUp] = useState(false);
  const [recommendationLetter, setRecommendationLetter] = useState("");
  const [letterStatus, setLetterStatus] = useState("");
  const [overrideOutcome, setOverrideOutcome] = useState("escalate");
  const [activeTurnIndex, setActiveTurnIndex] = useState(0);
  const [openedEvidence, setOpenedEvidence] = useState<Record<string, string>>({});
  const [evidenceErrors, setEvidenceErrors] = useState<Record<string, string>>({});
  const turnRefs = useRef<Map<number, HTMLLIElement>>(new Map());
  const runId = auditBundle?.run.run_id;

  const integrityReport = useMemo(
    () => (auditBundle ? findIntegrityReport(auditBundle.events || []) : null),
    [auditBundle]
  );

  const criteriaState = useMemo(() => {
    if (!auditBundle) {
      return null;
    }

    return findLatestCriteriaState(auditBundle);
  }, [auditBundle]);

  const visibleCheckpoints = useMemo(
    () => (auditBundle ? deduplicateCheckpoints(auditBundle.checkpoints) : []),
    [auditBundle],
  );

  const conversationTurns = useMemo(
    () => (auditBundle ? buildConversationTurns(auditBundle.events).map((turn, index) => ({ ...turn, index })) : []),
    [auditBundle],
  );
  const warmup = useMemo(
    () => (auditBundle ? findWarmup(auditBundle.events) : null),
    [auditBundle],
  );
  const hasWarmup = warmup !== null;
  const competencySummaries = useMemo(() => summarizeCompetencies(conversationTurns), [conversationTurns]);
  const fullDecisionLog = useMemo(() => getFullDecisionLog(auditBundle), [auditBundle]);
  const systemRecommendation = criteriaState?.graph.final_route ?? null;

  useEffect(() => {
    setIntegrityDisposition("inconclusive");
    setIntegrityRationale("");
    setIntegrityDispositionStatus("");
    setFollowUp(null);
    setFollowUpAction("Request a focused follow-up interview.");
    setFollowUpNote("");
    setFollowUpStatus("");
    setRecommendationLetter("");
    setLetterStatus("");
    setActiveTurnIndex(hasWarmup ? -1 : 0);
    setOpenedEvidence({});
    setEvidenceErrors({});
  }, [runId, hasWarmup]);

  useEffect(() => {
    setOverrideOutcome(systemRecommendation === "escalate" ? "conclude" : "escalate");
  }, [runId, systemRecommendation]);

  useEffect(() => {
    if (!runId) return;
    void (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/integrity-disposition`, { headers: reviewerAuthHeaders() });
        if (!response.ok) return;
        const saved = await response.json() as { disposition?: string; rationale?: string } | null;
        if (saved) {
          setIntegrityDisposition(saved.disposition ?? "inconclusive");
          setIntegrityRationale(saved.rationale ?? "");
        } else {
          setIntegrityDisposition("inconclusive");
          setIntegrityRationale("");
        }
      } catch {
        setIntegrityDispositionStatus("Could not load saved disposition.");
      }
    })();
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    void getFollowUp(runId)
      .then((response) => {
        const saved = response.ok ? response.data as FollowUp | null : null;
        setFollowUp(saved);
        if (saved) {
          setFollowUpAction(saved.requested_action);
          setFollowUpNote(saved.note);
        }
      })
      .catch(() => setFollowUpStatus("Could not load follow-up status."));
  }, [runId]);

  async function requestFollowUp() {
    if (!runId || !followUpAction.trim()) {
      setFollowUpStatus("A follow-up request is required.");
      return;
    }
    setIsSavingFollowUp(true);
    try {
      const response = await saveFollowUp(runId, { reviewer: reviewerName, requested_action: followUpAction });
      const payload = response.data as FollowUp & { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "Could not request follow-up.");
      setFollowUp(payload);
      setFollowUpStatus("Follow-up requested.");
    } catch (error) {
      setFollowUpStatus(error instanceof Error ? error.message : "Could not request follow-up.");
    } finally {
      setIsSavingFollowUp(false);
    }
  }

  async function changeFollowUpStatus(status: FollowUp["status"]) {
    if (!runId || !followUp) return;
    setIsSavingFollowUp(true);
    try {
      const response = await updateFollowUp(runId, { reviewer: reviewerName, status, note: followUpNote });
      const payload = response.data as FollowUp & { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "Could not update follow-up.");
      setFollowUp(payload);
      setFollowUpStatus(`Follow-up marked ${status}.`);
    } catch (error) {
      setFollowUpStatus(error instanceof Error ? error.message : "Could not update follow-up.");
    } finally {
      setIsSavingFollowUp(false);
    }
  }

  async function generateLetter() {
    if (!runId) return;
    setLetterStatus("Generating recommendation letter...");
    const response = await generateRecommendationLetter(runId, reviewerName);
    const payload = response.data as { content?: string; detail?: string };
    if (!response.ok) {
      setLetterStatus(payload.detail ?? "Could not generate recommendation letter.");
      return;
    }
    setRecommendationLetter(payload.content ?? "");
    setLetterStatus("Recommendation letter generated.");
  }

  function printAssessment() {
    window.print();
  }

  function downloadAssessment() {
    if (!auditBundle) return;
    const blob = new Blob([JSON.stringify(auditBundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${auditBundle.run.run_id}-assessment.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadHtmlAssessment() {
    if (!runId) return;
    const response = await downloadAssessmentHtml(runId);
    if (!response.ok || !response.blob) return;
    const url = URL.createObjectURL(response.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${runId}-assessment.html`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function saveIntegrityDisposition() {
    if (!runId || !integrityRationale.trim()) {
      setIntegrityDispositionStatus("A rationale is required.");
      return;
    }
    setIsSavingIntegrityDisposition(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/integrity-disposition`,
        {
          method: "PUT",
          headers: { ...reviewerAuthHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({ reviewer: reviewerName, disposition: integrityDisposition, rationale: integrityRationale }),
        },
      );
      const payload = await response.json() as { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? `Save failed (${response.status}).`);
      setIntegrityDispositionStatus("Integrity disposition saved.");
    } catch (error) {
      setIntegrityDispositionStatus(error instanceof Error ? error.message : "Could not save disposition.");
    } finally {
      setIsSavingIntegrityDisposition(false);
    }
  }

  if (!auditBundle) {
    return (
      <>
        <section id="summary-grid" className="summary-grid hidden"></section>
        <section id="audit-area" className="audit-grid hidden"></section>
        <section id="payload-area" className="card payload hidden"></section>
        <section id="integrity-area" className="card payload hidden"></section>
        <section id="criteria-area" className="card payload hidden"></section>
        <section id="review-area" className="card review-panel hidden"></section>
      </>
    );
  }

  return (
    <>
      <section id="summary-grid" className="summary-grid">
        <article className="stat card">
          <span className="stat-label">Run</span>
          <strong id="run-id-value">{auditBundle.run.run_id}</strong>
          <p id="run-status-value">Status: {auditBundle.run.status}</p>
        </article>
        <article className="stat card">
          <span className="stat-label">Scope</span>
          <strong id="run-scope-value">
            {auditBundle.run.role} / {auditBundle.run.doc_type}
          </strong>
          <p id="run-timestamps-value">
            {formatTimestamp(auditBundle.run.created_at)} to {formatTimestamp(auditBundle.run.updated_at)}
          </p>
        </article>
        <article className="stat card">
          <span className="stat-label">Events</span>
          <strong id="event-count-value">{auditBundle.events.length} events</strong>
          <small className="event-type-summary" title={auditBundle.events.map((event) => event.event_type).join(" · ")}>
            {auditBundle.events.map((event) => event.event_type).join(" · ")}
          </small>
          <p id="checkpoint-count-value">{visibleCheckpoints.length} checkpoints</p>
        </article>
      </section>

      <div className="audit-content-stack">
      <section className="card payload competency-review">
        <div className="panel-head"><h2>Scores by competency</h2><span>Each score links to its evaluated answer</span></div>
        {!competencySummaries.length ? <p className="empty-state">No scored competencies in this run.</p> : (
          <div className="competency-review-grid">
            {competencySummaries.map((summary) => (
              <article className="competency-review-item" key={summary.competency}>
                <div className="competency-review-heading"><h3>{summary.competency}</h3><strong>{summary.averageScore.toFixed(2)} avg</strong></div>
                <p>{summary.turns.length} evaluated turn(s)</p>
                <ul>{summary.turns.map((turn) => (
                  <li key={turn.event.event_id}>
                    <button type="button" className="turn-jump-link" onClick={() => navigateTurn(turn.index, turnRefs.current, setActiveTurnIndex)}>
                      Turn {turn.index + 1} · score {typeof turn.evaluation.score === "number" ? turn.evaluation.score.toFixed(2) : "n/a"}
                    </button>
                    <span>{turn.question}</span>
                    <small>{turn.evaluation.answer}</small>
                    {turn.evaluation.evidence.length ? (
                      <ul className="score-evaluation-evidence">{turn.evaluation.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
                    ) : null}
                    {turn.sources.length ? (
                      <ul className="score-source-links">{turn.sources.map((source) => (
                        <li key={source.chunk_id}>
                          <button type="button" className="source-link" onClick={() => void loadCorpusEvidence(source.chunk_id, setOpenedEvidence, setEvidenceErrors)}>
                            Open source: {source.doc_id} · {source.chunk_id}
                          </button>
                          {openedEvidence[source.chunk_id] ? <blockquote>{openedEvidence[source.chunk_id]}</blockquote> : null}
                          {evidenceErrors[source.chunk_id] ? <small className="corpus-error">{evidenceErrors[source.chunk_id]}</small> : null}
                        </li>
                      ))}</ul>
                    ) : <small>No corpus chunks were retrieved for this answer.</small>}
                  </li>
                ))}</ul>
              </article>
            ))}
          </div>
        )}
      </section>

      <section id="audit-area" className="audit-grid">
        <article className="card panel">
          <div className="panel-head">
            <h2>Event Stream</h2>
            <span id="event-stream-note">{conversationTurns.length} evaluated turn(s){warmup ? " · warm-up not scored" : ""}</span>
          </div>
          {conversationTurns.length || warmup ? (
            <div className="turn-navigation" aria-label="Turn navigation">
              <button type="button" className="secondary" disabled={activeTurnIndex <= (warmup ? -1 : 0)} onClick={() => navigateTurn(activeTurnIndex - 1, turnRefs.current, setActiveTurnIndex)}>Previous turn</button>
              <select aria-label="Jump to turn" value={activeTurnIndex} onChange={(event) => navigateTurn(Number(event.target.value), turnRefs.current, setActiveTurnIndex)}>
                {warmup ? <option value={-1}>Warm-up: calibration (not scored)</option> : null}
                {conversationTurns.map((turn, index) => <option key={turn.event.event_id} value={index}>Turn {index + 1}: {turn.competency ?? "Uncategorized"}</option>)}
              </select>
              <button type="button" className="secondary" disabled={activeTurnIndex >= conversationTurns.length - 1} onClick={() => navigateTurn(activeTurnIndex + 1, turnRefs.current, setActiveTurnIndex)}>Next turn</button>
            </div>
          ) : <p className="empty-state">No answered turns recorded.</p>}
          <ol id="event-list" className="timeline">
            {warmup ? (
              <li
                ref={(element) => {
                  if (element) turnRefs.current.set(-1, element);
                  else turnRefs.current.delete(-1);
                }}
                className={activeTurnIndex === -1 ? "review-turn active" : "review-turn"}
                onFocus={() => setActiveTurnIndex(-1)}
              >
                <div className="event-heading">
                  <span className="event-type">Warm-up · Calibration (not scored)</span>
                  <span className="event-meta">
                    #{warmup.event.event_id} · {formatTimestamp(warmup.event.created_at)}
                  </span>
                </div>
                <div className="conversation-message question-message">
                  <span className="conversation-label">Question</span>
                  <p>{warmup.question ?? "Warm-up question unavailable."}</p>
                </div>
                <div className="conversation-message answer-message">
                  <span className="conversation-label">Candidate answer</span>
                  <p>{warmup.answer}</p>
                </div>
                <details className="event-details">
                  <summary>Technical event details</summary>
                  <pre>{JSON.stringify(warmup.event.payload, null, 2)}</pre>
                </details>
              </li>
            ) : null}
            {conversationTurns.map((turn, turnIndex) => {
              const { event, responseEvent, question, evaluation } = turn;

              return (
              <li
                key={event.event_id}
                ref={(element) => {
                  if (element) turnRefs.current.set(turnIndex, element);
                  else turnRefs.current.delete(turnIndex);
                }}
                className={activeTurnIndex === turnIndex ? "review-turn active" : "review-turn"}
                onFocus={() => setActiveTurnIndex(turnIndex)}
              >
                <div className="event-heading">
                  <span className="event-type">Turn {turnIndex + 1} · {turn.competency ?? "Uncategorized"}</span>
                  <span className="event-meta">
                    #{event.event_id} · {formatTimestamp(event.created_at)}
                  </span>
                </div>
                <div className="conversation-message question-message">
                  <span className="conversation-label">Question</span>
                  <p>{question}</p>
                </div>
                {evaluation?.answer ? (
                  <div className="conversation-message answer-message">
                    <span className="conversation-label">Candidate answer</span>
                    <p>{evaluation.answer}</p>
                    {typeof evaluation.score === "number" ? (
                      <div className="answer-score">Score: {evaluation.score.toFixed(2)}</div>
                    ) : null}
                    {evaluation.evidence.length ? (
                      <div className="turn-evidence">
                        <strong>Evaluation evidence</strong>
                        <ul>{evaluation.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {turn.sources.length ? (
                  <div className="turn-sources">
                    <strong>Grounding evidence</strong>
                    {turn.sources.map((source) => (
                      <div className="source-evidence" key={source.chunk_id}>
                        <button type="button" className="source-link" onClick={() => void loadCorpusEvidence(source.chunk_id, setOpenedEvidence, setEvidenceErrors)}>
                          {source.doc_id} · {source.chunk_id} · Retrieval relevance: {source.score.toFixed(2)}
                        </button>
                        {openedEvidence[source.chunk_id] ? <blockquote>{openedEvidence[source.chunk_id]}</blockquote> : null}
                        {evidenceErrors[source.chunk_id] ? <small className="corpus-error">{evidenceErrors[source.chunk_id]}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                <details className="event-details">
                  <summary>Technical event details</summary>
                  <pre>{JSON.stringify(responseEvent?.payload ?? event.payload, null, 2)}</pre>
                </details>
              </li>
              );
            })}
          </ol>
        </article>

        <article className="card panel">
          <div className="panel-head">
            <h2>Checkpoints</h2>
          </div>
          <div id="checkpoint-list" className="checkpoint-stack">
            {visibleCheckpoints.map((checkpoint, visibleIndex) => (
              <article key={checkpoint.checkpoint_id} className="checkpoint">
                <h3>Checkpoint {visibleIndex + 1}</h3>
                <div className="checkpoint-meta">
                  Source index {checkpoint.checkpoint_index} · #{checkpoint.checkpoint_id} · {formatTimestamp(checkpoint.created_at)}
                </div>
                <pre>{JSON.stringify(checkpoint.state, null, 2)}</pre>
              </article>
            ))}
          </div>
        </article>
      </section>

      </div>

      <DecisionLogSection entries={fullDecisionLog} />

      {criteriaState ? (
        <section id="criteria-area" className="card payload">
          <div className="panel-head">
            <h2>Adaptive criteria</h2>
            <span>Coverage, confidence, and safety checkpoints</span>
          </div>
          <div className="criteria-grid">
            <article className="criteria-stat">
              <span className="stat-label">Coverage</span>
              <strong id="criteria-coverage-value">
                {asPercentage(criteriaState.review.competency_coverage)} / {asPercentage(criteriaState.review.competency_coverage_target)}
              </strong>
              <p id="criteria-coverage-status" className={criteriaState.review.competency_coverage_met ? "criteria-ok" : "criteria-warn"}>
                {criteriaState.review.competency_coverage_met ? "Meets target" : "Below target"}
              </p>
            </article>

            <article className="criteria-stat">
              <span className="stat-label">Confidence</span>
              <strong id="criteria-confidence-value">
                {asScore(criteriaState.review.cumulative_confidence)} / {asScore(criteriaState.review.cumulative_confidence_target)}
              </strong>
              <p
                id="criteria-confidence-status"
                className={criteriaState.review.cumulative_confidence_met ? "criteria-ok" : "criteria-warn"}
              >
                {criteriaState.review.cumulative_confidence_met ? "Healthy confidence" : "Low confidence"}
              </p>
            </article>

            <article className="criteria-stat">
              <span className="stat-label">Safety</span>
              <strong id="criteria-safety-value">
                {criteriaState.graph.evaluated_turns ?? 0} / {criteriaState.review.safety_turn_limit ?? criteriaState.graph.max_turns ?? 0} turns
              </strong>
              <p id="criteria-safety-status" className={criteriaState.review.safety_turn_limit_reached ? "criteria-warn" : "criteria-ok"}>
                {criteriaState.review.safety_turn_limit_reached ? "Turn limit reached" : "Within turn limit"}
              </p>
            </article>
          </div>

          <div className="criteria-meta">
            <p id="criteria-remaining-competencies">
              Remaining competencies: {criteriaState.graph.remaining_competencies ?? 0} of {criteriaState.graph.total_competencies ?? 0}
            </p>
            <p id="criteria-off-topic-count">Off-topic count: {criteriaState.review.off_topic_count ?? 0}</p>
          </div>
        </section>
      ) : (
        <section id="criteria-area" className="card payload hidden"></section>
      )}

      <section id="payload-area" className="card payload">
        <div className="panel-head">
          <h2>Raw payload</h2>
          <span>Useful for debugging and exports</span>
        </div>
        <pre id="payload-json">{JSON.stringify(auditBundle, null, 2)}</pre>
      </section>

      {integrityReport ? (
        <section id="integrity-area" className="card payload">
          <div className="panel-head">
            <h2>Integrity appendix</h2>
            <span>Latest recorded integrity report · AAI index and signal breakdown</span>
          </div>
          <div className="integrity-grid">
            <article className="integrity-stat">
              <div className="integrity-stat-heading">
                <span className="stat-label">AAI index:</span>
                <button
                  type="button"
                  className="integrity-info-button"
                  aria-label="About the AAI index"
                  aria-expanded={showAaiInfo}
                  aria-controls="aai-index-info"
                  onClick={() => setShowAaiInfo((shown) => !shown)}
                >i</button>
              </div>
              <strong id="aai-index-value">{integrityReport.aai_index}</strong>
              <div id="aai-index-info" className="integrity-info" hidden={!showAaiInfo}>
                <p>The AAI is an integrity review signal from 0 to 100 for the latest recorded report. It is not a probability of misconduct or a hiring decision.</p>
                <p>The system compares available answer metrics with the candidate&apos;s warm-up baseline and converts their differences into deviations. It takes the highest deviation per family, calculates a weighted average, multiplies it by the configured maximum penalty, rounds it and caps it at 100. If disclosure was not accepted, 6 points are added, up to 100.</p>
                <p>Suppressed families, disabled focus telemetry and metrics without a baseline are excluded. Event counts alone do not determine the index; motion and content currently do not produce deviations. A zero can also mean no comparable deviations were available.</p>
                <p>An index of 50 or more is marked for reviewer attention. Differences alone do not prove misconduct and require context and human review.</p>
              </div>
            </article>
            <article className="integrity-stat">
              <span className="stat-label">Disposition:</span>
              <strong id="integrity-disposition-value">{integrityReport.disposition}</strong>
            </article>
            <article className="integrity-stat">
              <span className="stat-label">Warm-up baseline:</span>
              {integrityReport.baseline_available ? (
                <div className="integrity-baseline-details">
                  <div><span>Warm-up answer</span><strong>{integrityReport.baseline_answer_length ?? "Unavailable"}{integrityReport.baseline_answer_length != null ? " chars" : ""}</strong></div>
                  <div><span>Latest evaluated answer</span><strong>{integrityReport.current_answer_length ?? "Unavailable"}{integrityReport.current_answer_length != null ? " chars" : ""}</strong></div>
                  <div><span>Absolute length difference</span><strong>{integrityReport.baseline_deviation_ratio != null ? `${(integrityReport.baseline_deviation_ratio * 100).toFixed(1)}%` : "Unavailable"}</strong></div>
                  <small>Compared with the warm-up length; this difference alone does not indicate misconduct.</small>
                </div>
              ) : <strong>Unavailable</strong>}
              {warmup ? <button type="button" className="turn-jump-link" onClick={() => navigateTurn(-1, turnRefs.current, setActiveTurnIndex)}>View warm-up answer</button> : null}
            </article>
          </div>
          <div className="integrity-block">
            <h3>Signal breakdown</h3>
            <ul id="integrity-breakdown-list">
              {integrityReport.signal_breakdown.map((item) => (
                <li key={`${item.signal_family}-${item.event_count}-${String(item.suppressed)}`}>
                  <strong>{item.signal_family}: {item.event_count} events{item.suppressed ? " (suppressed)" : ""}</strong>
                  {item.evidence.length ? (
                    <ul key="grouped-evidence" className="integrity-evidence-list">
                      {groupIntegrityEvidence(item.evidence).map(({ text, count }) => (
                        <li key={text}>{text} ({count})</li>
                      ))}
                    </ul>
                  ) : <small>No event evidence recorded.</small>}
                </li>
              ))}
            </ul>
          </div>
          <div className="integrity-block">
            <h3>Confounders</h3>
            <ul id="integrity-confounders-list">
              {integrityReport.confounders.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="integrity-disposition-form">
            <h3>Reviewer disposition</h3>
            <label>
              Integrity assessment
              <select value={integrityDisposition} onChange={(event) => setIntegrityDisposition(event.target.value)}>
                <option value="confirmed">Confirmed</option>
                <option value="dismissed">Dismissed</option>
                <option value="inconclusive">Inconclusive</option>
              </select>
            </label>
            <label>
              Rationale
              <textarea rows={3} value={integrityRationale} onChange={(event) => setIntegrityRationale(event.target.value)} required />
            </label>
            <button type="button" onClick={() => void saveIntegrityDisposition()} disabled={isSavingIntegrityDisposition}>
              {isSavingIntegrityDisposition ? "Saving..." : "Save disposition"}
            </button>
            <p className="status" aria-live="polite">{integrityDispositionStatus}</p>
          </div>
        </section>
      ) : (
        <section id="integrity-area" className="card payload hidden"></section>
      )}

      <div className="review-workflow-stack">
      {auditBundle.run.status === "in_review" || auditBundle.run.status === "completed" ? (
        <section id="review-area" className="card review-panel">
          <div className="panel-head">
            <h2>Finalize review</h2>
            <span>Preview the system outcome and your decision before submitting</span>
          </div>

          <div className="review-diff-preview" aria-live="polite">
            <div className="review-diff-column">
              <span className="stat-label">System recommendation</span>
              <strong>{formatRecommendation(systemRecommendation)}</strong>
              <small>
                {criteriaState?.review.cumulative_confidence !== undefined
                  ? `Confidence ${asScore(criteriaState.review.cumulative_confidence)}`
                  : "No confidence summary available"}
              </small>
            </div>
            <div className="review-diff-arrow" aria-hidden="true">→</div>
            <div className={decision === "overridden" ? "review-diff-column changed" : "review-diff-column"}>
              <span className="stat-label">Reviewer action</span>
              <strong>{decision === "overridden" ? `Override: ${formatRecommendation(overrideOutcome)}` : "Approve system recommendation"}</strong>
              {decision === "overridden" ? (
                <label className="override-outcome-select">
                  Replacement outcome
                  <select value={overrideOutcome} onChange={(event) => setOverrideOutcome(event.target.value)}>
                    <option value="conclude">Conclude</option>
                    <option value="escalate">Escalate</option>
                  </select>
                </label>
              ) : null}
              <small>{rationale.trim() || "Rationale will appear here before submission."}</small>
            </div>
          </div>

          <div className="review-grid">
            <label>
              Reviewer name
              <input id="reviewer-name-input" type="text" value={reviewerName} onChange={(event) => setReviewerName(event.target.value)} />
            </label>
            <label>
              Decision
              <select id="decision-select" value={decision} onChange={(event) => setDecision(event.target.value)}>
                <option value="approved">Approved</option>
                <option value="overridden">Overridden</option>
              </select>
            </label>
          </div>

          <label className="review-rationale">
            Rationale
            <textarea id="rationale-input" rows={5} placeholder="Explain the decision and any override notes." value={rationale} onChange={(event) => setRationale(event.target.value)}></textarea>
          </label>

          <div className="review-actions">
            <button id="submit-review-btn" type="button" onClick={() => void onSubmitReview(decision === "overridden" ? overrideOutcome : undefined)} disabled={isSubmittingReview}>
              Submit review
            </button>
            <p id="review-status-text" className="status">{reviewStatusText}</p>
          </div>
        </section>
      ) : (
        <section id="review-area" className="card review-panel hidden"></section>
      )}

      <section className="card payload reviewer-actions">
        <div className="panel-head"><h2>Follow-up</h2><span>{followUp ? `Status: ${followUp.status}` : "No follow-up requested"}</span></div>
        <label>
          Requested action
          <textarea rows={3} value={followUpAction} onChange={(event) => setFollowUpAction(event.target.value)} />
        </label>
        <label>
          Management note
          <textarea rows={2} value={followUpNote} onChange={(event) => setFollowUpNote(event.target.value)} />
        </label>
        <div className="review-actions">
          <button type="button" onClick={() => void requestFollowUp()} disabled={isSavingFollowUp}>Request follow-up</button>
          {followUp ? <>
            <button type="button" className="secondary" onClick={() => void changeFollowUpStatus("in_progress")} disabled={isSavingFollowUp}>Mark in progress</button>
            <button type="button" className="secondary" onClick={() => void changeFollowUpStatus("completed")} disabled={isSavingFollowUp}>Mark completed</button>
            <button type="button" className="secondary" onClick={() => void changeFollowUpStatus("cancelled")} disabled={isSavingFollowUp}>Cancel</button>
          </> : null}
        </div>
        <p className="status" aria-live="polite">{followUpStatus}</p>
      </section>

      <section className="card payload reviewer-actions">
        <div className="panel-head"><h2>Recommendation letter</h2><span>Available after final review</span></div>
        <button type="button" onClick={() => void generateLetter()} disabled={auditBundle.run.status !== "finalized"}>
          Generate recommendation letter
        </button>
        <p className="status" aria-live="polite">{letterStatus}</p>
        {recommendationLetter ? <pre className="recommendation-letter">{recommendationLetter}</pre> : null}
      </section>

      <section className="card payload reviewer-actions assessment-export">
        <div className="panel-head"><h2>Assessment output</h2><span>Share or print the audit</span></div>
        <div className="review-actions">
          <button type="button" onClick={printAssessment} disabled={auditBundle.run.status !== "finalized"}>Print assessment</button>
          <button type="button" onClick={() => void downloadHtmlAssessment()} disabled={auditBundle.run.status !== "finalized"}>Download HTML</button>
          <button type="button" className="secondary" onClick={downloadAssessment} disabled={auditBundle.run.status !== "finalized"}>Download JSON</button>
        </div>
      </section>
      </div>
    </>
  );
}

function DecisionLogSection({ entries }: { entries: DecisionLogItem[] }) {
  const decisionEntries = entries.filter((entry) => entry.node === "decide");

  return (
    <section id="decision-log-area" className="card payload">
      <div className="panel-head">
        <h2>Decision log</h2>
        <span>Chosen route, reason, and alternatives not selected</span>
      </div>
      {decisionEntries.length ? (
        <ol className="decision-log-list">
          {decisionEntries.map((entry, index) => (
            <li key={`${entry.node}-${entry.route}-${index}`} className="decision-log-item">
              <div className="decision-log-heading">
                <strong>{formatEventType(entry.route)}</strong>
                <span>Decision {index + 1}</span>
              </div>
              <p>{entry.reason}</p>
              {entry.alternatives?.length ? (
                <div className="decision-alternatives">
                  <span>Alternatives not selected</span>
                  <ul>
                    {entry.alternatives.map((alternative) => <li key={alternative}>{formatEventType(alternative)}</li>)}
                  </ul>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-state">No routing decisions recorded.</p>
      )}
    </section>
  );
}

function navigateTurn(
  index: number,
  refs: Map<number, HTMLLIElement>,
  setActive: (index: number) => void,
) {
  setActive(index);
  refs.get(index)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadCorpusEvidence(
  chunkId: string,
  setEvidence: (update: (current: Record<string, string>) => Record<string, string>) => void,
  setErrors: (update: (current: Record<string, string>) => Record<string, string>) => void,
) {
  setErrors((current) => ({ ...current, [chunkId]: "" }));
  try {
    const response = await fetch(`${API_BASE_URL}/admin/corpus/chunks/${encodeURIComponent(chunkId)}`, { headers: reviewerAuthHeaders() });
    if (!response.ok) throw new Error(response.status === 404 ? "Source chunk is no longer in the corpus." : `Source lookup failed (${response.status}).`);
    const payload = await response.json() as { text: string };
    setEvidence((current) => ({ ...current, [chunkId]: payload.text }));
  } catch (error) {
    setErrors((current) => ({ ...current, [chunkId]: error instanceof Error ? error.message : "Could not load source." }));
  }
}

function summarizeCompetencies(turns: ConversationTurn[]) {
  const groups = new Map<string, ConversationTurn[]>();
  for (const turn of turns) {
    const competency = turn.competency ?? "Uncategorized";
    groups.set(competency, [...(groups.get(competency) ?? []), turn]);
  }
  return Array.from(groups, ([competency, groupedTurns]) => {
    const scores = groupedTurns.map((turn) => turn.evaluation.score).filter((score): score is number => typeof score === "number");
    return {
      competency,
      turns: groupedTurns,
      averageScore: scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length : 0,
    };
  });
}

function getFullDecisionLog(auditBundle: AuditBundle | null): DecisionLogItem[] {
  if (!auditBundle) return [];
  const finalCheckpoint = auditBundle.checkpoints.at(-1);
  const checkpointLog = finalCheckpoint?.state.decision_log;
  if (Array.isArray(checkpointLog)) {
    return checkpointLog.filter((entry): entry is DecisionLogItem => Boolean(entry && typeof entry === "object"));
  }
  return findLatestCriteriaState(auditBundle)?.graph.decision_log_tail ?? [];
}

function deduplicateCheckpoints(checkpoints: AuditBundle["checkpoints"]): AuditBundle["checkpoints"] {
  const latestByIndex = new Map<string, AuditBundle["checkpoints"][number]>();
  for (const checkpoint of checkpoints) {
    const evaluatedTurns = checkpoint.state.evaluated_turns;
    const key = `${checkpoint.checkpoint_index}:${typeof evaluatedTurns === "number" ? evaluatedTurns : "unknown"}`;
    latestByIndex.set(key, checkpoint);
  }
  return [...latestByIndex.values()].sort((left, right) => left.checkpoint_id - right.checkpoint_id);
}

function findLatestCriteriaState(auditBundle: AuditBundle) {
  for (let index = auditBundle.events.length - 1; index >= 0; index -= 1) {
    const payload = auditBundle.events[index]?.payload;
    if (!payload || typeof payload !== "object") {
      continue;
    }

    const review = (payload as Record<string, unknown>).review_state as ReviewStateSnapshot | undefined;
    const graph = (payload as Record<string, unknown>).graph_state as GraphStateSnapshot | undefined;

    if (review || graph) {
      return {
        review: review ?? {},
        graph: graph ?? {},
      };
    }
  }

  return null;
}

function asPercentage(value: number | undefined) {
  if (typeof value !== "number") {
    return "0%";
  }

  return `${Math.round(value * 100)}%`;
}

function asScore(value: number | undefined) {
  if (typeof value !== "number") {
    return "0.00";
  }

  return value.toFixed(2);
}

function getEventText(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function findWarmup(events: AuditBundle["events"]) {
  const index = events.findIndex((event) => event.event_type === "warmup_completed" && getEventText(event.payload, "answer"));
  if (index < 0) return null;
  const event = events[index];
  const start = events.slice(0, index).find((item) => item.event_type === "run_started");
  return {
    event,
    question: start ? getEventText(start.payload, "question") : null,
    answer: getEventText(event.payload, "answer"),
  };
}

function buildConversationTurns(events: AuditBundle["events"]) {
  return events.flatMap((event) => {
    if (event.event_type !== "turn_completed" && event.event_type !== "run_completed") {
      return [];
    }

    const question = getEventText(event.payload, "question");
    const answer = getEventText(event.payload, "answer");
    if (!question || !answer) {
      return [];
    }

    const grounded = Array.isArray(event.payload.grounded_context) ? event.payload.grounded_context : [];
    const sources = grounded.flatMap((raw) => {
      const source = asRecord(raw);
      if (!source || typeof source.chunk_id !== "string" || typeof source.doc_id !== "string") return [];
      return [{
        chunk_id: source.chunk_id,
        doc_id: source.doc_id,
        score: typeof source.score === "number" ? source.score : 0,
      }];
    });
    return [{
      event,
      responseEvent: event,
      question,
      competency: getEventText(event.payload, "competency"),
      sources,
      evaluation: getEvaluation(event.payload),
    }];
  });
}

type ConversationTurn = ReturnType<typeof buildConversationTurns>[number] & { index: number };

function getEvaluation(payload: Record<string, unknown>) {
  const evidence = Array.isArray(payload.evaluation_evidence)
    ? payload.evaluation_evidence.filter((item): item is string => typeof item === "string")
    : [];
  const graphState = asRecord(payload.graph_state);
  const decisionLog = Array.isArray(graphState?.decision_log_tail) ? graphState.decision_log_tail : [];
  const lastDecision = decisionLog.at(-1);
  const reason = asRecord(lastDecision)?.reason;
  const legacyScore = typeof reason === "string" ? reason.match(/score=([0-9]+(?:\.[0-9]+)?)/)?.[1] : null;

  return {
    answer: getEventText(payload, "answer"),
    score:
      typeof payload.evaluation_score === "number"
        ? payload.evaluation_score
        : legacyScore
          ? Number(legacyScore)
          : null,
    evidence,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? value as Record<string, unknown> : null;
}

function formatEventType(eventType: string) {
  return eventType.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatRecommendation(route: string | null | undefined) {
  if (!route) return "No final recommendation recorded";
  return formatEventType(route);
}
