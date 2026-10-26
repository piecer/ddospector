import { expect, it } from "vitest";
import {
  cloneScenarioSelection,
  scenarioSelectionFromLocation,
  scenarioSelectionPath,
} from "./scenario-selection";
import { recordFixture } from "../pages/scenarios/testRecords";
it.each([
  "0",
  "01",
  "11",
  "1.0",
  "1e0",
  "+1",
  " 1",
  "١",
  "1&extra=x",
  "1&version=2",
])("rejects nonliteral/extra version %s", (version) => {
  expect(
    scenarioSelectionFromLocation({
      pathname: "/profiles",
      search: "?scenario=legacy-scenario&version=" + version,
    }),
  ).toBeUndefined();
});
it.each([
  "?scenario=legacy-scenario&version=1&scenario=other",
  "?scenario=%FF&version=1",
  "?scenario=UPPER&version=1",
  "?scenario=legacy-scenario&version=1&expectation=x",
])("rejects malformed selector %s", (search) => {
  expect(
    scenarioSelectionFromLocation({ pathname: "/profiles", search }),
  ).toBeUndefined();
});
it("clones and deeply freezes validated complete expectation with literal Identifier", async () => {
  const scenario = await recordFixture(1, { id: "legacy-scenario" }),
    input = {
      id: scenario.id,
      version: 1,
      expectation: { scenario, after_scenario_revision: 1 },
    };
  const pending = cloneScenarioSelection(input);
  scenario.definition.name = "mutation";
  const selected = await pending;
  expect(selected.expectation!.scenario.definition.name).not.toBe("mutation");
  expect(
    Object.isFrozen(selected.expectation!.scenario.definition.traffic_budget),
  ).toBe(true);
  expect(scenarioSelectionPath(selected)).toBe(
    "/profiles?scenario=legacy-scenario&version=1",
  );
});
it("does not normalize getters or foreign prototypes into authority", async () => {
  const scenario = await recordFixture(1, { id: "legacy-scenario" }),
    value = {
      id: scenario.id,
      version: 1,
      expectation: { scenario, after_scenario_revision: 1 },
    };
  Object.defineProperty(value.expectation, "after_scenario_revision", {
    enumerable: true,
    get: () => 1,
  });
  await expect(cloneScenarioSelection(value)).rejects.toThrow();
});
