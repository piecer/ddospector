import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext } from "@playwright/test";
import type {
  AIModelProfile,
  AISettingsSnapshot,
} from "../src/pages/ai-settings/types";

const endpoint = "/api/v1/ai-settings";
function profile(
  name: string,
  patch: Partial<AIModelProfile> = {},
): AIModelProfile {
  return {
    id: `llm-${randomUUID()}`,
    name,
    format: "openai",
    model: "literal/operator-model",
    base_url: "",
    credential_env: "",
    rate_per_second: 0,
    rate_per_minute: 0,
    context_window_k: 0,
    streaming: true,
    max_tokens: 0,
    max_tokens_field: "",
    thinking_type: "",
    reasoning_effort: "",
    retry: {
      connect: { attempts: 0, interval_ms: 0 },
      empty: { attempts: 0, interval_ms: 0 },
      stream: { attempts: 0, interval_ms: 0 },
    },
    ...patch,
  };
}
async function read(request: APIRequestContext): Promise<AISettingsSnapshot> {
  const response = await request.get(endpoint);
  expect(response.status()).toBe(200);
  return response.json();
}
async function restore(request: APIRequestContext, before: AISettingsSnapshot) {
  const current = await read(request);
  const response = await request.put(endpoint, {
    data: {
      revision: current.revision,
      profiles: before.profiles,
      default_profile_id: before.default_profile_id,
      agent_profile_id: before.agent_profile_id,
    },
  });
  expect(response.status()).toBe(200);
  expect(await read(request)).toEqual(await response.json());
}
const corpus = [
  { id: "ascii-control", profiles: () => [profile("ASCII control")] },
  {
    id: "numeric-dns-label",
    profiles: () => [
      profile("Numeric DNS label", { base_url: "https://model.123/v1" }),
    ],
  },
  {
    id: "hex-looking-dns-label",
    profiles: () => [
      profile("Hex DNS label", { base_url: "https://model.0xabc/v1" }),
    ],
  },
  {
    id: "hex-single-label",
    profiles: () => [
      profile("Hex single label", { base_url: "http://0x7f000001/v1" }),
    ],
  },
  {
    id: "ipv6-port",
    profiles: () => [
      profile("IPv6", { base_url: "https://[2001:db8::1]:8443/v1" }),
    ],
  },
  {
    id: "trailing-dot",
    profiles: () => [
      profile("Trailing dot", { base_url: "https://example.invalid./v1" }),
    ],
  },
  {
    id: "unicode-literal-boundaries",
    profiles: () => [
      profile("한".repeat(119) + "🔬", {
        model: "🧪".repeat(200),
        base_url: "https://예시.한국/모델",
      }),
    ],
  },
  {
    id: "idna-compatible-dot",
    profiles: () => [
      profile("IDNA compatibility mapping", {
        base_url: "https://model\u2024example/v1",
      }),
    ],
  },
  {
    id: "idna-unassigned-codepoint",
    profiles: () => [
      profile("IDNA unassigned scalar", {
        base_url: "https://\u0378.example/v1",
      }),
    ],
  },
  {
    id: "unicode-cyrillic-fold-boundary",
    profiles: () => [profile("Case \u1c89"), profile("Case \u1c8a")],
  },
  {
    id: "unicode-latin-fold-boundary",
    profiles: () => [profile("Case \ua7cb"), profile("Case \u0264")],
  },
];

for (const sample of corpus) {
  test(`actual producer bytes remain editable in Chromium: ${sample.id}`, async ({
    page,
    request,
  }, info) => {
    const before = await read(request);
    const profiles = sample.profiles();
    const external: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        ["http:", "https:"].includes(url.protocol) &&
        url.origin !== "http://127.0.0.1:5175"
      )
        external.push(request.url());
    });
    try {
      const response = await request.put(endpoint, {
        data: {
          revision: before.revision,
          profiles,
          default_profile_id: null,
          agent_profile_id: null,
        },
      });
      expect(response.status()).toBe(200);
      const producerBytes = await response.body();
      await info.attach("actual-producer-put.json", {
        body: producerBytes,
        contentType: "application/json",
      });
      const saved = JSON.parse(
        producerBytes.toString("utf8"),
      ) as AISettingsSnapshot;
      expect(saved.profiles).toEqual(profiles);
      const get = await request.get(endpoint);
      const getBytes = await get.body();
      await info.attach("actual-producer-get.json", {
        body: getBytes,
        contentType: "application/json",
      });
      expect(getBytes).toEqual(producerBytes);
      await page.goto("/ai-settings");
      const client = await page.evaluate(async () => {
        try {
          const modulePath = "/src/pages/ai-settings/client.ts";
          const { aiSettingsAPI } = await import(/* @vite-ignore */ modulePath);
          return { accepted: true, snapshot: await aiSettingsAPI.read() };
        } catch (error) {
          return { accepted: false, error: String(error) };
        }
      });
      await info.attach("shipped-client-result.json", {
        body: JSON.stringify(client),
        contentType: "application/json",
      });
      expect(
        client.accepted,
        `Real producer snapshot ${sample.id} rejected by shipped browser client`,
      ).toBe(true);
      expect(client.snapshot).toEqual(saved);
      for (let reload = 0; reload < 2; reload++) {
        if (reload) await page.reload();
        await expect(
          page.getByRole("button", { name: "Create profile", exact: true }),
        ).toBeEnabled();
        for (const value of profiles) {
          await expect(
            page.getByRole("heading", { name: value.name, exact: true }),
          ).toBeVisible();
          await page
            .getByRole("button", { name: "Edit " + value.name, exact: true })
            .click();
          const dialog = page.getByRole("dialog");
          await expect(
            dialog.getByLabel("Profile name", { exact: true }),
          ).toHaveValue(value.name);
          await expect(
            dialog.getByLabel("Base URL", { exact: true }),
          ).toHaveValue(value.base_url);
          await page.keyboard.press("Escape");
          await expect(dialog).not.toBeVisible();
        }
      }
      expect(await read(request)).toEqual(saved);
      expect(external).toEqual([]);
    } finally {
      await restore(request, before);
    }
  });
}

test("producer still rejects unsafe endpoints, malformed IP syntax, controls and folded duplicate names", async ({
  request,
}, info) => {
  const before = await read(request);
  const invalid = [
    {
      id: "abbreviated-ip",
      profiles: [profile("Invalid", { base_url: "http://1.2.3/v1" })],
    },
    {
      id: "octal-ip",
      profiles: [profile("Invalid", { base_url: "http://0127.0.0.1/v1" })],
    },
    {
      id: "malformed-idna",
      profiles: [
        profile("Invalid", { base_url: "https://xn--invalid-.example/v1" }),
      ],
    },
    {
      id: "zero-port",
      profiles: [
        profile("Invalid", { base_url: "https://model.example:0/v1" }),
      ],
    },
    {
      id: "userinfo",
      profiles: [
        profile("Invalid", { base_url: "https://user@model.example/v1" }),
      ],
    },
    {
      id: "query",
      profiles: [
        profile("Invalid", { base_url: "https://model.example/v1?key=value" }),
      ],
    },
    {
      id: "fragment",
      profiles: [
        profile("Invalid", { base_url: "https://model.example/v1#part" }),
      ],
    },
    { id: "format-control", profiles: [profile("Invalid\u200d")] },
    {
      id: "casefold-duplicate",
      profiles: [profile("Straße"), profile("STRASSE")],
    },
  ];
  const receipts = [];
  for (const sample of invalid) {
    const response = await request.put(endpoint, {
      data: {
        revision: before.revision,
        profiles: sample.profiles,
        default_profile_id: null,
        agent_profile_id: null,
      },
    });
    receipts.push({
      id: sample.id,
      status: response.status(),
      body: await response.json(),
    });
    expect(response.status(), sample.id).toBe(422);
    expect(await read(request)).toEqual(before);
  }
  await info.attach("negative-controls.json", {
    body: JSON.stringify(receipts),
    contentType: "application/json",
  });
});
