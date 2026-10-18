import { useCallback, useEffect, useRef, useState } from "react";
import { toolClient, bindDecision } from "./chat-tool-client";
import type { DecisionInput } from "./chat-tool-client";
import { callTerminal, reconcileTranscript } from "./chat-tool-wire";
import type { ChatTurn } from "./chat-types";
import type { ToolCall, ToolTranscript } from "./chat-tool-types";
import { terminal } from "./chat-wire";
/** One completion-spaced reader per visible Turn, independent of decision ownership. */
export type ToolReadGate = { owner: symbol | null; completed: number };
export type TranscriptLedger = Map<string, ToolTranscript>;
export type DecisionLedger = Map<
  string,
  { call: string; input: DecisionInput }
>;
export function useToolTranscript(
  turn: ChatTurn,
  enabled: boolean,
  viewEpoch: number,
  ledger?: DecisionLedger,
  records?: TranscriptLedger,
  sharedGate?: ToolReadGate,
) {
  const ownLedger = useRef<DecisionLedger>(new Map());
  const decisions = ledger ?? ownLedger.current;
  const ownRecords = useRef<TranscriptLedger>(new Map());
  const history = records ?? ownRecords.current;
  const localGate = useRef<ToolReadGate>({ owner: null, completed: -Infinity });
  const gate = sharedGate ?? localGate.current;
  const [record, setRecord] = useState<ToolTranscript | null>(null);
  const [stale, setStale] = useState(true);
  const [decisionState, setDecisionState] = useState<
    "idle" | "sending" | "acknowledged" | "unknown"
  >("idle");
  const turnRef = useRef(turn);
  turnRef.current = turn;
  const latest = useRef<ToolTranscript | null>(null);
  const generation = useRef(0);
  const decisionOwner = useRef<symbol | null>(null);
  const expected = useRef<{ call: string; input: DecisionInput } | null>(null);
  const wake = useRef<() => void>(() => undefined);
  const refresh = useCallback(() => wake.current(), []);
  useEffect(() => {
    const token = ++generation.current;
    latest.current = history.get(turn.id) ?? null;
    setRecord(latest.current);
    setStale(true);
    expected.current = decisions.get(turn.id) ?? null;
    setDecisionState(expected.current ? "unknown" : "idle");
    if (!enabled) return;
    let disposed = false,
      running = false,
      finalDone = false,
      completed = -Infinity;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const schedule = () => {
      if (
        disposed ||
        running ||
        finalDone ||
        document.visibilityState === "hidden"
      )
        return;
      clearTimeout(timer);
      timer = setTimeout(
        () => void read(),
        Math.max(
          gate.owner ? 500 : 0,
          Math.max(completed, gate.completed) + 500 - Date.now(),
        ),
      );
    };
    const read = async () => {
      if (disposed || running || document.visibilityState === "hidden") return;
      if (gate.owner || Date.now() < gate.completed + 500) {
        schedule();
        return;
      }
      const readOwner = Symbol();
      gate.owner = readOwner;
      running = true;
      // This marker is captured AFTER terminal observation, never borrowed from an older request.
      const finalRead = terminal(turnRef.current);
      controller = new AbortController();
      try {
        const result = await toolClient.tools(turn.id, controller.signal);
        if (
          disposed ||
          token !== generation.current ||
          controller.signal.aborted
        )
          return;
        const next = latest.current
          ? reconcileTranscript(latest.current, result)
          : result;
        if (finalRead && next.calls.some((c) => !callTerminal(c)))
          throw Error("Unsettled terminal companion");
        latest.current = next;
        history.set(turn.id, next);
        setRecord(next);
        setStale(false);
        if (expected.current) {
          try {
            bindDecision(
              next.calls.find((c) => c.id === expected.current!.call)?.decision,
              expected.current.call,
              expected.current.input,
            );
            setDecisionState("acknowledged");
          } catch {
            setDecisionState("unknown");
          }
        }
        if (finalRead) finalDone = true;
      } catch {
        if (!disposed && token === generation.current) setStale(true);
        // Terminal failures are unknown, not an implicit successful final synchronization.
        if (finalRead) finalDone = true;
      } finally {
        running = false;
        completed = Date.now();
        if (gate.owner === readOwner) {
          gate.owner = null;
          gate.completed = completed;
        }
        if (!disposed) schedule();
      }
    };
    const retry = () => {
      finalDone = false;
      schedule();
    };
    const visibility = () => {
      if (document.visibilityState === "hidden") {
        clearTimeout(timer);
        controller?.abort();
      } else schedule();
    };
    wake.current = retry;
    document.addEventListener("visibilitychange", visibility);
    schedule();
    return () => {
      disposed = true;
      ++generation.current;
      clearTimeout(timer);
      controller?.abort();
      wake.current = () => undefined;
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [turn.id, enabled, viewEpoch, decisions, history, gate]);
  const isTerminal = terminal(turn);
  useEffect(() => {
    if (isTerminal) wake.current();
  }, [isTerminal]);
  async function decide(
    call: ToolCall,
    decision: "approve" | "deny",
    allowed: boolean,
  ) {
    if (
      !allowed ||
      stale ||
      decisionOwner.current ||
      expected.current ||
      call.status !== "awaiting_approval" ||
      !call.proposal ||
      isTerminal ||
      Date.now() >= Date.parse(call.proposal.expires_at)
    )
      return;
    if (latest.current?.calls.find((c) => c.id === call.id) !== call) return;
    const owner = Symbol(),
      token = generation.current;
    decisionOwner.current = owner;
    const input = {
      request_id: crypto.randomUUID(),
      proposal_digest: call.proposal.digest,
      decision,
    };
    const submission = { call: call.id, input };
    expected.current = submission;
    decisions.set(turn.id, submission);
    setDecisionState("sending");
    try {
      await toolClient.decide(call.id, turn.id, input, false);
      if (token === generation.current && expected.current === submission)
        setDecisionState("acknowledged");
    } catch {
      if (token === generation.current && expected.current === submission)
        setDecisionState("unknown");
    } finally {
      // An old view cannot clear another request's ownership or adopt an ACK.
      if (decisionOwner.current === owner) decisionOwner.current = null;
      if (token === generation.current) refresh();
    }
  }
  return {
    record,
    stale,
    refresh,
    decide,
    decisionState,
    decisionBlocked: decisionState !== "idle",
  };
}
