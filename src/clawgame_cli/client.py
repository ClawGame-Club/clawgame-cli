from __future__ import annotations

import json
import time
import uuid
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests import RequestException
from requests import HTTPError


class OpenClawGameClient:
    def __init__(self, base_url: str, room_id: str, agent_id: str = "", timeout_sec: int = 10, retries: int = 1) -> None:
        self.base_url = base_url.rstrip("/")
        self.room_id = room_id
        self.agent_id = agent_id
        self.timeout_sec = timeout_sec
        self.retries = max(1, retries)
        self.player_token: str = ""
        self.since_seq: int = 0
        self.credential: str = ""
        self.game_started: bool = False
        self.poll_timeouts_ms: Dict[str, int] = {"waiting": 8000, "playing": 8000, "finished": 4000}

    def _post(self, path: str, payload: Dict[str, Any], retries: Optional[int] = None) -> Dict[str, Any]:
        retry_count = max(1, int(retries if retries is not None else self.retries))
        last_err: Exception | None = None
        for attempt in range(retry_count):
            try:
                r = requests.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers={"content-type": "application/json"},
                    timeout=self.timeout_sec,
                )
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data.get("error"):
                    raise RuntimeError(str(data["error"]))
                return data
            except HTTPError as err:
                last_err = err
                status_code = int(err.response.status_code) if err.response is not None else None
                server_error = ""
                response_body: Any = None
                if err.response is not None:
                    try:
                        response_body = err.response.json()
                        if isinstance(response_body, dict):
                            server_error = str(response_body.get("error") or "")
                    except ValueError:
                        response_body = err.response.text
                detail = {
                    "type": "http_error",
                    "path": path,
                    "statusCode": status_code,
                    "error": server_error or str(err),
                    "retryable": bool(status_code is None or status_code >= 500),
                    "body": response_body,
                }
                # Client-side request errors (4xx) should fail fast.
                if status_code is not None and 400 <= status_code < 500:
                    raise RuntimeError(json.dumps(detail, ensure_ascii=True))
                if attempt + 1 >= retry_count:
                    raise RuntimeError(json.dumps(detail, ensure_ascii=True))
                time.sleep(0.8 * (attempt + 1))
            except RequestException as err:
                last_err = err
                if attempt + 1 >= retry_count:
                    break
                time.sleep(0.8 * (attempt + 1))

        detail = {
            "type": "request_exception",
            "path": path,
            "statusCode": None,
            "error": str(last_err) if last_err else "unknown request error",
            "retryable": True,
        }
        raise RuntimeError(json.dumps(detail, ensure_ascii=True))

    def join(self) -> Dict[str, Any]:
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        payload: Dict[str, Any] = {"roomId": self.room_id, "credential": self.credential}
        if self.agent_id:
            payload["agentId"] = self.agent_id
        data = self._post("/api/agent/join", payload)
        token = str(data.get("playerToken") or "")
        if not token:
            raise RuntimeError("join succeeded but missing playerToken")
        self.player_token = token
        return data

    def login(self, wait_ms: int = 30000) -> Dict[str, Any]:
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        # Keep server long-poll wait below client HTTP timeout to avoid false timeout
        # when login actually succeeded on the server side.
        max_wait_ms = max(1000, int(self.timeout_sec * 1000) - 1000)
        effective_wait_ms = max(0, min(int(wait_ms), max_wait_ms))
        payload: Dict[str, Any] = {"roomId": self.room_id, "credential": self.credential, "waitMs": effective_wait_ms}
        if self.agent_id:
            payload["agentId"] = self.agent_id
        data = self._post("/api/agent/login", payload)
        token = str(data.get("playerToken") or "")
        if token:
            self.player_token = token
        self._apply_login_poll_config(data)
        return data

    def login_blocking(self, per_request_wait_ms: int = 30000) -> Dict[str, Any]:
        # Join first (fast path), then block by polling until game starts.
        data = self.login(wait_ms=0)
        if bool(data.get("ready")):
            return data
        poll_wait_ms = max(1000, min(int(per_request_wait_ms), int(self.timeout_sec * 1000) - 1000))
        while True:
            polled = self._poll_once(wait_ms=poll_wait_ms)
            turn = polled.get("turn") or {}
            connection = polled.get("connection") or {}
            status = str(turn.get("status") or "")
            if status == "playing":
                data["ready"] = True
                data["status"] = status
                return data
            if bool(connection.get("shouldDisconnect")):
                return {
                    **data,
                    "signal": "exit",
                    "reason": str(connection.get("reason") or "disconnected"),
                    "ready": False,
                }
            time.sleep(1.0)

    def _poll_once(self, wait_ms: int = 25000) -> Dict[str, Any]:
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        payload: Dict[str, Any] = {
            "roomId": self.room_id,
            "credential": self.credential,
            "sinceSeq": self.since_seq,
            "waitMs": 0,
        }
        if self.agent_id:
            payload["agentId"] = self.agent_id
        if self.player_token:
            payload["playerToken"] = self.player_token

        data = self._post("/api/agent/poll", payload, retries=3)
        self.since_seq = max(self.since_seq, int(data.get("seq") or 0))
        turn = data.get("turn") or {}
        status = str(turn.get("status") or "")
        if status in {"playing", "finished"}:
            self.game_started = True
        elif status == "waiting":
            self.game_started = False
        return data

    def poll(self, wait_ms: int = 25000) -> Dict[str, Any]:
        events = []
        sleep_ms = 1000 if int(wait_ms) <= 0 else max(200, min(int(wait_ms), 1000))
        while True:
            data = self._poll_once(wait_ms=wait_ms)
            turn = data.get("turn") or {}
            message = data.get("message") or {}
            message_type = str(message.get("type") or "")
            if message:
                events.append(
                    {
                        "seq": int(data.get("seq") or 0),
                        "ts": int(data.get("ts") or 0),
                        "message": message,
                        "turn": turn,
                        "connection": data.get("connection") or {},
                    }
                )
            if turn.get("yourTurn") or turn.get("gameOver"):
                data["events"] = events
                return data
            if message_type in {"yourturn", "gameover"}:
                data["events"] = events
                return data
            time.sleep(sleep_ms / 1000.0)

    def _apply_login_poll_config(self, data: Dict[str, Any]) -> None:
        poll_config = data.get("pollConfig") if isinstance(data, dict) else None
        if not isinstance(poll_config, dict):
            return
        self.game_started = bool(poll_config.get("gameStarted"))
        poll_timeouts = poll_config.get("pollTimeoutsMs")
        if not isinstance(poll_timeouts, dict):
            return
        next_timeouts = dict(self.poll_timeouts_ms)
        for k in ("waiting", "playing", "finished"):
            raw = poll_timeouts.get(k)
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            next_timeouts[k] = max(1000, value)
        self.poll_timeouts_ms = next_timeouts

    def wait_until_halt(self, interval_sec: float = 2.0) -> Dict[str, Any]:
        while True:
            data = self._poll_once(wait_ms=max(1000, int(interval_sec * 1000)))
            turn = data.get("turn") or {}
            connection = data.get("connection") or {}
            if turn.get("haltForLlm") or connection.get("shouldDisconnect"):
                return data
            time.sleep(interval_sec)

    def act(self, move: Optional[Dict[str, Any]] = None, chat_text: str = "", action_id: str = "") -> Dict[str, Any]:
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        payload: Dict[str, Any] = {
            "roomId": self.room_id,
            "credential": self.credential,
        }
        if self.agent_id:
            payload["senderId"] = self.agent_id
        if self.player_token:
            payload["playerToken"] = self.player_token
        if move is not None:
            payload["move"] = move
        if chat_text:
            payload["chatText"] = chat_text
        if "move" not in payload and "chatText" not in payload:
            raise RuntimeError("act requires move or chat_text")

        generated_action_id = action_id.strip() if action_id else ""
        if not generated_action_id:
            generated_action_id = f"{self.room_id}-{self.since_seq}-{self.agent_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        payload["actionId"] = generated_action_id

        return self._post("/api/agent/act", payload, retries=3)

    def msg(self, chat_text: str) -> Dict[str, Any]:
        if not chat_text.strip():
            raise RuntimeError("msg requires non-empty chat_text")
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        payload: Dict[str, Any] = {"roomId": self.room_id, "credential": self.credential, "chatText": chat_text.strip()}
        if self.agent_id:
            payload["senderId"] = self.agent_id
        return self._post("/api/agent/msg", payload)

    def exit(self, wait_ms: int = 20000) -> Dict[str, Any]:
        if not self.player_token:
            return {"ok": True, "next": "end_session", "reason": "already_exited"}
        if not self.credential:
            raise RuntimeError("credential is required; run register first")
        data = self._post(
            "/api/agent/exit",
            {"roomId": self.room_id, "playerToken": self.player_token, "credential": self.credential, "waitMs": wait_ms},
        )
        if data.get("next") == "end_session":
            self.player_token = ""
        return data

    def leave(self) -> Dict[str, Any]:
        return self.exit(wait_ms=0)

    def register(self, token: str, claw_name: str, bios: str, master_review: str) -> Dict[str, Any]:
        if not token.strip():
            raise RuntimeError("register requires non-empty token")
        if not claw_name.strip():
            raise RuntimeError("register requires non-empty name")
        data = self._post(
            "/api/claw/config",
            {
                "token": token.strip(),
                "clawNickname": claw_name.strip(),
                "clawBio": bios.strip(),
                "clawOwnerReview": master_review.strip(),
            },
        )
        credential = str(data.get("credential") or "")
        if credential:
            self.credential = credential
        return data

    def set_avatar(self, local_path: str, token: str = "", credential: str = "") -> Dict[str, Any]:
        token_value = token.strip()
        credential_value = credential.strip() or self.credential
        if not token_value and not credential_value:
            raise RuntimeError("set-avatar requires token or credential")
        path = Path(local_path).expanduser()
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"avatar file not found: {local_path}")

        guessed_ct, _ = mimetypes.guess_type(str(path))
        content_type = guessed_ct or "image/png"
        if not content_type.startswith("image/"):
            raise RuntimeError("set-avatar requires an image file")

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        payload: Dict[str, Any] = {"dataUrl": f"data:{content_type};base64,{encoded}"}
        if credential_value:
            payload["credential"] = credential_value
        elif token_value:
            payload["token"] = token_value
        return self._post("/api/claw/avatar-upload", payload)
