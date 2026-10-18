import { useCallback, useEffect, useRef, useState } from "react";
import type { Locale } from "../../lib/contracts";
import type { ChatRuntime, ChatSession, ChatTurn } from "./chat-types";
import {
  bindSubmission,
  chatClient,
  ChatRequestError,
  observeTurn,
} from "./chat-client";
import { toolClient } from "./chat-tool-client";
import { readChatMetadata } from "./chat-metadata";
import type { ToolGrant } from "./chat-tool-types";
import { terminal, validText } from "./chat-wire";
type Submission = {
  session: ChatSession;
  request: string;
  text: string;
  grantRequest?: string;
  grant?: ToolGrant;
  dispatched?: boolean;
};
export function useChat(
  locale: Locale,
  mutationsEnabled: boolean,
  toolsAllowed = false,
) {
  const authority = useRef({ mutationsEnabled, toolsAllowed });
  authority.current = { mutationsEnabled, toolsAllowed };
  const [toolTurns, setToolTurns] = useState<string[]>([]);
  const [viewEpoch, setViewEpoch] = useState(0);
  const [runtime, setRuntime] = useState<ChatRuntime | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [before, setBefore] = useState<number | undefined>(undefined);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [reading, setReading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const stopped = useRef<string | null>(null);
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState("loading");
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  // Request ownership is independent of which view may adopt its result.
  const locked = useRef<symbol | null>(null);
  const stopOwner = useRef<symbol | null>(null);
  const reader = useRef<AbortController | null>(null);
  const observer = useRef<AbortController | null>(null);
  const detachObservation = useCallback(() => {
    observer.current?.abort();
    observer.current = null;
    // Retire on replacement, even if the aborted transport settles much later.
    if (reader.current) {
      reader.current = null;
      setReading(false);
    }
  }, []);
  function acquireMutation() {
    const owner = Symbol();
    locked.current = owner;
    setBusy(true);
    return owner;
  }
  function releaseMutation(owner: symbol) {
    if (locked.current !== owner) return;
    locked.current = null;
    setBusy(false);
  }
  const inputRef = useRef(input);
  inputRef.current = input;
  const pending = useRef<{
    session: ChatSession;
    request: string;
    text: string;
    grantRequest?: string;
    grant?: ToolGrant;
    dispatched?: boolean;
  } | null>(null);
  const pendingSession = useRef<{
    request: string;
    runtime: ChatRuntime;
    locale: Locale;
  } | null>(null);
  const currentTurn = turns.at(-1) ?? null;
  const refresh = useCallback(async () => {
    const token = generation.current;
    const controller = new AbortController();
    detachObservation();
    observer.current = controller;
    try {
      const [r, list] = await Promise.all([
        readChatMetadata(chatClient.runtime, controller.signal),
        readChatMetadata(chatClient.sessions, controller.signal),
      ]);
      if (token !== generation.current || controller.signal.aborted) return;
      const creation = pendingSession.current;
      const found =
        creation && list.find((s) => s.request_id === creation.request);
      if (
        found &&
        found.profile_id === creation.runtime.profile?.id &&
        found.model === creation.runtime.profile.model &&
        found.endpoint === creation.runtime.profile.endpoint &&
        found.streaming === creation.runtime.profile.streaming &&
        found.settings_revision === creation.runtime.settings_revision &&
        found.locale === creation.locale
      )
        pendingSession.current = null;
      setRuntime(r);
      setSessions(list);
      setPhase(
        pendingSession.current
          ? "unknown-session"
          : pending.current
            ? "unknown-send"
            : "ready",
      );
    } catch {
      if (token === generation.current && !controller.signal.aborted)
        setPhase("read-error");
      // Retire the sibling GET (including its retry wait) on terminal failure.
      controller.abort();
    }
  }, [detachObservation]);
  useEffect(() => {
    void refresh();
    return () => {
      ++generation.current;
      observer.current?.abort();
      observer.current = null;
      reader.current = null;
      locked.current = null;
      stopOwner.current = null;
    };
  }, [refresh]);
  function watch(t: ChatTurn, token: number, streaming: boolean) {
    detachObservation();
    const controller = new AbortController();
    observer.current = controller;
    const adopt = (next: ChatTurn) => {
      if (token !== generation.current || controller.signal.aborted) return;
      setTurns((old) =>
        old.map((t) =>
          t.id === next.id && next.revision >= t.revision ? next : t,
        ),
      );
      setSession((old) =>
        old && old.id === next.session_id
          ? { ...old, active_turn_id: terminal(next) ? null : next.id }
          : old,
      );
      setPhase(terminal(next) ? "ready" : "observing");
    };
    if (terminal(t)) {
      adopt(t);
      return;
    }
    void observeTurn(t, controller.signal, adopt, streaming)
      .then((next) => {
        if (
          token === generation.current &&
          !controller.signal.aborted &&
          !terminal(next)
        )
          setPhase("detached");
      })
      .catch(() => {
        if (token === generation.current && !controller.signal.aborted)
          setPhase("read-error");
      });
  }
  async function start() {
    if (
      locked.current ||
      pendingSession.current ||
      pending.current ||
      !mutationsEnabled ||
      !runtime?.supported
    )
      return false;
    const owner = acquireMutation();
    const token = ++generation.current;
    detachObservation();
    setPhase("starting");
    setErrorCode(null);
    const request = crypto.randomUUID();
    const creation = { request, runtime, locale };
    pendingSession.current = creation;
    try {
      const created = await chatClient.start(runtime, request, locale);
      if (pendingSession.current === creation) pendingSession.current = null;
      if (token !== generation.current) return false;
      stopOwner.current = null;
      setStopping(false);
      setSession(created);
      setTurns([]);
      setBefore(undefined);
      setNextBefore(null);
      setSessions((old) =>
        [created, ...old.filter((s) => s.id !== created.id)].slice(0, 32),
      );
      setPhase("ready");
      return true;
    } catch (error) {
      if (
        error instanceof ChatRequestError &&
        error.definite &&
        pendingSession.current === creation
      )
        pendingSession.current = null;
      if (token === generation.current) {
        if (error instanceof ChatRequestError && error.definite) {
          setErrorCode(error.code);
          setPhase("rejected");
        } else setPhase("unknown-session");
      }
      return false;
    } finally {
      releaseMutation(owner);
    }
  }
  async function send(toolMode = false) {
    if (
      locked.current ||
      pending.current ||
      reading ||
      before !== undefined ||
      !mutationsEnabled ||
      !session ||
      session.active_turn_id ||
      session.sequence >= 64 ||
      !validText(input, 8192, true) ||
      (toolMode && !toolsAllowed)
    )
      return;
    const owner = acquireMutation();
    setPhase("sending");
    setErrorCode(null);
    const token = generation.current,
      text = input;
    const request = crypto.randomUUID();
    const submission: Submission = {
      session,
      request,
      text,
      ...(toolMode
        ? { grantRequest: crypto.randomUUID(), dispatched: false }
        : {}),
    };
    pending.current = submission;
    try {
      if (submission.grantRequest) {
        submission.grant = await toolClient.grant(
          session,
          submission.grantRequest,
          request,
          text,
        );
        if (
          token !== generation.current ||
          !authority.current.mutationsEnabled ||
          !authority.current.toolsAllowed
        ) {
          if (token === generation.current) setPhase("grant-recovered");
          return;
        }
      }
      const accepted = submission.grant
        ? await toolClient.submit(session, submission.grant, text, () => {
            if (
              token !== generation.current ||
              !authority.current.mutationsEnabled ||
              !authority.current.toolsAllowed
            )
              return false;
            submission.dispatched = true;
            return true;
          })
        : await chatClient.submit(session.id, request, session.sequence, text);
      // Bound acceptance can retire this request without adopting an old view.
      if (pending.current === submission) pending.current = null;
      if (token !== generation.current) return;
      if (inputRef.current === text) setInput("");
      setSession({
        ...session,
        sequence: accepted.sequence,
        active_turn_id: terminal(accepted) ? null : accepted.id,
      });
      if (toolMode) setToolTurns((old) => [...old, accepted.id]);
      setTurns((old) => [...old, accepted].slice(-2));
      setBefore(undefined);
      setNextBefore(accepted.sequence > 2 ? accepted.sequence - 1 : null);
      watch(accepted, token, session.streaming);
    } catch (error) {
      if (
        error instanceof ChatRequestError &&
        error.definite &&
        pending.current === submission
      )
        pending.current = null;
      if (token === generation.current) {
        if (error instanceof ChatRequestError && error.definite) {
          setErrorCode(error.code);
          setPhase("rejected");
        } else setPhase("unknown-send");
      }
    } finally {
      releaseMutation(owner);
    }
  }
  async function recoverSubmission() {
    const submission = pending.current;
    if (!submission || locked.current) return;
    const owner = acquireMutation();
    const token = ++generation.current;
    detachObservation();
    try {
      const { session: saved, request, text } = submission;
      if (submission.grantRequest && !submission.dispatched) {
        submission.grant = await toolClient.recoverGrant(
          saved,
          submission.grantRequest,
          request,
          text,
        );
        if (
          ["revoked", "expired"].includes(submission.grant.status) &&
          pending.current === submission
        )
          pending.current = null;
        if (token === generation.current)
          setPhase(pending.current ? "grant-recovered" : "ready");
        return;
      }
      const accepted = bindSubmission(
        await chatClient.byRequest(request),
        saved.id,
        request,
        saved.sequence,
        text,
      );
      // Bound acceptance can retire this request without adopting an old view.
      if (pending.current === submission) pending.current = null;
      if (token !== generation.current) return;
      if (inputRef.current === text) setInput("");
      setSession({
        ...saved,
        sequence: accepted.sequence,
        active_turn_id: terminal(accepted) ? null : accepted.id,
      });
      if (submission.grantRequest) setToolTurns((old) => [...old, accepted.id]);
      setTurns([accepted]);
      setBefore(undefined);
      setNextBefore(accepted.sequence > 1 ? accepted.sequence : null);
      watch(accepted, token, saved.streaming);
    } catch {
      if (token === generation.current) setPhase("unknown-send");
    } finally {
      releaseMutation(owner);
    }
  }
  async function continueGrant() {
    const submission = pending.current;
    if (
      !submission?.grant ||
      submission.dispatched ||
      submission.grant.status !== "pending" ||
      locked.current ||
      !authority.current.mutationsEnabled ||
      !authority.current.toolsAllowed
    )
      return;
    const owner = acquireMutation(),
      token = ++generation.current;
    detachObservation();
    setPhase("sending");
    const { session: saved, text, grant } = submission;
    try {
      const accepted = await toolClient.submit(saved, grant, text, () => {
        if (
          token !== generation.current ||
          !authority.current.mutationsEnabled ||
          !authority.current.toolsAllowed
        )
          return false;
        submission.dispatched = true;
        return true;
      });
      if (pending.current === submission) pending.current = null;
      if (token !== generation.current) return;
      if (inputRef.current === text) setInput("");
      setSession({
        ...saved,
        sequence: accepted.sequence,
        active_turn_id: terminal(accepted) ? null : accepted.id,
      });
      setTurns([accepted]);
      setToolTurns([accepted.id]);
      setBefore(undefined);
      setNextBefore(accepted.sequence > 1 ? accepted.sequence : null);
      watch(accepted, token, saved.streaming);
    } catch (error) {
      if (
        error instanceof ChatRequestError &&
        error.definite &&
        pending.current === submission
      )
        pending.current = null;
      if (token === generation.current)
        setPhase(pending.current ? "unknown-send" : "rejected");
    } finally {
      releaseMutation(owner);
    }
  }
  async function revokeGrant() {
    const submission = pending.current;
    if (!submission?.grant || submission.dispatched || locked.current) return;
    const owner = acquireMutation(),
      token = generation.current;
    try {
      await toolClient.revoke(submission.grant);
      if (pending.current === submission) pending.current = null;
      if (token === generation.current) setPhase("ready");
    } catch {
      if (token === generation.current) setPhase("unknown-send");
    } finally {
      releaseMutation(owner);
    }
  }
  async function open(id: string, cursor?: number) {
    if (locked.current) return;
    const token = ++generation.current;
    detachObservation();
    const controller = new AbortController();
    observer.current = controller;
    reader.current = controller;
    setToolTurns([]);
    setReading(true);
    stopOwner.current = null;
    setStopping(false);
    setErrorCode(null);
    setPhase("loading");
    try {
      const page = await chatClient.history(id, cursor, controller.signal);
      if (token !== generation.current || controller.signal.aborted) return;
      setSession(page.session);
      setTurns(page.turns);
      setToolTurns(page.turns.map((t) => t.id));
      setViewEpoch((v) => v + 1);
      setBefore(cursor);
      setNextBefore(page.next_before_sequence);
      setPhase(cursor === undefined ? "ready" : "history");
      const active = page.turns.find(
        (t) => t.id === page.session.active_turn_id,
      );
      if (cursor === undefined && active)
        watch(active, token, page.session.streaming);
    } catch {
      if (token === generation.current && !controller.signal.aborted)
        setPhase("read-error");
    } finally {
      if (reader.current === controller) {
        reader.current = null;
        setReading(false);
      }
    }
  }
  async function stop() {
    const id = session?.active_turn_id;
    if (!id || stopped.current === id) return;
    stopped.current = id;
    const owner = Symbol();
    stopOwner.current = owner;
    setErrorCode(null);
    setStopping(true);
    setPhase("cancel_requested");
    const token = ++generation.current;
    detachObservation();
    try {
      const latest = await chatClient.stop(id);
      if (token !== generation.current) return;
      setTurns((old) =>
        old.map((t) =>
          t.id === latest.id && latest.revision >= t.revision ? latest : t,
        ),
      );
      setSession((old) =>
        old
          ? { ...old, active_turn_id: terminal(latest) ? null : latest.id }
          : old,
      );
      setPhase(terminal(latest) ? latest.status : "cancel_requested");
      if (!terminal(latest) && before === undefined)
        watch(latest, token, session.streaming);
    } catch {
      if (token === generation.current) setPhase("stop-unknown");
    } finally {
      if (stopOwner.current === owner) {
        stopOwner.current = null;
        setStopping(false);
      }
    }
  }
  return {
    toolTurns,
    viewEpoch,
    runtime,
    sessions,
    session,
    turns,
    input,
    setInput,
    phase,
    busy,
    currentTurn,
    refresh,
    start,
    send,
    open,
    stop,
    reading,
    stopping,
    before,
    nextBefore,
    recoverSubmission,
    continueGrant,
    revokeGrant,
    recoveredGrant:
      pending.current?.grant && !pending.current.dispatched
        ? {
            text: pending.current.text,
            session: pending.current.session.id,
            grant: pending.current.grant,
          }
        : null,
    errorCode,
    uncertainSession: !!pendingSession.current,
    uncertain: !!pending.current,
    stopRequested: stopped.current === session?.active_turn_id,
  };
}
