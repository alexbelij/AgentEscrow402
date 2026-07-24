/**
 * Tests for HMAC-SHA256 webhook signature verification.
 *
 * Run with: `node --test --experimental-strip-types webhooks.test.ts`
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  signWebhookPayload,
  verifyWebhookSignature,
  WebhookSignatureError,
} from "./webhooks.ts";

const SECRET = "whsec_test_deadbeef_deadbeef_deadbeef";

const SAMPLE_EVENT = {
  id: "evt_01HVXKJ0K0K0K0K0K0K0K0K0K0",
  type: "escrow.created",
  created: 1_752_000_000,
  data: {
    escrow_id: "deadbeef".repeat(8),
    amount: "10.5",
    token: "CSPR",
  },
};

describe("signWebhookPayload / verifyWebhookSignature roundtrip", () => {
  it("verifies a signature it just produced", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_752_000_100;
    const header = await signWebhookPayload(payload, SECRET, t);
    assert.match(header, /^t=1752000100,v1=[0-9a-f]{64}$/);
    const parsed = await verifyWebhookSignature(payload, header, SECRET, {
      nowSeconds: t + 10,
    });
    assert.equal(parsed.id, SAMPLE_EVENT.id);
    assert.equal(parsed.type, "escrow.created");
  });

  it("verifies with tolerance at the edge (exactly 300s late)", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, SECRET, t);
    // 300s late — right at default tolerance
    const parsed = await verifyWebhookSignature(payload, header, SECRET, {
      nowSeconds: t + 300,
    });
    assert.equal(parsed.type, "escrow.created");
  });
});

describe("verifyWebhookSignature — reject conditions", () => {
  it("throws WebhookSignatureError on missing header", async () => {
    await assert.rejects(
      () => verifyWebhookSignature("{}", null, SECRET),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "missing_header",
    );
    await assert.rejects(
      () => verifyWebhookSignature("{}", "", SECRET),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "missing_header",
    );
  });

  it("throws on missing t=", async () => {
    await assert.rejects(
      () => verifyWebhookSignature("{}", "v1=abcd", SECRET),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "malformed_header",
    );
  });

  it("throws on missing v1=", async () => {
    await assert.rejects(
      () => verifyWebhookSignature("{}", "t=1000000000", SECRET),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "malformed_header",
    );
  });

  it("throws on non-numeric t=", async () => {
    await assert.rejects(
      () =>
        verifyWebhookSignature("{}", "t=not-a-number,v1=abcd", SECRET),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "malformed_header",
    );
  });

  it("throws when timestamp is older than tolerance", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, SECRET, t);
    await assert.rejects(
      () =>
        verifyWebhookSignature(payload, header, SECRET, {
          nowSeconds: t + 301, // just outside default 300s tolerance
        }),
      (err) =>
        err instanceof WebhookSignatureError &&
        err.reason === "timestamp_out_of_tolerance",
    );
  });

  it("throws when timestamp is in the future beyond tolerance", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, SECRET, t);
    await assert.rejects(
      () =>
        verifyWebhookSignature(payload, header, SECRET, {
          nowSeconds: t - 301,
        }),
      (err) =>
        err instanceof WebhookSignatureError &&
        err.reason === "timestamp_out_of_tolerance",
    );
  });

  it("throws when signature was signed with a different secret", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, "other_secret", t);
    await assert.rejects(
      () =>
        verifyWebhookSignature(payload, header, SECRET, {
          nowSeconds: t + 10,
        }),
      (err) =>
        err instanceof WebhookSignatureError &&
        err.reason === "no_matching_signature",
    );
  });

  it("throws when payload has been tampered with", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, SECRET, t);
    const tampered = payload.replace('"CSPR"', '"USDT"');
    await assert.rejects(
      () =>
        verifyWebhookSignature(tampered, header, SECRET, {
          nowSeconds: t + 10,
        }),
      (err) =>
        err instanceof WebhookSignatureError &&
        err.reason === "no_matching_signature",
    );
  });

  it("throws on empty secret", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const header = "t=1000000000,v1=deadbeef";
    await assert.rejects(
      () =>
        verifyWebhookSignature(payload, header, "", {
          nowSeconds: 1_000_000_000 + 10,
        }),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "invalid_secret",
    );
  });

  it("throws on malformed header segment (no equals sign)", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    await assert.rejects(
      () =>
        verifyWebhookSignature(payload, "t=1000000000,v1abc", SECRET, {
          nowSeconds: 1_000_000_000 + 10,
        }),
      (err) =>
        err instanceof WebhookSignatureError &&
        err.reason === "malformed_header",
    );
  });

  it("accepts multiple v1= entries (rolling secrets) — matches any", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const goodHeader = await signWebhookPayload(payload, SECRET, t);
    // Build a header with a bogus first v1= and the real one second
    const fakeSig = "0".repeat(64);
    const merged = goodHeader.replace(
      /^t=(\d+),v1=(.+)$/,
      (_, ts, real) => `t=${ts},v1=${fakeSig},v1=${real}`,
    );
    const parsed = await verifyWebhookSignature(payload, merged, SECRET, {
      nowSeconds: t + 10,
    });
    assert.equal(parsed.type, "escrow.created");
  });

  it("ignores unknown scheme keys (forward compat with v2=)", async () => {
    const payload = JSON.stringify(SAMPLE_EVENT);
    const t = 1_000_000_000;
    const header = await signWebhookPayload(payload, SECRET, t);
    const withV2 = `${header},v2=deadbeef,unknown=whatever`;
    const parsed = await verifyWebhookSignature(payload, withV2, SECRET, {
      nowSeconds: t + 10,
    });
    assert.equal(parsed.type, "escrow.created");
  });
});

describe("signWebhookPayload — misuse", () => {
  it("throws on non-finite timestamp", async () => {
    await assert.rejects(
      () => signWebhookPayload("{}", SECRET, Number.NaN),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "malformed_header",
    );
  });

  it("throws on zero timestamp", async () => {
    await assert.rejects(
      () => signWebhookPayload("{}", SECRET, 0),
      (err) =>
        err instanceof WebhookSignatureError && err.reason === "malformed_header",
    );
  });
});
