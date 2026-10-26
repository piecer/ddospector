import { useCallback, useEffect, useRef, useState } from "react";
import type { ScenarioSelection } from "./chat-scenario-types";
import type { ScenarioHistory, ScenarioVersion } from "../scenarios/types";
import { canonical } from "../scenarios/json";
import { chatScenarioClient } from "./chat-scenario-client";
import { scenarioAPI } from "../scenarios/client";
export type ScenarioReadbackState =
  | "loading"
  | "current-only"
  | "receipt-confirmed"
  | "discrepancy"
  | "unavailable"
  | "cancelled";
export function useScenarioReadback(selection?: ScenarioSelection) {
  const [result, setResult] = useState<{
    selection: ScenarioSelection;
    state: ScenarioReadbackState;
    record: ScenarioVersion | null;
    history: ScenarioHistory | null;
  } | null>(null);
  const reader = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const owner = useRef(false);
  const queued = useRef<(() => Promise<void>) | null>(null);
  const manualQueued = useRef<{
    run: () => Promise<void>;
    cancel: () => void;
  } | null>(null);
  const mounted = useRef(true);
  // App-local inspection ownership: one transport and one latest waiter per
  // view. Neither logical cancellation nor a manual codec result releases a
  // selected read into an unfinished transport / substitutes for P validation.
  const drain = useCallback(async () => {
    if (owner.current) return;
    owner.current = true;
    try {
      while (queued.current || manualQueued.current) {
        const next = queued.current;
        if (next) {
          queued.current = null;
          await next();
        } else {
          const manual = manualQueued.current!;
          manualQueued.current = null;
          await manual.run();
        }
      }
    } finally {
      owner.current = false;
    }
  }, []);
  const readManualHistory = useCallback(
    (id: string, signal: AbortSignal): Promise<ScenarioHistory> => {
      if (!mounted.current || signal.aborted)
        return Promise.reject(
          new DOMException("Inspection cancelled.", "AbortError"),
        );
      return new Promise((resolve, reject) => {
        const cancel = () => {
          if (manualQueued.current === job) manualQueued.current = null;
          signal.removeEventListener("abort", cancel);
          reject(new DOMException("Inspection cancelled.", "AbortError"));
        };
        const job = {
          cancel,
          run: async () => {
            try {
              signal.throwIfAborted();
              // Do not forward the view's AbortSignal: U0 would settle early
              // while an uncooperative fetch still owns its original lease.
              const history = await scenarioAPI.history(id);
              signal.throwIfAborted();
              if (!mounted.current) return cancel();
              resolve(history);
            } catch (error) {
              reject(error);
            } finally {
              signal.removeEventListener("abort", cancel);
            }
          },
        };
        manualQueued.current?.cancel();
        manualQueued.current = job;
        signal.addEventListener("abort", cancel, { once: true });
        void drain();
      });
    },
    [drain],
  );
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      manualQueued.current?.cancel();
      queued.current = null;
    };
  }, []);
  const read = useCallback(async () => {
    const token = ++generation.current;
    reader.current?.abort();
    if (!selection) return;
    const controller = new AbortController();
    reader.current = controller;
    setResult({ selection, state: "loading", record: null, history: null });
    queued.current = async () => {
      if (controller.signal.aborted || token !== generation.current) return;
      try {
        // Logical cancellation retires publication, not the transport lease. U0's
        // AbortSignal races a pending fetch; keep its original bounded GET alive
        // until retirement so a replacement cannot overlap it.
        const history = await chatScenarioClient.history(selection.id);
        if (controller.signal.aborted || token !== generation.current) return;
        const record =
          history.versions.find((v) => v.version === selection.version) ?? null;
        const expectation = selection.expectation;
        const state = !record
          ? "discrepancy"
          : !expectation
            ? "current-only"
            : history.revision >= expectation.after_scenario_revision &&
                canonical(record) === canonical(expectation.scenario)
              ? "receipt-confirmed"
              : "discrepancy";
        setResult({ selection, state, record, history });
      } catch {
        if (!controller.signal.aborted && token === generation.current)
          setResult({
            selection,
            state: "unavailable",
            record: null,
            history: null,
          });
      }
    };
    await drain();
  }, [selection, drain]);
  const cancel = useCallback(() => {
    ++generation.current;
    reader.current?.abort();
    if (selection)
      setResult({ selection, state: "cancelled", record: null, history: null });
  }, [selection]);
  useEffect(() => {
    void read();
    return () => {
      ++generation.current;
      reader.current?.abort();
    };
  }, [read]);
  const current = result?.selection === selection ? result : null;
  return {
    state: current?.state ?? "loading",
    record: current?.record ?? null,
    history: current?.history ?? null,
    retry: read,
    cancel,
    readManualHistory,
  };
}
export type ScenarioReadback = ReturnType<typeof useScenarioReadback>;
