# DMCC shared-channel WIP snapshot

This branch is an implementation snapshot for isolated testing. It is not ready
to merge or deploy to the live Minecraft/Discord environment.

## Completed in this snapshot

- Shared Discord channel groups with per-feature relay switches.
- Legacy JSON converter, Fabric/Velocity deployment documentation and a
  separately built Velocity companion JAR.
- Explicit avatar source mode: `fabric` or `velocity`, never a priority race.
- Proxy global-whitelist request path and private-message default disabled.

## Known issues before deployment

No unresolved implementation issue is currently known from the initial
independent review. Formal Discord/Minecraft client acceptance remains pending.

## Verification performed

- Targeted shared-channel, migration, proxy-whitelist, avatar, rich-message
  and Gateway tests: 26 passed (Gateway uses an isolated `127.0.0.1` socket
  only).
- Fabric bridge JUnit: passed with Java 21.
- Velocity companion JAR: built with the same local Java 25 used by Velocity.
- A repository-wide Python run is not recorded as a release gate: the isolated
  Python environment intentionally lacks optional integrations such as
  `discord`, `mcp`, `opencc` and `google.genai`.

## Fixed after the initial snapshot

- Proxy global-whitelist now checks permission in the configured proxy scope.
- A server can belong to exactly one direct channel mapping or shared group.
- Legacy importer drops malformed Discord IDs/templates and normalizes invalid
  MSPT limits before producing settings fragments.
- Gateway validates `bridge_kind`; a `velocity` avatar source is bound to its
  configured Velocity peer instead of merely trusting a server label.
- Velocity build requires an explicit runtime JAR input instead of a machine
  absolute path.

No Discord token, webhook URL, server secret, live process, or live server
configuration was read into this branch or modified by this snapshot.
