"""
src/ai_client.py — Bộ điều phối AI đa tầng (Gemini -> OpenAI-Compatible Fallback)
Hỗ trợ chuyển đổi mượt mà giữa Gemini và Ollama (Local) / OpenRouter / Groq (Cloud).
"""

import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ai_client")


class UnifiedAIClient:
    """
    Adapter AI thống nhất:
      - Primary : Google Gemini (mặc định gemini-3.8-flash)
      - Fallback: OpenAI-compatible endpoint (Ollama local qwen2.5 / qwen2.5-vl hoặc OpenRouter)
    Tự động kích hoạt Fallback khi Gemini gặp lỗi (503 Unavailable, 429 Rate Limit, Timeout, Quota).
    """

    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self._gemini_client = None

        self.fallback_base_url = os.getenv("FALLBACK_BASE_URL", "http://localhost:11434/v1")
        self.fallback_api_key = os.getenv("FALLBACK_API_KEY", "ollama")
        self.fallback_text_model = os.getenv("FALLBACK_TEXT_MODEL", "qwen2.5:7b")
        self.fallback_vision_model = os.getenv("FALLBACK_VISION_MODEL", "qwen2.5-vl:7b")
        self._fallback_client = None

    def _get_gemini(self):
        if self._gemini_client is None and self.gemini_api_key:
            from google import genai
            self._gemini_client = genai.Client(api_key=self.gemini_api_key)
        return self._gemini_client

    def _get_fallback(self):
        if self._fallback_client is None:
            from openai import OpenAI
            self._fallback_client = OpenAI(
                base_url=self.fallback_base_url,
                api_key=self.fallback_api_key,
                timeout=3.0
            )
        return self._fallback_client

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Lọc bỏ markdown code blocks ```json ... ``` nếu model trả về thừa."""
        t = text.strip()
        if t.startswith("```"):
            lines = t.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            t = "\n".join(lines).strip()
        return t

    # ══════════════════════════════════════════════════════════════════════════
    # 1. TEXT / NLP GENERATION (Cho brain.py)
    # ══════════════════════════════════════════════════════════════════════════

    def generate_json_text(self, prompt: str, system_instruction: str) -> Dict[str, Any]:
        """Gọi Gemini dịch lệnh text, tự động fallback sang model Gemini khác hoặc Qwen2.5 nếu lỗi."""
        # ── Bước 1: Thử nghiệm Gemini (Primary & Backup Gemini Models) ──
        if self.gemini_api_key:
            from google.genai import types
            client = self._get_gemini()
            models_to_try = [self.gemini_model, "gemini-3.5-flash", "gemini-flash-latest"]
            for m in models_to_try:
                try:
                    logger.info("[AI_CLIENT] Đang gọi Gemini NLP với model: %s...", m)
                    response = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json"
                        )
                    )
                    clean_txt = self._clean_json_text(response.text)
                    return json.loads(clean_txt)
                except Exception as e:
                    logger.warning("[AI_CLIENT] ⚠️ Gemini model '%s' gặp sự cố (%s). Thử model kế tiếp...", m, e)

        # ── Bước 2: Fallback sang OpenAI-Compatible (Ollama / OpenRouter) ──
        logger.info("[AI_CLIENT] Kích hoạt Fallback Model (%s)...", self.fallback_text_model)
        try:
            client = self._get_fallback()
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
            response = client.chat.completions.create(
                model=self.fallback_text_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            raw_text = response.choices[0].message.content or "{}"
            clean_txt = self._clean_json_text(raw_text)
            return json.loads(clean_txt)
        except Exception as e:
            logger.error("[AI_CLIENT] ❌ Toàn bộ AI Provider đều thất bại: %s", e)
            return {"error": f"Lỗi toàn bộ AI Provider: {e}"}

    # ══════════════════════════════════════════════════════════════════════════
    # 2. VISION MULTIMODAL GENERATION (Cho core_vision.py)
    # ══════════════════════════════════════════════════════════════════════════

    def generate_json_vision(self, frame: np.ndarray, prompt: str, system_instruction: str = "") -> Dict[str, Any]:
        """Gọi Gemini Vision, tự động fallback sang backup model hoặc Qwen2.5-VL nếu lỗi."""
        _, jpeg_buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        jpeg_bytes = jpeg_buf.tobytes()

        # ── Bước 1: Thử nghiệm Gemini Vision ──
        if self.gemini_api_key:
            from google.genai import types
            client = self._get_gemini()
            contents = [
                types.Part.from_bytes(data=jpeg_bytes, mime_type='image/jpeg'),
                prompt
            ]
            config = types.GenerateContentConfig(response_mime_type="application/json")
            if system_instruction:
                config.system_instruction = system_instruction

            models_to_try = [self.gemini_model, "gemini-3.5-flash", "gemini-flash-latest"]
            for m in models_to_try:
                try:
                    logger.info("[AI_CLIENT] Đang gọi Gemini Vision với model: %s...", m)
                    response = client.models.generate_content(
                        model=m,
                        contents=contents,
                        config=config
                    )
                    clean_txt = self._clean_json_text(response.text)
                    return json.loads(clean_txt)
                except Exception as e:
                    logger.warning("[AI_CLIENT] ⚠️ Gemini Vision model '%s' gặp sự cố (%s). Thử model kế tiếp...", m, e)

        # ── Bước 2: Fallback sang Qwen2.5-VL (Ollama / OpenRouter) ──
        logger.info("[AI_CLIENT] Kích hoạt VLM Fallback (%s)...", self.fallback_vision_model)
        try:
            client = self._get_fallback()
            b64_img = base64.b64encode(jpeg_bytes).decode('utf-8')
            data_url = f"data:image/jpeg;base64,{b64_img}"

            system_msg = system_instruction or (
                "Bạn là trợ lý thị giác máy tính cho game automation. "
                "Luôn trả về kết quả bằng định dạng JSON thuần tuý, không kèm giải thích markdown."
            )

            messages = [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ]

            response = client.chat.completions.create(
                model=self.fallback_vision_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            raw_text = response.choices[0].message.content or "{}"
            clean_txt = self._clean_json_text(raw_text)
            return json.loads(clean_txt)
        except Exception as e:
            logger.error("[AI_CLIENT] ❌ VLM Fallback thất bại: %s", e)
            return {"found": False, "screen_type": "unknown", "action": "none", "description": str(e)}
