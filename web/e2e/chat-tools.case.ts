import { expect, test, type APIRequestContext } from "@playwright/test";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  unexpectedConsole,
  type ConsoleFact,
  type MetadataResponse,
} from "../src/test/chat-metadata-console";

const dir = process.env.CHAT02A_DIR!;
const desiredName = process.env.CHAT02A_NAME!;
const real = process.env.CHAT02A_MODE === "real";
type Agent = {
  resource_id: "agent-profile";
  name: string;
  skill_ids: string[];
};
type Workspace = {
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
    before: Agent;
    after: Agent;
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
    : "native fixture approved Agent write",
  async ({ page, request }) => {
    const errors: string[] = [];
    const consoleFacts: ConsoleFact[] = [];
    const metadataResponses: MetadataResponse[] = [];
    const responseReads: Promise<void>[] = [];
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
      const session = (await sessionAck.json()) as { id: string };
      const prompt = `Read the current Agent profile with configuration_read first. Then propose exactly one agent_profile_update changing only the Agent name to "${desiredName}". Preserve the complete current skill_ids list unchanged. Wait for operator approval. Do not claim the change is saved without the tool result. After that result, reply briefly in Korean.`;
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
      const grant = (await grantAck.json()) as {
        id: string;
        turn_request_id: string;
        text_sha256: string;
        session_id: string;
      };
      expect(grant.text_sha256).toBe(sha(prompt));
      expect(grant.session_id).toBe(session.id);
      const turnAck = await turnResponse;
      expect(turnAck.status()).toBe(202);
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
      expect(read.arguments).toEqual({ kind: "agent_profile" });
      expect(read.result).toEqual({
        kind: "agent_profile",
        draft_revision: before.meta.audit_retention.total_recorded,
        agent_profile: profile(before),
      });
      expect(call.tool).toBe("agent_profile_update");
      expect(call.grant_id).toBe(grant.id);
      expect(call.provider_call_id).not.toBe(read.provider_call_id);
      expect(call.args_digest).toBe(sha(call.arguments));
      expect(call.arguments).toEqual({
        expected_draft_revision: before.meta.audit_retention.total_recorded,
        name: desiredName,
        skill_ids: before.agent_profile.skill_ids,
      });
      expect(call.proposal!.before).toEqual(profile(before));
      expect(call.proposal!.after).toEqual({
        ...profile(before),
        name: desiredName,
      });
      expect(call.proposal!.digest).toBe(
        sha({
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
        turn: admitted,
        transcript,
      });
      const card = page.getByTestId(`chat-tool-proposal-${call.id}`);
      await expect(card).toBeVisible();
      await expect(card).toContainText(desiredName);
      await expect(card).toContainText(before.agent_profile.name);
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
      expect(after.agent_profile).toEqual({
        ...before.agent_profile,
        name: desiredName,
      });
      expect(after.meta.audit_retention.total_recorded).toBe(
        before.meta.audit_retention.total_recorded + 1,
      );
      expect(after.audit.slice(0, -1)).toEqual(before.audit);
      const audit = after.audit.at(-1)!;
      expect(audit).toMatchObject({
        action: "agent_profile.updated",
        entity_id: "agent-profile",
        origin: "local_operator",
      });
      expect(operation.result).toEqual({
        kind: "agent_profile_updated",
        before_revision: before.meta.audit_retention.total_recorded,
        after_revision: after.meta.audit_retention.total_recorded,
        agent_profile: profile(after),
        audit,
      });
      await expect(page.getByTestId(`chat-tool-${call.id}`)).toHaveAttribute(
        "data-tool-status",
        "succeeded",
      );
      await page.getByTestId(`chat-tool-view-saved-${call.id}`).click();
      const assignment = page.getByRole("form", {
        name: /Agent assignment|에이전트 할당/,
      });
      await expect(assignment).toBeVisible();
      await expect(
        assignment.getByLabel(/Agent name|에이전트 이름/, { exact: true }),
      ).toHaveValue(desiredName);
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
        session,
        terminal,
        completed,
        before,
        after,
        requests,
      });
    } finally {
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
