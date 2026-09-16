"""
Speech synthesis and transcription, both through the Gemini API.

Why not Cloud Speech-to-Text and Cloud Text-to-Speech
-----------------------------------------------------
They are the obvious choice and they are excellent. They also require a
Google Cloud project, billing, a service account and Application Default
Credentials — four things a farmer-facing pilot run by a district office does
not have on day one, and four more places for a deployment to fail.

Gemini's TTS models and its native audio understanding do the same two jobs
through the API key the platform already uses for everything else. Verified
round-trip on Punjabi: synthesised speech fed back for transcription returned
the original text character for character.

Cloud Speech remains the right answer at national scale — it offers
streaming recognition, per-model tuning and phrase hints that matter when
transcribing thousands of concurrent calls on an IVR line. The interface here
is deliberately narrow so that swap is a driver change.

The browser's own Web Speech API stays as a third path. On Android Chrome it
is backed by Google's speech models at no cost and no round trip, which for a
farmer paying per megabyte is a real advantage. Server speech is used where
the browser has no voice for the language — which is most Indian languages on
most devices, and the reason spoken Punjabi was being read aloud by an
English voice before this existed.
"""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

from google.genai import types

from . import llm

# Gemini TTS returns raw signed 16-bit little-endian PCM at 24 kHz mono. It is
# not a playable file until it is given a container.
TTS_SAMPLE_RATE = 24000
TTS_SAMPLE_WIDTH = 2
TTS_CHANNELS = 1

TTS_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]

# Prebuilt Gemini voices. These are not language-specific -- the model adapts
# pronunciation to the text -- so the choice is about character rather than
# locale. Kore is even and unhurried, which suits advisory content someone is
# trying to retain while standing in a field.
DEFAULT_VOICE = "Kore"
VOICE_CHOICES = ("Kore", "Puck", "Charon", "Fenrir", "Aoede")

# Longer text is refused rather than truncated. A silently cut-off advisory is
# worse than none: the farmer hears "apply forty" and not the unit.
MAX_TTS_CHARS = 1200

MAX_AUDIO_BYTES = 12 * 1024 * 1024
ACCEPTED_AUDIO_MIME = {
    "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg",
    "audio/mpeg", "audio/mp4", "audio/m4a", "audio/aac", "audio/flac",
}


class SpeechError(RuntimeError):
    pass


# Below this root-mean-square amplitude (as a fraction of full scale) a
# recording carries no speech worth sending anywhere.
#
# This exists because asking the model nicely does not work. Given a second
# of pure digital silence and an explicit instruction to answer "[no speech]"
# if it heard nothing, Gemini returned "The next topic we're going to cover
# is how to register an app" -- a fluent, complete, entirely invented
# sentence. A farmer whose recording failed would have had that fabrication
# treated as their question and answered in earnest.
#
# A prompt is a request. An amplitude threshold is a fact. The check runs
# before the model is called at all, so silence cannot reach it.
SILENCE_RMS_THRESHOLD = 0.005


def wav_rms(audio_bytes: bytes) -> float | None:
    """Root-mean-square amplitude of a WAV recording, 0.0 to 1.0.

    Returns None for anything that is not decodable PCM WAV -- browsers
    usually record WebM/Opus, which needs a codec we deliberately do not
    ship. Those fall back to the model-side guard below.
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as w:
            frames = w.readframes(w.getnframes())
            width = w.getsampwidth()
        if width != 2 or not frames:
            return None
        import array
        samples = array.array("h")
        samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
        if not samples:
            return None
        total = sum(float(s) * float(s) for s in samples)
        return (total / len(samples)) ** 0.5 / 32768.0
    except Exception:  # noqa: BLE001
        return None


TRANSCRIPT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["contains_speech", "transcript"],
    properties={
        "contains_speech": types.Schema(
            type=types.Type.BOOLEAN,
            description=(
                "True only if you can actually hear a person speaking words. "
                "False for silence, background noise, music, or anything "
                "unintelligible."
            ),
        ),
        "transcript": types.Schema(
            type=types.Type.STRING,
            description=(
                "Exactly what was said, in the speaker's own words and "
                "register. Empty string when contains_speech is false."
            ),
        ),
        "language_heard": types.Schema(type=types.Type.STRING),
    },
)


def pcm_to_wav(
    pcm: bytes,
    sample_rate: int = TTS_SAMPLE_RATE,
    channels: int = TTS_CHANNELS,
    sample_width: int = TTS_SAMPLE_WIDTH,
) -> bytes:
    """Wrap raw PCM in a WAV container so a browser will play it."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buffer.getvalue()


def _parse_rate(mime_type: str, default: int = TTS_SAMPLE_RATE) -> int:
    """Read the sample rate out of a mime type like 'audio/L16;rate=24000'.

    The rate is parsed rather than assumed because the two TTS models return
    subtly different mime strings, and a wrong rate does not fail loudly --
    it plays back at the wrong pitch and speed, which sounds like a broken
    product rather than a configuration error.
    """
    for part in (mime_type or "").split(";"):
        part = part.strip().lower()
        if part.startswith("rate="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return default
    return default


async def synthesise(
    text: str,
    voice: str = DEFAULT_VOICE,
    language_name: str = "",
) -> dict[str, Any]:
    """Speak `text` aloud. Returns WAV bytes.

    The prompt asks for an unhurried delivery: advisory content carries
    numbers a listener needs to hold onto, and the default read is paced for
    notifications rather than instructions.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "abstain_reason": "Nothing to say."}
    if len(text) > MAX_TTS_CHARS:
        return {
            "ok": False,
            "abstain_reason": (
                f"That reply is too long to read aloud in one piece "
                f"({len(text)} characters). Ask for a shorter answer."
            ),
        }
    if voice not in VOICE_CHOICES:
        voice = DEFAULT_VOICE

    try:
        client = llm.build_client()
    except llm.LLMNotConfigured as exc:
        return {"ok": False, "abstain_reason": str(exc)}

    instruction = (
        "Read the following aloud clearly and unhurriedly, as if explaining "
        "something practical to a person standing in front of you"
        + (f", in {language_name}" if language_name else "")
        + ":\n\n"
        + text
    )

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    last_error: Exception | None = None
    ordered = [m for m in TTS_MODELS if not llm.is_cooling_down(m)] + \
              [m for m in TTS_MODELS if llm.is_cooling_down(m)]
    for model in ordered:
        try:
            response = await client.aio.models.generate_content(
                model=model, contents=instruction, config=config
            )
            for part in response.candidates[0].content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    rate = _parse_rate(inline.mime_type or "")
                    return {
                        "ok": True,
                        "audio": pcm_to_wav(inline.data, sample_rate=rate),
                        "mime_type": "audio/wav",
                        "model_used": model,
                        "voice": voice,
                    }
            last_error = SpeechError("Model returned no audio")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                llm.note_rate_limited(model, exc)
            if llm.is_retryable(exc):
                continue
            break

    message, _kind = llm.friendly_error(last_error or SpeechError("unknown"))
    return {"ok": False, "abstain_reason": message}


async def transcribe(
    audio_bytes: bytes,
    mime_type: str,
    language_name: str = "",
) -> dict[str, Any]:
    """Transcribe recorded speech.

    The prompt forbids translation and correction. A farmer speaking mixed
    Hinglish or a regional dialect must come back as what they said, not as
    formal Hindi -- both because the transcript is shown to them for
    confirmation, and because "correcting" someone's speech into a register
    they did not use is its own small insult.
    """
    if mime_type not in ACCEPTED_AUDIO_MIME:
        return {
            "ok": False,
            "abstain_reason": f"Audio type {mime_type} is not supported.",
        }
    if not audio_bytes:
        return {"ok": False, "abstain_reason": "Empty recording."}
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return {
            "ok": False,
            "abstain_reason": "That recording is too long. Please keep it under a minute.",
        }

    # Deterministic guard first, so silence never reaches a model that will
    # cheerfully invent something to fill it.
    rms = wav_rms(audio_bytes)
    if rms is not None and rms < SILENCE_RMS_THRESHOLD:
        return {
            "ok": False,
            "abstain_reason": (
                "I could not hear anything. Please hold the phone closer and "
                "speak again."
            ),
            "reason_code": "silence",
            "rms": round(rms, 6),
        }

    try:
        client = llm.build_client()
    except llm.LLMNotConfigured as exc:
        return {"ok": False, "abstain_reason": str(exc)}

    prompt = (
        "Transcribe this audio exactly as spoken.\n"
        "Set contains_speech to false unless you can genuinely hear a person "
        "saying words. Silence, background noise, wind, machinery or music "
        "are not speech. Do not fill an empty recording with plausible "
        "content -- an invented transcript will be answered as though the "
        "farmer said it.\n"
        "When there is speech, keep the speaker's own words and register, "
        "including mixed-language speech such as Hinglish, and local crop and "
        "practice names such as bajra, jowar, rabi or kharif. Do not correct "
        "grammar or convert dialect into a formal register."
    )
    if language_name:
        prompt += f"\nThe speaker is most likely speaking {language_name}."

    contents = [
        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        types.Part(text=prompt),
    ]

    last_error: Exception | None = None
    for model in llm.model_candidates():
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=TRANSCRIPT_SCHEMA,
                ),
            )
            parsed = response.parsed
            if parsed is None:
                import json
                parsed = json.loads(response.text)

            text = (parsed.get("transcript") or "").strip()
            # Both conditions must hold. A model that sets contains_speech
            # true and returns nothing, or false and returns a sentence, is
            # confused either way and must not be trusted.
            if not parsed.get("contains_speech") or not text:
                return {
                    "ok": False,
                    "abstain_reason": (
                        "I could not make out any speech in that recording. "
                        "Please try again, closer to the microphone."
                    ),
                    "reason_code": "no_speech",
                }
            return {
                "ok": True,
                "text": text,
                "language_heard": parsed.get("language_heard", ""),
                "model_used": model,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if llm.is_retryable(exc):
                continue
            break

    message, _kind = llm.friendly_error(last_error or SpeechError("unknown"))
    return {"ok": False, "abstain_reason": message}
