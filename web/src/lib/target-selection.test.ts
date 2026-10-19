import { expect, it } from "vitest";
import {
  cloneTargetSelection,
  targetSelectionFromLocation,
  targetSelectionPath,
} from "./target-selection";
import { target } from "../pages/ai/chat-target-test-fixtures";
it("clones and freezes bounded receipt expectations and rejects mismatched handoffs", () => {
  const original = {
    id: target.id,
    expectation: { target: { ...target }, after_revision: 3 },
  };
  const owned = cloneTargetSelection(original);
  original.expectation.target.address = "mutated.test";
  expect(owned.expectation?.target.address).toBe(target.address);
  expect(Object.isFrozen(owned.expectation?.target)).toBe(true);
  for (const bad of [
    { ...original, id: "other-id" },
    { ...original, extra: true },
    { ...original, expectation: { target, after_revision: -1 } },
    {
      ...original,
      expectation: {
        target: { ...target, name: "a".repeat(4097) },
        after_revision: 3,
      },
    },
  ])
    expect(() => cloneTargetSelection(bad)).toThrow();
});
it("URL retains ID only, rejects malformed or duplicate query, never restores receipt authority", () => {
  expect(
    targetSelectionPath({
      id: target.id,
      expectation: { target, after_revision: 3 },
    }),
  ).toBe(`/targets?target=${target.id}`);
  expect(
    targetSelectionFromLocation({
      pathname: "/targets",
      search: `?target=${target.id}`,
    }),
  ).toEqual({ id: target.id });
  for (const search of [
    "?target=UPPER",
    "?target=a&target=a",
    "?target=%",
    "?target=",
    "?target=../x",
    "?target=a&receipt=forged",
  ])
    expect(
      targetSelectionFromLocation({ pathname: "/targets", search }),
    ).toBeUndefined();
  expect(
    targetSelectionFromLocation({
      pathname: "/agent",
      search: "?target=valid",
    }),
  ).toBeUndefined();
});
