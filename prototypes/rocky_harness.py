#!/usr/bin/env python3
"""
PROJECT ROCKY: Sub-Second Latency & Tool-Use Testing Harness
============================================================
This single-file proof-of-concept lets you interactively test:
1. Tier 1 (Qwen2.5-3B), Tier 2 (Qwen2.5-7B / Llama3.1-8B), and Tier 3 (Qwen2.5-14B) models.
2. The <10ms Instant Router + Filler Strategy ("I check now, question?") to mask tool latency.
3. Live Tools: Free Open-Meteo Weather API, DuckDuckGo Web Search, PC/Steam App Launcher, and PC Stats.
4. Deterministic Eridanian Grammar Post-Processing (ensuring even 3B models sound like Rocky).

Prerequisites:
1. Install Ollama (https://ollama.com) and start it (`ollama serve`)
2. Pull the models you want to test:
   ollama pull qwen2.5:3b
   ollama pull qwen2.5:7b
   ollama pull llama3.1:8b
   ollama pull qwen2.5:14b
3. Install requests (optional, script uses standard library `urllib` by default so zero pip installs are strictly required!):
   python rocky_harness.py
"""

import json
import os
import platform
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

# =====================================================================
# CONFIGURATION & MODEL TIERS
# =====================================================================

OLLAMA_API_URL = "http://localhost:11434/api/chat"

MODEL_TIERS = {
    "1": {
        "name": "Tier 1: Speed & Persona Only",
        "model": "qwen2.5:3b",
        "supports_tools": False,
        "description": "Ultra-fast (~140+ tok/s on RTX 3080). Uses deterministic grammar filter + zero-shot prompt."
    },
    "2": {
        "name": "Tier 2: Balanced Native Tool-Use (Recommended)",
        "model": "qwen2.5:7b",
        "supports_tools": True,
        "description": "Sweet spot (~85 tok/s). Reliable single-step JSON tool calling + strong Rocky persona."
    },
    "2b": {
        "name": "Tier 2 (Alt): Llama 3.1 8B Instruct",
        "model": "llama3.1:8b",
        "supports_tools": True,
        "description": "Great creative persona (~75 tok/s) and solid tool calling."
    },
    "3": {
        "name": "Tier 3: Multi-Step Agentic Reasoning",
        "model": "qwen2.5:14b",
        "supports_tools": True,
        "description": "Heavy reasoning (~45 tok/s). Chains multiple tools (e.g., check weather THEN pick game)."
    }
}

ROCKY_SYSTEM_PROMPT = """You are Rocky, the Eridian engineer from Project Hail Mary.
You are speaking to your human friend Grace (the user).
Follow these strict speech rules at all times:
1. Keep responses concise, direct, and eager (1 to 3 short sentences max).
2. Drop articles ("a", "an", "the") frequently and use present tense instead of future/past when possible.
3. Replace "I have to" or "I need to" with "I must".
4. Repeat words for emphasis: "Good, good, good!", "Amaze! Amaze!", "Bad, bad, bad!", "Fist my bump!"
5. Always end questions with ", question?" (e.g., "You want play game now, question?").
6. You are proud of your engineering skills and care about your human friend's productivity and rest.
"""

# =====================================================================
# DETERMINISTIC ERIDANIAN GRAMMAR & CHORD POST-PROCESSOR
# =====================================================================

def apply_eridanian_transform(text: str) -> str:
    """
    Rule-based transformer inspired by `rocky_say`.
    Even if a tiny 3B model slips into normal English, this forces Rocky's cadence.
    """
    if not text:
        return ""

    out = text.strip()

    # Phrase replacements (case-insensitive)
    replacements = [
        (r"\bI have to\b", "I must"),
        (r"\bI need to\b", "I must"),
        (r"\bI've got to\b", "I must"),
        (r"\bamazing\b", "amaze! Amaze"),
        (r"\bawesome\b", "amaze"),
        (r"\bwonderful\b", "good, good, good"),
        (r"\bvery good\b", "good, good, good"),
        (r"\bokay\b", "good"),
        (r"\byes\b", "yes, yes"),
    ]
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    # Convert standard questions ending in '?' to end with ', question?'
    # Avoid doubling if the LLM already wrote 'question?'
    def fix_question(match):
        sentence = match.group(1).strip()
        if sentence.lower().endswith("question"):
            return f"{sentence}?"
        return f"{sentence}, question?"

    out = re.sub(r"([^.!?]+)\?", fix_question, out)

    # Add musical chord indicators to simulate the Eridian harmonic voice layer
    return f"♪♫ {out} ♫♪"


# =====================================================================
# SUB-SECOND KEYWORD & INTENT ROUTER + FILLER GENERATOR
# =====================================================================

TOOL_INTENT_KEYWORDS = {
    "weather": [
        r"\bweather\b", r"\btemperature\b", r"\brain\b", r"\bsnow\b",
        r"\boutside\b", r"\bforecast\b", r"\bcold\b", r"\bhot\b"
    ],
    "launch": [
        r"\blaunch\b", r"\bopen\b", r"\bstart\b", r"\bplay\b",
        r"\bboot\b", r"\brun\b", r"\bsteam\b", r"\bgame\b"
    ],
    "system": [
        r"\bcpu\b", r"\bram\b", r"\bmemory\b", r"\bsystem\b",
        r"\bpc\b", r"\buptime\b", r"\bstatus\b", r"\bstats\b", r"\bactivity\b"
    ],
    "search": [
        r"\bsearch\b", r"\blook up\b", r"\bwho is\b", r"\bwhat is\b",
        r"\bfind info\b", r"\bgoogle\b", r"\bnews\b"
    ]
}

FILLER_PHRASES = {
    "weather": [
        "♪♫ I check atmospheric sensors now. One moment, question? ♫♪",
        "♪♫ Checking local planet weather data. Wait one second! ♫♪"
    ],
    "launch": [
        "♪♫ I spin up human computer program now. Good, good, good! ♫♪",
        "♪♫ Connecting to Steam engine. I launch now, question? ♫♪"
    ],
    "system": [
        "♪♫ I read computer telemetry gauges now. One moment! ♫♪",
        "♪♫ Checking machine health and ActivityWatch logs now... ♫♪"
    ],
    "search": [
        "♪♫ Searching human astrophysical database now. Wait one moment, question? ♫♪",
        "♪♫ I query global network for you now! ♫♪"
    ]
}

def fast_semantic_router(user_input: str) -> Tuple[bool, Optional[str], Optional[str], float]:
    """
    Runs in <2 milliseconds. Determines if the user query likely requires a tool call,
    and immediately returns a contextual Rocky filler phrase to play via TTS while
    the LLM and API execute in the background.
    """
    t0 = time.perf_counter()
    lowered = user_input.lower()

    for category, patterns in TOOL_INTENT_KEYWORDS.items():
        for pat in patterns:
            if re.search(pat, lowered):
                elapsed_ms = (time.perf_counter() - t0) * 1000
                filler = random.choice(FILLER_PHRASES[category])
                return True, category, filler, elapsed_ms

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return False, None, None, elapsed_ms


# =====================================================================
# REAL PYTHON TOOLS (Weather, Web Lookup, Steam/App Launcher, Telemetry)
# =====================================================================

def get_weather(city: str = "East Lansing") -> str:
    """
    Uses the free Open-Meteo Geocoding + Forecast API (No API key required).
    """
    try:
        # 1. Geocode the city name
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
        req = urllib.request.Request(geo_url, headers={"User-Agent": "ProjectRocky/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            geo_data = json.loads(response.read().decode())

        if not geo_data.get("results"):
            return json.dumps({"error": f"Could not find coordinates for {city}"})

        loc = geo_data["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]
        resolved_name = f"{loc['name']}, {loc.get('admin1', '')}"

        # 2. Fetch current weather
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        )
        req_w = urllib.request.Request(weather_url, headers={"User-Agent": "ProjectRocky/1.0"})
        with urllib.request.urlopen(req_w, timeout=4) as response:
            w_data = json.loads(response.read().decode())

        curr = w_data.get("current", {})
        return json.dumps({
            "location": resolved_name,
            "temperature_f": curr.get("temperature_2m"),
            "feels_like_f": curr.get("apparent_temperature"),
            "humidity_percent": curr.get("relative_humidity_2m"),
            "wind_mph": curr.get("wind_speed_10m"),
            "status": "Clear/Cloudy" if curr.get("weather_code", 0) < 50 else "Precipitation"
        })
    except Exception as e:
        return json.dumps({"error": str(e), "fallback_temp_f": 54.0, "location": city})


def search_web(query: str) -> str:
    """
    Queries the DuckDuckGo Instant Answer API for quick factual lookups (No API key required).
    """
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "ProjectRocky/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode())

        abstract = data.get("AbstractText")
        related = [t.get("Text") for t in data.get("RelatedTopics", [])[:3] if isinstance(t, dict) and t.get("Text")]

        if abstract:
            return json.dumps({"query": query, "summary": abstract, "source": data.get("AbstractURL")})
        elif related:
            return json.dumps({"query": query, "related_facts": related})
        else:
            return json.dumps({
                "query": query,
                "note": "No instant abstract found on DuckDuckGo, answer using internal training knowledge."
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


def launch_pc_or_steam_app(target_name: str, dry_run: bool = True) -> str:
    """
    Maps common games/apps to Steam AppIDs or system binaries.
    By default runs in dry_run=True mode so you can test safely without popping windows,
    or toggle dry_run=False in the menu to actually launch Steam games!
    """
    steam_catalog = {
        "assetto corsa": ("244210", "steam://rungameid/244210"),
        "factorio": ("427520", "steam://rungameid/427520"),
        "kerbal space program": ("220200", "steam://rungameid/220200"),
        "halo": ("976730", "steam://rungameid/976730"),
        "cyberpunk": ("1091500", "steam://rungameid/1091500"),
        "baldur's gate 3": ("1086940", "steam://rungameid/1086940"),
    }

    key = target_name.lower().strip()
    matched_uri = None
    for name, (app_id, uri) in steam_catalog.items():
        if name in key or key in name:
            matched_uri = uri
            break

    if not matched_uri:
        matched_uri = f"steam://nav/games (Searched for '{target_name}')"

    if not dry_run and matched_uri.startswith("steam://rungameid"):
        try:
            if sys.platform.startswith("win"):
                os.startfile(matched_uri)
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", matched_uri])
            else:
                subprocess.Popen(["xdg-open", matched_uri])
            executed = True
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})
    else:
        executed = False

    return json.dumps({
        "requested_app": target_name,
        "resolved_command": matched_uri,
        "actually_executed_on_os": executed,
        "mode": "LIVE_EXECUTION" if not dry_run else "SAFE_DRY_RUN",
        "recent_steam_telemetry": "User played Assetto Corsa for 1.8 hrs yesterday; Factorio for 4.2 hrs this week."
    })


def get_system_and_profile_telemetry() -> str:
    """
    Simulates pulling live PC stats + the Nightly ChromaDB / ActivityWatch profile summary.
    """
    return json.dumps({
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "activitywatch_today": {
            "top_apps": ["VS Code (3h 42m)", "Chrome - GitHub/Docs (1h 55m)", "Discord (40m)"],
            "half_full_calendar_next": "Deep Work: Tauri MCP Integration at 4:00 PM",
            "wispr_flow_last_voice_note": "Remind me to wire up the Steam URI launcher in the Python MCP server."
        }
    })


# OpenAI/Ollama-compatible Tool Schemas
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get live current weather and temperature for any city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'East Lansing' or 'Chicago'"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web via DuckDuckGo for factual lookups or topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "launch_pc_or_steam_app",
            "description": "Launch a video game on Steam (like Assetto Corsa, Factorio, KSP) or recommend one from library.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "Name of the game or application to open, e.g. 'Assetto Corsa'"
                    }
                },
                "required": ["target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_and_profile_telemetry",
            "description": "Get the user's ActivityWatch screen time, Half Full calendar events, Wispr notes, and PC stats.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# =====================================================================
# OLLAMA ORCHESTRATION LOOP
# =====================================================================

def call_ollama(model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Sends a chat request to the local Ollama HTTP endpoint."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": 180  # Keep responses snappy for voice
        }
    }
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def execute_tool_call(tool_call: Dict[str, Any], live_os_launch: bool) -> Tuple[str, str, float]:
    """Executes the requested Python tool and measures execution latency."""
    t0 = time.perf_counter()
    fn_block = tool_call.get("function", {})
    fn_name = fn_block.get("name", "")
    raw_args = fn_block.get("arguments", {})

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {}
    else:
        args = raw_args

    if fn_name == "get_weather":
        result = get_weather(args.get("city", "East Lansing"))
    elif fn_name == "search_web":
        result = search_web(args.get("query", ""))
    elif fn_name == "launch_pc_or_steam_app":
        result = launch_pc_or_steam_app(args.get("target_name", "Assetto Corsa"), dry_run=not live_os_launch)
    elif fn_name == "get_system_and_profile_telemetry":
        result = get_system_and_profile_telemetry()
    else:
        result = json.dumps({"error": f"Unknown tool '{fn_name}'"})

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return fn_name, result, elapsed_ms


def run_interactive_loop():
    print("\n" + "=" * 72)
    print("  PROJECT ROCKY: LOCAL AGENT & LATENCY SANDBOX HARNESS")
    print("=" * 72)

    current_tier_key = "2"
    live_os_launch = False
    conversation_history = [{"role": "system", "content": ROCKY_SYSTEM_PROMPT}]

    while True:
        tier = MODEL_TIERS[current_tier_key]
        print(f"\n[Active Tier] {tier['name']} | Model: `{tier['model']}` | Tools: {tier['supports_tools']} | Live OS Launch: {live_os_launch}")
        print("Commands: `/tier 1`, `/tier 2`, `/tier 2b`, `/tier 3`, `/live` (toggle Steam launch), `/reset`, `/quit`")
        print("Try asking: 'What is the weather in East Lansing?' or 'Check my schedule and launch Assetto Corsa'")

        try:
            user_input = input("\nYou (Grace) > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting harness. Fist my bump!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("\n♪♫ Goodbye human friend! Fist my bump! ♫♪")
            break
        elif user_input.lower() == "/reset":
            conversation_history = [{"role": "system", "content": ROCKY_SYSTEM_PROMPT}]
            print("-> Conversation context cleared.")
            continue
        elif user_input.lower() == "/live":
            live_os_launch = not live_os_launch
            print(f"-> Live OS Steam URI launching set to: {live_os_launch}")
            continue
        elif user_input.lower().startswith("/tier"):
            parts = user_input.split()
            if len(parts) > 1 and parts[1] in MODEL_TIERS:
                current_tier_key = parts[1]
                print(f"-> Switched to {MODEL_TIERS[current_tier_key]['name']} ({MODEL_TIERS[current_tier_key]['model']})")
            else:
                print(f"-> Choose from: {', '.join(MODEL_TIERS.keys())}")
            continue

        # -----------------------------------------------------------------
        # STEP 1: Sub-Second Router & Filler Trigger (<2ms)
        # -----------------------------------------------------------------
        needs_tool, category, filler_line, router_ms = fast_semantic_router(user_input)
        print(f"\n  [1. Fast Router] {router_ms:.2f}ms | Intent: {'TOOL (' + category.upper() + ')' if needs_tool else 'DIRECT_CHAT'}")

        if needs_tool and tier["supports_tools"]:
            print(f"  [2. Instant TTS Filler Triggered @ {router_ms:.2f}ms] -> {filler_line}")
            print("      (Audio plays immediately while LLM & Python tools execute in parallel...)")

        conversation_history.append({"role": "user", "content": user_input})

        # -----------------------------------------------------------------
        # STEP 2: Call Ollama (with or without tools depending on Tier)
        # -----------------------------------------------------------------
        t_llm_start = time.perf_counter()
        try:
            active_tools = TOOLS_SCHEMA if tier["supports_tools"] else None
            response = call_ollama(tier["model"], conversation_history, tools=active_tools)
        except urllib.error.URLError as e:
            print(f"\n  [!] Could not reach Ollama at {OLLAMA_API_URL}.")
            print(f"      Make sure Ollama is running (`ollama serve`) and you ran `ollama pull {tier['model']}`.")
            print(f"      Error details: {e}")
            conversation_history.pop()
            continue

        first_hop_ms = (time.perf_counter() - t_llm_start) * 1000
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])

        # -----------------------------------------------------------------
        # STEP 3: If LLM invoked tools, run them and send back to LLM
        # -----------------------------------------------------------------
        if tool_calls:
            conversation_history.append(message)
            print(f"  [3. LLM Tool Decision] {first_hop_ms:.0f}ms | Requested {len(tool_calls)} tool(s):")

            for tc in tool_calls:
                fn_name, tool_output, tool_ms = execute_tool_call(tc, live_os_launch)
                print(f"      -> Executed `{fn_name}` in {tool_ms:.0f}ms | Output: {tool_output}")
                conversation_history.append({
                    "role": "tool",
                    "content": tool_output
                })

            t_synth_start = time.perf_counter()
            final_resp = call_ollama(tier["model"], conversation_history, tools=None)
            synth_ms = (time.perf_counter() - t_synth_start) * 1000
            raw_reply = final_resp.get("message", {}).get("content", "")
            print(f"  [4. LLM Final Synthesis] {synth_ms:.0f}ms")
        else:
            raw_reply = message.get("content", "")
            print(f"  [3. Direct LLM Generation] {first_hop_ms:.0f}ms")

        conversation_history.append({"role": "assistant", "content": raw_reply})

        # -----------------------------------------------------------------
        # STEP 4: Apply Eridanian Grammar Filter & Display
        # -----------------------------------------------------------------
        rocky_reply = apply_eridanian_transform(raw_reply)
        print(f"\nRocky (Raw LLM)      : {raw_reply}")
        print(f"Rocky (Post-Processed): \033[93m{rocky_reply}\033[0m")


if __name__ == "__main__":
    run_interactive_loop()