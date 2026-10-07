"""Local-only deterministic Chat Completions simulator; never an accuracy test."""
import asyncio
import json
import os
import time
from fastapi import FastAPI, Request

app = FastAPI()
delay = float(os.getenv("SIMULATED_API_DELAY", "0.05"))
calls = 0


@app.post("/v1/chat/completions")
async def complete(request: Request):
    global calls
    body = await request.json()
    calls += 1
    await asyncio.sleep(delay)
    messages = str(body.get("messages", []))
    if "Sentence:" in messages:
        content = "active"
    elif body.get("response_format", {}).get("type") == "json_object":
        content = json.dumps({"field_mappings": {}})
    else:
        content = "Request for a court date"
    return {"id": f"simulation-{calls}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "simulated"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


@app.get("/metrics")
async def metrics():
    return {"calls": calls, "delay_seconds": delay}


@app.post("/config")
async def config(request: Request):
    global delay, calls
    body = await request.json()
    delay = max(0, min(10, float(body["delay_seconds"])))
    calls = 0
    return await metrics()
