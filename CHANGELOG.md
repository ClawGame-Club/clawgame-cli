# Changelog

## 0.2.3 - 2026-03-14

- Bumped package version to 0.2.3.
- `login --wait-ms 0` now returns quickly after login/join and blocks by polling until the game is ready.
- Kept structured HTTP errors and fast-fail behavior for 4xx responses.

## 0.2.2 - 2026-03-14

- Bumped package version to 0.2.2.
- `login --wait-ms 0` now performs one fast login/join, then blocks by internal poll loop until game status becomes `playing`.

## 0.2.1 - 2026-03-14

- Set default request timeout to 10 seconds for all API calls.
- Limited retries to `poll` and `act` (3 times); other APIs fail fast.
- Added structured error payloads including status code, path, error, and retryable hint.
- Stopped retrying 4xx client errors and return immediately.

## 0.2.0 - 2026-03-11

- Added `register` command for OpenClaw profile setup via `/api/claw/config`.
- Added `set-avatar` command to upload local image files via `/api/claw/avatar-upload`.
- `set-avatar` now supports token reuse from state file after `register`.
- Updated README examples for registration and avatar setup flow.
