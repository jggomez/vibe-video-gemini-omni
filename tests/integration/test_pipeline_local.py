"""
Local integration test: verify all 4 agents fire in sequence.
Runs the ADK pipeline directly (no WebSocket) and checks state after each agent.

Usage:
    uv run python tests/integration/test_pipeline_local.py

Expected output:
    creative_director  ✅ fired
    prompt_architect   ✅ fired
    video_producer     ✅ fired
    critic             ✅ fired
"""

import asyncio
import os
import sys
import logging

logging.basicConfig(level=logging.WARNING)  # suppress ADK noise

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from app.constants import user_api_key_var
from app.agent import root_agent, app
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai.types import Content, Part


PROMPT = "Target duration 5s: A serene mountain lake at golden hour, cinematic wide shot, warm golden light reflecting on calm water, majestic peaks in background"

EXPECTED_AGENTS = ["creative_director", "prompt_architect", "video_producer", "critic"]


async def run_test():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set in .env — cannot run test")
        sys.exit(1)

    print(f"✅ API key found ({api_key[:8]}...)")
    print(f"🔧 root_agent type: {type(root_agent).__name__}")
    print(f"🔧 sub_agents: {[a.name for a in root_agent.sub_agents]}")
    print()

    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()

    session = await session_service.create_session(
        app_name="app",
        user_id="test_user",
        state={
            "current_turn": 1,
            # Empty strings (not None) so ADK {var} template injection works
            "creative_director_review": "",
            "optimized_prompt": "",
            "production_result": "",
            "critic_review": "",
        },
    )

    runner = Runner(
        agent=root_agent,
        app_name="app",
        session_service=session_service,
        artifact_service=artifact_service,
    )

    token = user_api_key_var.set(api_key)

    seen_authors = []
    events_log = []

    print(f"🚀 Running pipeline with prompt: '{PROMPT[:60]}...'")
    print("─" * 60)

    try:
        async with __import__("contextlib").aclosing(
            runner.run_async(
                user_id="test_user",
                session_id=session.id,
                new_message=Content(parts=[Part(text=PROMPT)], role="user"),
            )
        ) as gen:
            async for event in gen:
                author = getattr(event, "author", None) or "pipeline"
                is_final = event.is_final_response()
                has_content = bool(event.content and event.content.parts)

                events_log.append({
                    "author": author,
                    "is_final": is_final,
                    "has_content": has_content,
                })

                if author not in seen_authors and author not in ("pipeline", "vibe_video_pipeline", "prompt_alignment_loop"):
                    seen_authors.append(author)
                    print(f"  📡 Agent fired: {author} (is_final={is_final})")

                # Show any text content
                if has_content and is_final and author in EXPECTED_AGENTS:
                    text = event.content.parts[0].text or ""
                    if text:
                        print(f"     ↳ Output preview: {text[:80].strip()}")

    except Exception as e:
        print(f"❌ Pipeline error: {e}")
        import traceback; traceback.print_exc()
    finally:
        user_api_key_var.reset(token)

    print()
    print("─" * 60)
    print("📊 RESULTS")
    print("─" * 60)

    all_pass = True
    for expected in EXPECTED_AGENTS:
        fired = expected in seen_authors
        status = "✅ fired" if fired else "❌ NOT FIRED"
        print(f"  {expected:<22} {status}")
        if not fired:
            all_pass = False

    print()

    # Check final state
    final_session = await session_service.get_session(
        app_name="app", user_id="test_user", session_id=session.id
    )
    state = final_session.state if final_session else {}

    print("📦 Final State Keys:")
    for key in ["creative_director_review", "optimized_prompt", "production_result", "critic_review", "last_artifact_name"]:
        val = state.get(key)
        status = "✅" if val else "❌ missing"
        preview = ""
        if isinstance(val, str):
            preview = f" → '{val[:60]}'"
        elif isinstance(val, dict):
            preview = f" → {list(val.keys())}"
        print(f"  {key:<30} {status}{preview}")

    print()
    print(f"Total ADK events received: {len(events_log)}")
    print(f"Unique agents seen: {seen_authors}")
    print()

    if all_pass:
        print("🎉 ALL AGENTS FIRED — PIPELINE FIX CONFIRMED ✅")
        return 0
    else:
        missing = [a for a in EXPECTED_AGENTS if a not in seen_authors]
        print(f"💥 PIPELINE INCOMPLETE — Missing: {missing}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_test())
    sys.exit(exit_code)
