# ae402 — command-line client

`ae402` is a thin, ergonomic wrapper over the Python SDK
(`agentescrow402_sdk.client.EscrowClient`). It ships with the SDK
package, so:

    pip install agentescrow402-sdk

installs both the library and the `ae402` console script.

## Design

- **1:1 wrapper.** Every subcommand maps to one `EscrowClient` method
  or one hosted REST endpoint. Adding a subcommand does not add a new
  API path — if a call isn't in the SDK yet, add it there first.
- **stdin / stdout are the API.** Every subcommand prints pretty JSON
  on stdout; errors and progress notices go to stderr. Exit code 0 on
  success, 1 on any error, 2 on argparse validation errors.
- **Signed by default.** The CLI defaults to signed x402 mode with a
  real Ed25519 identity, so a user does not accidentally hit
  production with `--sandbox`.

## Identity resolution

1. `--secret-key-hex 0x…` (or bare hex) on the command line.
2. `AE402_SECRET_KEY_HEX` in the environment.
3. Otherwise a fresh ephemeral key is generated for the run; the
   derived public key is printed on **stderr** so it can be pinned for
   later reuse.

For quick, unsigned reads against a running dev server use `--sandbox`
(and optionally `--sender <label>`).

## Commands

    ae402 health
    ae402 stats
    ae402 list-escrows [--limit N]
    ae402 get-escrow --service-hash <64-hex>
    ae402 get-history --service-hash <64-hex>
    ae402 reputation --agent <64-hex>

    ae402 create-escrow --receiver <64-hex> --amount <motes> [--ttl <seconds>]
    ae402 release --service-hash <64-hex>
    ae402 refund  --service-hash <64-hex>
    ae402 dispute --service-hash <64-hex> --reason-hash <64-hex>

    ae402 compute-hash       --sender <hex> --receiver <hex> --amount <motes> --nonce <str>
    ae402 build-x402-header  --escrow-hash <64-hex> --amount <motes>
                             [--method POST] [--path /escrow]

    ae402 mcp-tools [--names-only]
    ae402 mcp-call <tool_name> [--arguments-json '{"k":"v"}' | --arguments-file args.json]

Every command accepts these global flags before the subcommand:

    --api-url <base>         # default: $AE402_API_URL or the hosted service
    --sandbox                # unsigned mode (?sender=)
    --sender <label>         # sandbox sender label (default: cli-sandbox)
    --secret-key-hex <hex>   # Ed25519 seed hex; overrides env
    --timeout <seconds>      # per-request timeout (default: 30)

## Piping

Because output is JSON:

    ae402 stats | jq '.escrows_created'
    ae402 mcp-tools --names-only | jq -r '.[]'
    export ESC=$(ae402 create-escrow --receiver <hex> --amount 1000000 | jq -r '.escrow_hash')
    ae402 get-history --service-hash "$ESC"

## Local-only commands

- `compute-hash` — computes a canonical service hash without any
  network call. Useful in CI / tests to check hash agreement with the
  SDK.
- `build-x402-header` — prints a signed `X-Payment` header without
  posting anything. Handy when driving the API from `curl`.

## MCP catalogue integration

- `ae402 mcp-tools [--names-only]` fetches the shipped catalogue served
  by the hosted playground (`GET /mcp/tools`).
- `ae402 mcp-call <name>` invokes a single tool
  (`POST /mcp/tools/<name>/call`); arguments can be an inline JSON
  string or a file. Response is echoed verbatim with the same
  `content` / `isError` / `status` shape as the playground so scripts
  can share code with the browser UI.

## Not in scope

- **Interactive shell mode** — argparse is enough; we do not ship a
  repl.
- **Persistent config file** — everything reads from env vars and CLI
  flags. A config file is a footgun in CI.
- **Wallet UI** — the CLI signs bytes; a Casper Signer UI is not the
  right surface for a shell client.
