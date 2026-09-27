import re
import logging
from typing import List, Dict, AsyncGenerator
from openai import AsyncOpenAI
from config import settings

logger = logging.getLogger("llm_service")

class LLMService:
    def __init__(self):
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NVIDIA_BASE_URL
        self.model = settings.NVIDIA_MODEL
        
        # AsyncOpenAI client configured for NVIDIA NIM
        self.client = AsyncOpenAI(
            api_key=self.api_key or "placeholder_key",
            base_url=self.base_url
        )

    def create_initial_history(self) -> List[Dict[str, str]]:
        """Returns the initial message history with system prompt (zero hardcoded replies)."""
        return [
            {"role": "system", "content": settings.get_system_prompt()}
        ]

    async def get_response_stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """
        Streams sentences from NVIDIA NIM model with minimal latency.
        Yields short sentences/clauses so TTS voice starts immediately.
        """
        if not self.api_key or self.api_key == "your_nvidia_api_key_here":
            logger.warning("NVIDIA_API_KEY is not configured.")
            yield f"I am J.A.R.V.I.S. Please configure the NVIDIA API key in your settings so I can converse fully."
            return

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.4,
                top_p=0.9,
                max_tokens=130,
                stream=True
            )

            buffer = ""
            sentence_delimiters = re.compile(r'([.!?]+[\s\n]+)')

            async for chunk in stream:
                content = chunk.choices[0].delta.content if chunk.choices else ""
                if content:
                    buffer += content
                    parts = sentence_delimiters.split(buffer)
                    if len(parts) > 1:
                        complete_sentence = "".join(parts[:-1]).strip()
                        buffer = parts[-1]
                        if complete_sentence:
                            clean_text = self._clean_for_speech(complete_sentence)
                            if clean_text:
                                yield clean_text

            # Yield any remaining text in buffer
            if buffer.strip():
                clean_text = self._clean_for_speech(buffer.strip())
                if clean_text:
                    yield clean_text

        except Exception as e:
            logger.error(f"Error calling NVIDIA API: {e}")
            yield f"I apologize, but I am experiencing an internal communication delay. Could you please repeat that?"

    async def generate_summary(self, full_transcript: str) -> str:
        """Generates a structured post-call summary using the NVIDIA LLM."""
        if not full_transcript.strip():
            return "No conversation recorded."

        if not self.api_key or self.api_key == "your_nvidia_api_key_here":
            return f"Call ended.\nTranscript:\n{full_transcript}"

        prompt = settings.get_summary_prompt(full_transcript)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=400
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return f"Summary generation failed ({e}).\n\nRaw Transcript:\n{full_transcript}"

    def _clean_for_speech(self, text: str) -> str:
        """Removes markdown symbols, emojis, and unpronounceable characters."""
        # Remove markdown stars, underscores, hashes, brackets
        cleaned = re.sub(r'[\*\_#\[\]\(\)<>`~]', '', text)
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

llm_service = LLMService()
