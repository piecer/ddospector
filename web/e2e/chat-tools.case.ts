import { expect, test, type APIRequestContext } from "@playwright/test";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  observePersistedGrant,
  type GrantObservation,
  type GrantObserverFact,
} from "./chat-grant-observer";
import type { ChatSession } from "../src/pages/ai/chat-types";
import {
  unexpectedConsole,
  type ConsoleFact,
  type MetadataResponse,
} from "../src/test/chat-metadata-console";

const dir = process.env.CHAT02A_DIR!;
const desiredName = process.env.CHAT02A_NAME!;
const real = process.env.CHAT02A_MODE === "real";
const targetCase = process.env.CHAT02B1_FIXTURE_CASE === "target";
const targetInput = { name: desiredName, address: "Example.COM.", kind: "DUT" };
type Target = {
  id: string;
  name: string;
  address: string;
  kind: "DUT" | "SINK";
  status: "draft";
  created_at: string;
};
type TargetInspection = {
  schema_version: 1;
  draft_revision: number;
  targets: Target[];
};
type Agent = {
  resource_id: "agent-profile";
  name: string;
  skill_ids: string[];
};
type Workspace = {
  targets: Target[];
  agent_profile: {
    name: string;
    skill_ids: string[];
    mcp_server_ids: string[];
    autonomy: string;
    execution_enabled: boolean;
  };
  audit: Record<string, unknown>[];
  meta: { audit_retention: { total_recorded: number } };
};
type Decision = {
  request_id: string;
  call_id: string;
  proposal_digest: string;
  decision: string;
};
type Call = {
  id: string;
  index: number;
  grant_id: string;
  provider_call_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  args_digest: string;
  status: string;
  result: Record<string, unknown> | null;
  error_code: string | null;
  proposal: {
    digest: string;
    operation?: "target_create";
    before: Agent | null;
    after: Agent | typeof targetInput;
    expected_draft_revision: number;
    expires_at: string;
  } | null;
  decision: Decision | null;
};
type Transcript = {
  schema_version: number;
  turn_id: string;
  revision: number;
  calls: Call[];
};
type Turn = {
  id: string;
  status: string;
  session_id: string;
  assistant_text: string;
  error_code: string | null;
};

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const item = value as Record<string, unknown>;
    return `{${Object.keys(item)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(item[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
function sha(value: unknown) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}
function artifact(name: string, value: unknown) {
  writeFileSync(join(dir, name + ".pending"), JSON.stringify(value, null, 2));
  renameSync(join(dir, name + ".pending"), join(dir, name));
}
async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get("/api/v1/" + path);
  expect(response.status(), path).toBe(200);
  return response.json() as Promise<T>;
}
function profile(workspace: Workspace): Agent {
  return {
    resource_id: "agent-profile",
    name: workspace.agent_profile.name,
    skill_ids: workspace.agent_profile.skill_ids,
  };
}

// ONE conversation for all locales/viewports. No model retries, route.fulfill,
// manufactured proposals, manual profile saves or text/JSON fallback execution.
test(
  real
    ? "native real model approved Agent write"
    : targetCase
      ? "native fixture approved target creation"
      : "native fixture approved Agent write",
  async ({ page, request }) => {
    const errors: string[] = [];
    const consoleFacts: ConsoleFact[] = [];
    const metadataResponses: MetadataResponse[] = [];
    const responseReads: Promise<void>[] = [];
    const grantObserverFacts: GrantObserverFact[] = [];
    let grantObservation: GrantObservation | undefined;
    let responseOrder = 0;
    const requests: { method: string; path: string; body: unknown }[] = [];
    page.on("pageerror", (error) => {
      errors.push(error.message);
      consoleFacts.push({ text: error.message, url: "" });
    });
    page.on("console", (message) => {
      if (message.type() === "error") {
        errors.push(message.text());
        consoleFacts.push({
          text: message.text(),
          url: message.location().url,
        });
      }
    });
    page.on("response", (response) => {
      if (!new URL(response.url()).pathname.startsWith("/api/v1/chat/")) return;
      const fact: MetadataResponse = {
        order: ++responseOrder,
        url: response.url(),
        method: response.request().method(),
        status: response.status(),
      };
      metadataResponses.push(fact);
      if (fact.status === 429) {
        responseReads.push(
          response.json().then(
            (body: { code?: string }) => {
              fact.code = body.code;
            },
            () => {
              /* Unreadable responses cannot qualify for accounting. */
            },
          ),
        );
      }
    });
    page.on("request", (req) => {
      const url = new URL(req.url());
      expect(url.port).not.toBe("11434");
      if (url.pathname.startsWith("/api/"))
        requests.push({
          method: req.method(),
          path: url.pathname,
          body: req.method() === "GET" ? null : req.postDataJSON(),
        });
    });
    try {
      const before = await get<Workspace>(request, "workspace");
      expect(before).toEqual(
        JSON.parse(readFileSync(join(dir, "workspace-before.json"), "utf8")),
      );
      await page.goto("/agent");
      await page.locator(".language-control select").selectOption("ko");
      await expect(page.getByTestId("chat-tools-toggle")).not.toBeChecked();
      expect(
        (await get<{ sessions: unknown[] }>(request, "chat/sessions")).sessions,
      ).toEqual([]);
      await page.getByTestId("chat-new-session").click();
      const sessionResponse = page.waitForResponse(
        (res) =>
          res.request().method() === "POST" &&
          res.url().endsWith("/api/v1/chat/sessions"),
      );
      await page.getByTestId("chat-start-confirm").click();
      const sessionAck = await sessionResponse;
      expect(sessionAck.status()).toBe(201);
      const session = (await sessionAck.json()) as ChatSession;
      const prompt = targetCase
        ? `Read targets with configuration_read first. Propose exactly one target_create with name "${desiredName}", literal address "Example.COM.", kind DUT and the observed current revision. Wait for explicit approval. This is inert syntax-only creation, not a network probe. Report only saved tool facts.`
        : `Read the current Agent profile with configuration_read first. Then propose exactly one agent_profile_update changing only the Agent name to "${desiredName}". Preserve the complete current skill_ids list unchanged. Wait for operator approval. Do not claim the change is saved without the tool result. After that result, reply briefly in Korean.`;
      if (targetCase) {
        const scope = page.getByTestId("chat-tool-scope");
        await expect(scope).toHaveValue("agent_v1");
        await expect(scope).toHaveAccessibleName("도구 허용 범위");
        await page
          .getByRole("button", { name: "도구 사용 가능 여부 / 차단 읽기" })
          .click();
        await expect(
          page.getByRole("option", { name: "대상 생성" }),
        ).toBeEnabled();
        await scope.selectOption("target_create_v2");
        await expect(scope).toHaveValue("target_create_v2");
        await expect(page.getByTestId("chat-tools-toggle")).toHaveAccessibleName(
          "정확히 다음 메시지만: 대상 읽기와 대상 생성 제안 1건에 동의합니다. 저장 권한이 아니며 정확한 제안에 별도 승인이 필요합니다.",
        );
        await expect(page.getByTestId("chat-tools-toggle")).not.toBeChecked();
        expect(
          requests.filter(
            (item) =>
              item.method === "POST" &&
              (item.path.endsWith("/tool-grants") ||
                item.path.endsWith("/tool-turns")),
          ),
        ).toEqual([]);
      }
      await page.getByTestId("chat-tools-toggle").check();
      await page.getByTestId("chat-input").fill(prompt);
      const grantResponse = page.waitForResponse(
        (res) =>
          res.request().method() === "POST" &&
          res.url().endsWith("/api/v1/chat/tool-grants"),
      );
      const turnResponse = page.waitForResponse(
        (res) =>
          res.request().method() === "POST" &&
          res.url().endsWith(`/api/v1/chat/sessions/${session.id}/tool-turns`),
      );
      await page.getByTestId("chat-send").click();
      const consent = page.getByTestId("chat-tools-grant-confirm");
      if (await consent.isVisible()) await consent.click();
      const grantAck = await grantResponse;
      expect(grantAck.status()).toBe(201);
      const turnAck = await turnResponse;
      expect(turnAck.status()).toBe(202);
      // Observe original POST identities, but never depend on its historical
      // CDP response body. The independent GET may truthfully be consumed.
      grantObservation = await observePersistedGrant({
        post: {
          method: grantAck.request().method(),
          path: new URL(grantAck.url()).pathname,
          status: grantAck.status(),
          body: grantAck.request().postDataJSON(),
        },
        session,
        prompt,
        authority: targetCase ? "target_create_v2" : "agent_v1",
        observedTurn: {
          method: turnAck.request().method(),
          path: new URL(turnAck.url()).pathname,
          body: turnAck.request().postDataJSON(),
        },
        get: async (path, options) => {
          const response = await request.get(path, options);
          return { status: response.status(), body: await response.text() };
        },
        record: (fact) => grantObserverFacts.push(fact),
      });
      const grant = grantObservation.grant as GrantObservation["grant"] & {
        scope?: string;
        proposal_tools?: string[];
      };
      expect(grant.text_sha256).toBe(sha(prompt));
      expect(grant.session_id).toBe(session.id);
      if (targetCase) {
        expect(grant.schema_version).toBe(2);
        expect(grant.scope).toBe("target_create");
        expect(grant.read_scope).toEqual(["targets", "target"]);
        expect(grant.proposal_tools).toEqual(["target_create"]);
        expect(grant).not.toHaveProperty("proposal_fields");
        const posted = grantAck.request().postDataJSON() as Record<
          string,
          unknown
        >;
        expect(posted.schema_version).toBe(2);
        expect(posted.scope).toBe("target_create");
        await expect(page.getByTestId("chat-tool-scope")).toBeDisabled();
      } else {
        expect(grant.schema_version).toBe(1);
        expect(grantAck.request().postDataJSON()).not.toHaveProperty(
          "schema_version",
        );
        expect(grantAck.request().postDataJSON()).not.toHaveProperty("scope");
      }
      const admitted = (await turnAck.json()) as Turn & { request_id: string };
      expect(admitted.request_id).toBe(grant.turn_request_id);
      let transcript: Transcript | undefined;
      await expect
        .poll(
          async () => {
            transcript = await get<Transcript>(
              request,
              `chat/turns/${admitted.id}/tools`,
            );
            return transcript.calls.some(
              (call) => call.status === "awaiting_approval",
            );
          },
          { timeout: 115_000, intervals: [200, 500] },
        )
        .toBe(true);
      expect(transcript!.calls).toHaveLength(2);
      const read = transcript!.calls[0];
      const call = transcript!.calls[1];
      expect(read.tool).toBe("configuration_read");
      expect(read.status).toBe("succeeded");
      expect(read.arguments).toEqual(
        targetCase
          ? { kind: "targets", offset: 0, limit: 10 }
          : { kind: "agent_profile" },
      );
      expect(read.result).toEqual(
        targetCase
          ? {
              kind: "targets",
              draft_revision: before.meta.audit_retention.total_recorded,
              items: before.targets.slice(0, 10),
              next_offset: before.targets.length > 10 ? 10 : null,
            }
          : {
              kind: "agent_profile",
              draft_revision: before.meta.audit_retention.total_recorded,
              agent_profile: profile(before),
            },
      );
      expect(call.tool).toBe(
        targetCase ? "target_create" : "agent_profile_update",
      );
      expect(call.grant_id).toBe(grant.id);
      expect(call.provider_call_id).not.toBe(read.provider_call_id);
      expect(call.args_digest).toBe(sha(call.arguments));
      expect(call.arguments).toEqual(
        targetCase
          ? {
              expected_draft_revision:
                before.meta.audit_retention.total_recorded,
              ...targetInput,
            }
          : {
              expected_draft_revision:
                before.meta.audit_retention.total_recorded,
              name: desiredName,
              skill_ids: before.agent_profile.skill_ids,
            },
      );
      expect(call.proposal!.before).toEqual(
        targetCase ? null : profile(before),
      );
      expect(call.proposal!.after).toEqual(
        targetCase
          ? targetInput
          : {
              ...profile(before),
              name: desiredName,
            },
      );
      expect(call.proposal!.digest).toBe(
        sha({
          ...(targetCase ? { operation: "target_create" } : {}),
          call_id: call.id,
          grant_id: grant.id,
          expected_draft_revision: call.proposal!.expected_draft_revision,
          before: call.proposal!.before,
          after: call.proposal!.after,
          expires_at: call.proposal!.expires_at,
        }),
      );
      expect(call.decision).toBeNull();
      expect(call.result).toBeNull();
      // Independent fresh HTTP read, not the UI cache or the model's words.
      expect(await get<Workspace>(request, "workspace")).toEqual(before);
      artifact("before-approval.json", {
        before,
        grant,
        grant_evidence_source: "persisted-grant-by-request-GET",
        original_grant_response_body: "not-observed",
        turn: admitted,
        transcript,
      });
      const card = page.getByTestId(`chat-tool-proposal-${call.id}`);
      await expect(card).toBeVisible();
      await expect(card).toContainText(desiredName);
      if (targetCase) {
        expect(call.proposal!.operation).toBe("target_create");
        await expect(card).toContainText("Example.COM.");
        await expect(card).toContainText("DUT");
      } else {
        await expect(card).toContainText(before.agent_profile.name);
      }
      const approve = page.getByTestId(`chat-tool-approve-${call.id}`);
      await approve.focus();
      await expect(approve).toBeFocused();
      const decisionResponse = page.waitForResponse(
        (res) =>
          res.request().method() === "POST" &&
          res.url().endsWith(`/api/v1/chat/tool-calls/${call.id}/decision`),
      );
      await approve.press("Enter");
      const decisionAck = await decisionResponse;
      expect(decisionAck.status()).toBe(201);
      const acceptedDecision = (await decisionAck.json()) as Decision;
      expect(acceptedDecision.call_id).toBe(call.id);
      expect(acceptedDecision.proposal_digest).toBe(call.proposal!.digest);
      expect(acceptedDecision.decision).toBe("approve");
      let terminal: Turn | undefined;
      await expect
        .poll(
          async () => {
            terminal = await get<Turn>(request, `chat/turns/${admitted.id}`);
            return ["succeeded", "failed", "cancelled", "interrupted"].includes(
              terminal.status,
            );
          },
          { timeout: 125_000, intervals: [200, 500] },
        )
        .toBe(true);
      expect(terminal!.status).toBe("succeeded");
      expect(terminal!.assistant_text.trim()).not.toBe("");
      expect(terminal!.error_code).toBeNull();
      // A5: independently GET companion AFTER observing terminal, never reuse old GET.
      const completed = await get<Transcript>(
        request,
        `chat/turns/${admitted.id}/tools`,
      );
      const operation = completed.calls[1];
      expect(operation.status).toBe("succeeded");
      expect(operation.decision).toEqual(acceptedDecision);
      expect(operation.error_code).toBeNull();
      expect(operation.proposal).toEqual(call.proposal);
      const after = await get<Workspace>(request, "workspace");
      expect(after.agent_profile).toEqual(
        targetCase
          ? before.agent_profile
          : {
              ...before.agent_profile,
              name: desiredName,
            },
      );
      expect(after.meta.audit_retention.total_recorded).toBe(
        before.meta.audit_retention.total_recorded + 1,
      );
      expect(after.audit.slice(0, -1)).toEqual(before.audit);
      const audit = after.audit.at(-1)!;
      const savedTarget = targetCase ? after.targets.at(-1)! : undefined;
      expect(audit).toMatchObject({
        action: targetCase ? "target.created" : "agent_profile.updated",
        entity_id: targetCase ? savedTarget!.id : "agent-profile",
        origin: "local_operator",
      });
      expect(operation.result).toEqual(
        targetCase
          ? {
              kind: "target_created",
              before_revision: before.meta.audit_retention.total_recorded,
              after_revision: after.meta.audit_retention.total_recorded,
              target: savedTarget,
              audit,
            }
          : {
              kind: "agent_profile_updated",
              before_revision: before.meta.audit_retention.total_recorded,
              after_revision: after.meta.audit_retention.total_recorded,
              agent_profile: profile(after),
              audit,
            },
      );
      await expect(page.getByTestId(`chat-tool-${call.id}`)).toHaveAttribute(
        "data-tool-status",
        "succeeded",
      );
      await page.getByTestId(`chat-tool-view-saved-${call.id}`).click();
      if (targetCase) {
        expect(after.targets.slice(0, -1)).toEqual(before.targets);
        expect(savedTarget).toEqual({
          ...targetInput,
          id: savedTarget!.id,
          status: "draft",
          created_at: savedTarget!.created_at,
        });
        expect(savedTarget!.id).toMatch(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        );
        expect(audit.created_at).toBe(savedTarget!.created_at);
        expect(before.targets.some((item) => item.id === savedTarget!.id)).toBe(
          false,
        );
        expect(
          await get<TargetInspection>(request, "chat/tools/targets"),
        ).toEqual({
          schema_version: 1,
          draft_revision: after.meta.audit_retention.total_recorded,
          targets: after.targets,
        });
        const persisted = JSON.parse(
          readFileSync(join(dir, "owned-state", "draft.json"), "utf8"),
        ) as {
          targets: Target[];
          audit: Record<string, unknown>[];
          audit_total: number;
        };
        expect(persisted.targets).toEqual(after.targets);
        expect(persisted.audit).toEqual(after.audit);
        expect(persisted.audit_total).toBe(
          after.meta.audit_retention.total_recorded,
        );
        await expect(page).toHaveURL(
          new RegExp(`/targets\\?target=${savedTarget!.id}$`),
        );
        await expect(
          page.getByTestId("target-readback-status"),
        ).toHaveAttribute("data-readback", "receipt-confirmed");
        const row = page.getByTestId(`target-row-${savedTarget!.id}`);
        await expect(row).toHaveAttribute("data-selected", "true");
        for (const literal of [
          savedTarget!.id,
          desiredName,
          "Example.COM.",
          "DUT",
        ]) {
          await expect(row).toContainText(literal);
        }
        for (const locale of ["en", "ko"]) {
          await page.locator(".language-control select").selectOption(locale);
          for (const width of [900, 390]) {
            await page.setViewportSize({ width, height: 1000 });
            await expect(row).toBeVisible();
            await expect(
              page.getByTestId("target-readback-status"),
            ).toHaveAttribute("data-readback", "receipt-confirmed");
            expect(
              await page.evaluate(
                () => document.documentElement.scrollWidth <= innerWidth + 1,
              ),
            ).toBe(true);
            await page.screenshot({
              path: join(dir, `target-${locale}-${width}.png`),
              fullPage: true,
            });
          }
        }
      } else {
        const assignment = page.getByRole("form", {
          name: /Agent assignment|에이전트 할당/,
        });
        await expect(assignment).toBeVisible();
        await expect(
          assignment.getByLabel(/Agent name|에이전트 이름/, { exact: true }),
        ).toHaveValue(desiredName);
      }
      const writeCount = requests.filter(
        (item) => item.method !== "GET",
      ).length;
      artifact("saved-operation.json", {
        terminal,
        completed,
        after,
        writeCount,
      });
      // Parent restarts ONLY its owned service; this marker is not a product endpoint.
      artifact("restart-request.json", { turn_id: admitted.id });
      await expect
        .poll(() => existsSync(join(dir, "restart-ready.json")), {
          timeout: 30_000,
        })
        .toBe(true);
      expect(await get<Workspace>(request, "workspace")).toEqual(after);
      expect(
        await get<Transcript>(request, `chat/turns/${admitted.id}/tools`),
      ).toEqual(completed);
      await page.reload();
      if (targetCase) {
        await expect(
          page.getByTestId(`target-row-${savedTarget!.id}`),
        ).toHaveAttribute("data-selected", "true");
        await expect(
          page.getByTestId("target-readback-status"),
        ).toHaveAttribute("data-readback", "current-only");
        // Reload retains only URL selection, never an invented historical receipt.
        await page.goto("/agent");
      }
      await page.getByTestId(`chat-session-${session.id}`).click();
      await expect(page.getByTestId(`chat-tool-${call.id}`)).toHaveAttribute(
        "data-tool-status",
        "succeeded",
      );
      for (const locale of ["en", "ko"]) {
        await page.locator(".language-control select").selectOption(locale);
        for (const width of [900, 390]) {
          await page.setViewportSize({ width, height: 1000 });
          await expect(page.getByTestId(`chat-tool-${call.id}`)).toContainText(
            desiredName,
          );
          expect(
            await page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth + 1,
            ),
          ).toBe(true);
          const companion = page.getByTestId(`chat-tools-${admitted.id}`);
          expect(
            await companion.evaluate(
              (el) => el.scrollWidth <= el.clientWidth + 1,
            ),
          ).toBe(true);
          await expect(page.getByTestId("chat-tools-toggle")).not.toBeChecked();
          await page.screenshot({
            path: join(dir, `tools-${locale}-${width}.png`),
            fullPage: true,
          });
        }
      }
      expect(requests.filter((item) => item.method !== "GET")).toHaveLength(
        writeCount,
      );
      expect(
        requests.filter(
          (item) =>
            item.path === "/api/v1/agent-profile" && item.method === "PUT",
        ),
      ).toEqual([]);
      expect(
        requests.filter(
          (item) => item.path.endsWith("/decision") && item.method === "POST",
        ),
      ).toHaveLength(1);
      expect(
        requests.filter(
          (item) => item.path === "/api/v1/targets" && item.method !== "GET",
        ),
      ).toEqual([]);
      expect(await get<Workspace>(request, "workspace")).toEqual(after);
      expect(
        await get<Transcript>(request, `chat/turns/${admitted.id}/tools`),
      ).toEqual(completed);
      await Promise.all(responseReads);
      // Exact typed metadata 429 + later same-URL GET200 only, not a status ignore list.
      expect(
        unexpectedConsole(
          consoleFacts,
          metadataResponses,
          new URL(page.url()).origin,
        ),
      ).toEqual([]);
      artifact("browser-proof.json", {
        mode: real ? "real" : "fixture",
        fixture_case: targetCase ? "target" : "agent",
        session,
        terminal,
        completed,
        before,
        after,
        requests,
      });
    } finally {
      artifact("grant-observation.json", {
        historical_post_body_failure: {
          status: "unresolved",
          source: "chat02b1-browser62d/agent/browser.log",
          error: "response.json: Protocol error (Network.getResponseBody): No data found for resource with given identifier",
          note: "Persisted readback is not the historical POST acknowledgement or a diagnosis of its body failure.",
        },
        facts: grantObserverFacts,
        observation: grantObservation ?? null,
      });
      await Promise.all(responseReads);
      artifact("browser-diagnostics.json", {
        errors,
        requests,
        consoleFacts,
        metadataResponses,
      });
    }
  },
);
