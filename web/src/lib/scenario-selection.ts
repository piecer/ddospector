import type { ScenarioSelection } from "../pages/ai/chat-scenario-types";
import { parseV4 } from "../pages/ai/chat-scenario-wire";
import { identifier } from "../pages/scenarios/validation";
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
export async function cloneScenarioSelection(
  value: ScenarioSelection,
): Promise<ScenarioSelection> {
  // P0 captures synchronously before its first await, without normalizing accessors.
  return freeze(await parseV4("ScenarioSelection", value));
}
export function scenarioSelectionPath(selection: ScenarioSelection): string {
  return `/profiles?scenario=${encodeURIComponent(selection.id)}&version=${selection.version}`;
}
/** Only literal id/version navigation; URL or history state never supplies authority. */
export function scenarioSelectionFromLocation(
  location: Pick<Location, "pathname" | "search">,
): ScenarioSelection | undefined {
  if (location.pathname !== "/profiles") return undefined;
  try {
    decodeURIComponent(location.search);
    const params = new URLSearchParams(location.search);
    const id = params.get("scenario"),
      version = params.get("version");
    if (
      [...params].length !== 2 ||
      params.getAll("scenario").length !== 1 ||
      params.getAll("version").length !== 1 ||
      !identifier(id) ||
      !version ||
      !/^(?:[1-9]|10)$/.test(version)
    )
      return undefined;
    return Object.freeze({
      id: id as string,
      version: Number(version),
      expectation: null,
    });
  } catch {
    return undefined;
  }
}
