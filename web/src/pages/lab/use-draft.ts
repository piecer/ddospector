import { useRef, useState } from "react";

/** Separate create and refresh: a failed read must never repeat a successful POST. */
export function useDraft(refresh: () => Promise<void>, onComplete: () => void) {
  const lock = useRef(false);
  const committed = useRef(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<"save" | "refresh" | null>(null);

  async function submit(create: () => Promise<unknown>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      if (!committed.current) {
        await create();
        committed.current = true;
        setSaved(true);
      }
      await refresh();
      committed.current = false;
      setSaved(false);
      onComplete();
    } catch {
      setError(committed.current ? "refresh" : "save");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  return { busy, saved, error, submit };
}
