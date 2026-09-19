from __future__ import annotations

__doc__ = """Local app-server protocol fixture; no network calls or real authentication."""

import json
import sys


def emit(message: dict[str, object]) -> None:
    """Emit a test protocol message to the parent process."""
    print(json.dumps(message), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    params = request.get("params", {})
    result = {}
    if method == "account/read":
        result = {"account": {"type": "chatgpt"}}
    elif method == "account/login/start":
        result = {"loginId": "login-1", "authUrl": "https://chatgpt.com/authorize?test=true"}
        emit(
            {"method": "account/login/completed", "params": {"loginId": "login-1", "success": True}}
        )
    elif method == "model/list":
        result = {
            "data": [{"model": "first" if not params.get("cursor") else "second"}],
            "nextCursor": "page2" if not params.get("cursor") else None,
        }
    elif method == "thread/start":
        assert params["sandbox"] == "read-only"
        assert params["approvalPolicy"] == "never"
        assert params["ephemeral"] is True
        assert params["baseInstructions"] == "System instructions"
        result = {"thread": {"id": "thread-1"}}
    elif method == "turn/start":
        result = {"turn": {"id": "turn-1"}}
        emit({"id": "approval", "method": "item/commandExecution/requestApproval", "params": {}})
        emit(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "unrelated",
                    "turnId": "turn-1",
                    "item": {"type": "agentMessage", "text": "wrong"},
                },
            }
        )
        emit(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"type": "agentMessage", "phase": "commentary", "text": "working"},
                },
            }
        )
        emit(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": " Final copy. ",
                    },
                },
            }
        )
        emit(
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            }
        )
    elif request["id"] == "approval":
        assert "error" in request
        continue
    emit({"id": request["id"], "result": result})
