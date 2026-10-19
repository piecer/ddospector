import { useEffect, useRef, useState } from "react";
import type {
  TargetSelection,
  Target,
  WorkspaceSnapshot,
} from "../../lib/contracts";
import { cloneTargetSelection } from "../../lib/target-selection";
import { canonical } from "../scenarios/json";
import { toolClient } from "./chat-tool-client";
type State =
  | "loading"
  | "receipt-confirmed"
  | "current-only"
  | "mismatch"
  | "unavailable"
  | "stale";
type Readback = {
  selection: TargetSelection;
  workspace: WorkspaceSnapshot;
  retry: number;
  state: State;
  target?: Target;
};
export function useTargetReadback(
  selection: TargetSelection | undefined,
  workspace: WorkspaceSnapshot,
) {
  const [retry, setRetry] = useState(0);
  const [readback, setReadback] = useState<Readback | null>(null);
  const [pending, setPending] = useState(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const token = ++generation.current;
    if (!selection) return;
    const reader = new AbortController();
    controller.current = reader;
    // Capture and validate before the asynchronous GET. Never compare a mutated alias.
    let captured: TargetSelection;
    try {
      captured = cloneTargetSelection(selection);
    } catch {
      setReadback({ selection, workspace, retry, state: "mismatch" });
      return;
    }
    setPending(true);
    void (async () => {
      // Let synchronous cleanup retire this intent before occupying the no-queue worker.
      await Promise.resolve();
      if (token !== generation.current || reader.signal.aborted) return;
      const snapshot = await toolClient.targets(reader.signal);
      if (token !== generation.current || reader.signal.aborted) return;
      const target = snapshot.targets.find((t) => t.id === captured.id);
      const expectation = captured.expectation;
      const state: State = !target
        ? "mismatch"
        : expectation
          ? snapshot.draft_revision >= expectation.after_revision &&
            canonical(target) === canonical(expectation.target)
            ? "receipt-confirmed"
            : "mismatch"
          : "current-only";
      setReadback({ selection, workspace, retry, state, target });
    })()
      .catch(() => {
        if (token === generation.current && !reader.signal.aborted)
          setReadback((old) => ({
            selection,
            workspace,
            retry,
            state: "unavailable",
            target: old?.selection.id === selection.id ? old.target : undefined,
          }));
      })
      .finally(() => {
        if (token === generation.current) setPending(false);
      });
    return () => {
      ++generation.current;
      reader.abort();
    };
  }, [selection, workspace, retry]);
  const sameOwner =
    readback?.selection === selection &&
    readback?.workspace === workspace &&
    readback.retry === retry;
  const target =
    readback?.selection.id === selection?.id ? readback?.target : undefined;
  const state: State = sameOwner
    ? readback.state
    : target
      ? "stale"
      : "loading";
  return {
    target,
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
          target,
        });
    },
  };
}
