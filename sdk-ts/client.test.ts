import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { AgentEscrow402ReadClient } from "./client.ts";
import { NotFoundError, APIError } from "./errors.ts";
import { EscrowStatus, TokenType } from "./types.ts";

async function withServer(
  handler: http.RequestListener,
  fn: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("failed to bind test server");
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    await fn(baseUrl);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

test("getEscrow: parses a 200 response into the escrow shape", async () => {
  const escrow = {
    id: "00000000-0000-0000-0000-000000000001",
    agent_id: "agent-1",
    client_id: "client-1",
    amount: 5000,
    current_balance: 5000,
    token_type: TokenType.CSPR,
    status: EscrowStatus.FUNDED,
    description: "test escrow for the read client",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  await withServer(
    (req, res) => {
      assert.equal(req.url, "/escrow/deadbeef");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(escrow));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(baseUrl);
      const result = await client.getEscrow("deadbeef");
      assert.equal(result.status, EscrowStatus.FUNDED);
      assert.equal(result.amount, 5000);
    },
  );
});

test("getEscrow: 404 raises NotFoundError with the server's detail message", async () => {
  await withServer(
    (_req, res) => {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "escrow not found" }));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(baseUrl);
      await assert.rejects(
        () => client.getEscrow("missing"),
        (err: unknown) => {
          assert.ok(err instanceof NotFoundError);
          assert.equal((err as NotFoundError).message, "escrow not found");
          assert.equal((err as NotFoundError).status_code, 404);
          return true;
        },
      );
    },
  );
});

test("getEscrow: 500 raises the generic APIError", async () => {
  await withServer(
    (_req, res) => {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "internal error" }));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(baseUrl);
      await assert.rejects(() => client.getEscrow("x"), APIError);
    },
  );
});

test("getReputation: hits /reputation/{agent} and returns raw JSON", async () => {
  await withServer(
    (req, res) => {
      assert.equal(req.url, "/reputation/agent-42");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ agent_id: "agent-42", score: 87.5 }));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(baseUrl);
      const rep = await client.getReputation("agent-42");
      assert.equal(rep.score, 87.5);
    },
  );
});

test("health: hits /health and returns status", async () => {
  await withServer(
    (req, res) => {
      assert.equal(req.url, "/health");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok" }));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(baseUrl);
      const health = await client.health();
      assert.equal(health.status, "ok");
    },
  );
});

test("base URL trailing slash is normalized", async () => {
  await withServer(
    (req, res) => {
      assert.equal(req.url, "/health");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok" }));
    },
    async (baseUrl) => {
      const client = new AgentEscrow402ReadClient(`${baseUrl}///`);
      const health = await client.health();
      assert.equal(health.status, "ok");
    },
  );
});
