# test-model-api

这个仓库包含两个本地工具：

- `test_model_api.py`：测试 `/chat/completions` 和 `/messages` 接口。
- `mock_model_api_server.py`：本地 mock 服务，方便联调和回归验证。

## 快速使用

1. 基于示例文件创建本地配置：

```bash
cp .env.example .env
```

2. 编辑 `.env`，至少填写这些值：

```dotenv
BASE_URL=http://your-host:your-port
API_KEY=your-api-key
```

3. 运行测试脚本：

```bash
python3 test_model_api.py
```

脚本会自动读取项目根目录下的 `.env`，并请求：

- `${BASE_URL}/chat/completions`
- `${BASE_URL}/messages`

如果两个端点都返回 `HTTP status: 200`，说明调用正常。

## 配置

项目根目录下提供了两个环境文件：

- `.env`：本地默认配置，脚本启动时会自动加载。
- `.env.example`：示例模板，便于复制到新环境。

`.env` 已加入 `.gitignore`，默认不应提交真实密钥。

当前支持的环境变量：

- `BASE_URL`
- `API_KEY`
- `MODEL`
- `PROMPT`
- `MAX_TOKENS`
- `ENDPOINT`
- `TIMEOUT`
- `ANTHROPIC_VERSION`
- `MOCK_HOST`
- `MOCK_PORT`

## 启动本地 mock 服务

```bash
python3 mock_model_api_server.py
```

默认会读取 `.env` 中的 `API_KEY`、`ANTHROPIC_VERSION`、`MOCK_HOST` 和 `MOCK_PORT`。

如果需要覆盖配置，可以直接传命令行参数：

```bash
python3 mock_model_api_server.py --host 127.0.0.1 --port 9000 --api-key test-key
```

## 运行测试脚本

```bash
python3 test_model_api.py
```

脚本会自动读取 `.env` 中的配置，并分别请求：

- `${BASE_URL}/chat/completions`
- `${BASE_URL}/messages`

也可以通过命令行覆盖 `.env` 中的值：

```bash
python3 test_model_api.py --api-key test-key --base-url http://127.0.0.1:8765 --endpoint both
```

## 一个典型联调流程

1. 启动本地 mock 服务。
2. 运行测试脚本确认两个端点都返回 `200`。
3. 切换 `.env` 中的 `BASE_URL` 和 `API_KEY`，再对真实服务执行相同测试。

## 说明

- 如果你的 `/messages` 接口兼容 Anthropic Messages API，通常仍需要 `ANTHROPIC_VERSION`。
- 如果真实服务路径带 `/v1` 前缀，请把 `BASE_URL` 写成类似 `http://host:port/v1`。
