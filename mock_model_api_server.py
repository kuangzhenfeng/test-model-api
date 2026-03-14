#!/usr/bin/env python3

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_API_KEY = "test-key"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DOTENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local mock server for chat/completions and messages endpoints."
    )
    parser.add_argument("--host", default=os.getenv("MOCK_HOST", DEFAULT_HOST), help="Host to bind.")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MOCK_PORT", str(DEFAULT_PORT))),
        help="Port to listen on.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("API_KEY", DEFAULT_API_KEY),
        help="Expected API key for both endpoints.",
    )
    parser.add_argument(
        "--anthropic-version",
        default=os.getenv("ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION),
        help="Expected anthropic-version header for /messages.",
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


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    # 统一处理请求体解析，让两个端点共用同一套基础校验。
    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except ValueError:
        return None

    body = handler.rfile.read(length).decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_text_from_messages(payload: dict[str, Any]) -> str:
    # 把支持的多种消息内容格式整理成一段可读文本，便于 mock 回显。
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return "mock response"

    texts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])

    if not texts:
        return "mock response"
    return " | ".join(texts)


class MockModelAPIHandler(BaseHTTPRequestHandler):
    server_version = "MockModelAPI/1.0"

    def do_POST(self) -> None:
        # 统一入口分发两个兼容端点，避免重复处理请求解析逻辑。
        payload = parse_json_body(self)
        if payload is None:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Invalid JSON body"}},
            )
            return

        if self.path == "/chat/completions":
            self.handle_chat(payload)
            return

        if self.path == "/messages":
            self.handle_messages(payload)
            return

        self.send_json(
            HTTPStatus.NOT_FOUND,
            {"error": {"message": f"Unknown path: {self.path}"}},
        )

    def handle_chat(self, payload: dict[str, Any]) -> None:
        # OpenAI 兼容接口使用 Bearer 认证，响应体里返回 choices。
        auth_header = self.headers.get("Authorization")
        expected = f"Bearer {self.server.expected_api_key}"
        if auth_header != expected:
            self.send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"message": "Invalid Authorization header"}},
            )
            return

        if not self.valid_payload(payload):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Invalid request payload"}},
            )
            return

        prompt = build_text_from_messages(payload)
        response = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": f"chat mock reply: {prompt}",
                    },
                }
            ],
        }
        self.send_json(HTTPStatus.OK, response)

    def handle_messages(self, payload: dict[str, Any]) -> None:
        # Anthropic 兼容接口使用 x-api-key 和 anthropic-version。
        api_key = self.headers.get("x-api-key")
        version = self.headers.get("anthropic-version")

        if api_key != self.server.expected_api_key:
            self.send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"message": "Invalid x-api-key header"}},
            )
            return

        if version != self.server.expected_anthropic_version:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Invalid anthropic-version header"}},
            )
            return

        if not self.valid_payload(payload):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Invalid request payload"}},
            )
            return

        prompt = build_text_from_messages(payload)
        response = {
            "id": "msg_mock_001",
            "type": "message",
            "role": "assistant",
            "model": payload["model"],
            "content": [{"type": "text", "text": f"messages mock reply: {prompt}"}],
            "stop_reason": "end_turn",
        }
        self.send_json(HTTPStatus.OK, response)

    def valid_payload(self, payload: dict[str, Any]) -> bool:
        # mock 只校验测试脚本真正依赖的最小字段集合。
        messages = payload.get("messages")
        return (
            isinstance(payload.get("model"), str)
            and isinstance(payload.get("max_tokens"), int)
            and isinstance(messages, list)
        )

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


class MockHTTPServer(HTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        expected_api_key: str,
        expected_anthropic_version: str,
    ) -> None:
        super().__init__(server_address, handler_class)
        # 把共享配置挂到 server 上，方便每个请求处理器直接读取。
        self.expected_api_key = expected_api_key
        self.expected_anthropic_version = expected_anthropic_version


def main() -> int:
    load_dotenv(DOTENV_PATH)
    args = parse_args()
    server = MockHTTPServer(
        (args.host, args.port),
        MockModelAPIHandler,
        expected_api_key=args.api_key,
        expected_anthropic_version=args.anthropic_version,
    )

    print(f"Mock server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down mock server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
