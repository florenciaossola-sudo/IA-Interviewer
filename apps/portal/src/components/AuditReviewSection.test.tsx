import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditBundle } from "../types";
import { AuditReviewSection } from "./AuditReviewSection";

const decisions = [
  { node: "decide", route: "probe_deeper", reason: "decision one", alternatives: ["escalate"] },
  { node: "decide", route: "switch_competency", reason: "decision two", alternatives: ["probe_deeper"] },
  { node: "decide", route: "probe_deeper", reason: "decision three", alternatives: ["conclude"] },
  { node: "decide", route: "conclude", reason: "decision four", alternatives: ["escalate"] },
];

const bundle = {
  run: {
    run_id: "iv_example",
    role: "frontend_engineer",
    doc_type: "role_description",
    status: "completed",
    created_at: "2026-09-29T13:08:25.000Z",
    updated_at: "2026-09-29T13:08:36.000Z",
  },
  events: [
    {
      event_id: 7,
      event_type: "run_started",
      created_at: "2026-09-29T13:08:25.000Z",
      payload: { question: "Question 1." },
    },
    {
      event_id: 8,
      event_type: "turn_completed",
      created_at: "2026-09-29T13:08:34.000Z",
      payload: {
        question: "Question 1.", answer: "First answer", evaluation_score: 0.4,
        competency: "debugging", evaluation_evidence: ["debugging: trace"],
        grounded_context: [{ chunk_id: "role::chunk-0", doc_id: "role", score: 0.82 }],
        graph_state: { final_route: "escalate", decision_log_tail: decisions.slice(-1) },
      },
    },
    {
      event_id: 9,
      event_type: "run_completed",
      created_at: "2026-09-29T13:08:36.000Z",
      payload: {
        question: "Question 2", answer: "Second answer", evaluation_score: 0.5,
        competency: "api_design", evaluation_evidence: ["api_design: backward"],
        graph_state: { final_route: "escalate", decision_log_tail: decisions.slice(-1) },
      },
    },
  ],
  checkpoints: [{
    checkpoint_id: 9,
    checkpoint_index: 2,
    created_at: "2026-09-29T13:08:36.000Z",
    state: { decision_log: decisions },
  }],
} as AuditBundle;

describe("AuditReviewSection event stream", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response("null", { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the latest integrity report rather than the initial zero counts", async () => {
    const startIntegrity = {
      aai_index: 0,
      signal_breakdown: [{ signal_family: "motion", event_count: 0, evidence: [] }],
      baseline_available: false,
    };
    const finalIntegrity = {
      aai_index: 33,
      disposition: "reviewer_visible_only",
      signal_breakdown: [
        { signal_family: "motion", event_count: 3, evidence: ["pointer_move: answer-input", "pointer_move: answer-input", "other: answer-input"] },
        { signal_family: "focus", event_count: 3, evidence: ["focus: answer-input", "blur: answer-input", "focus: answer-input"] },
        { signal_family: "input", event_count: 0, suppressed: true, evidence: [] },
      ],
      confounders: ["input suppressed by accommodation"],
      baseline_available: true,
      baseline_answer_length: 120,
      current_answer_length: 140,
      baseline_deviation_ratio: 0.1667,
    };
    const events = bundle.events.map((event, index) => ({
      ...event,
      payload: {
        ...event.payload,
        ...(index === 0 ? { integrity_state: startIntegrity } : {}),
        ...(index === 2 ? { integrity_state: finalIntegrity } : {}),
      },
    }));
    render(
      <AuditReviewSection
        auditBundle={{ ...bundle, events }}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const appendix = document.querySelector<HTMLElement>("#integrity-area")!;
    expect(within(appendix).getByText("motion: 3 events")).toBeTruthy();
    expect(within(appendix).getByText("pointer_move: answer-input (2)")).toBeTruthy();
    expect(within(appendix).getByText("other: answer-input (1)")).toBeTruthy();
    expect(within(appendix).getByText("focus: answer-input (2)")).toBeTruthy();
    expect(within(appendix).getByText("blur: answer-input (1)")).toBeTruthy();
    expect(within(appendix).getAllByText("focus: answer-input (2)")).toHaveLength(1);
    expect(within(appendix).getByText("input: 0 events (suppressed)")).toBeTruthy();
    expect(within(appendix).getByText("120 chars")).toBeTruthy();
    expect(within(appendix).getByText("140 chars")).toBeTruthy();
    expect(within(appendix).getByText("16.7%")).toBeTruthy();
    expect(within(appendix).getByText("Latest evaluated answer")).toBeTruthy();
    expect(within(appendix).getByText("Absolute length difference")).toBeTruthy();
    expect(within(appendix).getByText("input suppressed by accommodation")).toBeTruthy();
    expect(appendix.querySelector("#aai-index-value")?.textContent).toBe("33");
    const infoButton = within(appendix).getByRole("button", { name: "About the AAI index" });
    const info = appendix.querySelector<HTMLElement>("#aai-index-info")!;
    expect(info.hidden).toBe(true);
    expect(infoButton.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(infoButton);
    expect(info.hidden).toBe(false);
    expect(infoButton.getAttribute("aria-expanded")).toBe("true");
    expect(within(info).getByText(/weighted average/)).toBeTruthy();
    expect(within(info).getByText(/not a probability of misconduct/)).toBeTruthy();
    fireEvent.click(infoButton);
    expect(info.hidden).toBe(true);
    expect(infoButton.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps checkpoints with the same index when they represent different evaluated turns", async () => {
    const makeCheckpoint = (checkpoint_id: number, checkpoint_index: number, evaluated_turns: number) => ({
      checkpoint_id,
      checkpoint_index,
      created_at: "2026-09-29T13:08:36.000Z",
      state: { evaluated_turns, llm_trace: { model: `model-${evaluated_turns}` } },
    });
    const checkpoints = [
      makeCheckpoint(1, 0, 0),
      makeCheckpoint(2, 0, 0),
      makeCheckpoint(3, 2, 1),
      makeCheckpoint(4, 3, 2),
      makeCheckpoint(5, 3, 3),
    ];
    render(
      <AuditReviewSection
        auditBundle={{ ...bundle, checkpoints }}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const list = document.querySelector<HTMLElement>("#checkpoint-list")!;
    expect(list.children).toHaveLength(4);
    expect(within(list).getByText(/"model": "model-2"/)).toBeTruthy();
    expect(within(list).getByText(/"model": "model-3"/)).toBeTruthy();
  });

  it("renders one card per submitted answer without counting run_started as a turn", async () => {
    render(
      <AuditReviewSection
        auditBundle={bundle}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

    const eventList = document.querySelector<HTMLOListElement>("#event-list");
    expect(eventList).not.toBeNull();
    const turns = Array.from((eventList as HTMLOListElement).children);
    expect(turns).toHaveLength(2);
    expect(within(turns[0] as HTMLElement).getByText("Question 1.")).toBeTruthy();
    expect(within(turns[0] as HTMLElement).getByText("First answer")).toBeTruthy();
    expect(within(turns[0] as HTMLElement).getByText(/Retrieval relevance: 0\.82/)).toBeTruthy();
    expect(within(turns[1] as HTMLElement).getByText("Question 2")).toBeTruthy();
    expect(within(turns[1] as HTMLElement).getByText("Second answer")).toBeTruthy();
    expect(screen.queryByText("This turn does not have a submitted answer yet.")).toBeNull();
  });

  it("shows the warm-up before scored turns without changing scores or turn numbering", async () => {
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    const warmupBundle: AuditBundle = {
      ...bundle,
      events: [
        { ...bundle.events[0], payload: { question: "Tell us about a recent project." } },
        {
          event_id: 10,
          event_type: "warmup_completed",
          created_at: "2026-09-29T13:08:30.000Z",
          payload: {
            answer: "I built a database service.",
            question: "Question 1.",
            integrity_state: { baseline_available: true, baseline_answer_length: 27 },
          },
        },
        ...bundle.events.slice(1),
      ],
    };
    render(
      <AuditReviewSection
        auditBundle={warmupBundle}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const eventList = document.querySelector<HTMLOListElement>("#event-list")!;
    const turns = Array.from(eventList.children) as HTMLElement[];
    expect(turns).toHaveLength(3);
    expect(within(turns[0]).getByText("Warm-up · Calibration (not scored)")).toBeTruthy();
    expect(within(turns[0]).getByText("Tell us about a recent project.")).toBeTruthy();
    expect(within(turns[0]).getByText("I built a database service.")).toBeTruthy();
    expect(within(turns[0]).queryByText("Question 1.")).toBeNull();
    expect(within(turns[0]).queryByText(/Score:/)).toBeNull();
    expect(within(turns[1]).getByText("Turn 1 · debugging")).toBeTruthy();
    expect(screen.getByText("2 evaluated turn(s) · warm-up not scored")).toBeTruthy();
    expect(screen.getByText("0.40 avg")).toBeTruthy();
    expect(screen.getByText("0.50 avg")).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "Jump to turn" }) as HTMLSelectElement).value).toBe("-1");

    fireEvent.click(screen.getByRole("button", { name: "Next turn" }));
    expect((screen.getByRole("combobox", { name: "Jump to turn" }) as HTMLSelectElement).value).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "View warm-up answer" }));
    expect((screen.getByRole("combobox", { name: "Jump to turn" }) as HTMLSelectElement).value).toBe("-1");
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
  });

  it("shows an unavailable question for a warm-up without its start event", async () => {
    const warmupOnly: AuditBundle = {
      ...bundle,
      events: [{
        event_id: 10,
        event_type: "warmup_completed",
        created_at: "2026-09-29T13:08:30.000Z",
        payload: { answer: "Warm-up answer", question: "A later question" },
      }],
    };
    render(
      <AuditReviewSection
        auditBundle={warmupOnly}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const eventList = document.querySelector<HTMLOListElement>("#event-list")!;
    expect(eventList.children).toHaveLength(1);
    expect(within(eventList).getByText("Warm-up question unavailable.")).toBeTruthy();
    expect(within(eventList).getByText("Warm-up answer")).toBeTruthy();
    expect(within(eventList).queryByText("A later question")).toBeNull();
    expect(screen.getByText("No scored competencies in this run.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next turn" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("groups scores by competency and navigates between turns", async () => {
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ text: "Source attached to this competency score" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )) as typeof fetch);
    render(
      <AuditReviewSection
        auditBundle={bundle}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

    expect(screen.getByRole("heading", { name: "Scores by competency" })).toBeTruthy();
    expect(screen.getByText("debugging")).toBeTruthy();
    expect(screen.getByText("api_design")).toBeTruthy();
    const competencyCard = document.querySelector(".competency-review-item");
    expect(competencyCard).not.toBeNull();
    act(() => within(competencyCard as HTMLElement).getByRole("button", { name: /Open source:/ }).click());
    expect(await screen.findAllByText("Source attached to this competency score")).toHaveLength(2);
    act(() => screen.getByRole("button", { name: "Next turn" }).click());
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("opens corpus source text and displays the full decision log, not only the tail", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("integrity-disposition")) {
        return new Response("null", { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ text: "Source corpus excerpt" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch);
    {
      render(
        <AuditReviewSection
          auditBundle={bundle}
          reviewerName="reviewer@example.test"
          decision="approved"
          rationale=""
          reviewStatusText=""
          isSubmittingReview={false}
          setReviewerName={vi.fn()}
          setDecision={vi.fn()}
          setRationale={vi.fn()}
          onSubmitReview={vi.fn(async () => undefined)}
        />,
      );
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

      const sourceButtons = screen.getAllByRole("button", { name: /role · role::chunk-0/ });
      act(() => sourceButtons[0].click());
      expect(await screen.findAllByText("Source corpus excerpt")).toHaveLength(2);
      expect(screen.getByText("decision four")).toBeTruthy();
      expect(screen.getByText("Decision 4")).toBeTruthy();
    }
  });

  it("shows only the latest checkpoint when an index is persisted twice", async () => {
    const duplicatedBundle: AuditBundle = {
      ...bundle,
      checkpoints: [
        ...bundle.checkpoints,
        {
          checkpoint_id: 10,
          checkpoint_index: 2,
          created_at: "2026-09-29T13:08:37.000Z",
          state: { decision_log: [...decisions, { node: "finalize", route: "escalate", reason: "latest" }] },
        },
      ],
    };
    render(
      <AuditReviewSection
        auditBundle={duplicatedBundle}
        reviewerName="reviewer@example.test"
        decision="approved"
        rationale=""
        reviewStatusText=""
        isSubmittingReview={false}
        setReviewerName={vi.fn()}
        setDecision={vi.fn()}
        setRationale={vi.fn()}
        onSubmitReview={vi.fn(async () => undefined)}
      />,
    );

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(screen.getByText("1 checkpoints")).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: /Checkpoint 1/ })).toHaveLength(1);
    const checkpointList = document.querySelector("#checkpoint-list");
    expect(checkpointList?.querySelector("pre")?.textContent).toContain("latest");
  });

  it("previews the system recommendation against an override before submitting", async () => {
    const props = {
      auditBundle: bundle,
      reviewerName: "reviewer@example.test",
      decision: "approved",
      rationale: "",
      reviewStatusText: "",
      isSubmittingReview: false,
      setReviewerName: vi.fn(),
      setDecision: vi.fn(),
      setRationale: vi.fn(),
      onSubmitReview: vi.fn(async () => undefined),
    };
    const view = render(<AuditReviewSection {...props} />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "overridden" } });
    fireEvent.change(screen.getByLabelText("Rationale"), {
      target: { value: "The transcript does not support the system conclusion." },
    });
    view.rerender(
      <AuditReviewSection
        {...props}
        decision="overridden"
        rationale="The transcript does not support the system conclusion."
      />,
    );

    const preview = document.querySelector(".review-diff-preview");
    expect(preview).not.toBeNull();
    expect(within(preview as HTMLElement).getByText("System recommendation")).toBeTruthy();
    expect(within((preview as HTMLElement).children[0] as HTMLElement).getByText("Escalate")).toBeTruthy();
    expect(within(preview as HTMLElement).getByText("Override: Conclude")).toBeTruthy();
    expect(within(preview as HTMLElement).getByText("The transcript does not support the system conclusion.")).toBeTruthy();
  });
});
