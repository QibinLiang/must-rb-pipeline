"""Volcengine TTS client: voice clone + text-to-speech."""

import json
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from .logger import logger
from .retry import retry_on_http_error


class VolcengineTTSClient:
    """Client for Volcengine TTS (v3 standard + v1 clone)."""

    def __init__(
        self,
        api_key: str,
        appid: str,
        resource_id: str = "volc.service_type.10029",
    ):
        self.api_key = api_key
        self.appid = appid
        self.resource_id = resource_id
        self.v3_headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "X-Api-Resource-Id": resource_id,
        }
        self.v1_headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }

    # ------------------------------------------------------------------
    # Voice Clone (v1 API) - requires clone service license
    # ------------------------------------------------------------------

    def upload_audio(self, audio_path: Path) -> str:
        """Upload audio file for voice cloning. Returns audio_id."""
        url = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload"
        audio_bytes = audio_path.read_bytes()
        audio_b64 = __import__("base64").b64encode(audio_bytes).decode()

        payload = {"appid": self.appid, "type": "wap", "audio": audio_b64}
        response = httpx.post(url, headers=self.v1_headers, json=payload, timeout=120.0)
        response.raise_for_status()
        resp_data = response.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"Upload failed: {resp_data}")
        audio_id = resp_data.get("data", {}).get("audio_id")
        if not audio_id:
            raise ValueError(f"Upload failed: {resp_data}")
        logger.info(f"Audio uploaded, audio_id={audio_id}")
        return audio_id

    def submit_clone(self, audio_id: str, speaker_name: str = "redbook_speaker") -> str:
        """Submit voice clone training job. Returns speaker_id."""
        url = "https://openspeech.bytedance.com/api/v1/mega_tts/train/submit"
        payload = {
            "appid": self.appid,
            "speaker_name": speaker_name,
            "audio_id": audio_id,
            "audios": [{"object_key": audio_id}],
            "type": "wap",
            "model_type": 1,
        }
        response = httpx.post(url, headers=self.v1_headers, json=payload, timeout=30.0)
        response.raise_for_status()
        resp_data = response.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"Clone submit failed: {resp_data}")
        speaker_id = resp_data.get("data", {}).get("speaker_id")
        if not speaker_id:
            raise ValueError(f"Clone submit failed: {resp_data}")
        logger.info(f"Clone training submitted, speaker_id={speaker_id}")
        return speaker_id

    def query_clone_status(self, speaker_id: str) -> dict:
        """Query voice clone training status."""
        url = "https://openspeech.bytedance.com/api/v1/mega_tts/status"
        payload = {"appid": self.appid, "speaker_id": speaker_id}
        response = httpx.post(url, headers=self.v1_headers, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()

    def clone_voice(
        self,
        audio_path: Path,
        speaker_name: str = "redbook_speaker",
        poll_interval: int = 10,
    ) -> str:
        """Full voice clone pipeline: upload -> submit -> poll -> return speaker_id."""
        audio_id = self.upload_audio(audio_path)
        speaker_id = self.submit_clone(audio_id, speaker_name)

        max_wait = 600  # 10 minutes
        waited = 0
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            status_resp = self.query_clone_status(speaker_id)
            status = status_resp.get("data", {}).get("status", "")
            logger.info(f"Clone status: {status} (waited {waited}s)")
            if status == "Success":
                logger.info(f"Voice clone completed! speaker_id={speaker_id}")
                return speaker_id
            if status in ("Failed", "Error"):
                raise RuntimeError(f"Voice clone failed: {status_resp}")

        raise TimeoutError(f"Voice clone timeout after {max_wait}s")

    # ------------------------------------------------------------------
    # TTS Synthesis (v1 API) - cloned voices via volcano_mega
    # ------------------------------------------------------------------

    def synthesize_v1(
        self,
        text: str,
        speaker: str,
        output_path: Path,
        speed_ratio: float = 1.0,
    ) -> None:
        """Synthesize text to audio using v1 API (cloned voices).

        Cloned voices must use the volcano_mega cluster.
        """
        url = "https://openspeech.bytedance.com/api/v1/tts"
        payload = {
            "app": {"cluster": "volcano_mega"},
            "user": {"uid": "redbook"},
            "audio": {
                "voice_type": speaker,
                "encoding": "mp3",
                "speed_ratio": speed_ratio,
            },
            "request": {
                "reqid": str(uuid.uuid4()).replace("-", ""),
                "text": text,
                "operation": "query",
            },
        }

        response = httpx.post(url, headers=self.v1_headers, json=payload, timeout=60.0)
        response.raise_for_status()

        resp_data = response.json()
        if resp_data.get("code") != 3000:
            msg = resp_data.get("message", "Unknown error")
            raise RuntimeError(f"v1 TTS API error: {msg}")

        audio_b64 = resp_data.get("data")
        if not audio_b64:
            raise ValueError("No audio data in v1 response")

        audio_bytes = __import__("base64").b64decode(audio_b64)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        logger.info(f"Audio saved: {output_path} ({len(audio_bytes)} bytes)")

    # ------------------------------------------------------------------
    # TTS Synthesis (v3 API) - standard built-in voices
    # ------------------------------------------------------------------

    def synthesize_v3(
        self,
        text: str,
        speaker: str,
        output_path: Path,
        speed_ratio: float = 1.0,
    ) -> None:
        """Synthesize text to audio using v3 API (standard voices).

        Response format: JSON header + binary audio data.
        """
        url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        payload = {
            "req_params": {
                "text": text,
                "speaker": speaker,
                "additions": json.dumps(
                    {
                        "disable_markdown_filter": True,
                        "enable_language_detector": True,
                        "enable_latex_tn": True,
                    }
                ),
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    "speed": speed_ratio,
                },
            }
        }

        response = httpx.post(url, headers=self.v3_headers, json=payload, timeout=60.0)
        response.raise_for_status()

        # Parse mixed JSON + binary response
        content = response.content
        audio_bytes = self._parse_v3_response(content)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        logger.info(f"Audio saved: {output_path} ({len(audio_bytes)} bytes)")

    def _parse_v3_response(self, content: bytes) -> bytes:
        """Parse v3 API response.

        Supports two formats:
        1. NDJSON (newline-delimited JSON): each line has base64 audio in 'data' field
        2. Mixed format: single JSON header followed by binary audio
        """
        # Try NDJSON format first (base64 chunks separated by newlines).
        # Some chunks are status markers (e.g. code=20000000, message="OK",
        # data=null) and should be skipped.
        audio_parts: list[bytes] = []
        lines = content.split(b"\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "data" in chunk and isinstance(chunk["data"], str):
                audio_parts.append(__import__("base64").b64decode(chunk["data"]))

        if audio_parts:
            return b"".join(audio_parts)

        # Fall back to mixed format: JSON header + binary audio
        brace_count = 0
        in_json = False
        json_end = 0
        for i, b in enumerate(content):
            if b == ord("{"):
                if not in_json:
                    in_json = True
                brace_count += 1
            elif b == ord("}"):
                brace_count -= 1
                if brace_count == 0 and in_json:
                    json_end = i + 1
                    break

        if json_end == 0:
            raise ValueError("Could not find JSON boundary in response")

        data = json.loads(content[:json_end])
        if data.get("code") != 0:
            msg = data.get("message", "Unknown error")
            raise RuntimeError(f"TTS API error: {msg}")

        audio_data = content[json_end:]
        if not audio_data:
            raise ValueError("No audio data in response")

        return audio_data
