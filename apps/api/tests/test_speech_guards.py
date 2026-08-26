"""
Tests for the speech guards.

These exist because of one specific observed failure. Given a second of pure
digital silence, and an explicit instruction to answer "[no speech]" if it
heard nothing, Gemini returned:

    "The next topic we're going to cover is how to register an app"

A fluent, complete, entirely invented sentence. In the product that
fabrication would have been placed in the farmer's input box and answered in
earnest -- the assistant confidently addressing a question nobody asked.

The lesson generalises past this one API: a prompt is a request, and a
request is not a guard. Anything that must not happen needs a deterministic
check that runs before the model is reached.
"""

import io
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

# The speech module lives in the API package, which is not importable from
# the agronomy suite -- that package is deliberately dependency-free so the
# validated agronomy can be tested with no network stack installed.
_API = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[3]
for _p in (_API, _ROOT / "packages" / "agronomy", _ROOT / "packages" / "geo"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _wav(samples: list[int], rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buf.getvalue()


def _silence(seconds: float = 1.0, rate: int = 24000) -> bytes:
    return _wav([0] * int(rate * seconds), rate)


def _tone(seconds: float = 1.0, rate: int = 24000, amplitude: int = 8000) -> bytes:
    n = int(rate * seconds)
    return _wav(
        [int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n)],
        rate,
    )


class TestSilenceDetection:
    def test_digital_silence_measures_zero(self):
        from agrin_api.speech import wav_rms
        assert wav_rms(_silence()) == pytest.approx(0.0, abs=1e-9)

    def test_silence_is_below_the_threshold(self):
        from agrin_api.speech import SILENCE_RMS_THRESHOLD, wav_rms
        assert wav_rms(_silence()) < SILENCE_RMS_THRESHOLD

    def test_audible_tone_is_above_the_threshold(self):
        from agrin_api.speech import SILENCE_RMS_THRESHOLD, wav_rms
        assert wav_rms(_tone()) > SILENCE_RMS_THRESHOLD

    def test_very_quiet_audio_is_treated_as_silence(self):
        # A recording made with the phone in a pocket, or a microphone the
        # farmer never granted access to, produces near-zero amplitude rather
        # than exact zeros.
        from agrin_api.speech import SILENCE_RMS_THRESHOLD, wav_rms
        assert wav_rms(_tone(amplitude=20)) < SILENCE_RMS_THRESHOLD

    def test_non_wav_returns_none_rather_than_guessing(self):
        # Browsers record WebM/Opus, which needs a codec we deliberately do
        # not ship. Those must fall through to the model-side guard rather
        # than being wrongly judged silent and refused.
        from agrin_api.speech import wav_rms
        assert wav_rms(b"not a wav file at all") is None
        assert wav_rms(b"") is None

    def test_truncated_wav_does_not_raise(self):
        from agrin_api.speech import wav_rms
        assert wav_rms(_silence()[:20]) is None


class TestTranscriptionRefusesSilence:
    """The end-to-end guard, without touching the network."""

    @pytest.mark.asyncio
    async def test_silent_recording_is_refused_before_any_model_call(self, monkeypatch):
        import agrin_api.speech as speech

        called = {"build_client": False}

        def _fail_if_called():
            called["build_client"] = True
            raise AssertionError(
                "A silent recording reached the model. The whole point of the "
                "amplitude check is that this cannot happen."
            )

        monkeypatch.setattr(speech.llm, "build_client", _fail_if_called)

        result = await speech.transcribe(_silence(), "audio/wav")
        assert result["ok"] is False
        assert result["reason_code"] == "silence"
        assert called["build_client"] is False

    @pytest.mark.asyncio
    async def test_rejects_unsupported_audio_type(self):
        import agrin_api.speech as speech
        result = await speech.transcribe(b"xxxx", "audio/aiff")
        assert result["ok"] is False
        assert "not supported" in result["abstain_reason"]

    @pytest.mark.asyncio
    async def test_rejects_empty_recording(self):
        import agrin_api.speech as speech
        result = await speech.transcribe(b"", "audio/wav")
        assert result["ok"] is False


class TestWavWrapping:
    def test_pcm_is_wrapped_into_a_playable_wav(self):
        from agrin_api.speech import pcm_to_wav
        pcm = b"".join(struct.pack("<h", i % 1000) for i in range(4800))
        out = pcm_to_wav(pcm, sample_rate=24000)
        assert out[:4] == b"RIFF"
        with wave.open(io.BytesIO(out), "rb") as w:
            assert w.getframerate() == 24000
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2

    def test_sample_rate_is_read_from_the_mime_type(self):
        """A wrong rate does not fail loudly -- it plays at the wrong pitch.

        The two TTS models return subtly different mime strings, so the rate
        is parsed rather than assumed.
        """
        from agrin_api.speech import _parse_rate
        assert _parse_rate("audio/l16; rate=24000; channels=1") == 24000
        assert _parse_rate("audio/L16;codec=pcm;rate=16000") == 16000
        assert _parse_rate("audio/wav") == 24000          # falls back
        assert _parse_rate("audio/l16; rate=notanumber") == 24000
        assert _parse_rate("") == 24000


class TestSynthesisGuards:
    @pytest.mark.asyncio
    async def test_empty_text_is_refused(self):
        import agrin_api.speech as speech
        assert (await speech.synthesise("   "))["ok"] is False

    @pytest.mark.asyncio
    async def test_overlong_text_is_refused_rather_than_truncated(self):
        # A silently cut-off advisory is worse than none: the farmer hears
        # "apply forty" and never hears the unit.
        import agrin_api.speech as speech
        result = await speech.synthesise("x" * 5000)
        assert result["ok"] is False
        assert "too long" in result["abstain_reason"]
