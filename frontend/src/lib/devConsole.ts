// Devtools console easter egg.
//
// Purely cosmetic + read-only: prints a banner and exposes a small
// `window.ae402` helper object with links/facts an engineer poking at
// devtools would actually want (repo, docs, live contracts, API base).
// Nothing here touches app state, secrets, or writes anything — it only
// reads from the already-public generated manifest.
import { API_URL, FRONTEND_URL, NETWORK, CONTRACTS } from './manifest.generated';

const CONTRACT_COUNT = Object.keys(CONTRACTS).length;

const BANNER = `
%c   __ _  __ _  ___ _ __ | |_ | | ___  ___  ___ _ __ ___ __      __ | || |  ___
  / _\` |/ _\` |/ _ \\ '_ \\| __|| |/ _ \\/ __|/ __| '__/ _ \\\\ \\ /\\ / / | || | / _ \\\\
 | (_| | (_| |  __/ | | | |_ | |  __/\\__ \\ (__| | | (_) |\\ V  V /  |__   _|  __/
  \\__,_|\\__, |\\___|_| |_|\\__||_|\\___||___/\\___|_|  \\___/  \\_/\\_/      |_|  \\___|
        |___/
%cAgents pay agents. On-chain. No humans in the loop.
`;

const HELP = `
%cae402 devtools

%c  ae402.help()      %cshow this again
%c  ae402.repo()      %copen the GitHub repo
%c  ae402.docs()      %copen API / SDK / MCP docs
%c  ae402.contracts() %clist all ${CONTRACT_COUNT} live Casper testnet contracts
%c  ae402.health()    %cping the live API health endpoint
%c  ae402.hire()      %cwe are agents building for agents. talk to us.
`;

function open(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer');
}

export function installDevConsoleEasterEgg(): void {
  if (typeof window === 'undefined') return;
  // Vitest / SSR / non-browser contexts: skip.
  if (!window.console || !('log' in window.console)) return;

  console.log(
    BANNER,
    'color:#6366f1;font-weight:bold;font-family:monospace',
    'color:#9ca3af;font-style:italic'
  );
  console.log(
    `%cLive: %c${FRONTEND_URL}  %c|  API: %c${API_URL}  %c|  ${NETWORK}`,
    'color:#6b7280', 'color:#22c55e;font-weight:bold',
    'color:#6b7280', 'color:#0ea5e9;font-weight:bold',
    'color:#6b7280'
  );
  console.log('%cType ae402.help() for a few things you can poke at.', 'color:#6b7280;font-style:italic');

  (window as unknown as Record<string, unknown>).ae402 = {
    help() {
      console.log(
        HELP,
        'color:#6366f1;font-weight:bold', 'color:#e5e7eb', 'color:#6b7280',
        'color:#e5e7eb', 'color:#6b7280', 'color:#e5e7eb', 'color:#6b7280',
        'color:#e5e7eb', 'color:#6b7280', 'color:#e5e7eb', 'color:#6b7280',
        'color:#e5e7eb', 'color:#6b7280'
      );
    },
    repo() {
      open('https://github.com/alexbelij/AgentEscrow402');
    },
    docs() {
      open(`${FRONTEND_URL}/console/docs`);
    },
    contracts() {
      console.table(
        Object.values(CONTRACTS).map((c) => ({
          name: c.name,
          contract_hash: c.contractHash,
          version: c.version,
          explorer: c.explorer,
        }))
      );
    },
    async health() {
      try {
        const res = await fetch(`${API_URL}/health`);
        console.log(await res.json());
      } catch (err) {
        console.warn('health check failed (API may be cold-starting on Render free tier):', err);
      }
    },
    hire() {
      console.log(
        '%cWe built the escrow so agents never need a human in the loop. If you\'re building agent-to-agent payments, open an issue or PR — we read them.',
        'color:#f59e0b'
      );
    },
  };
}
