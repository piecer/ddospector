/** B3 reads use the accepted Identifier-compatible codec, not the manual UUID codec. */
import {
  readScenarioHistoryWith,
  readScenarioPageWith,
} from "../scenarios/client";
import {
  parseScenarioHistoryV4,
  parseScenarioPageV4,
} from "./chat-scenario-wire";
import type { ScenarioHistory, ScenarioPage } from "../scenarios/types";
export { parseScenarioVersionV4 } from "./chat-scenario-wire";
export const chatScenarioClient = {
  history(id: string, signal?: AbortSignal): Promise<ScenarioHistory> {
    return readScenarioHistoryWith(id, parseScenarioHistoryV4, signal);
  },
  read(offset = 0, limit = 50, signal?: AbortSignal): Promise<ScenarioPage> {
    return readScenarioPageWith(offset, limit, parseScenarioPageV4, signal);
  },
};
