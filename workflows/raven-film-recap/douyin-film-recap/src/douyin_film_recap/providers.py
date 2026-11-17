from __future__ import annotations

import base64
import mimetypes
import json
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from .config import ModelConfig
from .send_guard import check_active_send, guarded_send
from .utils import extract_json_object

T = TypeVar("T", bound=BaseModel)

# Intent-key namespace for chat_json requests whose schema prompt is rendered as JSON.
SCHEMA_PROMPT_FORMAT = "schema-json"


class ProviderError(RuntimeError):
    """Raised when a model provider cannot return a usable response."""


class OpenAICompatibleClient:
    """Small OpenAI-compatible client with structured-output fallback.

    It intentionally avoids a provider-specific SDK so the Skill can work with
    public cloud APIs, enterprise gateways, or local OpenAI-compatible servers.
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self.base_url = config.base_url()
        self.api_key = config.api_key()
        self.timeout = httpx.Timeout(config.timeout_sec)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def healthcheck(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=min(self.config.timeout_sec, 20.0)) as client:
                response = client.get(f"{self.base_url}/models", headers=self.headers)
            if response.status_code < 400:
                return True, f"HTTP {response.status_code}"
            return False, f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:  # pragma: no cover - network dependent
            return False, str(exc)

    @staticmethod
    def _image_part(path: str | Path) -> dict[str, Any]:
        image_path = Path(path)
        mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        }

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return "\n".join(parts)
        return str(content)

    def chat(
        self,
        *,
        system: str,
        prompt: str,
        vision: bool = False,
        images: list[str | Path] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        intent_key: str | None = None,
        superseded_intent_key: str | None = None,
    ) -> str:
        model = self.config.vlm_model if vision else self.config.llm_model
        user_content: str | list[dict[str, Any]]
        if images:
            user_content = [{"type": "text", "text": prompt}]
            user_content.extend(self._image_part(path) for path in images)
        else:
            user_content = prompt

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        for fallback in range(2):
            def send():
                with httpx.Client(timeout=self.timeout) as client:
                    check_active_send()
                    response = client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=payload,
                    )
                return {"status_code": response.status_code, "text": response.text}

            observed = guarded_send("chat", {"endpoint": f"{self.base_url}/chat/completions",
                                             "body": payload}, send,
                intent_key=f"{intent_key}:format-{fallback}" if intent_key else None,
                superseded_keys=(f"{superseded_intent_key}:format-{fallback}",) if superseded_intent_key else ())
            if observed["status_code"] >= 400:
                # Only an observed rejection can trigger this separately reserved send.
                if observed["status_code"] in {400, 404, 422} and "response_format" in payload:
                    payload.pop("response_format", None)
                    continue
                raise ProviderError(f"Provider HTTP {observed['status_code']}: {observed['text'][:1000]}")
            try:
                data = json.loads(observed["text"])
            except ValueError as exc:
                raise ProviderError("Provider returned invalid response JSON; response preserved") from exc
            choices = data.get("choices") or []
            if not choices:
                raise ProviderError(f"Provider response has no choices: {str(data)[:1000]}")
            message = choices[0].get("message", {})
            return self._message_text(message.get("content", ""))
        raise ProviderError("Structured-output fallback exhausted")

    def chat_json(
        self,
        *,
        system: str,
        prompt: str,
        model_type: type[T],
        vision: bool = False,
        images: list[str | Path] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        intent_key: str | None = None,
    ) -> T:
        # Render the schema as JSON, not a Python dict repr (single quotes, True,
        # None), which invites invalid JSON replies and paid repair requests.
        schema = json.dumps(model_type.model_json_schema(), ensure_ascii=False, sort_keys=True)
        schema_prompt = (
            f"\n\n你必须只输出满足下列 JSON Schema 的 JSON，不要输出 Markdown 或解释：\n{schema}"
        )
        # Prompt bytes changed with the JSON rendering; a separate key namespace
        # keeps old intents from turning reruns into SEND_INTENT_PAYLOAD_CHANGED,
        # while UNKNOWN sends under the former keys still block the replacement.
        legacy_key = intent_key
        intent_key = f"{intent_key}:{SCHEMA_PROMPT_FORMAT}" if intent_key else None
        raw = self.chat(
            system=system,
            prompt=prompt + schema_prompt,
            vision=vision,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            intent_key=intent_key,
            superseded_intent_key=legacy_key,
        )
        try:
            return model_type.model_validate(extract_json_object(raw))
        except Exception as exc:
            repair_prompt = (
                "下面的模型输出未通过 JSON Schema 校验。只修复结构、字段类型与缺失字段，"
                "不要改变原有事实判断。只返回合法 JSON。\n\n"
                f"原始输出：\n{raw}\n\n校验错误：\n{exc}\n\nJSON Schema：\n{schema}"
            )
            repaired = self.chat(
                system="你是严格的 JSON 修复器。不得补造没有来源的事实。",
                prompt=repair_prompt,
                vision=False,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                intent_key=f"{intent_key}:json-repair" if intent_key else None,
                superseded_intent_key=f"{legacy_key}:json-repair" if legacy_key else None,
            )
            try:
                return model_type.model_validate(extract_json_object(repaired))
            except Exception as repair_exc:
                raise ProviderError(
                    f"Structured response validation failed: {repair_exc}"
                ) from repair_exc
