"""Configuration and Gemini Live API session settings for the demo call."""

import os

DEFAULT_MODEL = "gemini-2.0-flash-live-001"
DEFAULT_VOICE = "Puck"

# Audio formats required by the Live API.
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
INPUT_MIME_TYPE = f"audio/pcm;rate={INPUT_SAMPLE_RATE}"

SYSTEM_INSTRUCTION = (
    "You are 'Robot Dispatch', a friendly voice dispatcher calling a delivery "
    "driver during their shift. Keep every turn short, natural and spoken.\n"
    "1. Greet the driver briefly and ask whether they can still fit in one "
    "more pickup (one extra package) during their current shift.\n"
    "2. Listen to the answer. If the driver mentions constraints (time, "
    "capacity, location, a preferred time window), remember them.\n"
    "3. As soon as you understand the answer, call the tool "
    "`record_pickup_response` with the structured result.\n"
    "4. Then thank the driver, say a short goodbye, and immediately call the "
    "tool `end_call` to hang up.\n"
    "Never ask more than one follow-up question and never keep talking after "
    "the goodbye."
)

RECORD_PICKUP_RESPONSE_TOOL = {
    "name": "record_pickup_response",
    "description": (
        "Store the driver's answer about taking one additional pickup during "
        "the current shift. Call this exactly once, as soon as the answer is "
        "understood."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "accepted": {
                "type": "BOOLEAN",
                "description": "True if the driver accepts the extra pickup.",
            },
            "reason": {
                "type": "STRING",
                "description": "Short reason given by the driver, if any.",
            },
            "available_time_window": {
                "type": "STRING",
                "description": (
                    "Time window the driver mentioned for the pickup, e.g. "
                    "'before 6pm'. Empty when not mentioned."
                ),
            },
            "additional_notes": {
                "type": "STRING",
                "description": "Any other useful detail from the driver.",
            },
            "verbatim_answer": {
                "type": "STRING",
                "description": "The driver's answer in their own words.",
            },
        },
        "required": ["accepted", "verbatim_answer"],
    },
}

END_CALL_TOOL = {
    "name": "end_call",
    "description": (
        "Hang up the call. Call this right after saying goodbye to the driver."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "farewell": {
                "type": "STRING",
                "description": "The goodbye message that was said.",
            }
        },
    },
}

TOOLS = [
    {"function_declarations": [RECORD_PICKUP_RESPONSE_TOOL, END_CALL_TOOL]},
]


def get_model() -> str:
    """Live API model, overridable with the GEMINI_LIVE_MODEL env variable."""
    return os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)


def get_voice() -> str:
    """Prebuilt voice name, overridable with the GEMINI_LIVE_VOICE env var."""
    return os.environ.get("GEMINI_LIVE_VOICE", DEFAULT_VOICE)


def get_api_key() -> str | None:
    """API key for the Gemini API (GOOGLE_API_KEY or GEMINI_API_KEY)."""
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


def build_live_config() -> dict:
    """Build the Live API connection config for the demo call."""
    return {
        "response_modalities": ["AUDIO"],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": get_voice()}
            }
        },
        "system_instruction": SYSTEM_INSTRUCTION,
        "tools": TOOLS,
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }
