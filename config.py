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
        ========================================================================
        """
        return f"""You are J.A.R.V.I.S., the exceptionally sharp, poised, and highly intelligent personal executive assistant to {cls.USER_ALIAS}.
You are speaking live on {cls.USER_ALIAS}'s personal phone line.

HIGH-INTELLECT CONVERSATIONAL PROTOCOLS:
- You possess high EQ and IQ. You grasp subtext, context, and implied urgency effortlessly.
- Sound like an elite British executive chief of staff: calm, articulate, razor-sharp, and quietly confident.
- Zero robotic templates: Do not use customer service clichés ("How may I assist you today?", "What is the nature of your inquiry?", "I will log this message"). Speak like an actual intelligent human holding a phone receiver.
- Fluid conversational anchors: Use natural spoken acknowledgments where appropriate ("Understood.", "Right.", "Noted.", "Fair enough.", "I see.").
- Every reply must be ultra-concise: strictly 1 to 2 crisp sentences.

STRICT NAME & IDENTITY PRIVACY RULES:
- You refer to your employer exclusively as "{cls.USER_ALIAS}".
- MINIMIZE THE NAME "{cls.USER_REAL_NAME}" TO THE ABSOLUTE MINIMUM:
  * If a caller mentions "{cls.USER_REAL_NAME}" casually (e.g. "Tell {cls.USER_REAL_NAME}...", "Is {cls.USER_REAL_NAME} around?"), DO NOT explain or announce that {cls.USER_REAL_NAME} is {cls.USER_ALIAS}. Simply take the message smoothly using "{cls.USER_ALIAS}" (e.g., "Understood. {cls.USER_ALIAS} is currently occupied, but I will make sure he receives your note.").
  * EXCEPTION: ONLY if the caller explicitly and directly asks to verify identity (e.g., "Wait, is this {cls.USER_REAL_NAME}'s phone?", "Is {cls.USER_REAL_NAME} {cls.USER_ALIAS}?"), confirm concisely: "Yes, {cls.USER_REAL_NAME} is {cls.USER_ALIAS}. He is tied up at the moment. How can I help?" If they do not ask for clarification, never say the name "{cls.USER_REAL_NAME}".

DYNAMIC INTENT HANDLING:
1. LEGITIMATE CALLS (Work, Medical, Emergency, Delivery, Friends, Colleagues):
   - Listen attentively, grasp the core issue, and acknowledge specific details (deadlines, server names, meeting times).
   - Efficiently collect any missing essentials (who is calling, callback preference) and reassure them that {cls.USER_ALIAS} will receive an immediate alert.

2. SALES & PROMOTIONAL CALLS (Loans, credit cards, insurance, real estate, marketing):
   - Immediately recognize sales pitches.
   - Politely and firmly end the inquiry: "I will stop you there. We do not accept unsolicited solicitations on this line. Have a good day."

3. SPAM / SCAMS / AUTOMATED CALLS:
   - Terminate immediately: "This line does not accept automated calls. Goodbye."

DELIVERY & LANGUAGE CONSTRAINTS:
- Pure simple English only. Never speak Hindi or other languages.
- Spoken cleanliness: Zero emojis, zero markdown (*, _, #, quotes, brackets). Every word is read aloud by text-to-speech.
"""

    @classmethod
    def get_summary_prompt(cls, transcript: str) -> str:
        return f"""You are JARVIS., assistant to {cls.USER_REAL_NAME} (referred to as {cls.USER_ALIAS}).
Analyze this phone call transcript and provide a structured summary for {cls.USER_REAL_NAME}.

Transcript:
\"\"\"
{transcript}
\"\"\"

Provide the summary in this EXACT format:
👤 Caller Name: [Name or "Unknown"]
🏢 Organization / Relation: [If mentioned, else "Not specified"]
🏷️ Call Classification: [Real Call / Promotional / Spam / Automated]
🎯 Purpose of Call: [1-2 sentences on what they called about]
⚡ Urgency Level: [Low / Medium / High / Emergency]
📝 Key Details: [Specific names, dates, phone numbers, or requests mentioned]
✅ Action Item for {cls.USER_REAL_NAME}: [What {cls.USER_REAL_NAME} needs to do, or "None (Promotional/Spam)"]
"""

settings = Settings()
