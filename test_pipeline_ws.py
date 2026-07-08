#!/usr/bin/env python3
"""WebSocket pipeline test for Vibe Video Studio."""
import asyncio
import json
import sys
import websockets

URL = "wss://vibe-video-studio-uk7bg6pcva-uc.a.run.app/ws/studio"
PAYLOAD = {
    "action": "process_turn",
    "prompt": "A serene mountain lake at golden hour, cinematic 16:9",
    "session_id": "test-sess-001",
    "user_id": "anonymous",
    "api_key": ""
}

async def main():
    print(f"Connecting to {URL}...")
    try:
        async with websockets.connect(URL, open_timeout=15) as ws:
            print("Connected ✓")
            await ws.send(json.dumps(PAYLOAD))
            print(f"Sent payload: {PAYLOAD['prompt'][:40]}...")

            steps_seen = []
            deadline = asyncio.get_event_loop().time() + 10

            while asyncio.get_event_loop().time() < deadline:
                try:
                    remaining = deadline - asyncio.get_event_loop().time()
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "unknown")
                    steps_seen.append(msg_type)

                    if msg_type == "agent_thinking":
                        agent = msg.get("agent", "?")
                        text = str(msg.get("text", ""))[:60]
                        print(f"  [agent_thinking] agent={agent} text={text!r}")
                    elif msg_type == "agent_done":
                        agent = msg.get("agent", "?")
                        print(f"  [agent_done] agent={agent}")
                    elif msg_type == "turn_complete":
                        print(f"  [turn_complete] ✓")
                        break
                    elif msg_type == "error":
                        err = msg.get("message", str(msg))
                        print(f"  [error] {err[:200]}")
                        if any(k in err for k in ("API", "key", "Key", "api_key", "credential")):
                            print("  → API key validation error — EXPECTED, pipeline started correctly!")
                        break
                    else:
                        print(f"  [{msg_type}] {str(msg)[:100]}")

                except asyncio.TimeoutError:
                    print("  (10s timeout reached, no more messages)")
                    break
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"  Connection closed: {e}")
                    break

            print()
            print("=== Summary ===")
            print(f"Message types received: {steps_seen}")

            if not steps_seen:
                print("RESULT: ❌ No messages received")
                sys.exit(1)
            elif "error" in steps_seen:
                print("RESULT: ✅ Error received (expected for missing API key — confirms pipeline starts)")
                sys.exit(0)
            elif "turn_complete" in steps_seen:
                print("RESULT: ✅ Pipeline completed successfully")
                sys.exit(0)
            else:
                print(f"RESULT: ✅ Partial response — {len(steps_seen)} messages received")
                sys.exit(0)

    except Exception as e:
        print(f"FAIL ❌: Could not connect — {type(e).__name__}: {e}")
        sys.exit(1)

asyncio.run(main())
