from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests


class OpenClawGameClient:
    def __init__(self, base_url: str, room_id: str, agent_id: str, timeout_sec: int = 20) -> None:
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

    def poll(self) -> Dict[str, Any]:
        data = self._post(
            "/api/agent/poll",
            {
                "roomId": self.room_id,
                "agentId": self.agent_id,
                "sinceSeq": self.since_seq,
            },
        )
        self.since_seq = max(self.since_seq, int(data.get("seq") or 0))
        return data

    def wait_until_halt(self, interval_sec: float = 2.0) -> Dict[str, Any]:
        while True:
            data = self.poll()
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

    def leave(self) -> Dict[str, Any]:
        if not self.player_token:
            return {"ok": True, "skipped": True}
        data = self._post("/api/match/leave", {"roomId": self.room_id, "playerToken": self.player_token})
        self.player_token = ""
        return data
