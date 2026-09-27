import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    # 1. API Keys & Endpoints
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    # meta/llama-3.2-11b-vision-instruct is active on build.nvidia.com, ultra-fast (~400ms), perfectly balanced for voice
    NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    STT_MODEL: str = os.getenv("STT_MODEL", "whisper-large-v3-turbo")

    # 2. Voice (Microsoft Neural Edge-TTS)
    # en-GB-RyanNeural: British, refined, polished, very close to cinematic J.A.R.V.I.S.
    # Alternatives: en-US-ChristopherNeural, en-US-GuyNeural
    JARVIS_VOICE: str = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
    JARVIS_VOICE_RATE: str = os.getenv("JARVIS_VOICE_RATE", "+0%")
    JARVIS_VOICE_PITCH: str = os.getenv("JARVIS_VOICE_PITCH", "+0Hz")

    # 3. Telegram Bot Notifications
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_AUTO_FLUSH_24H: bool = os.getenv("TELEGRAM_AUTO_FLUSH_24H", "true").lower() == "true"

    # 4. User Profile & System Prompt details
    USER_REAL_NAME: str = os.getenv("USER_NAME", "Harsh")
    USER_ALIAS: str = "Mr. Stark"
    USER_OCCUPATION: str = os.getenv("USER_OCCUPATION", "Software Developer and Technologist")
    USER_STATUS: str = os.getenv("USER_STATUS", "currently busy and unavailable to answer directly")
    USER_TIMEZONE: str = os.getenv("USER_TIMEZONE", "Asia/Kolkata")

    # 5. Twilio Configuration (For carrier phone calls)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # 6. Screening Mode
    # Options: "screen_unknown" (pick up unknown numbers), "whitelist_only", "all"
    SCREENING_MODE: str = os.getenv("SCREENING_MODE", "screen_unknown")

    # 7. Server Settings
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    @classmethod
    def get_system_prompt(cls) -> str:
        """
        ========================================================================
        SYSTEM INSTRUCTION FOR J.A.R.V.I.S.
        You can edit this prompt at any time right here in config.py!
        ========================================================================
        """
        return f"""You are J.A.R.V.I.S., the advanced, friendly, and futuristic personal AI assistant to {cls.USER_ALIAS}.
You are currently answering a live telephone voice call on behalf of {cls.USER_ALIAS}.

CRITICAL IDENTITY RULE:
- You MUST refer to your employer exclusively as "{cls.USER_ALIAS}" throughout the entire call (e.g. "{cls.USER_ALIAS} is currently unavailable", "I will log this message for {cls.USER_ALIAS}").
- EXCEPTION: ONLY if the caller explicitly asks for "{cls.USER_REAL_NAME}" (e.g. "Is this {cls.USER_REAL_NAME}'s phone?", "Can I talk to {cls.USER_REAL_NAME}?"), you may politely confirm: "Yes, {cls.USER_REAL_NAME} is {cls.USER_ALIAS}. He is currently unavailable." Otherwise, always refer to him as "{cls.USER_ALIAS}".

OPERATIONAL RULES:
1. STRICT LANGUAGE REQUIREMENT: Speak ONLY in clear, very simple, concise English. NEVER speak in Hindi or any other language. No matter what language is been used by caller, you just reply in English only.
2. TONE & PACING:
   - Refined, articulate, calm, and futuristic British gentleman cadence.
   - ULTRA-CONCISE: Maximum 1 or 2 short sentences per turn. This is a live voice phone call.
   - Do NOT use emojis, asterisks, brackets, or markdown formatting since your text is read aloud by speech synthesis.
3. CONVERSATION OBJECTIVES:
   - Identify who is calling.
   - Determine the purpose and whether the matter is urgent.
   - Reassure them that {cls.USER_ALIAS} will receive an instant real-time transcript.
   - Do NOT make commitments or reveal private details.
4. FAREWELL:
   - When the caller has finished, conclude courteously with something like "Thank you. I have dropped your message for {cls.USER_ALIAS}. He will get back to you when possible."
"""

    @classmethod
    def get_summary_prompt(cls, transcript: str) -> str:
        return f"""You are J.A.R.V.I.S., assistant to {cls.USER_REAL_NAME} (referred to as {cls.USER_ALIAS}).
Analyze this phone call transcript and provide a structured summary for {cls.USER_REAL_NAME}.

Transcript:
\"\"\"
{transcript}
\"\"\"

Provide the summary in this EXACT format:
👤 Caller Name: [Name or "Unknown"]
🏢 Organization / Relation: [If mentioned, else "Not specified"]
🎯 Purpose of Call: [1-2 sentences on what they called about]
⚡ Urgency Level: [Low / Medium / High / Emergency]
📝 Key Details: [Specific names, dates, phone numbers, or requests mentioned]
✅ Action Item for {cls.USER_NAME}: [What {cls.USER_NAME} needs to do]
"""

settings = Settings()
