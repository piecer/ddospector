import { useCallback, useEffect, useRef, useState } from "react";
import { toolClient } from "./chat-tool-client";
import { readChatMetadata } from "./chat-metadata";
import { reconcileFence } from "./chat-tool-wire";
import type {
  AgentConfig,
  ReconcileReceipt,
  ToolCall,
  ToolFence,
  ToolTranscript,
} from "./chat-tool-types";
import type { OperatorSkillSummary } from "./chat-skill-wire";
import type { Target, Skill } from "../../lib/contracts";
type Review = {
  fence: ToolFence;
  agent?: AgentConfig;
  targets?: Target[];
  skills?: OperatorSkillSummary[];
  skillDetail?: Skill;
  calls: ToolCall[];
};
export function useToolAuthority(mutationsEnabled: boolean) {
  const [fence, setFence] = useState<ToolFence | null>(null);
  const [ready, setReady] = useState(false);
  const [supported, setSupported] = useState(false);
  const [targetSupported, setTargetSupported] = useState(false);
  const [skillSupported, setSkillSupported] = useState(false);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewState, setReviewState] = useState("idle");
  const [receipt, setReceipt] = useState<ReconcileReceipt | null>(null);
  const [reconciling, setReconciling] = useState(false);
  const known = useRef<ToolFence | null>(null);
  const knownCalls = useRef(new Map<string, ToolCall>());
  const generation = useRef(0);
  const reader = useRef<AbortController | null>(null);
  const owner = useRef<symbol | null>(null);
  const unresolved = useRef<{ request: string; fence: ToolFence } | null>(null);
  const allowed = useRef(mutationsEnabled);
  allowed.current = mutationsEnabled;
  const mounted = useRef(true);
  const adopt = useCallback((next: ToolFence) => {
    known.current = known.current ? reconcileFence(known.current, next) : next;
    setFence(known.current);
    if (
      unresolved.current &&
      next.generation > unresolved.current.fence.generation
    )
      unresolved.current = null;
    return known.current;
  }, []);
  const refresh = useCallback(async () => {
    const token = ++generation.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setReady(false);
    setReview(null);
    try {
      // Both reads use the same no-queue native worker. A parallel fence can
      // legitimately return a null revision while runtime still owns it.
      const runtime = await readChatMetadata(
        toolClient.runtime,
        controller.signal,
      );
      const next = await readChatMetadata(toolClient.fence, controller.signal);
      if (
        !mounted.current ||
        token !== generation.current ||
        controller.signal.aborted
      )
        return;
      adopt(next);
      setSupported(runtime.supported);
      setTargetSupported(
        runtime.supported &&
          (runtime.schema_version === 2 || runtime.schema_version === 3),
      );
      setSkillSupported(runtime.supported && runtime.schema_version === 3);
      setReady(true);
    } catch {
      if (mounted.current && token === generation.current) setReady(false);
    }
  }, [adopt]);
  const observe = useCallback(
    (record: ToolTranscript) => {
      let newUncertain = false;
      for (const call of record.calls) {
        if (call.status === "uncertain" && !knownCalls.current.has(call.id))
          newUncertain = true;
        if (call.status === "uncertain") knownCalls.current.set(call.id, call);
      }
      if (newUncertain) {
        setReady(false);
        void refresh();
      }
    },
    [refresh],
  );
  const inspect = useCallback(async () => {
    const token = ++generation.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setReview(null);
    setReviewState("loading");
    setReady(false);
    try {
      const targetScope = known.current?.call_ids.some(
        (id) => knownCalls.current.get(id)?.tool === "target_create",
      );
      const skillScope = known.current?.call_ids.some(
        (id) => knownCalls.current.get(id)?.tool === "skill_create",
      );
      const current = skillScope
        ? await toolClient.inspectSkills(controller.signal)
        : targetScope
          ? await toolClient.inspectTargets(controller.signal)
          : await toolClient.inspectCurrent(controller.signal);
      if (
        !mounted.current ||
        token !== generation.current ||
        controller.signal.aborted
      )
        return;
      adopt(current.fence);
      const calls = current.fence.call_ids.map((id) =>
        knownCalls.current.get(id),
      );
      if (
        !current.fence.fenced ||
        calls.some((c) => !c) ||
        calls.some(
          (c) =>
            (c?.tool === "target_create") !== !!targetScope ||
            (c?.tool === "skill_create") !== !!skillScope,
        )
      ) {
        setReviewState("history-required");
        return;
      }
      setReview({ ...current, calls: calls as ToolCall[] });
      setReviewState("review");
    } catch {
      if (mounted.current && token === generation.current)
        setReviewState("unknown");
    }
  }, [adopt]);
  async function inspectSkill(id: string) {
    if (
      !review?.skills?.some((s) => s.id === id) ||
      owner.current ||
      unresolved.current
    )
      return;
    const held = review,
      token = ++generation.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setReview(null);
    setReviewState("loading");
    try {
      const skillDetail = await toolClient.inspectSkill(
        id,
        held.fence,
        controller.signal,
      );
      if (
        !mounted.current ||
        token !== generation.current ||
        controller.signal.aborted
      )
        return;
      setReview({ ...held, skillDetail });
      setReviewState("review");
    } catch {
      if (mounted.current && token === generation.current)
        setReviewState("unknown");
    }
  }
  async function acknowledge() {
    if (
      !allowed.current ||
      !review ||
      owner.current ||
      unresolved.current ||
      review.fence.generation !== known.current?.generation
    )
      return;
    const request = crypto.randomUUID(),
      requestOwner = Symbol();
    owner.current = requestOwner;
    const held = { request, fence: review.fence };
    unresolved.current = held;
    setReconciling(true);
    setReady(false);
    setReview(null);
    setReviewState("sending");
    try {
      const result = await toolClient.reconcile(request, held.fence);
      if (mounted.current) {
        setReceipt(result);
        setReviewState("acknowledged");
      }
      // Historical receipt is NEVER adopted as the current fence.
    } catch {
      if (mounted.current) setReviewState("unknown");
    } finally {
      if (owner.current === requestOwner) {
        owner.current = null;
        if (mounted.current) setReconciling(false);
      }
      if (mounted.current) await refresh();
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++generation.current;
      reader.current?.abort();
    };
  }, []);
  return {
    fence,
    ready,
    refresh,
    observe,
    inspect,
    inspectSkill,
    review,
    reviewState,
    receipt,
    reconciling,
    acknowledge,
    canReconcile:
      mutationsEnabled &&
      review !== null &&
      !reconciling &&
      !unresolved.current,
    targetSupported: ready && targetSupported,
    skillSupported: ready && skillSupported,
    canGrant:
      mutationsEnabled &&
      ready &&
      supported &&
      fence !== null &&
      fence.current_draft_revision !== null,
    canWrite:
      mutationsEnabled &&
      ready &&
      supported &&
      fence !== null &&
      !fence.fenced &&
      fence.current_draft_revision !== null,
  };
}
