import { useEffect, useRef, useState } from "react";
import type {
  SkillSelection,
  Skill,
  WorkspaceSnapshot,
} from "../../lib/contracts";
import { cloneSkillSelection } from "../../lib/skill-selection";
import { canonical } from "../scenarios/json";
import { ChatRequestError } from "./chat-client";
import { SkillReadbackMismatch } from "./chat-skill-wire";
import { toolClient } from "./chat-tool-client";
type State =
  | "loading"
  | "receipt-confirmed"
  | "current-only"
  | "discrepancy"
  | "unavailable"
  | "stale";
type Readback = {
  selection: SkillSelection;
  workspace: WorkspaceSnapshot | null;
  retry: number;
  state: State;
  skill?: Skill;
};
export function useSkillReadback(
  selection: SkillSelection | undefined,
  workspace: WorkspaceSnapshot | null,
  active = true,
) {
  const [retry, setRetry] = useState(0);
  const [readback, setReadback] = useState<Readback | null>(null);
  const [pending, setPending] = useState(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const token = ++generation.current;
    if (!selection || !active) return;
    const reader = new AbortController();
    controller.current = reader;
    // Capture and validate before the asynchronous GET. Never compare a mutated alias.
    let captured: SkillSelection;
    try {
      captured = cloneSkillSelection(selection);
    } catch {
      setReadback({ selection, workspace, retry, state: "discrepancy" });
      return;
    }
    setPending(true);
    void (async () => {
      // Let synchronous cleanup retire this intent before occupying the no-queue worker.
      await Promise.resolve();
      if (token !== generation.current || reader.signal.aborted) return;
      const snapshot = await toolClient.skill(captured.id, reader.signal);
      if (token !== generation.current || reader.signal.aborted) return;
      const skill = snapshot.skill;
      const expectation = captured.expectation;
      const state: State = !skill
        ? "discrepancy"
        : expectation
          ? snapshot.draft_revision >= expectation.after_revision &&
            canonical(skill) === canonical(expectation.skill)
            ? "receipt-confirmed"
            : "discrepancy"
          : "current-only";
      setReadback({ selection, workspace, retry, state, skill });
    })()
      .catch((error: unknown) => {
        if (token === generation.current && !reader.signal.aborted)
          setReadback((old) => ({
            selection,
            workspace,
            retry,
            state:
              error instanceof SkillReadbackMismatch ||
              (error instanceof ChatRequestError &&
                error.code === "CHAT_NOT_FOUND")
                ? "discrepancy"
                : "unavailable",
            skill: old?.selection.id === selection.id ? old.skill : undefined,
          }));
      })
      .finally(() => {
        if (token === generation.current) setPending(false);
      });
    return () => {
      ++generation.current;
      reader.abort();
    };
  }, [selection, workspace, retry, active]);
  const sameOwner =
    readback?.selection === selection &&
    readback?.workspace === workspace &&
    readback.retry === retry;
  const skill =
    readback?.selection.id === selection?.id ? readback?.skill : undefined;
  const state: State = sameOwner ? readback.state : skill ? "stale" : "loading";
  return {
    skill,
    state,
    pending,
    refresh: () => setRetry((n) => n + 1),
    cancel: () => {
      ++generation.current;
      controller.current?.abort();
      setPending(false);
      if (selection)
        setReadback({
          selection,
          workspace,
          retry,
          state: "unavailable",
          skill,
        });
    },
  };
}
