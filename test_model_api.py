#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


# 默认配置
DEFAULT_BASE_URL = "http://YOUR_HOST:YOUR_PORT"
DEFAULT_API_KEY_ENV = "API_KEY"
DEFAULT_MODEL = "gpt-5"
DEFAULT_PROMPT = "Hello!"
DEFAULT_MAX_TOKENS = 1000
DEFAULT_ENDPOINT = "both"
DEFAULT_TIMEOUT = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test the chat/completions and messages API endpoints."
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv(DEFAULT_API_KEY_ENV),
        help=f"API key. Defaults to the {DEFAULT_API_KEY_ENV} environment variable.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model name to send in the request.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="User message content.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="max_tokens value to send in the request.",
    )
    parser.add_argument(
        "--endpoint",
        choices=("chat", "messages", "both"),
        default=DEFAULT_ENDPOINT,
        help="Which endpoint to test.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds.",
    )
    return parser.parse_args()


def build_payload(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }


def send_request(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> tuple[int, float, dict[str, Any] | str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    started_at = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            elapsed = time.perf_counter() - started_at
            body = response.read().decode("utf-8")
            return response.status, elapsed, try_parse_json(body)
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - started_at
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, elapsed, try_parse_json(body)
    except urllib.error.URLError as exc:
        elapsed = time.perf_counter() - started_at
        return 0, elapsed, f"Network error: {exc}"


def try_parse_json(value: str) -> dict[str, Any] | str:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def extract_text(payload: dict[str, Any] | str) -> str | None:
    if not isinstance(payload, dict):
        return None

    # OpenAI 风格的 chat/completions 响应通常在这里返回文本。
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(item["text"])
            if texts:
                return "\n".join(texts)

    # 有些 message 接口会直接在顶层 content 返回文本。
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        if texts:
            return "\n".join(texts)

    return None


def print_result(name: str, url: str, status: int, elapsed: float, payload: dict[str, Any] | str) -> None:
    print(f"=== {name} ===")
    print(f"URL: {url}")
    print(f"HTTP status: {status}")
    print(f"Elapsed: {elapsed:.2f}s")

    text = extract_text(payload)
    if text:
        print("Assistant text:")
        print(text)
    else:
        print("Response body:")
        if isinstance(payload, str):
            print(payload)
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print(
            f"Missing API key. Use --api-key or set {DEFAULT_API_KEY_ENV}.",
            file=sys.stderr,
        )
        return 1

    base_url = args.base_url.rstrip("/")
    payload = build_payload(args.model, args.prompt, args.max_tokens)

    # 这两个接口使用不同的认证请求头。
    endpoints: list[tuple[str, str, dict[str, str]]] = []
    if args.endpoint in ("chat", "both"):
        endpoints.append(
            (
                "chat/completions",
                f"{base_url}/chat/completions",
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {args.api_key}",
                },
            )
        )
    if args.endpoint in ("messages", "both"):
        endpoints.append(
            (
                "messages",
                f"{base_url}/messages",
                {
                    "Content-Type": "application/json",
                    "X-API-Key": args.api_key,
                },
            )
        )

    failed = False
    for name, url, headers in endpoints:
        status, elapsed, response_payload = send_request(url, headers, payload, args.timeout)
        print_result(name, url, status, elapsed, response_payload)
        if status < 200 or status >= 300:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
