import asyncio
import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from audio_utils import ulaw_to_linear16, resample_pcm, calculate_rms
from stt_service import stt_service
from tts_service import tts_service
from llm_service import llm_service
from rules_engine import rules_engine
from telegram_service import telegram_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("jarvis_app")

# Background auto-flush worker for 24h retention
async def auto_flush_cron():
    while True:
        try:
            await telegram_service.flush_expired_logs()
        except Exception as e:
            logger.error(f"Error in auto-flush worker: {e}")
        await asyncio.sleep(600)  # Check every 10 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    flush_task = asyncio.create_task(auto_flush_cron())
    logger.info("J.A.R.V.I.S. Voice Server started successfully.")
    yield
    flush_task.cancel()

app = FastAPI(title="J.A.R.V.I.S. Voice Call Assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# 1. TWILIO INBOUND CALL WEBHOOK
# -------------------------------------------------------------------
@app.post("/voice")
async def handle_inbound_call(request: Request):
    """
    Twilio calls this webhook when a telephone call arrives.
    We inspect caller ID, evaluate screening rules, and connect to WebSocket.
    """
    form_data = await request.form()
    caller_number = form_data.get("From", "Unknown")
    call_sid = form_data.get("CallSid", "unknown_call")
    host = request.headers.get("host")

    logger.info(f"Incoming call from: {caller_number} (CallSid: {call_sid})")

    # Evaluate rules engine
    should_answer, reason = rules_engine.should_answer(caller_number)
    logger.info(f"Screening evaluation: {should_answer} ({reason})")

    if not should_answer:
        # Politely reject or disconnect
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Brian">The recipient is unavailable. Thank you.</Say>
    <Reject />
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Build TwiML to start bidirectional WebSocket audio stream
    # Note: Twilio requires wss:// (secure) when hosted publicly
    protocol = "wss" if "https" in str(request.url) or "hf.space" in host or "render" in host else "ws"
    ws_url = f"{protocol}://{host}/media-stream"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="callerNumber" value="{caller_number}" />
            <Parameter name="callSid" value="{call_sid}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")

# -------------------------------------------------------------------
# 2. TWILIO WEBSOCKET MEDIA STREAM (REAL-TIME AUDIO LOOP)
# -------------------------------------------------------------------
@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("Twilio Media Stream WebSocket connected.")

    stream_sid: Optional[str] = None
    call_sid: str = f"call_{int(time.time())}"
    caller_info: str = "Unknown Caller"
    
    # State tracking
    conversation_history = llm_service.create_initial_history()
    transcript_display: List[str] = []
    telegram_msg_id: Optional[int] = None

    # Audio buffering for STT (Voice Activity Detection)
    audio_buffer = bytearray()
    silence_frames = 0
    is_speaking = False
    
    # Tuned VAD constants (for 20ms frames at 8kHz)
    RMS_THRESHOLD = 350.0       # Energy threshold for speech
    SILENCE_LIMIT_FRAMES = 22   # ~440ms of silence triggers STT (ultra-responsive)

    async def send_tts_to_caller(text: str):
        """Synthesizes text with Edge-TTS and streams audio chunks to Twilio."""
        if not stream_sid:
            return
        nonlocal is_speaking
        is_speaking = True
        try:
            async for chunk in tts_service.generate_audio_stream(text):
                b64_payload = base64.b64encode(chunk).decode("utf-8")
                media_message = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": b64_payload}
                }
                await websocket.send_text(json.dumps(media_message))
                # Small yield to maintain socket flow
                await asyncio.sleep(0.001)
        except Exception as err:
            logger.error(f"Error streaming TTS to caller: {err}")
        finally:
            is_speaking = False

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            event = data.get("event")

            if event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid", call_sid)
                custom_params = start_data.get("customParameters", {})
                caller_info = custom_params.get("callerNumber", caller_info)
                
                logger.info(f"Stream started: {stream_sid} for caller: {caller_info}")

                # Send initial alert to Harsh's Telegram
                telegram_msg_id = await telegram_service.send_call_started(call_sid, caller_info)

                # Speak initial greeting to the caller
                initial_greeting = conversation_history[1]["content"]
                transcript_display.append(f"🤖 **Jarvis:** {initial_greeting}")
                asyncio.create_task(send_tts_to_caller(initial_greeting))

            elif event == "media":
                media_payload = data.get("media", {}).get("payload", "")
                if not media_payload:
                    continue

                mulaw_bytes = base64.b64decode(media_payload)
                pcm_8k = ulaw_to_linear16(mulaw_bytes)
                pcm_16k = resample_pcm(pcm_8k, in_rate=8000, out_rate=16000)

                # Check speech energy
                energy = calculate_rms(pcm_16k)
                if energy > RMS_THRESHOLD:
                    # Caller is actively speaking
                    silence_frames = 0
                    audio_buffer.extend(pcm_16k)
                else:
                    # Silence detected
                    if len(audio_buffer) > 0:
                        silence_frames += 1
                        audio_buffer.extend(pcm_16k)

                        # Once silence exceeds limit, process turn
                        if silence_frames >= SILENCE_LIMIT_FRAMES:
                            recorded_audio = bytes(audio_buffer)
                            audio_buffer.clear()
                            silence_frames = 0

                            # Transcribe with Groq Whisper
                            user_text = await stt_service.transcribe(recorded_audio)
                            if user_text and len(user_text.strip()) > 1:
                                logger.info(f"Caller Said: {user_text}")
                                transcript_display.append(f"👤 **Caller:** {user_text}")
                                conversation_history.append({"role": "user", "content": user_text})

                                # Update live Telegram transcript
                                asyncio.create_task(
                                    telegram_service.update_live_transcript(
                                        telegram_msg_id, caller_info, transcript_display
                                    )
                                )

                                # Generate Jarvis response using NVIDIA LLM
                                full_reply = ""
                                async for sentence in llm_service.get_response_stream(conversation_history):
                                    full_reply += " " + sentence
                                    await send_tts_to_caller(sentence)

                                full_reply = full_reply.strip()
                                if full_reply:
                                    transcript_display.append(f"🤖 **Jarvis:** {full_reply}")
                                    conversation_history.append({"role": "assistant", "content": full_reply})
                                    asyncio.create_task(
                                        telegram_service.update_live_transcript(
                                            telegram_msg_id, caller_info, transcript_display
                                        )
                                    )

            elif event == "stop":
                logger.info(f"Stream stopped by caller: {stream_sid}")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed.")
    except Exception as e:
        logger.error(f"Error in media stream loop: {e}", exc_info=True)
    finally:
        # Wrap up call: summarize and notify Harsh
        full_transcript = "\n".join(transcript_display)
        if full_transcript.strip():
            logger.info("Generating post-call summary...")
            summary = await llm_service.generate_summary(full_transcript)
            await telegram_service.send_call_summary(
                call_sid, telegram_msg_id, caller_info, summary, full_transcript
            )

# -------------------------------------------------------------------
# 3. LOCAL SIMULATION / WEB TESTING DASHBOARD
# -------------------------------------------------------------------
class TestMessage(BaseModel):
    message: str
    history: List[Dict[str, str]] = []

@app.post("/api/test-turn")
async def test_turn(payload: TestMessage):
    """Allows testing Jarvis's LLM reasoning and Edge-TTS synthesis from your browser or curl."""
    history = payload.history
    if not history:
        history = llm_service.create_initial_history()

    history.append({"role": "user", "content": payload.message})

    # Get Jarvis response
    jarvis_reply_parts = []
    async for sentence in llm_service.get_response_stream(history):
        jarvis_reply_parts.append(sentence)
    
    jarvis_reply = " ".join(jarvis_reply_parts).strip()
    history.append({"role": "assistant", "content": jarvis_reply})

    return {
        "reply": jarvis_reply,
        "history": history
    }

class WhitelistItem(BaseModel):
    phone_number: str
    contact_name: str

@app.get("/api/tts")
async def get_tts(text: str):
    """Returns streaming MP3 audio for browser playback."""
    audio_bytes = await tts_service.generate_mp3_bytes(text)
    return Response(content=audio_bytes, media_type="audio/mpeg")

class SummaryRequest(BaseModel):
    transcript: str

@app.post("/api/test-summary")
async def test_summary(payload: SummaryRequest):
    """Generates post-call summary and forwards to Telegram for testing."""
    summary = await llm_service.generate_summary(payload.transcript)
    await telegram_service.send_call_summary(
        f"test_{int(time.time())}", None, "Simulator Test Caller", summary, payload.transcript
    )
    return {"summary": summary}

@app.get("/api/whitelist")
async def get_whitelist():
    return {
        "mode": rules_engine.get_mode(),
        "whitelist": rules_engine.get_whitelist()
    }

class ModeItem(BaseModel):
    mode: str

@app.post("/api/mode")
async def set_mode(item: ModeItem):
    rules_engine.set_mode(item.mode)
    return {"status": "success", "mode": item.mode}

@app.post("/api/whitelist")
async def add_whitelist(item: WhitelistItem):
    rules_engine.add_whitelist(item.phone_number, item.contact_name)
    return {"status": "success", "added": item.dict()}

@app.delete("/api/whitelist/{phone_number}")
async def remove_whitelist(phone_number: str):
    rules_engine.remove_whitelist(phone_number)
    return {"status": "success", "removed": phone_number}

# -------------------------------------------------------------------
# 4. FUTURISTIC WEB DASHBOARD (FOR LAPTOP & PHONE TESTING)
# -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>J.A.R.V.I.S. Voice Control Center</title>
    <style>
        :root {
            --bg: #090d16;
            --panel: #111827;
            --accent: #00d2ff;
            --accent-glow: rgba(0, 210, 255, 0.3);
            --text: #e2e8f0;
            --text-dim: #94a3b8;
            --card-border: #1e293b;
            --success: #10b981;
        }
        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 24px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }
        .logo {
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: 2px;
            color: var(--accent);
            text-shadow: 0 0 10px var(--accent-glow);
        }
        .status-badge {
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
            border: 1px solid var(--success);
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--success);
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }
        .card {
            background: var(--panel);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
        }
        h2 {
            margin-top: 0;
            font-size: 1.1rem;
            color: var(--accent);
            letter-spacing: 0.5px;
        }
        .chat-box {
            height: 320px;
            overflow-y: auto;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 12px;
            background: #0b1120;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .msg {
            padding: 8px 12px;
            border-radius: 8px;
            max-width: 85%;
            font-size: 0.95rem;
            line-height: 1.4;
        }
        .msg.caller {
            background: #1e293b;
            align-self: flex-start;
            border-left: 3px solid #64748b;
        }
        .msg.jarvis {
            background: rgba(0, 210, 255, 0.1);
            border-left: 3px solid var(--accent);
            align-self: flex-end;
        }
        .input-row {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }
        input, select, button {
            background: #0f172a;
            border: 1px solid var(--card-border);
            color: var(--text);
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 0.95rem;
        }
        input { flex: 1; }
        button {
            background: var(--accent);
            color: #090d16;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }
        button:hover {
            box-shadow: 0 0 12px var(--accent-glow);
        }
        .whitelist-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .del-btn {
            background: #ef4444;
            color: white;
            padding: 4px 8px;
            font-size: 0.75rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">⚡ J.A.R.V.I.S. VOICE ASSISTANT</div>
            <div class="status-badge">
                <span class="status-dot"></span> Online & Ready
            </div>
        </header>

        <div class="grid">
            <!-- Simulator Card -->
            <div class="card">
                <h2>🎙️ Live Call Simulator</h2>
                <p style="font-size: 0.85rem; color: var(--text-dim); margin-top: -6px;">
                    Test Jarvis right now without needing Twilio!
                </p>
                <div class="chat-box" id="chatBox">
                    <div class="msg jarvis">
                        <strong>J.A.R.V.I.S.:</strong> Hello. This is J.A.R.V.I.S., assistant to Mr. Stark. Mr. Stark is currently in an important meeting. May I ask who is calling and how I may assist you?
                    </div>
                </div>

                <!-- Status indicator -->
                <div id="statusIndicator" style="display: none; font-size: 0.85rem; color: var(--accent); margin-top: 8px; font-weight: 500;">
                    ⚡ <span id="statusText">Processing...</span>
                </div>

                <div style="display: flex; gap: 8px; margin-top: 10px; align-items: center; justify-content: space-between;">
                    <label style="font-size: 0.85rem; color: var(--text-dim); display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="checkbox" id="voiceToggle" checked style="width: auto; cursor: pointer;">
                        🔊 Voice: <strong>en-GB-RyanNeural</strong>
                    </label>
                    <div style="display: flex; gap: 6px;">
                        <button id="replayBtn" onclick="replayAudio()" style="display: none; background: #475569; font-size: 0.75rem; padding: 4px 8px;">
                            🔁 Replay Voice
                        </button>
                        <button onclick="endAndSummarize()" style="background: #3b82f6; font-size: 0.8rem; padding: 6px 12px;">
                            📋 End & Summarize Call
                        </button>
                    </div>
                </div>

                <!-- Input area with Mic & Send -->
                <div class="input-row" style="margin-top: 10px;">
                    <input type="text" id="userInput" placeholder="Type a message or click '🎙️ Mic' to speak..." />
                    <button id="micBtn" onclick="toggleMic()" style="background: #0284c7; min-width: 90px;">🎙️ Mic</button>
                    <button onclick="sendTurn()" style="min-width: 75px;">Send</button>
                </div>

                <!-- Quick-test Chips -->
                <div style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px;">
                    <span style="font-size: 0.75rem; color: var(--text-dim); align-self: center;">Quick Test:</span>
                    <button type="button" onclick="quickSend('Hi, this is Vikram from tech support. Is Harsh available?')" style="background: #1e293b; color: #94a3b8; font-size: 0.75rem; padding: 4px 8px;">
                        💼 Vikram (Work)
                    </button>
                    <button type="button" onclick="quickSend('Hi, this is Dr. Aris calling regarding Harsh\'s appointment.')" style="background: #1e293b; color: #94a3b8; font-size: 0.75rem; padding: 4px 8px;">
                        🏥 Dr. Aris
                    </button>
                    <button type="button" onclick="quickSend('Urgent: Server is down, please notify Harsh immediately.')" style="background: #1e293b; color: #ef4444; font-size: 0.75rem; padding: 4px 8px;">
                        🚨 Urgent Alert
                    </button>
                </div>

                <!-- Summary Display Area -->
                <div id="summaryCard" style="display: none; margin-top: 14px; background: #0b1120; border: 1px solid var(--accent); border-radius: 8px; padding: 12px;">
                    <h3 style="margin-top: 0; font-size: 0.95rem; color: var(--accent);">📊 Call Summary (Sent to Phone)</h3>
                    <pre id="summaryText" style="white-space: pre-wrap; font-size: 0.85rem; color: #cbd5e1; font-family: inherit; margin: 0;"></pre>
                </div>
            </div>

            <!-- Rules & Whitelist Card -->
            <div class="card">
                <h2>🛡️ Call Screening & Whitelist</h2>
                <p style="font-size: 0.85rem; color: var(--text-dim); margin-top: -6px;">
                    Control who Jarvis answers calls for.
                </p>
                <div style="margin-bottom: 16px;">
                    <label style="font-size: 0.85rem; color: var(--text-dim);">Screening Mode:</label>
                    <select id="modeSelect" onchange="changeMode()" style="width: 100%; margin-top: 4px;">
                        <option value="screen_unknown">Screen Unknown & Declined Calls (Recommended)</option>
                        <option value="whitelist_only">Whitelist Contacts Only</option>
                        <option value="all">Answer All Calls</option>
                    </select>
                </div>
                <div class="input-row" style="margin-bottom: 16px;">
                    <input type="text" id="wlName" placeholder="Name (e.g. Mom)" style="max-width: 120px;" />
                    <input type="text" id="wlNumber" placeholder="Phone (+91...)" />
                    <button onclick="addWhitelist()">Add</button>
                </div>
                <div id="whitelistList" style="max-height: 140px; overflow-y: auto;">
                    <!-- Whitelist entries loaded via JS -->
                </div>
            </div>
        </div>
    </div>

    <script>
        let history = [];
        let currentAudio = null;
        let lastReply = "";
        let recognition = null;
        let isRecording = false;

        // Initialize Speech Recognition if supported
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SpeechRec();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';

            recognition.onstart = () => {
                isRecording = true;
                document.getElementById('micBtn').innerText = '🔴 Listening...';
                document.getElementById('micBtn').style.background = '#ef4444';
                showStatus('🎙️ Listening to your microphone...');
            };

            recognition.onresult = (event) => {
                const speechResult = event.results[0][0].transcript;
                document.getElementById('userInput').value = speechResult;
                hideStatus();
                sendTurn();
            };

            recognition.onerror = (event) => {
                console.error("Speech recognition error:", event.error);
                stopMic();
                showStatus('⚠️ Microphone error: ' + event.error);
                setTimeout(hideStatus, 3000);
            };

            recognition.onend = () => {
                stopMic();
            };
        }

        function toggleMic() {
            if (!recognition) {
                alert("Speech recognition is not supported in this browser. Please type your message.");
                return;
            }
            if (isRecording) {
                recognition.stop();
            } else {
                try {
                    recognition.start();
                } catch (e) {
                    console.log("Mic start error:", e);
                }
            }
        }

        function stopMic() {
            isRecording = false;
            const btn = document.getElementById('micBtn');
            btn.innerText = '🎙️ Mic';
            btn.style.background = '#0284c7';
            hideStatus();
        }

        function showStatus(text) {
            const ind = document.getElementById('statusIndicator');
            document.getElementById('statusText').innerText = text;
            ind.style.display = 'block';
        }

        function hideStatus() {
            document.getElementById('statusIndicator').style.display = 'none';
        }

        function quickSend(sampleText) {
            document.getElementById('userInput').value = sampleText;
            sendTurn();
        }

        async function sendTurn() {
            const input = document.getElementById("userInput");
            let text = input.value.trim();
            if (!text) {
                // If user clicks send without typing, offer a helpful greeting test
                text = "Hello, is Harsh available?";
            }

            appendMsg("caller", "Caller: " + text);
            input.value = "";
            showStatus("⚡ Jarvis is thinking & synthesizing speech...");

            try {
                const res = await fetch("/api/test-turn", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ message: text, history: history })
                });
                const data = await res.json();
                history = data.history;
                lastReply = data.reply;
                appendMsg("jarvis", "J.A.R.V.I.S.: " + data.reply);
                document.getElementById('replayBtn').style.display = 'inline-block';

                // Play voice if toggle enabled
                if (document.getElementById("voiceToggle").checked && data.reply) {
                    playVoice(data.reply);
                } else {
                    hideStatus();
                }
            } catch (err) {
                hideStatus();
                appendMsg("jarvis", "J.A.R.V.I.S.: [Error: " + err + "]");
            }
        }

        function playVoice(text) {
            showStatus("🔊 Playing J.A.R.V.I.S. neural voice...");
            if (currentAudio) {
                currentAudio.pause();
            }
            currentAudio = new Audio("/api/tts?text=" + encodeURIComponent(text));
            currentAudio.onended = () => hideStatus();
            currentAudio.onerror = (e) => {
                console.error("Audio playback error:", e);
                hideStatus();
            };
            currentAudio.play().catch(e => {
                console.log("Audio play blocked by browser:", e);
                showStatus("⚠️ Click '🔁 Replay Voice' if audio was blocked by browser");
            });
        }

        function replayAudio() {
            if (lastReply) {
                playVoice(lastReply);
            }
        }

        async function endAndSummarize() {
            if (history.length === 0) {
                alert("Please have a brief conversation with Jarvis first.");
                return;
            }
            let transcript = history.map(h => (h.role === 'assistant' ? 'Jarvis: ' : 'Caller: ') + h.content).join("\n");
            
            const summaryCard = document.getElementById("summaryCard");
            const summaryText = document.getElementById("summaryText");
            summaryCard.style.display = "block";
            summaryText.innerText = "⏳ Generating AI summary and sending to Telegram...";

            try {
                const res = await fetch("/api/test-summary", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ transcript: transcript })
                });
                const data = await res.json();
                summaryText.innerText = data.summary;
            } catch (e) {
                summaryText.innerText = "Failed to generate summary: " + e;
            }
        }

        function appendMsg(cls, text) {
            const box = document.getElementById("chatBox");
            const div = document.createElement("div");
            div.className = "msg " + cls;
            div.innerText = text;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        async function loadWhitelist() {
            const res = await fetch("/api/whitelist");
            const data = await res.json();
            document.getElementById("modeSelect").value = data.mode;
            const listDiv = document.getElementById("whitelistList");
            listDiv.innerHTML = "";
            data.whitelist.forEach(item => {
                const row = document.createElement("div");
                row.className = "whitelist-item";
                row.innerHTML = `
                    <span><strong>${item.contact_name || 'Contact'}</strong>: ${item.phone_number}</span>
                    <button class="del-btn" onclick="removeWl('${item.phone_number}')">Remove</button>
                `;
                listDiv.appendChild(row);
            });
            if (data.whitelist.length === 0) {
                listDiv.innerHTML = '<div style="color: var(--text-dim); font-size: 0.85rem;">No contacts whitelisted yet.</div>';
            }
        }

        async function changeMode() {
            const mode = document.getElementById("modeSelect").value;
            await fetch("/api/mode", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mode: mode })
            });
        }

        async function addWhitelist() {
            const name = document.getElementById("wlName").value.trim();
            const num = document.getElementById("wlNumber").value.trim();
            if (!num) return;
            await fetch("/api/whitelist", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone_number: num, contact_name: name })
            });
            document.getElementById("wlName").value = "";
            document.getElementById("wlNumber").value = "";
            loadWhitelist();
        }

        async function removeWl(num) {
            await fetch("/api/whitelist/" + encodeURIComponent(num), { method: "DELETE" });
            loadWhitelist();
        }

        document.getElementById("userInput").addEventListener("keydown", (e) => {
            if (e.key === "Enter") sendTurn();
        });

        loadWhitelist();
    </script>
</body>
</html>
"""

# -------------------------------------------------------------------
# 5. HUGGING FACE FREE TIER (GRADIO MOUNT & ENTRYPOINT)
# -------------------------------------------------------------------
try:
    import gradio as gr
    with gr.Blocks(title="J.A.R.V.I.S. Voice Assistant") as demo:
        gr.Markdown(f"""
        # ⚡ J.A.R.V.I.S. Voice Assistant
        **Status:** 🟢 Online & Running 24/7 in the Cloud  
        **Assistant to:** {settings.USER_ALIAS} ({settings.USER_REAL_NAME})  
        **Inbound Webhook:** `/voice`  
        **WebSocket Audio:** `/media-stream`  
        """)
    app = gr.mount_gradio_app(app, demo, path="/gradio")
except Exception as e:
    logger.info(f"Gradio mount skipped or not installed: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)

