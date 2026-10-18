import { ChatRequestError } from "./chat-client";

/** Startup metadata GETs only: never retry a submission or permission mutation. */
export async function readChatMetadata<T>(
  read: (signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  for (let attempt = 0; ; ++attempt) {
    signal.throwIfAborted();
    try {
      const value = await read(signal);
      signal.throwIfAborted();
      return value;
    } catch (error) {
      signal.throwIfAborted();
      if (
        attempt >= 2 ||
        !(error instanceof ChatRequestError) ||
        error.code !== "CHAT_BUSY" ||
        !error.definite
      )
        throw error;
      // A cancelled HTTP observer does not retire the native worker. Space
      // retries from completion (not dispatch); never queue or poll indefinitely.
      await new Promise<void>((resolve, reject) => {
        const deadline = performance.now() + 500;
        const abort = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", abort);
          reject(signal.reason);
        };
        const finish = () => {
          const remaining = deadline - performance.now();
          if (remaining > 0) {
            timer = setTimeout(finish, Math.ceil(remaining));
            return;
          }
          signal.removeEventListener("abort", abort);
          resolve();
        };
        let timer = setTimeout(finish, 500);
        signal.addEventListener("abort", abort, { once: true });
      });
    }
  }
}
