# Minecraft Archive Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Integrate the archive's validated Minecraft security, control, backup, documentation, and packaging improvements without replacing the current AI code or locally built Fabric bridge.

**Architecture:** Keep the existing `bot.mod.dmcc` Gateway and `bot.mod.mc_backup` module boundaries. Adopt the archive's focused validation and provider behavior behind existing configuration interfaces; add root-level regression tests and a release `bridge/` directory whose jar is copied only from the current locally built bridge artifact.

**Tech Stack:** Python 3.11, discord.py, aiohttp, pytest, tmux shell helpers, Fabric/Gradle.

**Spec:** `docs/superpowers/specs/2026-10-06-mc-archive-integration-design.md`

## Global Constraints

- Do not commit plaintext secrets or `.env` values.
- Do not modify unrelated AI code or dependency constraints.
- Gateway host must remain `127.0.0.1`; Protocol frame ceiling is exactly `262144` bytes.
- The published jar must be built from `test_mod/minecraft-bridge`, never copied from the archive jar.
- Preserve Python 3.11 compatibility and the current module-loader lifecycle.

## Review Focus

- Oversized outbound and declared inbound frames must fail before sending or allocating payload memory (Task 1 regression tests).
- A stale response after request timeout must not disconnect a valid bridge (Task 1 regression tests).
- Configuration strings such as `"false"`, non-loopback hosts, missing secrets, and invalid control coordinates must fail during settings loading (Task 2 regression tests).
- Backup archives containing links, traversal paths, or corrupted persistence data must fail safely without overwriting the world (Task 3 regression tests).
- The packaged jar checksum must match the jar that Gradle produced from the local source tree (Task 4 release verification).

### Task 1: Harden DMCC protocol request boundaries

**Files:**
- Modify: `bot/mod/dmcc/protocol/codec.py`, `bot/mod/dmcc/gateway/connection.py`, `bot/mod/dmcc/gateway/server.py`, `bot/mod/dmcc/services/requests.py`
- Create: `tests/test_dmcc_regressions.py`

**Interfaces:**
- Produces: `encode_frame(envelope, max_frame_bytes=...)` rejects oversized frames; `RequestService.resolve()` accepts stale responses without protocol failure.

- [x] **Step 1: Write failing protocol and stale-response regression tests**

Cover a 128-byte outbound limit, a declared 129-byte inbound frame, and a response arriving after a 1 ms timeout.

- [x] **Step 2: Run focused tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dmcc_regressions.py -q`
Expected: FAIL because current protocol does not enforce all specified boundaries.

- [x] **Step 3: Enforce symmetric frame limits and safe stale-response handling**

Keep `ProtocolError` as the public failure type and ignore only responses whose request IDs are no longer pending.

- [x] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dmcc_regressions.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add bot/mod/dmcc tests/test_dmcc_regressions.py
git commit -m "fix: harden dmcc protocol boundaries"
```

### Task 2: Complete DMCC settings and control providers

**Files:**
- Modify: `bot/mod/dmcc/config.py`, `bot/mod/dmcc/extension.py`, `bot/mod/dmcc/providers/panel_http.py`, `bot/mod/dmcc/providers/control/mcsm.py`
- Create: `bot/mod/dmcc/providers/control/local_tmux.py`
- Modify: `tests/test_dmcc_regressions.py`

**Interfaces:**
- Consumes: `ControlProviderDefinition`, `DmccSettings`, `PanelHttpClient`.
- Produces: `LocalTmuxControlProvider(provider_id, server_dir, session_name, start_argv)` and validated `local_tmux` / MCSManager settings.

- [x] **Step 1: Write failing settings and provider contract tests**

Cover strict booleans, loopback/port validation, 262144-byte setting ceiling, empty bridge secrets, local tmux target mismatch, MCSManager coordinates, endpoint paths, and query API key authentication.

- [x] **Step 2: Run focused tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dmcc_regressions.py -q`
Expected: FAIL on missing validation/provider behavior.

- [x] **Step 3: Implement configuration validation and provider wiring**

Add the local tmux provider with fixed argv and server-directory cwd; make MCSManager use `/api/instance` plus protected GET action endpoints; select query authentication only for MCSManager.

- [x] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dmcc_regressions.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add bot/mod/dmcc tests/test_dmcc_regressions.py
git commit -m "feat: complete dmcc control providers"
```

### Task 3: Strengthen backup persistence and restore safety

**Files:**
- Modify: `bot/mod/mc_backup/providers/local_tar.py`, `bot/mod/mc_backup/providers/local_tmux.py`, `bot/mod/mc_backup/repositories/json_file.py`, `bot/mod/mc_backup/repositories/history.py`, `bot/mod/mc_backup/repositories/schedules.py`, `bot/mod/mc_backup/resources/local_control/start.sh`, `bot/mod/mc_backup/resources/local_control/stop.sh`
- Create: `tests/test_backup_regressions.py`

**Interfaces:**
- Produces: crash-safe `AtomicJsonFile`, strict persisted boolean parsing, safe artifact creation/restore, and tmux scripts that operate from `server_dir`.

- [x] **Step 1: Write failing backup safety regression tests**

Cover corrupt JSON quarantine, atomic round-trip, strict schedule/history/manifest booleans, an 80-character backup name, symlink rejection, and tmux start arguments including `server_dir`.

- [x] **Step 2: Run focused tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backup_regressions.py -q`
Expected: FAIL on current unsafe or non-atomic behavior.

- [x] **Step 3: Implement atomic persistence and archive/tmux safety**

Use same-directory temporary files with flush, fsync, and atomic replace; quarantine invalid JSON; validate tar members before publication and extraction; make scripts executable and wait for stop completion.

- [x] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backup_regressions.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add bot/mod/mc_backup tests/test_backup_regressions.py
git commit -m "fix: harden minecraft backup operations"
```

### Task 4: Publish deployment documentation and the locally built bridge

**Files:**
- Create: `docs/DMCC.md`, `docs/MC_BACKUP.md`, `bridge/README.md`, `bridge/SHA256SUMS`, `bridge/java_bridge.jar`
- Modify: `README.md`, `.gitignore`

**Interfaces:**
- Consumes: `test_mod/minecraft-bridge/dist/java_bridge.jar` after Gradle build.
- Produces: a documented bridge release artifact with a reproducible SHA-256.

- [x] **Step 1: Write failing release-integrity tests**

Assert that the bridge jar exists, its SHA-256 matches `bridge/SHA256SUMS`, documentation links resolve, and Python regression tests are not ignored.

- [x] **Step 2: Run focused release tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_release_integrity.py -q`
Expected: FAIL because the release package and documentation do not yet exist.

- [x] **Step 3: Build, package, and document the local bridge artifact**

Run Gradle from `test_mod/minecraft-bridge`, copy only its produced `dist/java_bridge.jar`, generate a matching checksum, and document the deployment settings without secrets.

- [x] **Step 4: Run focused and full verification**

Run: `.venv/bin/python -m pytest -q` and `./gradlew --no-daemon test remapJar`
Expected: all Bot tests pass and Gradle reports `BUILD SUCCESSFUL`.

- [x] **Step 5: Commit**

```bash
git add README.md .gitignore docs bridge tests/test_release_integrity.py
git commit -m "docs: publish minecraft deployment package"
```

### Task 5: Perform limited production smoke validation

**Files:**
- Modify: none

**Interfaces:**
- Consumes: the complete packaged modules, current `.env`, and channel `1556847086346178690`.
- Produces: an authenticated Discord connection, extension load/unload confirmation, and one test-channel status message.

- [x] **Step 1: Run the constrained live smoke script**

Load only `bot.mod.dmcc.extension` and `bot.mod.mc_backup.extension`, send one status message to the designated test channel, unload both extensions, and close the client.

- [x] **Step 2: Record exact outcome and commit only source/document changes if needed**

Expected: successful login, module lifecycle, Gateway startup, and message delivery; no token or secret is printed or committed.
