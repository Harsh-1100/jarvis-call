import io
import math
import struct
import wave
from typing import Tuple, List

# Attempt to load audioop (built-in in Python <= 3.12, available via audioop-lts in 3.13+)
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
    except ImportError:
        audioop = None

# Pure Python fallback for G.711 mu-law table if audioop is absent
_BIAS = 0x84
_CLIP = 32635

def _build_ulaw_tables():
    # Build decode table (ulaw 8-bit -> linear 16-bit)
    decode_table = []
    for i in range(256):
        u = ~i
        t = ((u & 0x0F) << 3) + _BIAS
        t <<= (u & 0x70) >> 4
        decode_table.append(struct.pack('<h', -(t - _BIAS) if (u & 0x80) == 0 else (t - _BIAS)))
    return b''.join(decode_table)

_ULAW_DECODE_BYTES = _build_ulaw_tables()

def ulaw_to_linear16(ulaw_bytes: bytes) -> bytes:
    """Converts 8-bit mu-law audio at 8kHz to 16-bit linear PCM."""
    if audioop:
        return audioop.ulaw2lin(ulaw_bytes, 2)
    # Fallback using precomputed lookup table
    out = bytearray(len(ulaw_bytes) * 2)
    for idx, b in enumerate(ulaw_bytes):
        out[idx*2 : idx*2+2] = _ULAW_DECODE_BYTES[b*2 : b*2+2]
    return bytes(out)

def linear16_to_ulaw(pcm_bytes: bytes) -> bytes:
    """Converts 16-bit linear PCM audio to 8-bit mu-law."""
    if audioop:
        return audioop.lin2ulaw(pcm_bytes, 2)
    
    # Fallback implementation
    out = bytearray(len(pcm_bytes) // 2)
    for i in range(0, len(pcm_bytes), 2):
        sample = struct.unpack('<h', pcm_bytes[i:i+2])[0]
        sign = 0x80 if sample < 0 else 0
        if sample < 0:
            sample = -sample
        sample = min(sample, _CLIP)
        sample += _BIAS
        exponent = 7
        for exp in range(8):
            if sample <= (0x7F << (exp + 3)):
                exponent = exp
                break
        mantissa = (sample >> (exponent + 3)) & 0x0F
        ulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
        out[i // 2] = ulaw_byte
    return bytes(out)

def resample_pcm(pcm_bytes: bytes, in_rate: int, out_rate: int) -> bytes:
    """Resamples 16-bit mono linear PCM audio between sample rates."""
    if in_rate == out_rate:
        return pcm_bytes
    if audioop:
        converted, _ = audioop.ratecv(pcm_bytes, 2, 1, in_rate, out_rate, None)
        return converted
    
    # Basic linear interpolation fallback
    num_in_samples = len(pcm_bytes) // 2
    if num_in_samples == 0:
        return b""
    in_samples = struct.unpack(f'<{num_in_samples}h', pcm_bytes)
    num_out_samples = int(num_in_samples * (out_rate / in_rate))
    out_samples = []
    for i in range(num_out_samples):
        in_idx = i * (in_rate / out_rate)
        idx_floor = int(in_idx)
        idx_ceil = min(idx_floor + 1, num_in_samples - 1)
        weight = in_idx - idx_floor
        val = int(in_samples[idx_floor] * (1.0 - weight) + in_samples[idx_ceil] * weight)
        out_samples.append(val)
    return struct.pack(f'<{len(out_samples)}h', *out_samples)

def create_wav_file(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Packs raw 16-bit mono linear PCM into a valid WAV container in memory."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)      # Mono
        wav.setsampwidth(2)      # 16-bit = 2 bytes
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return buf.getvalue()

def calculate_rms(pcm_bytes: bytes) -> float:
    """Calculates RMS (Root Mean Square) energy of 16-bit linear PCM audio."""
    if not pcm_bytes:
        return 0.0
    if audioop:
        return float(audioop.rms(pcm_bytes, 2))
    
    num_samples = len(pcm_bytes) // 2
    if num_samples == 0:
        return 0.0
    samples = struct.unpack(f'<{num_samples}h', pcm_bytes)
    sum_squares = sum(s * s for s in samples)
    return math.sqrt(sum_squares / num_samples)
