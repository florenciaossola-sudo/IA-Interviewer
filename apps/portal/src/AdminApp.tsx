import { useEffect, useState } from "react";
import { AnalyticsSection } from "./components/AnalyticsSection";
import { useAnalytics } from "./hooks/useAnalytics";

const API_BASE_URL = "http://127.0.0.1:8081";
const ACTIVE_LANGGRAPH_THRESHOLDS = {
  decision: 0.75,
  conclusion: 0.55,
  confidence: 0.7,
};

type RoleDefinition = {
  role_id: string;
  title: string;
  location: string;
  description: string;
  created_at: string;
  updated_at: string;
};

type CorpusDocument = {
  doc_id: string;
  filename: string;
  doc_type: string;
  role: string;
  status: "ingested" | "failed" | "ingesting";
  chunk_count: number;
  created_at: string;
  updated_at: string;
  last_ingested_at: string | null;
  error: string | null;
};

type ScheduledInterview = {
  interview_id: string;
  candidate_name: string;
  candidate_email: string;
  role_id: string;
  job_offer: string;
  scheduled_at: string;
  expires_at: string;
  status: string;
  invitation_status: "not_sent" | "sending" | "sent" | "logged" | "failed";
  invitation_sent_at: string | null;
  invitation_error: string | null;
  invitation_attempts: number;
  reviewer: string;
  created_at: string;
  updated_at: string;
};

type AdminAuditEvent = {
  event_id: number;
  actor: string;
  event_type: string;
  target: string;
  details: Record<string, unknown>;
  created_at: string;
};

type SyncRun = {
  sync_id: number;
  status: string;
  snapshot_id: number | null;
  diagnostics: string;
  started_at: string;
  completed_at: string;
};

type RoleConfiguration = {
  role_id: string;
  decision_threshold: number;
  recommendation_low_max: number;
  recommendation_high_min: number;
  conclusion_threshold: number;
  confidence_threshold: number;
  max_turns: number;
  interviewer_persona: string;
  question_prompt: string;
  updated_at: string | null;
};

type IntegrityConfiguration = {
  signal_weights: Record<string, number>;
  max_penalty: number;
  ai_text_cap: number;
  updated_at?: string;
};

const DOCUMENT_TYPES = [
  { value: "role_description", label: "Role description" },
  { value: "engineering_standard", label: "Engineering standard" },
  { value: "competency_framework", label: "Competency framework" },
  { value: "topic_bank", label: "Topic bank" },
  { value: "exemplar_answer", label: "Exemplar answer" },
];

function toLocalDateTimeInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function addDays(value: Date, days: number): Date {
  const result = new Date(value);
  result.setDate(result.getDate() + days);
  return result;
}

function AdminScreen() {
  const analytics = useAnalytics();
  const [adminStatus, setAdminStatus] = useState("Load the roles available in the system.");
  const [roles, setRoles] = useState<RoleDefinition[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string>("sr_software_engineer");
  const [roleId, setRoleId] = useState("sr_software_engineer");
  const [title, setTitle] = useState("SR Software Engineer (Data)");
  const [location, setLocation] = useState("Rochester, New York (Remote)");
  const [description, setDescription] = useState(
    "Design data pipelines and agent systems for LLM-native products.",
  );
  const [isSavingRole, setIsSavingRole] = useState(false);
  const [documents, setDocuments] = useState<CorpusDocument[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState("role_description");
  const [documentRole, setDocumentRole] = useState("backend_engineer");
  const [corpusStatus, setCorpusStatus] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [interviews, setInterviews] = useState<ScheduledInterview[]>([]);
  const [interviewSearch, setInterviewSearch] = useState("");
  const [interviewStatusFilter, setInterviewStatusFilter] = useState("");
  const [interviewOffset, setInterviewOffset] = useState(0);
  const [interviewTotal, setInterviewTotal] = useState(0);
  const [interviewStatus, setInterviewStatus] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [candidateEmail, setCandidateEmail] = useState("");
  const [interviewRoleId, setInterviewRoleId] = useState("");
  const [jobOffer, setJobOffer] = useState("");
  const [scheduledAt, setScheduledAt] = useState(() => toLocalDateTimeInput(new Date()));
  const [expiresAt, setExpiresAt] = useState(() => toLocalDateTimeInput(addDays(new Date(), 7)));
  const [createdCandidateLink, setCreatedCandidateLink] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [bulkFile, setBulkFile] = useState<File | null>(null);
  const [configRoleId, setConfigRoleId] = useState("");
  const [roleConfiguration, setRoleConfiguration] = useState<RoleConfiguration>({
    role_id: "", decision_threshold: 0.75, recommendation_low_max: 0.4,
    recommendation_high_min: 0.7, conclusion_threshold: 0.55, confidence_threshold: 0.7,
    max_turns: 3, interviewer_persona: "", question_prompt: "", updated_at: null,
  });
  const [integrityConfiguration, setIntegrityConfiguration] = useState<IntegrityConfiguration>({
    signal_weights: { focus: 3, timing: 3, input: 3, motion: 3, content: 3 },
    max_penalty: 100, ai_text_cap: 0.1,
  });
  const [configurationStatus, setConfigurationStatus] = useState("");
  const [auditEvents, setAuditEvents] = useState<AdminAuditEvent[]>([]);
  const [auditSearch, setAuditSearch] = useState("");
  const [auditTotal, setAuditTotal] = useState(0);
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);

  const selectedRole = roles.find((item) => item.role_id === selectedRoleId) ?? roles[0] ?? null;
  const documentTypes = Array.from(
    new Set([...DOCUMENT_TYPES.map((item) => item.value), ...documents.map((item) => item.doc_type)]),
  );
  const documentRoles = roles.map((item) => [item.role_id, item.title] as const);
  const interviewRoles = Array.from(
    new Map(
      roles.map((role) => [role.role_id, role] as const),
    ).values(),
  );

  useEffect(() => {
    void loadRoles();
    void loadCorpusDocuments();
    void loadInterviews();
    void loadAuditEvents();
    void loadSyncHistory();
    void loadIntegrityConfiguration();
  }, []);

  useEffect(() => {
    if (configRoleId) {
      void loadRoleConfiguration(configRoleId);
    }
  }, [configRoleId]);

  async function loadRoles() {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/roles`);
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}.`);
      }

      const payload = (await response.json()) as RoleDefinition[];
      setRoles(payload);
      const savedIds = new Set(payload.map((item) => item.role_id));

      if (payload.length > 0) {
        setSelectedRoleId(payload[0].role_id);
        setConfigRoleId((current) => savedIds.has(current) ? current : payload[0].role_id);
        setInterviewRoleId((current) => savedIds.has(current) ? current : payload[0].role_id);
        setDocumentRole((current) => current || payload[0].role_id);
      } else {
        setConfigRoleId("");
        setInterviewRoleId("");
      }
    } catch {
      setAdminStatus("Could not load roles from the admin API.");
    }
  }

  async function saveRole(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSavingRole(true);
    setAdminStatus("Saving role...");

    try {
      const response = await fetch(`${API_BASE_URL}/admin/roles`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          role_id: roleId,
          title,
          location,
          description,
        }),
      });

      if (!response.ok) {
        throw new Error(`Save failed with status ${response.status}.`);
      }

      const payload = (await response.json()) as RoleDefinition;
      setAdminStatus(`Saved role: ${payload.role_id}`);
      setSelectedRoleId(payload.role_id);
      await loadRoles();
    } catch {
      setAdminStatus("The role could not be saved.");
    } finally {
      setIsSavingRole(false);
    }
  }

  async function loadCorpusDocuments() {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/corpus/documents`);
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}.`);
      }
      setDocuments((await response.json()) as CorpusDocument[]);
    } catch {
      setCorpusStatus("Could not load corpus documents from the admin API.");
    }
  }

  async function uploadDocument(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      return;
    }
    const form = event.currentTarget;
    setIsUploading(true);
    setCorpusStatus("Uploading and ingesting document...");
    const query = new URLSearchParams({
      filename: selectedFile.name,
      doc_type: documentType,
      role: documentRole,
    });

    try {
      const response = await fetch(`${API_BASE_URL}/admin/corpus/documents?${query}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: selectedFile,
      });
      const payload = (await response.json()) as CorpusDocument | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload ? payload.detail : `Upload failed (${response.status}).`);
      }
      const document = payload as CorpusDocument;
      setCorpusStatus(
        document.status === "ingested"
          ? `Ingested ${document.filename}: ${document.chunk_count} chunks.`
          : `Ingestion failed: ${document.error ?? "Unknown error"}`,
      );
      setSelectedFile(null);
      form.reset();
      await loadCorpusDocuments();
    } catch (error) {
      setCorpusStatus(error instanceof Error ? error.message : "The document could not be uploaded.");
    } finally {
      setIsUploading(false);
    }
  }

  async function reingestDocument(document: CorpusDocument) {
    setCorpusStatus(`Re-ingesting ${document.filename}...`);
    try {
      const response = await fetch(
        `${API_BASE_URL}/admin/corpus/documents/${encodeURIComponent(document.doc_id)}/ingest`,
        { method: "POST" },
      );
      const payload = (await response.json()) as CorpusDocument | { detail?: string };
      if (!response.ok) {
        throw new Error("detail" in payload ? payload.detail : `Re-ingestion failed (${response.status}).`);
      }
      const updated = payload as CorpusDocument;
      setCorpusStatus(
        updated.status === "ingested"
          ? `Ingested ${updated.filename}: ${updated.chunk_count} chunks.`
          : `Ingestion failed: ${updated.error ?? "Unknown error"}`,
      );
      await loadCorpusDocuments();
    } catch (error) {
      setCorpusStatus(error instanceof Error ? error.message : "The document could not be re-ingested.");
    }
  }

  async function deleteDocument(document: CorpusDocument) {
    if (!window.confirm(`Delete ${document.filename} and its indexed content?`)) {
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE_URL}/admin/corpus/documents/${encodeURIComponent(document.doc_id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(`Delete failed (${response.status}).`);
      }
      setCorpusStatus(`Deleted ${document.filename}.`);
      await loadCorpusDocuments();
    } catch (error) {
      setCorpusStatus(error instanceof Error ? error.message : "The document could not be deleted.");
    }
  }

  async function loadInterviews(nextOffset = interviewOffset) {
    const query = new URLSearchParams({
      search: interviewSearch,
      status: interviewStatusFilter,
      limit: "10",
      offset: String(nextOffset),
    });
    try {
      const response = await fetch(`${API_BASE_URL}/admin/interviews?${query}`);
      if (!response.ok) throw new Error(`Request failed (${response.status}).`);
      const payload = await response.json() as { items: ScheduledInterview[]; total: number };
      setInterviews(payload.items);
      setInterviewTotal(payload.total);
      setInterviewOffset(nextOffset);
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not load interviews.");
    }
  }

  async function exportInterviewsCsv() {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/interviews/export.csv`);
      if (!response.ok) throw new Error(`Export failed (${response.status}).`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "scheduled-interviews.csv";
      anchor.click();
      URL.revokeObjectURL(url);
      setInterviewStatus("Interview CSV exported.");
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not export interview CSV.");
    }
  }

  async function createInterview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setInterviewStatus("Creating interview...");
    try {
      const response = await fetch(`${API_BASE_URL}/admin/interviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_name: candidateName,
          candidate_email: candidateEmail,
          role_id: interviewRoleId,
          job_offer: jobOffer,
          scheduled_at: new Date(scheduledAt).toISOString(),
          expires_at: new Date(expiresAt).toISOString(),
        }),
      });
      const payload = await response.json() as { interview?: ScheduledInterview; candidate_url?: string; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? `Create failed (${response.status}).`);
      setCreatedCandidateLink(payload.candidate_url ?? "");
      setCandidateName("");
      setCandidateEmail("");
      setJobOffer("");
      setInterviewStatus(`Created ${payload.interview?.interview_id ?? "interview"}. Link is ready to copy.`);
      await loadInterviews(0);
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not create interview.");
    }
  }

  async function importInterviewCsv(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!bulkFile) return;
    setInterviewStatus("Importing CSV...");
    try {
      const response = await fetch(`${API_BASE_URL}/admin/interviews/bulk`, {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: bulkFile,
      });
      const payload = await response.json() as { created?: number; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? `Import failed (${response.status}).`);
      setInterviewStatus(`Created ${payload.created ?? 0} interviews from CSV.`);
      setBulkFile(null);
      event.currentTarget.reset();
      await loadInterviews(0);
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not import CSV.");
    }
  }

  async function interviewAction(
    interview: ScheduledInterview,
    action: "activate" | "revoke" | "regenerate-link" | "send-invitation",
  ) {
    try {
      const actionPath = action === "send-invitation" ? "send-invitation" : action;
      const response = await fetch(
        `${API_BASE_URL}/admin/interviews/${encodeURIComponent(interview.interview_id)}/${actionPath}`,
        { method: "POST" },
      );
      const payload = await response.json() as { candidate_url?: string; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? `Action failed (${response.status}).`);
      if (payload.candidate_url) setCreatedCandidateLink(payload.candidate_url);
      if (action === "regenerate-link") {
        setInterviewStatus("Old link invalidated. Copy the regenerated link.");
      } else if (action === "send-invitation") {
        setInterviewStatus("Candidate invitation sent.");
      } else {
        setInterviewStatus(`Interview ${action}d.`);
      }
      await loadInterviews();
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Interview action failed.");
      await loadInterviews();
    }
  }

  async function assignReviewer(interview: ScheduledInterview, reviewer: string) {
    try {
      const response = await fetch(
        `${API_BASE_URL}/admin/interviews/${encodeURIComponent(interview.interview_id)}/reviewer`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewer }),
        },
      );
      if (!response.ok) throw new Error(`Assignment failed (${response.status}).`);
      await loadInterviews();
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not assign reviewer.");
    }
  }

  async function copyCandidateLink() {
    if (!createdCandidateLink) return;
    await navigator.clipboard.writeText(createdCandidateLink);
    setCopyStatus("Copied");
  }

  async function loadAuditEvents() {
    const query = new URLSearchParams({ search: auditSearch, limit: "20" });
    try {
      const response = await fetch(`${API_BASE_URL}/admin/audit-events?${query}`);
      if (!response.ok) throw new Error(`Audit request failed (${response.status}).`);
      const payload = await response.json() as { items: AdminAuditEvent[]; total: number };
      setAuditEvents(payload.items);
      setAuditTotal(payload.total);
    } catch (error) {
      setInterviewStatus(error instanceof Error ? error.message : "Could not load audit events.");
    }
  }

  async function loadSyncHistory() {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/analytics/sync-history`);
      if (response.ok) setSyncRuns(await response.json() as SyncRun[]);
    } catch {
      setInterviewStatus("Could not load analytics sync history.");
    }
  }

  async function loadRoleConfiguration(role: string) {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/roles/${encodeURIComponent(role)}/configuration`);
      if (!response.ok) throw new Error(`Configuration request failed (${response.status}).`);
      setRoleConfiguration(await response.json() as RoleConfiguration);
    } catch (error) {
      setConfigurationStatus(error instanceof Error ? error.message : "Could not load role configuration.");
    }
  }

  async function saveRoleConfiguration(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!configRoleId) return;
    try {
      const response = await fetch(`${API_BASE_URL}/admin/roles/${encodeURIComponent(configRoleId)}/configuration`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...roleConfiguration, role_id: undefined, updated_at: undefined }),
      });
      const payload = await response.json() as RoleConfiguration | { detail?: string };
      if (!response.ok) throw new Error("detail" in payload ? payload.detail : `Save failed (${response.status}).`);
      setRoleConfiguration(payload as RoleConfiguration);
      setConfigurationStatus(`Saved configuration for ${configRoleId}.`);
      await loadAuditEvents();
    } catch (error) {
      setConfigurationStatus(error instanceof Error ? error.message : "Could not save role configuration.");
    }
  }

  async function saveIntegrityConfiguration(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const response = await fetch(`${API_BASE_URL}/admin/integrity/configuration`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(integrityConfiguration),
      });
      const payload = await response.json() as IntegrityConfiguration | { detail?: string };
      if (!response.ok) throw new Error("detail" in payload ? payload.detail : `Save failed (${response.status}).`);
      setIntegrityConfiguration(payload as IntegrityConfiguration);
      setConfigurationStatus("Saved integrity scoring settings.");
      await loadAuditEvents();
    } catch (error) {
      setConfigurationStatus(error instanceof Error ? error.message : "Could not save integrity settings.");
    }
  }

  async function loadIntegrityConfiguration() {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/integrity/configuration`);
      if (response.ok) setIntegrityConfiguration(await response.json() as IntegrityConfiguration);
    } catch {
      setConfigurationStatus("Could not load integrity configuration.");
    }
  }

  const candidateLink = selectedRole
    ? `http://127.0.0.1:4174/?role_id=${selectedRole.role_id}`
    : "http://127.0.0.1:4174/";

  return (
    <>
      <section className="card admin-hero admin-section">
        <div className="admin-heading">
          <p className="eyebrow">Admin portal</p>
          <h1>Manage hiring roles for candidate interviews.</h1>
          <p className="lede">
            Save the job opening, derive the stable role id, and generate the link that the candidate will use to start the interview.
          </p>
        </div>

        <div className="admin-grid">
          <form className="admin-form" onSubmit={saveRole}>
            <label>
              Role id
              <input
                value={roleId}
                onChange={(event) => setRoleId(event.target.value.trim())}
                placeholder="sr_software_engineer"
              />
            </label>

            <label>
              Title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="SR Software Engineer (Data)"
              />
            </label>

            <label>
              Location
              <input
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="Rochester, New York (Remote)"
              />
            </label>

            <label>
              Job description
              <textarea
                rows={10}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Paste the role description here"
              />
            </label>

            <button type="submit" disabled={isSavingRole}>
              {isSavingRole ? "Saving..." : "Save role"}
            </button>

            <p className="admin-status">{adminStatus}</p>
          </form>

          <aside className="role-list-panel">
            <div className="panel-head compact">
              <div>
                <p className="eyebrow small">Available roles</p>
                <h2>Saved openings</h2>
              </div>
              <button type="button" className="secondary" onClick={() => void loadRoles()}>
                Refresh
              </button>
            </div>

            <ul className="role-list">
              {roles.length === 0 ? (
                <li className="empty-role">No roles saved yet.</li>
              ) : (
                roles.map((role) => (
                  <li key={role.role_id}>
                    <button
                      type="button"
                      className={selectedRoleId === role.role_id ? "role-item active" : "role-item"}
                      onClick={() => setSelectedRoleId(role.role_id)}
                    >
                      <strong>{role.title}</strong>
                      <span>{role.role_id}</span>
                      <small>{role.location}</small>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </aside>
        </div>
      </section>

      <section className="card admin-preview">
        <div className="panel-head compact">
          <div>
            <p className="eyebrow small">Role preview</p>
            <h2>{selectedRole ? selectedRole.title : "No role selected"}</h2>
          </div>
        </div>

        {selectedRole ? (
          <>
            <p className="role-meta">
              <strong>Role id:</strong> {selectedRole.role_id}
            </p>
            <p className="role-meta">
              <strong>Location:</strong> {selectedRole.location}
            </p>
            <div className="role-description-box">
              {selectedRole.description}
            </div>
            <div className="candidate-link-box">
              <label>Candidate link</label>
              <input value={candidateLink} readOnly />
            </div>
          </>
        ) : (
          <p className="lede">Select or save a role to preview it.</p>
        )}
      </section>

      <section className="card admin-configuration">
        <div className="panel-head compact"><div><p className="eyebrow small">Hiring policy</p><h2>Role-level configuration</h2></div></div>
        <form className="role-configuration-form" onSubmit={saveRoleConfiguration}>
          <label>Role<select required value={configRoleId} onChange={(event) => setConfigRoleId(event.target.value)}>
            <option value="" disabled>{interviewRoles.length ? "Select a saved role" : "No saved roles"}</option>
            {interviewRoles.map((role) => <option key={role.role_id} value={role.role_id}>{role.title} ({role.role_id})</option>)}
          </select></label>
          <label>Decision threshold<input aria-describedby="threshold-decision threshold-limitations" type="number" value={ACTIVE_LANGGRAPH_THRESHOLDS.decision} readOnly /></label>
          <label>Low recommendation max<input aria-describedby="threshold-low" type="number" min="0" max="1" step="0.01" value={roleConfiguration.recommendation_low_max} onChange={(event) => setRoleConfiguration({ ...roleConfiguration, recommendation_low_max: Number(event.target.value) })} /></label>
          <label>High recommendation min<input aria-describedby="threshold-high" type="number" min="0" max="1" step="0.01" value={roleConfiguration.recommendation_high_min} onChange={(event) => setRoleConfiguration({ ...roleConfiguration, recommendation_high_min: Number(event.target.value) })} /></label>
          <label>Conclusion score threshold<input aria-describedby="threshold-conclusion threshold-limitations" type="number" value={ACTIVE_LANGGRAPH_THRESHOLDS.conclusion} readOnly /></label>
          <label>Confidence threshold<input aria-describedby="threshold-confidence threshold-limitations" type="number" value={ACTIVE_LANGGRAPH_THRESHOLDS.confidence} readOnly /></label>
          <label>Maximum interview questions (warm-up excluded)<input type="number" min="3" max="10" step="1" value={roleConfiguration.max_turns} onChange={(event) => setRoleConfiguration({ ...roleConfiguration, max_turns: Number(event.target.value) })} /></label>
          <label>Interviewer persona<input value={roleConfiguration.interviewer_persona} onChange={(event) => setRoleConfiguration({ ...roleConfiguration, interviewer_persona: event.target.value })} placeholder="e.g. supportive, concise, technical" /></label>
          <label className="configuration-wide">Question prompt guidance<textarea rows={3} value={roleConfiguration.question_prompt} onChange={(event) => setRoleConfiguration({ ...roleConfiguration, question_prompt: event.target.value })} /></label>
          <button type="submit" disabled={!configRoleId}>Save role settings</button>
          <div className="threshold-help">
            <p>Scores range from 0 to 1. These settings guide the interview; they are not final hiring decisions.</p>
            <p id="threshold-decision"><strong>Decision threshold:</strong> A single answer at or above this score can move the interview to the next competency, when one remains. Other rules can also trigger a switch.</p>
            <p id="threshold-low"><strong>Low recommendation max:</strong> An answer at or below this score lowers the next question&apos;s difficulty by one level, down to low. An off-topic answer also lowers difficulty.</p>
            <p id="threshold-high"><strong>High recommendation min:</strong> An on-topic answer at or above this score raises the next question&apos;s difficulty by one level, up to high. Scores between the low and high limits keep the same difficulty.</p>
            <p id="threshold-conclusion"><strong>Conclusion score threshold:</strong> The latest answer must reach this score to conclude the automated interview, together with the other conclusion conditions.</p>
            <p id="threshold-confidence"><strong>Confidence threshold:</strong> The average of all scored answers must reach this value to conclude, once all competencies are covered and the latest answer meets the conclusion threshold.</p>
            <p id="threshold-limitations"><strong>Fixed values:</strong> Decision, conclusion and confidence show the values currently used by LangGraph and cannot be edited here. Low and high difficulty thresholds remain configurable.</p>
          </div>
        </form>
        <div hidden>
        <form className="integrity-configuration-form" onSubmit={saveIntegrityConfiguration}>
          <div><p className="eyebrow small">Integrity policy</p><h3>Signal weights and caps</h3></div>
          {Object.entries(integrityConfiguration.signal_weights).map(([family, weight]) => <label key={family}>{family} weight<input aria-describedby={`integrity-${family} integrity-weights integrity-accommodations`} type="number" min="0" max="20" value={weight} onChange={(event) => setIntegrityConfiguration({ ...integrityConfiguration, signal_weights: { ...integrityConfiguration.signal_weights, [family]: Number(event.target.value) } })} /></label>)}
          <label>Maximum penalty<input aria-describedby="integrity-penalty" type="number" min="0" max="100" value={integrityConfiguration.max_penalty} onChange={(event) => setIntegrityConfiguration({ ...integrityConfiguration, max_penalty: Number(event.target.value) })} /></label>
          <label>AI-text signal cap<input aria-describedby="integrity-content integrity-cap" type="number" min="0" max="0.1" step="0.01" value={integrityConfiguration.ai_text_cap} onChange={(event) => setIntegrityConfiguration({ ...integrityConfiguration, ai_text_cap: Number(event.target.value) })} /></label>
          <button type="submit" className="secondary">Save integrity settings</button>
          <div className="threshold-help">
            <p id="integrity-weights"><strong>Signal weights:</strong> Control each available signal family&apos;s relative influence on the integrity index (AAI), not the technical answer score. A weight of 0 excludes that family; equal weights have equal influence.</p>
            <p id="integrity-focus"><strong>Focus:</strong> Changes in answer-field focus. Focus telemetry is optional and is excluded when not enabled by the candidate.</p>
            <p id="integrity-timing"><strong>Timing:</strong> Changes in response timing, such as time to first keystroke, composition time and typing speed.</p>
            <p id="integrity-input"><strong>Input:</strong> Changes in input patterns, such as answer length, keystroke intervals, paste fraction and revisions.</p>
            <p id="integrity-motion"><strong>Motion:</strong> Device interaction signals. The current baseline calculation does not produce a motion deviation, so its weight currently has no effect on the AAI.</p>
            <p id="integrity-content"><strong>Content:</strong> Text-related signals. The current baseline calculation does not produce a content deviation, so its weight and AI-text cap currently have no effect on the AAI.</p>
            <p id="integrity-penalty"><strong>Maximum penalty:</strong> Scales the weighted deviation into the AAI; 100 applies the full scale. If disclosure is not accepted, 6 points are added separately, up to an overall index of 100.</p>
            <p id="integrity-cap"><strong>AI-text signal cap:</strong> Limits the content deviation used in the AAI to at most this fraction (maximum 0.10), if a content deviation is available; it is not a percentage of AI authorship.</p>
            <p id="integrity-accommodations"><strong>Accommodation declaration:</strong> The candidate can suppress any of these families. Suppressed families are excluded from the AAI regardless of their weight. Available signals are compared with the warm-up baseline; missing signals do not contribute.</p>
            <p>The AAI is a review signal, not proof of misconduct or an automatic hiring decision.</p>
          </div>
        </form>
        </div>
        <p className="admin-status" aria-live="polite">{configurationStatus}</p>
      </section>

      <section className="card admin-interviews">
        <div className="panel-head compact">
          <div>
            <p className="eyebrow small">Interview operations</p>
            <h2>Scheduled interviews</h2>
          </div>
          <button type="button" className="secondary" onClick={() => void loadInterviews(0)}>Refresh</button>
        </div>

        <form className="interview-create-form" onSubmit={createInterview}>
          <label>Candidate name<input value={candidateName} onChange={(event) => setCandidateName(event.target.value)} required /></label>
          <label>Candidate email<input type="email" value={candidateEmail} onChange={(event) => setCandidateEmail(event.target.value)} required /></label>
          <label>Role<select required value={interviewRoleId} onChange={(event) => setInterviewRoleId(event.target.value)}>
            <option value="" disabled>{interviewRoles.length ? "Select a saved role" : "No saved roles"}</option>
            {interviewRoles.map((role) => <option key={role.role_id} value={role.role_id}>{role.title} ({role.role_id})</option>)}
          </select></label>
          <label>Scheduled at<input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} required /></label>
          <label>Link expires at<input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required /></label>
          <label className="interview-job-offer">Job offer / interview context<textarea rows={3} value={jobOffer} onChange={(event) => setJobOffer(event.target.value)} placeholder="Optional context for this candidate" /></label>
          <button type="submit" disabled={!interviewRoleId}>Create interview</button>
        </form>
        {createdCandidateLink ? (
          <div className="candidate-link-box interview-link-box">
            <label htmlFor="created-candidate-link">Candidate link</label>
            <div className="interview-link-row">
              <input id="created-candidate-link" value={createdCandidateLink} readOnly />
              <button type="button" onClick={() => void copyCandidateLink()}>Copy link</button>
              <span aria-live="polite">{copyStatus}</span>
            </div>
          </div>
        ) : null}
        <form className="interview-bulk-form" onSubmit={importInterviewCsv}>
          <label>Bulk import CSV<input aria-describedby="bulk-import-help" type="file" accept=".csv,text/csv" onChange={(event) => setBulkFile(event.target.files?.[0] ?? null)} required /></label>
          <button type="submit" className="secondary" disabled={!bulkFile}>Import CSV</button>
          <button type="button" className="secondary" onClick={() => void exportInterviewsCsv()}>Export CSV</button>
        </form>
        <div id="bulk-import-help" className="bulk-import-help">
          <p>Import multiple scheduled interviews at once: one candidate and interview per CSV row. Use a UTF-8 comma-separated file with these column headers:</p>
          <p><code>candidate_name,candidate_email,role_id,scheduled_at,expires_at</code> (required); <code>job_offer</code> (optional).</p>
          <p>Use a saved role ID. Dates must include a time zone, for example <code>2026-12-01T10:00:00-03:00</code>; the expiration must be later than the scheduled time. Import creates scheduled interviews; it does not send invitations.</p>
          <p>If a row fails, earlier rows may already have been created. Check the interview list before retrying.</p>
        </div>
        <p className="admin-status" aria-live="polite">{interviewStatus}</p>

        <div className="interview-filters">
          <input aria-label="Search interviews" placeholder="Search candidate, email, role or ID" value={interviewSearch} onChange={(event) => setInterviewSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadInterviews(0); }} />
          <select aria-label="Filter interviews by status" value={interviewStatusFilter} onChange={(event) => { setInterviewStatusFilter(event.target.value); void loadInterviews(0); }}>
            <option value="">All statuses</option>
            {["scheduled", "active", "in_progress", "completed", "expired", "revoked"].map((status) => <option key={status} value={status}>{status.replace("_", " ")}</option>)}
          </select>
          <button type="button" className="secondary" onClick={() => void loadInterviews(0)}>Search</button>
        </div>
        <ul className="scheduled-interview-list">
          {interviews.length === 0 ? <li className="empty-role">No interviews found.</li> : interviews.map((interview) => (
            <li className="scheduled-interview-row" key={interview.interview_id}>
              <div className="scheduled-interview-info">
                <strong>{interview.candidate_name}</strong>
                <span>{interview.candidate_email} · {interview.role_id}</span>
                <span>{interview.interview_id} · {interview.status}</span>
                <span>
                  Invitation: {interview.invitation_status === "logged" ? "logged only (not emailed)" : interview.invitation_status}
                  {interview.invitation_attempts ? ` · ${interview.invitation_attempts} attempt(s)` : ""}
                  {interview.invitation_sent_at ? ` · sent ${new Date(interview.invitation_sent_at).toLocaleString()}` : ""}
                </span>
                {interview.invitation_error ? <small className="invitation-error">{interview.invitation_error}</small> : null}
                <small>Scheduled {new Date(interview.scheduled_at).toLocaleString()} · Expires {new Date(interview.expires_at).toLocaleString()}</small>
              </div>
              <div className="scheduled-interview-actions">
                <label>Reviewer<input aria-label={`Reviewer for ${interview.candidate_name}`} defaultValue={interview.reviewer} onBlur={(event) => { if (event.target.value !== interview.reviewer) void assignReviewer(interview, event.target.value); }} placeholder="Assign reviewer" /></label>
                {interview.status === "scheduled" ? <button type="button" className="secondary" onClick={() => void interviewAction(interview, "activate")}>Activate</button> : null}
                {interview.status === "active" && ["not_sent", "failed", "logged"].includes(interview.invitation_status) ? (
                  <button type="button" className="secondary" onClick={() => void interviewAction(interview, "send-invitation")}>
                    {interview.invitation_status === "failed" ? "Retry invitation" : interview.invitation_status === "logged" ? "Send email" : "Send invitation"}
                  </button>
                ) : null}
                {!(["revoked", "expired", "completed"].includes(interview.status)) ? <button type="button" className="secondary" onClick={() => void interviewAction(interview, "regenerate-link")}>Regenerate link</button> : null}
                {!(["revoked", "expired", "completed"].includes(interview.status)) ? <button type="button" className="danger" onClick={() => void interviewAction(interview, "revoke")}>Revoke</button> : null}
              </div>
            </li>
          ))}
        </ul>
        <div className="interview-pagination">
          <span>{interviewTotal} interview(s)</span>
          <button type="button" className="secondary" disabled={interviewOffset === 0} onClick={() => void loadInterviews(Math.max(0, interviewOffset - 10))}>Previous</button>
          <button type="button" className="secondary" disabled={interviewOffset + interviews.length >= interviewTotal} onClick={() => void loadInterviews(interviewOffset + 10)}>Next</button>
        </div>
      </section>

      <AnalyticsSection
        className="admin-analytics"
        analyticsStatusText={analytics.analyticsStatusText}
        analyticsLabelInput={analytics.analyticsLabelInput}
        analyticsPolicyInput={analytics.analyticsPolicyInput}
        analyticsPromptInput={analytics.analyticsPromptInput}
        baselineSnapshotId={analytics.baselineSnapshotId}
        candidateSnapshotId={analytics.candidateSnapshotId}
        driftScoreThreshold={analytics.driftScoreThreshold}
        driftOverrideThreshold={analytics.driftOverrideThreshold}
        analyticsSnapshots={analytics.analyticsSnapshots}
        analyticsEvaluations={analytics.analyticsEvaluations}
        analyticsTrend={analytics.analyticsTrend}
        analyticsComparison={analytics.analyticsComparison}
        isRefreshingAnalytics={analytics.isRefreshingAnalytics}
        isCreatingSnapshot={analytics.isCreatingSnapshot}
        isRunningSyncJob={analytics.isRunningSyncJob}
        isComparing={analytics.isComparing}
        isRunningDrift={analytics.isRunningDrift}
        setAnalyticsLabelInput={analytics.setAnalyticsLabelInput}
        setAnalyticsPolicyInput={analytics.setAnalyticsPolicyInput}
        setAnalyticsPromptInput={analytics.setAnalyticsPromptInput}
        setBaselineSnapshotId={analytics.setBaselineSnapshotId}
        setCandidateSnapshotId={analytics.setCandidateSnapshotId}
        setDriftScoreThreshold={analytics.setDriftScoreThreshold}
        setDriftOverrideThreshold={analytics.setDriftOverrideThreshold}
        onRefreshAnalytics={analytics.refreshAnalyticsSnapshots}
        onCreateSnapshot={analytics.onCreateSnapshot}
        onRunSnapshotSyncJob={async () => {
          await analytics.onRunSnapshotSyncJob();
          await loadSyncHistory();
          await loadAuditEvents();
        }}
        onCompareSnapshots={analytics.onCompareSnapshots}
        onRunDriftCheck={analytics.onRunDriftCheck}
      />

      <section className="card admin-audit">
        <div className="panel-head compact">
          <div><p className="eyebrow small">Operations</p><h2>Analytics sync history</h2></div>
          <button type="button" className="secondary" onClick={() => void loadSyncHistory()}>Refresh</button>
        </div>
        <ul className="admin-event-list">
          {!syncRuns.length ? <li className="empty-role">No sync runs recorded.</li> : syncRuns.map((run) => (
            <li key={run.sync_id}><strong>#{run.sync_id} · {run.status}</strong><span>Snapshot {run.snapshot_id ?? "—"} · {new Date(run.started_at).toLocaleString()}</span><small>{run.diagnostics}</small></li>
          ))}
        </ul>
      </section>

      <section className="card admin-audit">
        <div className="panel-head compact">
          <div><p className="eyebrow small">Traceability</p><h2>Global admin audit</h2></div>
          <button type="button" className="secondary" onClick={() => void loadAuditEvents()}>Refresh</button>
        </div>
        <div className="interview-filters">
          <input aria-label="Search audit events" placeholder="Search actor, event, target or details" value={auditSearch} onChange={(event) => setAuditSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadAuditEvents(); }} />
          <button type="button" className="secondary" onClick={() => void loadAuditEvents()}>Search</button>
          <span>{auditTotal} event(s)</span>
        </div>
        <ul className="admin-event-list">
          {!auditEvents.length ? <li className="empty-role">No audit events found.</li> : auditEvents.map((event) => (
            <li key={event.event_id}><strong>{event.event_type}</strong><span>{event.actor} · {event.target} · {new Date(event.created_at).toLocaleString()}</span><small>{JSON.stringify(event.details)}</small></li>
          ))}
        </ul>
      </section>

      <section className="card admin-corpus">
        <div className="panel-head compact">
          <div>
            <p className="eyebrow small">Knowledge corpus</p>
            <h2>Documents</h2>
          </div>
          <button type="button" className="secondary" onClick={() => void loadCorpusDocuments()}>
            Refresh
          </button>
        </div>
        <p className="corpus-help">Upload PDF, DOCX, or Markdown files up to 15 MB.</p>

        <form className="corpus-upload-form" onSubmit={uploadDocument}>
          <label>
            Document
            <input
              type="file"
              accept=".pdf,.docx,.md"
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <label htmlFor="corpus-document-type">
            Document type
            <select
              id="corpus-document-type"
              value={documentType}
              onChange={(event) => setDocumentType(event.target.value)}
              required
            >
              {documentTypes.map((type) => (
                <option key={type} value={type}>
                  {DOCUMENT_TYPES.find((item) => item.value === type)?.label ?? type}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="corpus-document-role">
            Role filter
            <select
              id="corpus-document-role"
              value={documentRole}
              onChange={(event) => setDocumentRole(event.target.value)}
              required
            >
              {documentRoles.map(([roleId, title]) => (
                <option key={roleId} value={roleId}>
                  {title} ({roleId})
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={!selectedFile || isUploading}>
            {isUploading ? "Ingesting..." : "Upload and ingest"}
          </button>
        </form>
        <p className="admin-status" aria-live="polite">{corpusStatus}</p>

        <ul className="corpus-document-list">
          {documents.length === 0 ? (
            <li className="empty-role">No corpus documents uploaded yet.</li>
          ) : (
            documents.map((document) => (
              <li className="corpus-document-row" key={document.doc_id}>
                <div className="corpus-document-info">
                  <strong>{document.filename}</strong>
                  <span>{document.doc_type} · {document.role} · {document.chunk_count} chunks</span>
                  <span className={`corpus-status ${document.status}`}>{document.status}</span>
                  {document.last_ingested_at ? (
                    <small>Last ingested {new Date(document.last_ingested_at).toLocaleString()}</small>
                  ) : null}
                  {document.error ? <small className="corpus-error">{document.error}</small> : null}
                </div>
                <div className="corpus-document-actions">
                  <button type="button" className="secondary" onClick={() => void reingestDocument(document)}>
                    {document.status === "failed" ? "Retry" : "Re-ingest"}
                  </button>
                  <button type="button" className="danger" onClick={() => void deleteDocument(document)}>
                    Delete
                  </button>
                </div>
              </li>
            ))
          )}
        </ul>
      </section>
    </>
  );
}

export function App() {
  return (
    <main className="shell">
      <AdminScreen />
    </main>
  );
}
