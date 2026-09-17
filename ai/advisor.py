"""脱敏诊断快照并调用 OpenAI 兼容接口（默认 DeepSeek 官网）。"""

from __future__ import annotations

import json
import re
from typing import Any

from ai.catalog import chat_completions_url, model_uses_thinking
from ai.prompt import SYSTEM_PROMPT
from core.models import Snapshot

_IP_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


def mask_ip(text: str) -> str:
    def repl(match: re.Match) -> str:
        a, b, c, d = match.groups()
        return f"{a}.{b}.x.x"

    return _IP_RE.sub(repl, text)


def sanitize_snapshot(snapshot: Snapshot) -> dict[str, Any]:
    data = snapshot.to_dict()
    data.pop("rdp", None)
    for peer in data.get("peers") or []:
        peer.pop("remote_snapshot", None)
        peer["tx_bytes"] = 0
        peer["rx_bytes"] = 0
    text = json.dumps(data, ensure_ascii=False)
    text = mask_ip(text)
    text = re.sub(r"[\w.\-]+@[\w.\-]+", "[email]", text)
    return json.loads(text)


def _http_error(resp) -> str:
    code = resp.status_code
    body = ""
    try:
        payload = resp.json()
        err = payload.get("error") or payload
        if isinstance(err, dict):
            body = str(err.get("message") or err.get("msg") or payload)[:400]
        else:
            body = str(err)[:400]
    except Exception:
        body = (resp.text or "")[:400]
    if code == 401:
        return "API Key 无效或未开通。请到 platform.deepseek.com 检查密钥。"
    if code == 402:
        return "账户余额不足，请先在 DeepSeek 平台充值。"
    if code == 429:
        return "请求过于频繁，请稍后再试。"
    return f"接口返回 {code}。{body}".strip()


def _post_chat(*, base_url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    import requests

    url = chat_completions_url(base_url)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if not resp.ok:
        raise RuntimeError(_http_error(resp))
    return resp.json()


def _message_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("模型没有返回内容。")
    msg = choices[0].get("message") or {}
    content = str(msg.get("content") or "").strip()
    if content:
        return content
    reasoning = str(msg.get("reasoning_content") or "").strip()
    if reasoning:
        return reasoning
    raise RuntimeError("模型返回为空。")


def _payload(model: str, messages: list[dict[str, str]], *, thinking: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    deepseek = model_uses_thinking(model) or (model or "").startswith("deepseek")
    if deepseek:
        if thinking:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = "high"
        else:
            body["thinking"] = {"type": "disabled"}
            body["temperature"] = 0.2
    else:
        body["temperature"] = 0.2
    return body


def advise(snapshot: Snapshot, *, base_url: str, model: str, api_key: str, timeout: int = 120) -> str:
    if not api_key:
        raise ValueError("未配置 API Key")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "诊断快照（已脱敏）：\n" + json.dumps(sanitize_snapshot(snapshot), ensure_ascii=False)[:12000],
        },
    ]
    data = _post_chat(
        base_url=base_url,
        api_key=api_key,
        payload=_payload(model, messages, thinking=model_uses_thinking(model)),
        timeout=timeout,
    )
    return _message_text(data)


def ping_model(*, base_url: str, model: str, api_key: str, timeout: int = 45) -> str:
    if not api_key:
        raise ValueError("未配置 API Key")
    messages = [
        {"role": "system", "content": "只用一句话确认你已接通。"},
        {"role": "user", "content": "请回复：已接通。"},
    ]
    data = _post_chat(
        base_url=base_url,
        api_key=api_key,
        payload=_payload(model, messages, thinking=False),
        timeout=timeout,
    )
    return _message_text(data)


def parse_sse_line(line: str) -> tuple[str, str] | None:
    if not line:
        return None
    raw = line.strip()
    if not raw.startswith("data:"):
        return None
    payload = raw[5:].strip()
    if payload == "[DONE]":
        return ("done", "")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    err = data.get("error")
    if err:
        if isinstance(err, dict):
            return ("error", str(err.get("message") or err))
        return ("error", str(err))
    choices = data.get("choices") or []
    if not choices:
        return None
    delta = choices[0].get("delta") or {}
    reasoning = delta.get("reasoning_content")
    if reasoning:
        return ("reasoning", str(reasoning))
    content = delta.get("content")
    if content:
        return ("content", str(content))
    return None


def stream_chat(
    *,
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    thinking: bool = True,
    timeout: int = 120,
):
    if not api_key:
        raise ValueError("未配置 API Key")
    import requests

    payload = _payload(model, messages, thinking=thinking)
    payload["stream"] = True
    if thinking:
        payload["reasoning_effort"] = "low"
    url = chat_completions_url(base_url)
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
        stream=True,
    )
    if not resp.ok:
        raise RuntimeError(_http_error(resp))
    for raw in resp.iter_lines(decode_unicode=True):
        event = parse_sse_line(raw or "")
        if not event:
            continue
        kind, text = event
        if kind == "done":
            break
        yield kind, text
