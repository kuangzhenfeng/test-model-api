#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from typing import Any


# 默认配置
DEFAULT_BASE_URL = "http://YOUR_HOST:YOUR_PORT"
DEFAULT_API_KEY_ENV = "API_KEY"
DEFAULT_MODEL = "gpt-5"
DEFAULT_PROMPT = "Hello!"
DEFAULT_MAX_TOKENS = 1000
DEFAULT_ENDPOINT = "both"
DEFAULT_TIMEOUT = 60
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DOTENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


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
        default=os.getenv("BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("MODEL", DEFAULT_MODEL),
        help="Model name to send in the request.",
    )
    parser.add_argument(
        "--prompt",
        default=os.getenv("PROMPT", DEFAULT_PROMPT),
        help="User message content.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.getenv("MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        help="max_tokens value to send in the request.",
    )
    parser.add_argument(
        "--endpoint",
        choices=("chat", "messages", "both"),
        default=os.getenv("ENDPOINT", DEFAULT_ENDPOINT),
        help="Which endpoint to test.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("TIMEOUT", str(DEFAULT_TIMEOUT))),
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--anthropic-version",
        default=os.getenv("ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION),
        help=(
            "Anthropic messages API version header. "
            f"Defaults to {DEFAULT_ANTHROPIC_VERSION}."
        ),
    )
    return parser.parse_args()


def load_dotenv(path: str) -> None:
    # 直接读取本地 .env，避免额外依赖 python-dotenv。
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                os.environ.setdefault(key, value)


def build_payload(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }


def build_chat_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def build_messages_headers(api_key: str, anthropic_version: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": anthropic_version,
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


def looks_like_html(payload: dict[str, Any] | str) -> bool:
    if not isinstance(payload, str):
        return False
    stripped = payload.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def is_successful_api_response(status: int, payload: dict[str, Any] | str) -> bool:
    # 网关首页即使返回 200 HTML，也不能算模型接口调用成功。
    return 200 <= status < 300 and isinstance(payload, dict)


def build_candidate_urls(base_url: str, endpoint_path: str) -> list[str]:
    urls = [f"{base_url}{endpoint_path}"]
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.path.rstrip("/").endswith("/v1"):
        return urls

    # 有些网关根路径是管理页面，真正的 API 挂在 /v1 下。
    urls.append(f"{base_url}/v1{endpoint_path}")
    return urls


def should_retry_with_v1(status: int, payload: dict[str, Any] | str) -> bool:
    if status in (404, 405):
        return True
    return looks_like_html(payload)


def send_request_with_fallback(
    base_url: str,
    endpoint_path: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> tuple[str, int, float, dict[str, Any] | str]:
    # 先尝试用户提供的 base URL；如果根路径其实是网页，再回退到 /v1。
    candidate_urls = build_candidate_urls(base_url, endpoint_path)
    last_result: tuple[str, int, float, dict[str, Any] | str] | None = None

    for index, url in enumerate(candidate_urls):
        status, elapsed, response_payload = send_request(url, headers, payload, timeout)
        last_result = (url, status, elapsed, response_payload)

        if is_successful_api_response(status, response_payload):
            return last_result

        has_more_candidates = index < len(candidate_urls) - 1
        if not has_more_candidates or not should_retry_with_v1(status, response_payload):
            return last_result

    assert last_result is not None
    return last_result


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


def extract_model(payload: dict[str, Any] | str) -> str | None:
    # 调试路由和模型别名时，以服务端实际返回的 model 为准。
    if not isinstance(payload, dict):
        return None

    model = payload.get("model")
    if isinstance(model, str):
        return model

    return None


def print_result(
    name: str,
    url: str,
    status: int,
    elapsed: float,
    payload: dict[str, Any] | str,
) -> None:
    print(f"=== {name} ===")
    print(f"URL: {url}")
    print(f"HTTP status: {status}")
    print(f"Elapsed: {elapsed:.2f}s")

    model = extract_model(payload)
    if model:
        print(f"Model: {model}")

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
    load_dotenv(DOTENV_PATH)
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
                "/chat/completions",
                build_chat_headers(args.api_key),
            )
        )
    if args.endpoint in ("messages", "both"):
        endpoints.append(
            (
                "messages",
                "/messages",
                build_messages_headers(args.api_key, args.anthropic_version),
            )
        )

    failed = False
    for name, endpoint_path, headers in endpoints:
        url, status, elapsed, response_payload = send_request_with_fallback(
            base_url,
            endpoint_path,
            headers,
            payload,
            args.timeout,
        )
        print_result(name, url, status, elapsed, response_payload)
        if not is_successful_api_response(status, response_payload):
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
