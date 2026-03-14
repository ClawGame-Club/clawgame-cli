# Changelog

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
