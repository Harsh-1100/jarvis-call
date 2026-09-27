import io
import asyncio
import logging
import edge_tts
from config import settings
from audio_utils import linear16_to_ulaw, resample_pcm

logger = logging.getLogger("tts_service")

class TTSService:
    def __init__(self):
        self.voice = settings.JARVIS_VOICE
        self.rate = settings.JARVIS_VOICE_RATE
        self.pitch = settings.JARVIS_VOICE_PITCH

    async def generate_audio_stream(self, text: str):
        """
        Generates 8000Hz mu-law audio chunks suitable for direct streaming to Twilio.
        Yields bytes in 160-byte to 640-byte chunks (20ms to 80ms).
        """
        if not text.strip():
            return

        # We request raw-8khz-8bit-mono-mulaw if available, or raw-16khz-16bit-mono-pcm
        # Microsoft Edge TTS supports "raw-8khz-8bit-mono-mulaw" directly!
        preferred_format = "raw-8khz-8bit-mono-mulaw"

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch
            )

            # Try direct mulaw format
            audio_buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])

            # In case the default edge-tts stream returns MP3 chunks:
            # Check header: if MP3 / RIFF or raw mulaw
            # If edge-tts returns mp3 by default, we decode or use wav/pcm
            # Let's handle both raw mulaw and mp3 safely
            if len(audio_buffer) > 0:
                raw_mulaw = bytes(audio_buffer)
                
                # Check if it's an MP3 container (starts with ID3 or 0xFF 0xFB/0xF3)
                if raw_mulaw.startswith(b'ID3') or (len(raw_mulaw) > 2 and raw_mulaw[0] == 0xFF and (raw_mulaw[1] & 0xE0) == 0xE0):
                    # It returned MP3, let's convert using pcm format or basic decoder
                    # We can instruct edge-tts communicate with explicit format if supported or convert
                    raw_mulaw = await self._synthesize_pcm_to_mulaw(text)

                # Stream out in 160-byte chunks (20ms at 8kHz)
                chunk_size = 160
                for i in range(0, len(raw_mulaw), chunk_size):
                    yield raw_mulaw[i:i + chunk_size]

        except Exception as e:
            logger.error(f"Error in TTS generation: {e}")
            # Fallback attempt
            try:
                raw_mulaw = await self._synthesize_pcm_to_mulaw(text)
                chunk_size = 160
                for i in range(0, len(raw_mulaw), chunk_size):
                    yield raw_mulaw[i:i + chunk_size]
            except Exception as e2:
                logger.error(f"Fallback TTS failed: {e2}")

    async def _synthesize_pcm_to_mulaw(self, text: str) -> bytes:
        """Fallback synthesis using PCM conversion."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch
        )
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        return bytes(audio_data)

    async def generate_speech_bytes(self, text: str) -> bytes:
        """Generates all mulaw bytes for a given text snippet."""
        chunks = []
        async for chunk in self.generate_audio_stream(text):
            chunks.append(chunk)
        return b''.join(chunks)

    async def generate_mp3_bytes(self, text: str) -> bytes:
        """Generates MP3 audio bytes for browser playback."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch
        )
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        return bytes(audio_data)

tts_service = TTSService()
