import io
import httpx
import logging
from config import settings
from audio_utils import create_wav_file

logger = logging.getLogger("stt_service")

class STTService:
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.base_url = settings.GROQ_BASE_URL
        self.model = settings.STT_MODEL
        self._client = httpx.AsyncClient(timeout=8.0, limits=httpx.Limits(max_keepalive_connections=5, max_connections=10))

    async def transcribe(self, pcm_16k_bytes: bytes) -> str:
        """
        Sends 16kHz linear PCM audio buffer to Groq Whisper for near-instant transcription.
        Returns transcribed text string.
        """
        if not pcm_16k_bytes or len(pcm_16k_bytes) < 3200:
            # Under 100ms of audio, ignore
            return ""

        if not self.api_key or self.api_key == "your_groq_api_key_here":
            logger.warning("GROQ_API_KEY is not configured. Returning empty transcript.")
            return ""

        wav_bytes = create_wav_file(pcm_16k_bytes, sample_rate=16000)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav")
        }
        
        data = {
            "model": self.model,
            "language": "en",  # Enforce English transcription
            "response_format": "text",
            "temperature": "0.0"
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/audio/transcriptions",
                headers=headers,
                files=files,
                data=data
            )
            if response.status_code == 200:
                text = response.text.strip()
                logger.info(f"Transcribed: '{text}'")
                return text
            else:
                logger.error(f"Groq STT error {response.status_code}: {response.text}")
                return ""
        except Exception as e:
            logger.error(f"Exception during STT transcription: {e}")
            return ""

stt_service = STTService()
