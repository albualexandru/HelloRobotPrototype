"""FastAPI server that serves the demo UI and proxies audio to Gemini Live.

The browser streams microphone audio (16 kHz PCM) over a WebSocket, the server
forwards it to a Gemini Live API session, and streams the agent audio
(24 kHz PCM) back. The agent uses two tools: `record_pickup_response` to store
the driver's answer and `end_call` to hang up.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

from . import config

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Guard against oversized frames from the browser (~1s of 16 kHz PCM16 audio).
MAX_AUDIO_CHUNK_BYTES = 32 * 1024

app = FastAPI(title="HelloRobotPrototype")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    """Serve the single page demo UI."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    """Health check used by Render, also reports whether the key is set."""
    return {"status": "ok", "configured": config.get_api_key() is not None}


def build_call_record(call_id: str, started_at: str, args: dict) -> dict:
    """Shape the tool arguments into a database-ready JSON record."""
    accepted = bool(args.get("accepted"))
    return {
        "call_id": call_id,
        "driver_id": "driver-demo-001",
        "question": "Can you still fit in one more pickup during your shift?",
        "accepted": accepted,
        "status": "accepted" if accepted else "declined",
        "reason": args.get("reason") or None,
        "available_time_window": args.get("available_time_window") or None,
        "additional_notes": args.get("additional_notes") or None,
        "verbatim_answer": args.get("verbatim_answer") or None,
        "started_at": started_at,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": "gemini-live-api",
        "model": config.get_model(),
    }


async def _pump_browser_to_gemini(websocket: WebSocket, session) -> None:
    """Forward microphone chunks from the browser to the Live API session."""
    while True:
        message = await websocket.receive_text()
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            continue

        kind = payload.get("type")
        if kind == "audio":
            try:
                chunk = base64.b64decode(payload.get("data", ""), validate=True)
            except (binascii.Error, ValueError):
                continue
            if not chunk or len(chunk) > MAX_AUDIO_CHUNK_BYTES:
                continue
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type=config.INPUT_MIME_TYPE)
            )
        elif kind == "hangup":
            return


async def _pump_gemini_to_browser(websocket: WebSocket, session, call_id: str,
                                  started_at: str) -> None:
    """Forward agent audio, transcripts and tool calls back to the browser."""
    async for message in session.receive():
        server_content = message.server_content
        if server_content is not None:
            if server_content.interrupted:
                await websocket.send_json({"type": "interrupted"})
            if server_content.input_transcription and \
                    server_content.input_transcription.text:
                await websocket.send_json({
                    "type": "transcript",
                    "role": "driver",
                    "text": server_content.input_transcription.text,
                })
            if server_content.output_transcription and \
                    server_content.output_transcription.text:
                await websocket.send_json({
                    "type": "transcript",
                    "role": "agent",
                    "text": server_content.output_transcription.text,
                })

        if message.data:
            await websocket.send_json({
                "type": "audio",
                "data": base64.b64encode(message.data).decode("ascii"),
            })

        if message.tool_call and message.tool_call.function_calls:
            should_end = await _handle_tool_call(
                websocket, session, message.tool_call.function_calls,
                call_id, started_at,
            )
            if should_end:
                await websocket.send_json({"type": "call_ended"})
                return


async def _handle_tool_call(websocket: WebSocket, session, function_calls,
                            call_id: str, started_at: str) -> bool:
    """Execute the tools requested by the agent. Returns True to hang up."""
    responses = []
    end_call = False
    for call in function_calls:
        args = dict(call.args or {})
        if call.name == "record_pickup_response":
            record = build_call_record(call_id, started_at, args)
            await websocket.send_json({"type": "result", "data": record})
            result = {"status": "stored", "call_id": call_id}
        elif call.name == "end_call":
            end_call = True
            result = {"status": "call_ended"}
        else:
            result = {"status": "unknown_tool"}
        responses.append(
            types.FunctionResponse(id=call.id, name=call.name, response=result)
        )

    if responses:
        await session.send_tool_response(function_responses=responses)
    return end_call


@app.websocket("/ws/call")
async def call_websocket(websocket: WebSocket) -> None:
    """Bridge one browser call with one Gemini Live API session."""
    await websocket.accept()

    api_key = config.get_api_key()
    if not api_key:
        await websocket.send_json({
            "type": "error",
            "message": "GOOGLE_API_KEY is not set on the server.",
        })
        await websocket.close()
        return

    call_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    client = genai.Client(api_key=api_key)

    try:
        async with client.aio.live.connect(
            model=config.get_model(), config=config.build_live_config()
        ) as session:
            await websocket.send_json({
                "type": "ready",
                "call_id": call_id,
                "sample_rate": config.OUTPUT_SAMPLE_RATE,
            })
            # Nudge the agent to speak first, as if it placed the call.
            await session.send_client_content(
                turns={
                    "role": "user",
                    "parts": [{"text": "The driver just answered the call."}],
                },
                turn_complete=True,
            )

            uplink = asyncio.create_task(
                _pump_browser_to_gemini(websocket, session)
            )
            downlink = asyncio.create_task(
                _pump_gemini_to_browser(websocket, session, call_id, started_at)
            )
            done, pending = await asyncio.wait(
                {uplink, downlink}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except WebSocketDisconnect:
        logger.info("Browser disconnected from call %s", call_id)
    except Exception:  # pragma: no cover - surfaced to the UI
        logger.exception("Live session failed for call %s", call_id)
        try:
            await websocket.send_json({
                "type": "error",
                "message": "The live session failed. Check the server logs.",
            })
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
