import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

type RoleDefinition = {
  role_id: string;
  title: string;
  location: string;
  description: string;
  created_at: string;
  updated_at: string;
};

type IntegrityTelemetryEvent = {
  signal_family: "focus" | "timing" | "input" | "motion" | "content";
  event_type: string;
  value: string;
};

type IntegrityPayload = {
  disclosure_accepted: boolean;
  focus_telemetry_enabled: boolean;
  suppressed_signal_families: Array<"focus" | "timing" | "input" | "motion" | "content">;
  telemetry_events: IntegrityTelemetryEvent[];
  current_metrics: Record<string, number>;
};

type AnswerMetricAccumulator = {
  focusedAt: number | null;
  firstKeystrokeAt: number | null;
  lastInputAt: number | null;
  typedCharacters: number;
  pastedCharacters: number;
  pendingPasteCharacters: number;
  revisionCount: number;
  focusBlurCount: number;
  keystrokeIntervals: number[];
  previousLength: number;
};

type InterviewPayload = {
  run_id: string;
  question: string | null;
  question_index: number;
  total_questions: number;
  completed: boolean;
  warmup?: boolean;
};

const API_BASE_URL = "http://127.0.0.1:8081";
const MODEL_OVERLOADED_MESSAGE =
  "El sistema o el modelo está saturado en este momento. Intenta nuevamente más tarde.";

const METRIC_SIGNAL_FAMILIES: Record<string, IntegrityTelemetryEvent["signal_family"]> = {
  time_to_first_keystroke_ms: "timing",
  composition_time_ms: "timing",
  words_per_minute: "timing",
  keystroke_interval_ms: "input",
  paste_fraction: "input",
  revision_ratio: "input",
  answer_length: "input",
  focus_blur_count: "focus",
};

function createAnswerMetricAccumulator(): AnswerMetricAccumulator {
  return {
    focusedAt: null,
    firstKeystrokeAt: null,
    lastInputAt: null,
    typedCharacters: 0,
    pastedCharacters: 0,
    pendingPasteCharacters: 0,
    revisionCount: 0,
    focusBlurCount: 0,
    keystrokeIntervals: [],
    previousLength: 0,
  };
}

export function App() {
  const [statusText, setStatusText] = useState("Click start to begin your interview.");
  const [disclosureAccepted, setDisclosureAccepted] = useState(false);
  const [disclosureChecked, setDisclosureChecked] = useState(false);
  const [focusTelemetryEnabled, setFocusTelemetryEnabled] = useState(false);
  const [accommodationFocus, setAccommodationFocus] = useState(false);
  const [accommodationTiming, setAccommodationTiming] = useState(false);
  const [accommodationInput, setAccommodationInput] = useState(false);
  const [accommodationMotion, setAccommodationMotion] = useState(false);
  const [accommodationContent, setAccommodationContent] = useState(false);

  const [role, setRole] = useState("backend_engineer");
  const [docType, setDocType] = useState("role_description");
  const [roleDescription, setRoleDescription] = useState("");
  const [interviewContext, setInterviewContext] = useState("");
  const [roleDefinition, setRoleDefinition] = useState<RoleDefinition | null>(null);
  const [roleLockedFromUrl, setRoleLockedFromUrl] = useState(false);
  const [interviewToken, setInterviewToken] = useState("");
  const [disclosureStorageKey, setDisclosureStorageKey] = useState<string | null>(null);
  const [interviewCanStart, setInterviewCanStart] = useState(true);
  const [interviewNeedsResume, setInterviewNeedsResume] = useState(false);

  const [runId, setRunId] = useState<string | null>(null);
  const [question, setQuestion] = useState<string>("");
  const [questionIndex, setQuestionIndex] = useState(0);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [answer, setAnswer] = useState("");
  const [answerPreview, setAnswerPreview] = useState(false);
  const [monospaceMode, setMonospaceMode] = useState(false);
  const [codeMode, setCodeMode] = useState(false);
  const [interviewStarted, setInterviewStarted] = useState(false);
  const [interviewCompleted, setInterviewCompleted] = useState(false);
  const [warmup, setWarmup] = useState(false);
  const [systemOverloaded, setSystemOverloaded] = useState(false);
  const [busy, setBusy] = useState(false);

  const [telemetryEvents, setTelemetryEvents] = useState<IntegrityTelemetryEvent[]>([]);
  const answerMetrics = useRef<AnswerMetricAccumulator>(createAnswerMetricAccumulator());

  const finalThankYouMessage =
    "Muchas gracias por su participación. En breve nos comunicaremos con usted vía email.";

  const startDisabled = useMemo(
    () => !(disclosureChecked && disclosureAccepted) || busy || interviewCompleted || !interviewCanStart,
    [disclosureChecked, disclosureAccepted, busy, interviewCompleted, interviewCanStart]
  );

  const submitDisabled = useMemo(() => busy || !interviewStarted || interviewCompleted, [
    busy,
    interviewStarted,
    interviewCompleted,
  ]);

  const suppressedSignalFamilies = useMemo(() => {
    const values: Array<"focus" | "timing" | "input" | "motion" | "content"> = [];
    if (accommodationFocus) {
      values.push("focus");
    }
    if (accommodationTiming) {
      values.push("timing");
    }
    if (accommodationInput) {
      values.push("input");
    }
    if (accommodationMotion) values.push("motion");
    if (accommodationContent) values.push("content");
    return values;
  }, [accommodationContent, accommodationFocus, accommodationInput, accommodationMotion, accommodationTiming]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const interviewTokenFromUrl = params.get("interview") ?? "";
    if (interviewTokenFromUrl) {
      setInterviewToken(interviewTokenFromUrl);
      setRoleLockedFromUrl(true);
      setInterviewCanStart(false);
      setStatusText("Validating your interview link...");
      let isCancelled = false;
      void (async () => {
        try {
          const response = await fetch(
            `${API_BASE_URL}/candidate/interviews/${encodeURIComponent(interviewTokenFromUrl)}`,
          );
          if (!response.ok) throw new Error("This interview link is invalid, expired, or revoked.");
          const payload = await response.json() as {
            interview_id: string;
            candidate_name: string;
            role_id: string;
            role_title: string;
            job_offer: string;
            role_description: string;
            scheduled_at: string;
            expires_at: string;
            status: string;
            integrity_preferences?: {
              disclosure_accepted: boolean;
              focus_telemetry_enabled: boolean;
              suppressed_signal_families: string[];
            } | null;
          };
          if (isCancelled) return;
          const storageKey = `ai-interviewer-disclosure:${payload.interview_id}`;
          try {
            const saved = window.localStorage.getItem(storageKey);
            const preferences = saved
              ? JSON.parse(saved) as Record<string, unknown>
              : payload.integrity_preferences
                ? {
                    disclosureAccepted: payload.integrity_preferences.disclosure_accepted,
                    focusTelemetryEnabled: payload.integrity_preferences.focus_telemetry_enabled,
                    suppressedSignalFamilies:
                      payload.integrity_preferences.suppressed_signal_families,
                  }
                : null;
            if (preferences) {
              const accepted = preferences.disclosureAccepted === true;
              const suppressed = Array.isArray(preferences.suppressedSignalFamilies)
                ? preferences.suppressedSignalFamilies
                : [];
              setDisclosureAccepted(accepted);
              setDisclosureChecked(accepted);
              setFocusTelemetryEnabled(preferences.focusTelemetryEnabled === true);
              setAccommodationFocus(
                preferences.accommodationFocus === true || suppressed.includes("focus"),
              );
              setAccommodationTiming(
                preferences.accommodationTiming === true || suppressed.includes("timing"),
              );
              setAccommodationInput(
                preferences.accommodationInput === true || suppressed.includes("input"),
              );
              setAccommodationMotion(
                preferences.accommodationMotion === true || suppressed.includes("motion"),
              );
              setAccommodationContent(
                preferences.accommodationContent === true || suppressed.includes("content"),
              );
            }
          } catch {
            setDisclosureStorageKey(null);
          }
          setDisclosureStorageKey(storageKey);
          setRole(payload.role_id);
          setRoleDescription(payload.role_description);
          setInterviewContext(payload.job_offer);
          setRoleDefinition({
            role_id: payload.role_id,
            title: payload.role_title,
            location: "",
            description: payload.role_description,
            created_at: "",
            updated_at: "",
          });
          const canStart = payload.status === "active" || payload.status === "in_progress";
          const needsResume = payload.status === "in_progress";
          setInterviewCanStart(canStart);
          setInterviewNeedsResume(needsResume);
          setStatusText(
            canStart
              ? needsResume
                ? `Interview in progress for ${payload.candidate_name}. Resume to continue.`
                : `Interview ready for ${payload.candidate_name}.`
              : `Interview is ${payload.status.replace("_", " ")}. It can only start when active.`,
          );
        } catch (error) {
          if (!isCancelled) {
            setInterviewCanStart(false);
            setStatusText(error instanceof Error ? error.message : "Could not validate interview link.");
          }
        }
      })();
      return () => {
        isCancelled = true;
      };
    }

    const roleIdFromUrl = params.get("role_id") ?? params.get("id_role");
    if (!roleIdFromUrl) {
      return;
    }

    const normalizedRole = roleIdFromUrl.trim();
    if (!normalizedRole) {
      return;
    }

    setRole(normalizedRole);
    setRoleLockedFromUrl(true);
    setStatusText(`Loading role ${normalizedRole}...`);

    let isCancelled = false;

    void (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/admin/roles/${encodeURIComponent(normalizedRole)}`);
        if (!response.ok) {
          throw new Error(`Cannot load role ${normalizedRole}`);
        }

        const payload = (await response.json()) as RoleDefinition;
        if (isCancelled) {
          return;
        }

        setRoleDefinition(payload);
        setRole(payload.role_id);
        setRoleDescription(payload.description);
        setDocType("role_description");
        setStatusText(`Interview ready for ${payload.title}.`);
      } catch {
        if (!isCancelled) {
          setStatusText(`Role ${normalizedRole} is not available yet.`);
        }
      }
    })();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!disclosureStorageKey || !disclosureAccepted) return;
    try {
      window.localStorage.setItem(
        disclosureStorageKey,
        JSON.stringify({
          disclosureAccepted,
          focusTelemetryEnabled,
          accommodationFocus,
          accommodationTiming,
          accommodationInput,
          accommodationMotion,
          accommodationContent,
        }),
      );
    } catch {
      return;
    }
  }, [
    disclosureStorageKey,
    disclosureAccepted,
    focusTelemetryEnabled,
    accommodationFocus,
    accommodationTiming,
    accommodationInput,
    accommodationMotion,
    accommodationContent,
  ]);

  function recordTelemetry(signalFamily: "focus" | "timing" | "input" | "motion" | "content", eventType: string, value: string) {
    if (!disclosureAccepted || suppressedSignalFamilies.includes(signalFamily)) {
      return;
    }
    if (signalFamily === "focus" && !focusTelemetryEnabled) {
      return;
    }

    setTelemetryEvents((previous) => [
      ...previous,
      {
        signal_family: signalFamily,
        event_type: eventType,
        value,
      },
    ]);
  }

  function buildIntegrityPayload(
    extraEvents: IntegrityTelemetryEvent[] = [],
    currentMetrics: Record<string, number> = {},
  ): IntegrityPayload {
    const allowedExtraEvents = extraEvents.filter(
      (event) => !suppressedSignalFamilies.includes(event.signal_family),
    );
    const allowedMetrics = Object.fromEntries(
      Object.entries(currentMetrics).filter(([metric]) => {
        const family = METRIC_SIGNAL_FAMILIES[metric];
        return Boolean(family)
          && !suppressedSignalFamilies.includes(family)
          && (family !== "focus" || focusTelemetryEnabled);
      }),
    );
    return {
      disclosure_accepted: disclosureAccepted,
      focus_telemetry_enabled: focusTelemetryEnabled,
      suppressed_signal_families: suppressedSignalFamilies,
      telemetry_events: [...telemetryEvents, ...allowedExtraEvents],
      current_metrics: allowedMetrics,
    };
  }

  function trackAnswerInput(value: string, inputType: string) {
    const metrics = answerMetrics.current;
    const now = performance.now();
    const insertedCharacters = Math.max(0, value.length - metrics.previousLength);
    const pastedCharacters = Math.min(metrics.pendingPasteCharacters, insertedCharacters);

    if (insertedCharacters > 0 && pastedCharacters < insertedCharacters) {
      if (metrics.firstKeystrokeAt === null) metrics.firstKeystrokeAt = now;
      if (metrics.lastInputAt !== null) metrics.keystrokeIntervals.push(now - metrics.lastInputAt);
      metrics.typedCharacters += insertedCharacters - pastedCharacters;
      metrics.lastInputAt = now;
    }
    if (inputType.startsWith("delete") || value.length < metrics.previousLength) {
      metrics.revisionCount += 1;
    }
    metrics.pendingPasteCharacters -= pastedCharacters;
    metrics.previousLength = value.length;
  }

  function buildAnswerMetrics(answerText: string): Record<string, number> {
    const metrics = answerMetrics.current;
    const submittedAt = performance.now();
    const startedAt = metrics.focusedAt ?? metrics.firstKeystrokeAt ?? submittedAt;
    const elapsed = Math.max(submittedAt - startedAt, 1);
    const medianInterval = metrics.keystrokeIntervals.length
      ? [...metrics.keystrokeIntervals].sort((left, right) => left - right)[
          Math.floor(metrics.keystrokeIntervals.length / 2)
        ]
      : 0;

    return {
      answer_length: answerText.length,
      time_to_first_keystroke_ms: metrics.firstKeystrokeAt === null
        ? 0
        : metrics.firstKeystrokeAt - startedAt,
      composition_time_ms: metrics.firstKeystrokeAt === null
        ? elapsed
        : submittedAt - metrics.firstKeystrokeAt,
      words_per_minute: answerText.trim().split(/\s+/).filter(Boolean).length * 60_000 / elapsed,
      keystroke_interval_ms: medianInterval,
      paste_fraction: metrics.pastedCharacters / Math.max(answerText.length, 1),
      revision_ratio: metrics.revisionCount / Math.max(metrics.typedCharacters, 1),
      focus_blur_count: metrics.focusBlurCount,
    };
  }

  function applyInterviewPayload(payload: InterviewPayload) {
    const overloaded = payload.question === MODEL_OVERLOADED_MESSAGE;
    setSystemOverloaded(overloaded);
    setQuestion(payload.question ?? "");
    setQuestionIndex(payload.question_index);
    setTotalQuestions(payload.total_questions);
    setInterviewCompleted(payload.completed);
    setWarmup(Boolean(payload.warmup));

    if (overloaded) {
      setAnswer("");
      setStatusText(MODEL_OVERLOADED_MESSAGE);
      setInterviewStarted(false);
    }
  }

  async function startInterview() {
    const resuming = interviewNeedsResume;
    setBusy(true);
    setStatusText(resuming ? "Resuming interview..." : "Starting interview...");

      try {
      recordTelemetry("timing", "start_click", "candidate");
      const requestBody = {
        role,
        doc_type: docType,
        role_description: roleDescription || roleDefinition?.description || "",
        integrity: buildIntegrityPayload(),
        ...(interviewToken ? { interview_token: interviewToken } : {}),
      };
      console.log("[FRONTEND] POST /run/start payload:", requestBody);
      const response = await fetch(`${API_BASE_URL}/run/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => "");
        setStatusText(`No se pudo iniciar la entrevista. ${errText || "Intente nuevamente."}`);
        setInterviewNeedsResume(Boolean(interviewToken));
        return;
      }

      const payload = (await response.json()) as InterviewPayload;
      setRunId(payload.run_id);
      setInterviewStarted(true);
      setInterviewNeedsResume(Boolean(interviewToken));
      applyInterviewPayload(payload);
      if (!resuming || question !== payload.question) setAnswer("");
      setStatusText(
        payload.warmup
          ? resuming
            ? "Interview resumed. Continue with the warm-up."
            : "Warm-up started. This response establishes your personal baseline."
          : resuming
            ? "Interview resumed. Continue with the pending question."
            : "Interview started.",
      );
    } catch (error) {
      setInterviewNeedsResume(Boolean(interviewToken));
      setStatusText(
        error instanceof Error
          ? `Connection interrupted. Restore internet and press Resume Interview to continue. ${error.message}`
          : "Connection interrupted. Restore internet and press Resume Interview to continue.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer() {
    const trimmed = answer.trim();
    if (!trimmed) {
      setStatusText("Please enter an answer before submitting.");
      return;
    }

    if (!runId) {
      setStatusText("Run not initialized. Please start interview again.");
      return;
    }

    setBusy(true);
    setStatusText("Submitting answer...");

    try {
      const currentMetrics = buildAnswerMetrics(trimmed);
      const metricEvents: IntegrityTelemetryEvent[] = Object.entries(currentMetrics).map(
        ([eventType, value]) => ({
          signal_family: METRIC_SIGNAL_FAMILIES[eventType] as IntegrityTelemetryEvent["signal_family"],
          event_type: eventType,
          value: String(value),
        }),
      );
      metricEvents.push(
        ...answerMetrics.current.keystrokeIntervals.map((interval) => ({
          signal_family: "input" as const,
          event_type: "keystroke_interval_ms",
          value: String(interval),
        })),
      );
      const requestBody = {
        run_id: runId,
        answer: trimmed,
        role,
        doc_type: docType,
        integrity: buildIntegrityPayload(metricEvents, currentMetrics),
      };
      console.log("[FRONTEND] POST /run/answer payload:", requestBody);
      const response = await fetch(`${API_BASE_URL}/run/answer`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => "");
        setStatusText(
          `Hubo un error al enviar la respuesta. ${errText || "Por favor, intente nuevamente."} Use Resume Interview para recuperar la última pregunta guardada.`,
        );
        return;
      }

      const payload = (await response.json()) as InterviewPayload;
      applyInterviewPayload(payload);
      setAnswer("");
      answerMetrics.current = createAnswerMetricAccumulator();
      if (payload.completed) {
        setStatusText(finalThankYouMessage);
      } else {
        setStatusText("Answer recorded.");
      }
    } catch (error) {
      setStatusText(
        error instanceof Error
          ? `Connection interrupted. Your answer may not have been saved. Restore internet and press Resume Interview to continue. ${error.message}`
          : "Connection interrupted. Your answer may not have been saved. Restore internet and press Resume Interview to continue.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <h1>AI Interviewer</h1>
      <p id="status-text" className="status">
        {statusText}
      </p>

      <section className="panel disclosure-panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Before we begin</p>
            <h2>Integrity disclosure</h2>
          </div>
          <span className="badge">Telemetry is off by default</span>
        </div>
        <p className="disclosure-copy">
          You can complete the interview without focus telemetry. If you opt in, the app will collect
          lightweight interaction signals and send them to the reviewer appendix. This does not change your
          competency score.
        </p>

        <label className="checkbox-row">
          <input
            id="disclosure-checkbox"
            type="checkbox"
            checked={disclosureChecked}
            onChange={(event) => setDisclosureChecked(event.target.checked)}
          />
          I understand the disclosure and want to continue.
        </label>

        <label className="checkbox-row">
          <input
            id="telemetry-checkbox"
            type="checkbox"
            checked={focusTelemetryEnabled}
            onChange={(event) => setFocusTelemetryEnabled(event.target.checked)}
          />
          Enable focus telemetry for this session.
        </label>

        <fieldset className="accommodations-fieldset">
          <legend>Accommodation declaration</legend>
          <p>Declare any signal families that should be suppressed for review.</p>
          <label className="checkbox-row">
            <input
              id="accommodation-focus"
              type="checkbox"
              checked={accommodationFocus}
              onChange={(event) => setAccommodationFocus(event.target.checked)}
            />
            Focus / attention
          </label>
          <label className="checkbox-row">
            <input
              id="accommodation-timing"
              type="checkbox"
              checked={accommodationTiming}
              onChange={(event) => setAccommodationTiming(event.target.checked)}
            />
            Timing / latency
          </label>
          <label className="checkbox-row">
            <input
              id="accommodation-input"
              type="checkbox"
              checked={accommodationInput}
              onChange={(event) => setAccommodationInput(event.target.checked)}
            />
            Input / motor pattern
          </label>
          <label className="checkbox-row">
            <input id="accommodation-motion" type="checkbox" checked={accommodationMotion} onChange={(event) => setAccommodationMotion(event.target.checked)} />
            Motion / device interaction
          </label>
          <label className="checkbox-row">
            <input id="accommodation-content" type="checkbox" checked={accommodationContent} onChange={(event) => setAccommodationContent(event.target.checked)} />
            Content signals
          </label>
        </fieldset>

        <button
          id="accept-disclosure-btn"
          type="button"
          disabled={!disclosureChecked}
          onClick={() => {
            setDisclosureAccepted(true);
            setStatusText("Disclosure accepted. You can start the interview now.");
          }}
        >
          Accept disclosure
        </button>
      </section>

      <section className="panel">
        {roleLockedFromUrl ? (
          <div className="role-summary">
            <p>
              <strong>Role:</strong> {roleDefinition?.title ?? role}
            </p>
            <p>
              <strong>Location:</strong> {roleDefinition?.location ?? "Not specified"}
            </p>
            <p>
              <strong>Role ID:</strong> {role}
            </p>
          </div>
        ) : (
          <div className="filters">
            <label htmlFor="role-select">Role</label>
            <select id="role-select" value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="backend_engineer">Backend Engineer</option>
              <option value="frontend_engineer">Frontend Engineer</option>
            </select>

            <label htmlFor="doc-type-select">Document Type</label>
            <select id="doc-type-select" value={docType} onChange={(event) => setDocType(event.target.value)}>
              <option value="role_description">Role Description</option>
              <option value="engineering_standard">Engineering Standard</option>
            </select>
          </div>
        )}

        {roleLockedFromUrl && roleDefinition ? (
          <div
            className="role-description-box"
            style={{
              marginTop: "1rem",
              maxHeight: "220px",
              overflowY: "auto",
              border: "1px solid #e5e7eb",
              borderRadius: "8px",
              padding: "0.75rem 1rem",
              background: "#f9fafb",
            }}
          >
            <strong>Role description</strong>
            <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{roleDefinition.description}</p>
          </div>
        ) : null}

        {interviewToken && interviewContext ? (
          <div className="role-description-box" style={{ marginTop: "1rem", maxHeight: "160px", overflowY: "auto", border: "1px solid #e5e7eb", borderRadius: "8px", padding: "0.75rem 1rem", background: "#f9fafb" }}>
            <strong>Interview context</strong>
            <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{interviewContext}</p>
          </div>
        ) : null}

        <button id="start-btn" type="button" disabled={startDisabled} onClick={startInterview}>
          {busy
            ? interviewNeedsResume ? "Resuming..." : "Starting..."
            : interviewNeedsResume ? "Resume Interview" : "Start Interview"}
        </button>

        {systemOverloaded ? (
          <div
            id="system-overloaded-message"
            className="panel"
            role="alert"
            style={{
              marginTop: "1rem",
              borderColor: "#f59e0b",
              background: "linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%)",
              boxShadow: "0 10px 24px rgba(245, 158, 11, 0.18)",
              borderLeft: "5px solid #f59e0b",
              padding: "1rem 1.25rem",
            }}
          >
            <h2 style={{ margin: "0 0 0.5rem", color: "#9a4d00" }}>El sistema está saturado</h2>
            <p style={{ margin: 0, color: "#7c2d12", fontWeight: 500 }}>{MODEL_OVERLOADED_MESSAGE}</p>
          </div>
        ) : null}

        {interviewStarted && !interviewCompleted && !systemOverloaded ? (
          <div id="question-area">
            <div className="progress-block" aria-label="Interview progress">
              <div className="progress-label">
                <span>{warmup ? "Warm-up calibration" : `Question ${questionIndex} of ${totalQuestions}`}</span>
                {!warmup ? <span>{totalQuestions ? Math.round((questionIndex / totalQuestions) * 100) : 0}%</span> : <span>Baseline</span>}
              </div>
              <progress value={warmup ? 0 : questionIndex} max={totalQuestions || 1} />
            </div>
            <h2 id="question-text">{question}</h2>
            <div className="answer-toolbar" aria-label="Answer editor controls">
              <button type="button" className="toolbar-button" onClick={() => setAnswerPreview((value) => !value)}>
                {answerPreview ? "Edit" : "Preview"}
              </button>
              <button type="button" className={`toolbar-button ${monospaceMode ? "active" : ""}`} onClick={() => setMonospaceMode((value) => !value)}>
                Monospace
              </button>
              <button type="button" className={`toolbar-button ${codeMode ? "active" : ""}`} onClick={() => setCodeMode((value) => !value)}>
                Code mode
              </button>
            </div>
            {answerPreview ? (
              <div id="answer-preview" className={`answer-preview ${monospaceMode || codeMode ? "monospace" : ""}`}>
                {answer.trim() ? renderMarkdown(answer) : <span className="preview-empty">Nothing to preview yet.</span>}
              </div>
            ) : (
              <textarea
                id="answer-input"
                className={monospaceMode || codeMode ? "monospace" : ""}
                rows={6}
                placeholder={codeMode ? "Paste or write code here" : "Write your answer here"}
                value={answer}
                onFocus={() => {
                  answerMetrics.current.focusedAt ??= performance.now();
                  recordTelemetry("focus", "focus", "answer-input");
                }}
                onBlur={() => {
                  answerMetrics.current.focusBlurCount += 1;
                  recordTelemetry("focus", "blur", "answer-input");
                }}
                onPaste={(event) => {
                  const pastedCharacters = event.clipboardData.getData("text").length;
                  answerMetrics.current.pastedCharacters += pastedCharacters;
                  answerMetrics.current.pendingPasteCharacters += pastedCharacters;
                  recordTelemetry("input", "paste_characters", String(pastedCharacters));
                }}
                onInput={(event) => {
                  const inputEvent = event.nativeEvent as InputEvent;
                  const value = (event.target as HTMLTextAreaElement).value;
                  trackAnswerInput(value, inputEvent.inputType || "insertText");
                  recordTelemetry("input", "input", String(value.length));
                }}
                onPointerMove={() => recordTelemetry("motion", "pointer_move", "answer-input")}
                onChange={(event) => setAnswer(event.target.value)}
              />
            )}
            <div className="actions">
              <button id="submit-answer" type="button" disabled={submitDisabled} onClick={submitAnswer}>
                {busy && interviewStarted ? "Submitting..." : "Submit Answer"}
              </button>
            </div>
          </div>
        ) : null}

        {interviewCompleted ? (
          <div
            id="completion-message"
            className="panel"
            style={{
              marginTop: "1rem",
              background: "linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)",
              borderColor: "#10b981",
              borderLeft: "5px solid #10b981",
              boxShadow: "0 10px 24px rgba(16, 185, 129, 0.15)",
              padding: "1rem 1.25rem",
            }}
          >
            <h2 style={{ margin: "0 0 0.5rem", color: "#065f46" }}>Muchas gracias por su participación.</h2>
            <p style={{ margin: 0, color: "#065f46", fontWeight: 500 }}>
              En breve nos comunicaremos con usted vía email.
            </p>
          </div>
        ) : null}

      </section>
    </main>
  );
}

function renderMarkdown(value: string): ReactNode[] {
  const lines = value.split("\n");
  const nodes: ReactNode[] = [];
  let inCode = false;
  let codeLines: string[] = [];

  lines.forEach((line, index) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        nodes.push(<pre key={`code-${index}`}><code>{codeLines.join("\n")}</code></pre>);
        codeLines = [];
      }
      inCode = !inCode;
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }
      if (line.startsWith("### ")) nodes.push(<h4 key={index}>{renderInlineMarkdown(line.slice(4), `${index}`)}</h4>);
      else if (line.startsWith("## ")) nodes.push(<h3 key={index}>{renderInlineMarkdown(line.slice(3), `${index}`)}</h3>);
      else if (line.startsWith("# ")) nodes.push(<h2 key={index}>{renderInlineMarkdown(line.slice(2), `${index}`)}</h2>);
      else {
        const content = renderInlineMarkdown(line, `${index}`);
        if (line.startsWith("- ") || line.startsWith("* ")) nodes.push(<li key={index}>{content.slice(1)}</li>);
        else nodes.push(<p key={index}>{content}</p>);
      }
  });
  if (inCode) nodes.push(<pre key="code-open"><code>{codeLines.join("\n")}</code></pre>);
  return nodes;
}

function renderInlineMarkdown(value: string, keyPrefix: string): ReactNode[] {
  return value.split(/(`[^`]+`)/g).map((part, index) =>
    part.startsWith("`") && part.endsWith("`")
      ? <code key={`${keyPrefix}-${index}`}>{part.slice(1, -1)}</code>
      : <span key={`${keyPrefix}-${index}`}>{part}</span>,
  );
}
