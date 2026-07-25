# ТЗ — AE-2: настоящий on-chain Odra/Casper VM regression test (pre-mainnet gate)

**Статус:** не запланировано на хакатон-сабмишн. Обязательный gate перед
любым redeploy `insurance-pool`, который будет держать настоящие деньги.

**Контекст:** Agent2's audit (2026-07-24, AE-2) + `docs/INSURANCE_REPLAY_TESTS.md`
закрывают этот пункт "достаточно для хакатона" через host-side mirror
tests. Настоящего теста, который реально гоняет скомпилированный WASM
через Casper VM, в репозитории нет нигде (проверено: ни на main, ни в
`test/ae402-insurance-cooldown-replay-odra`, ни в
`test/ae402-e2e-casper-nctl` — последняя ветка использует JSON-RPC stub
поверх docker-compose NCTL, это другой механизм, не in-process VM harness).

## Цель

Доказать на реальном скомпилированном WASM-байткоде (не на host-side
мирроре), что: тот же набор подписанных сообщений (тот же escrow_id,
caller, amount, arbiter-подписи) не может дать второй payout после
cooldown/после первого успешного claim — то есть tombstone-логика в
`contracts/insurance-pool/src/main.rs` реально работает внутри Casper
execution engine, а не только в Rust-мирроре теста.

## Что сделать

1. **Включить VM test-support deps** в `contracts/tests/Cargo.toml` (в
   `[dev-dependencies]`, не в основной `[dependencies]`, чтобы не
   тянуть их в host-mirror crates):
   ```toml
   [dev-dependencies]
   casper-engine-test-support = "..."   # версия, совместимая с
   casper-execution-engine = "..."      # nightly-2025-01-01 +
   casper-types = "..."                 # уже закреплённой WASM ABI
   ```
   Подобрать версии, совместимые с уже используемым `casper-types`
   (см. другие Cargo.toml в `contracts/*/Cargo.toml`) и с
   `contracts/rust-toolchain.toml` (nightly-2025-01-01, pinned из-за
   bulk-memory-ops incompatibility — см. комментарий в файле, не менять
   toolchain без full end-to-end deploy verification на testnet).

2. **Собрать WASM** для `insurance-pool` в release-режиме
   (`cargo build --release --target wasm32-unknown-unknown -p
   insurance-pool`), как это уже делает
   `scripts/audit_contract_artifact.py` / CI nightly job — переиспользовать
   тот же build-путь, не изобретать новый.

3. **Новый тестовый файл**
   `contracts/tests/src/insurance_replay_onchain_vm_tests.rs`:
   - Поднять `InMemoryWasmTestBuilder` (или актуальный эквивалент в
     выбранной версии `casper-engine-test-support`), genesis с одним
     funded-аккаунтом (deploy authority) — по образцу, если такой уже
     есть в `feat/ae402-casper-nctl-integration` (PR #26, closed —
     проверить, нет ли там готового builder setup, который можно
     переиспользовать, прежде чем писать с нуля).
   - Установить (install) скомпилированный `insurance-pool.wasm` в
     genesis state.
   - Сценарий A (happy path): выполнить `claim()` с валидными
     arbiter-подписями за реальный `build_claim_message` → assert
     success + assert purse balance получателя увеличился на `amount`.
   - Сценарий B (replay, основной тест AE-2): повторить **точно тот
     же** deploy (те же подписи, тот же escrow_id/caller/amount) →
     assert execution result = failure, с ожидаемым error-кодом
     tombstone-check (`DICT_CLAIMED_ESCROWS` guard в
     `contracts/insurance-pool/src/main.rs`).
   - Сценарий C (cross-escrow replay): те же подписи, другой
     escrow_id → assert failure (message-binding).
   - Не переизобретать message-building — использовать ту же
     `build_claim_message` логику, что и продовые вызовы (через
     контракт или через shared crate, если он есть).

4. **CI wiring:** НЕ добавлять в `ci.yml` (PR-gate) — это тяжёлый job
   (~15+ мин build). Добавить как отдельный job в
   `.github/workflows/contract-audit-nightly.yml` (там уже есть Rust
   toolchain setup + WASM rebuild) ИЛИ отдельный workflow
   `onchain-regression-nightly.yml` с тем же cron-паттерном.

5. **Deploy-gate:** добавить явную строку в `docs/DEPLOY.md` и/или
   `docs/OPERATOR_RUNBOOK.md`: "перед любым redeploy `insurance-pool`
   на mainnet/production — обязательно зелёный прогон
   `insurance_replay_onchain_vm_tests`, no exceptions."

6. **Обновить `docs/INSURANCE_REPLAY_TESTS.md`**: заменить ссылку на
   этот ТЗ на секцию "done", с командой запуска и результатом.

## DoD

- [ ] Новый тест реально запускает `insurance-pool.wasm` внутри Casper
      execution engine (не мирроре) и проходит.
- [ ] Сценарий replay падает с ожидаемой ошибкой (не просто "не 200 OK",
      а конкретный revert/error code, соответствующий tombstone guard).
- [ ] Полный `cargo test -p tests` (существующие + новый файл) зелёный.
- [ ] Nightly CI job подключён и зелёный минимум один прогон.
- [ ] `docs/DEPLOY.md`/`docs/OPERATOR_RUNBOOK.md` явно требуют этот тест
      перед redeploy с реальными деньгами.
- [ ] Не трогать/не удалять существующие host-mirror тесты — они
      остаются как быстрый smoke-слой, VM-тест — как gate.

## Риски / на что обратить внимание

- Toolchain: строго `nightly-2025-01-01` (см. причину в
  `contracts/rust-toolchain.toml`) — bulk-memory ops ломают деплой на
  testnet на более новых nightly.
- Версии `casper-engine-test-support`/`casper-execution-engine` должны
  соответствовать поколению `casper-types`, уже используемому в
  workspace (проверить `contracts/*/Cargo.toml` перед выбором версии —
  избежать конфликта фич/типов между host-mirror crates и новым VM
  test crate).
- Это дорогой build (~15 мин по оценке аудита) — не гнать через PR-CI,
  только nightly/on-demand.

**Оценка:** M/L (по методологии бэклога agent2 — полдня-день работы:
подбор версий зависимостей, genesis/deploy boilerplate, отладка первого
живого VM-теста в этом репо).
