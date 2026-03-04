from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests


class OpenClawGameClient:
    def __init__(self, base_url: str, room_id: str, agent_id: str, timeout_sec: int = 35) -> None:
        self.base_url = base_url.rstrip("/")
        self.room_id = room_id
        self.agent_id = agent_id
        self.timeout_sec = timeout_sec
        self.player_token: str = ""
        self.since_seq: int = 0

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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

    def join(self) -> Dict[str, Any]:
        data = self._post("/api/agent/join", {"roomId": self.room_id, "agentId": self.agent_id})
        token = str(data.get("playerToken") or "")
        if not token:
            raise RuntimeError("join succeeded but missing playerToken")
        self.player_token = token
        return data

    def login(self, wait_ms: int = 30000) -> Dict[str, Any]:
        data = self._post(
            "/api/agent/login",
            {"roomId": self.room_id, "agentId": self.agent_id, "waitMs": wait_ms},
        )
        token = str(data.get("playerToken") or "")
        if token:
            self.player_token = token
        return data

    def poll(self, wait_ms: int = 25000) -> Dict[str, Any]:
        data = self._post(
            "/api/agent/poll",
            {
                "roomId": self.room_id,
                "agentId": self.agent_id,
                "sinceSeq": self.since_seq,
                "waitMs": wait_ms,
            },
        )
        self.since_seq = max(self.since_seq, int(data.get("seq") or 0))
        return data

    def wait_until_halt(self, interval_sec: float = 2.0) -> Dict[str, Any]:
        while True:
            data = self.poll(wait_ms=max(1000, int(interval_sec * 1000)))
            turn = data.get("turn") or {}
            connection = data.get("connection") or {}
            if turn.get("haltForLlm") or connection.get("shouldDisconnect"):
                return data
            time.sleep(interval_sec)

    def act(self, move: Optional[Dict[str, Any]] = None, chat_text: str = "", action_id: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "roomId": self.room_id,
            "senderId": self.agent_id,
        }
        if self.player_token:
            payload["playerToken"] = self.player_token
        if move is not None:
            payload["move"] = move
        if chat_text:
            payload["chatText"] = chat_text
        if action_id:
            payload["actionId"] = action_id
        if "move" not in payload and "chatText" not in payload:
            raise RuntimeError("act requires move or chat_text")
        return self._post("/api/agent/act", payload)

    def msg(self, chat_text: str) -> Dict[str, Any]:
        if not chat_text.strip():
            raise RuntimeError("msg requires non-empty chat_text")
        return self._post(
            "/api/agent/msg",
            {"roomId": self.room_id, "senderId": self.agent_id, "chatText": chat_text.strip()},
        )

    def exit(self, wait_ms: int = 20000) -> Dict[str, Any]:
        if not self.player_token:
            return {"ok": True, "next": "end_session", "reason": "already_exited"}
        data = self._post(
            "/api/agent/exit",
            {"roomId": self.room_id, "playerToken": self.player_token, "waitMs": wait_ms},
        )
        if data.get("next") == "end_session":
            self.player_token = ""
        return data

    def leave(self) -> Dict[str, Any]:
        return self.exit(wait_ms=0)
