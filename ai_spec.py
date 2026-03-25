"""
ai_spec.py — Full AI Render Spec Generator
==========================================
Calls Google Gemini Flash API (server-side key, free tier) to produce a complete RenderSpec JSON.
BGM, Duration, Resolution are intentionally OUTSIDE the AI scope (manual user control).
"""
import json
import os

CAPTION_COLORS_MAP = {
    "Gold"      : (255, 215,   0),
    "White"     : (255, 255, 255),
    "Silver"    : (192, 192, 192),
    "Champagne" : (255, 223, 128),
    "Rose Gold" : (210, 180, 140),
}

DEFAULT_SPEC = {
    "segment_order": [],
    "trim": {},
    "transition": {"type": "Crossfade", "duration": 0.4},
    "captions": [],
    "font": "",
    "color_grade": {
        "enabled"   : True,
        "brightness": 1.05,
        "contrast"  : 1.10,
        "saturation": 1.05,
        "sharpness" : 1.10,
    },
    "reasoning": "",
}


def build_full_ai_prompt(
    clips: list[dict],
    description: str,
    style_prompt: str,
    available_fonts: list[str],
    n_captions: int = 3,
) -> str:
    clips_info = "\n".join(
        f"  [{c['index']}] {c['name']} — {c['duration']:.1f}s"
        + (f", score={c['score']:.2f}" if "score" in c else "")
        for c in clips
    )
    font_list  = ", ".join(available_fonts[:8]) if available_fonts else "DejaVu Sans Bold"
    first_font = available_fonts[0] if available_fonts else "DejaVu Sans Bold"

    return f"""Kamu adalah AI Director profesional untuk video properti di TikTok & Instagram (format 9:16 portrait).

DESKRIPSI PROPERTI:
{description}

INSTRUKSI GAYA:
{style_prompt.strip() if style_prompt.strip() else "Video properti modern, elegan, premium. Hook kuat dari scene terbaik. Tone warm dan aspirasional."}

KLIP TERSEDIA (index, nama, durasi, quality score 0-1):
{clips_info}

FONT TERSEDIA: {font_list}

Tugas: Hasilkan FULL RENDER SPEC. Balas dengan JSON SAJA, tanpa teks lain.

{{
  "segment_order": [urutan index klip, dari paling impresif ke penutup],
  "trim": {{
    "0": {{"start": 0.5, "end": 5.0}},
    "1": {{"start": 0.5, "end": 5.0}}
  }},
  "transition": {{
    "type": "Crossfade",
    "duration": 0.4
  }},
  "captions": [
    {{"text": "TEKS HOOK UPPERCASE", "color": "Gold", "align": "Center"}},
    {{"text": "Fitur Unggulan", "color": "White", "align": "Left"}}
  ],
  "font": "{first_font}",
  "color_grade": {{
    "enabled": true,
    "brightness": 1.05,
    "contrast": 1.15,
    "saturation": 1.10,
    "sharpness": 1.20
  }},
  "reasoning": "penjelasan singkat keputusan AI"
}}

ATURAN PENTING:
- segment_order: eksterior terbaik sebagai hook (posisi 1), tutup dengan view/lokasi/rooftop
- trim: setiap segmen 4–6 detik. start ≥ 0.3s dari awal, end ≤ durasi_klip - 0.3s
- transition.type: "Crossfade" | "Fade to Black" | "Tanpa Transisi"
- captions: TEPAT {n_captions} caption. Caption[0]=HOOK uppercase ≤4 kata. Selanjutnya fitur unggulan ≤7 kata.
- captions[*].color: "Gold"|"White"|"Silver"|"Champagne"|"Rose Gold". Hook selalu Gold.
- captions[*].align: "Center"|"Left"|"Right"
- color_grade properti premium: contrast 1.1–1.2, saturation 1.05–1.15, sharpness 1.1–1.3
- font: pilih yang paling bold/impactful untuk properti premium"""


def _extract_json(raw: str) -> str:
    """Strip markdown code blocks and return clean JSON string."""
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                return part
    return raw


class QuotaExceededError(Exception):
    """Raised when the AI provider's rate limit / daily quota is hit."""

class InvalidKeyError(Exception):
    """Raised when the API key is invalid or unauthorized."""


def _call_gemini(prompt: str, api_key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=1200),
    )
    try:
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("quota", "resource_exhausted", "resourceexhausted", "429", "rate limit", "too many")):
            raise QuotaExceededError("gemini")
        if any(k in msg for k in ("api key", "invalid", "401", "403", "unauthorized", "permission")):
            raise InvalidKeyError("gemini")
        raise


def _call_anthropic(prompt: str, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("rate_limit", "overloaded", "529", "429", "quota", "too many")):
            raise QuotaExceededError("anthropic")
        if any(k in msg for k in ("authentication", "invalid x-api-key", "401", "403", "unauthorized")):
            raise InvalidKeyError("anthropic")
        raise


def call_full_ai_spec(
    clips           : list[dict],
    description     : str,
    style_prompt    : str,
    available_fonts : list[str],
    n_captions      : int = 3,
    user_api_key    : str = "",
    user_key_provider: str = "",   # "gemini" | "anthropic" | ""
) -> dict:
    """
    Generate RenderSpec via AI.

    Priority:
      1. user_api_key + user_key_provider  → pakai key milik user
      2. GEMINI_API_KEY env var            → server free tier
      3. Raise ValueError                  → tidak ada key tersedia
    """
    prompt = build_full_ai_prompt(clips, description, style_prompt, available_fonts, n_captions)

    if user_api_key.strip():
        # User pakai key sendiri
        provider = user_key_provider.lower().strip()
        if provider == "anthropic":
            raw = _call_anthropic(prompt, user_api_key.strip())
        else:
            raw = _call_gemini(prompt, user_api_key.strip())
    else:
        # Server free tier (Gemini)
        server_key = os.getenv("GEMINI_API_KEY", "")
        if not server_key:
            raise ValueError("GEMINI_API_KEY belum dikonfigurasi di server.")
        raw = _call_gemini(prompt, server_key)

    return json.loads(_extract_json(raw))


def validate_and_fill(spec: dict, clips: list[dict], n_captions: int) -> dict:
    """Validate spec from Claude and fill in defaults for missing/invalid fields."""
    import copy
    result  = copy.deepcopy(DEFAULT_SPEC)
    n_clips = len(clips)
    all_idx = list(range(n_clips))

    # ── segment_order ────────────────────────────────────────────────────────
    order = [i for i in spec.get("segment_order", [])
             if isinstance(i, int) and 0 <= i < n_clips]
    for i in all_idx:
        if i not in order:
            order.append(i)
    result["segment_order"] = order

    # ── trim ─────────────────────────────────────────────────────────────────
    raw_trim = spec.get("trim", {})
    result["trim"] = {}
    for c in clips:
        key = str(c["index"])
        dur = float(c.get("duration", 10.0))
        t   = raw_trim.get(key) or raw_trim.get(c["index"])
        if isinstance(t, dict):
            s = max(0.3, float(t.get("start", 0.5)))
            e = min(dur - 0.3, float(t.get("end", s + 5.0)))
            if e - s < 2.0:
                e = min(s + 5.0, dur - 0.3)
        else:
            s = 0.5
            e = min(5.5, dur - 0.3)
            e = max(s + 2.0, e)
        result["trim"][key] = {"start": round(s, 2), "end": round(e, 2)}

    # ── transition ───────────────────────────────────────────────────────────
    trans       = spec.get("transition", {})
    valid_trans = ["Crossfade", "Fade to Black", "Tanpa Transisi"]
    t_type      = trans.get("type", "Crossfade")
    if t_type not in valid_trans:
        t_type = "Crossfade"
    t_dur = max(0.2, min(1.5, float(trans.get("duration", 0.4))))
    result["transition"] = {"type": t_type, "duration": t_dur}

    # ── captions ─────────────────────────────────────────────────────────────
    valid_colors = list(CAPTION_COLORS_MAP.keys())
    valid_aligns = ["Center", "Left", "Right"]
    filled       = []
    for i, cap in enumerate(spec.get("captions", [])[:n_captions]):
        text  = str(cap.get("text", f"CAPTION {i+1}")).strip() or f"CAPTION {i+1}"
        color = cap.get("color", "Gold" if i == 0 else "White")
        if color not in valid_colors:
            color = "Gold" if i == 0 else "White"
        align = cap.get("align", "Center")
        if align not in valid_aligns:
            align = "Center"
        filled.append({"text": text, "color": color, "align": align})
    while len(filled) < n_captions:
        filled.append({"text": f"CAPTION {len(filled)+1}", "color": "White", "align": "Center"})
    result["captions"] = filled

    # ── font ─────────────────────────────────────────────────────────────────
    result["font"] = str(spec.get("font", ""))

    # ── color_grade ──────────────────────────────────────────────────────────
    cg = spec.get("color_grade", {})
    result["color_grade"] = {
        "enabled"   : bool(cg.get("enabled", True)),
        "brightness": max(0.7, min(1.5, float(cg.get("brightness", 1.05)))),
        "contrast"  : max(0.7, min(1.5, float(cg.get("contrast",   1.10)))),
        "saturation": max(0.7, min(1.5, float(cg.get("saturation", 1.05)))),
        "sharpness" : max(0.7, min(2.0, float(cg.get("sharpness",  1.10)))),
    }

    result["reasoning"] = str(spec.get("reasoning", ""))
    return result
