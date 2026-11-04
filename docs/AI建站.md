# AI 自动建站

在后台的「AI 建站」中选择已有站点，或选择「新建站点并生成」，填写企业信息、页面语言、建站要求与模型配置。新建模式先生成并校验页面，再开通 WordPress / MariaDB 与行业模板，并开具所选套餐账单。任务在后台执行，关闭页面不会取消；可在任务列表查看进度。

完成后点击「预览草稿」「编辑页面」「发布当前草稿」。AI 内容默认不直接覆盖线上页面。已有未发布草稿需要勾选确认替换；原草稿备份到 `sites/<slug>/.backups/ai-<任务ID>.json`。生成失败、JSON 不合法、页面不完整时不会改写原草稿。正在生成期间暂不允许编辑或发布同一站点。

## GPT 模拟与真实模型

默认配置为 **GPT 模拟**：本地根据企业名称、需求和语言拼装示例页面，不调用真实 GPT，也不产生模型费用。模拟结果、任务和选择器会明确显示「模拟」。真实接口失败不会自动回退成模拟结果。

管理员可展开「服务商与模型配置」保存最多 20 套配置：

| 协议 | Base URL 示例 | 请求与鉴权 |
|---|---|---|
| OpenAI 兼容 Chat Completions | `https://服务商地址/v1` | `/chat/completions`，Bearer Key |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses`，Bearer Key |
| Anthropic Messages | `https://api.anthropic.com/v1` | `/messages`，`x-api-key`，版本 `2023-06-01` |
| Gemini GenerateContent | `https://generativelanguage.googleapis.com/v1beta` | `/models/<模型ID>:generateContent`，`x-goog-api-key` |
| Ollama 或本地兼容服务 | `http://127.0.0.1:11434/v1` | 选择 OpenAI 兼容协议，可不填 Key |

也可填写完整接口地址；不要把 API Key 放进 URL。DeepSeek、通义等服务使用其提供的 OpenAI 兼容 Base URL 和模型 ID。模型 ID 是自由输入项，不限制在预设列表内。供应商专属的 Azure 查询参数或其他非上述协议并不自动兼容。

配置保存后可「测试连接」「设为默认」「编辑」「删除」。测试连接会发送少量真实模型请求（模拟配置除外），超时最多 30 秒；建站生成使用所配置的 5–300 秒超时。输出 Token 上限为 256–32768。Chat 接口可以选择 `max_tokens`、`max_completion_tokens`，或不发送长度参数。JSON 输出模式默认关闭，服务商支持时才开启。

API Key 单独保存于 `console/ai-secrets.json`（权限 600），读取接口不返回密钥。编辑时留空保留原密钥，勾选「清除已保存密钥」可删除。普通配置保存于 `console/ai-config.json`；任务状态保存于 `console/ai-jobs.json`。系统重启会将未完成任务标记为中断，不会偷偷重发付费模型请求。若开通站点阶段失败，保留现场供修复，不自动删除容器或客户数据。

运营人员可选用已配置模型生成内容；只有管理员可配置密钥、删除配置或测试接口。财务角色不能调用 AI 建站接口。任务及配置变更写入原有审计日志，审计记录不包含 Key 或完整建站要求。

## 后台 HTTP 接口

沿用后台登录 Cookie 鉴权；未开启 MFA 的账号也可使用现有 Basic 鉴权。不要将后台账号或 Key 放在公开前端代码中。

| 方法与路径 | 用途 |
|---|---|
| `GET /api/ai/config` | 可选模型配置、默认配置；管理员还可见接口参数与预设 |
| `POST /api/ai/config` | 管理员保存、设默认或删除配置 |
| `POST /api/ai/test` | 管理员测试已保存配置 |
| `POST /api/ai/build` | 创建异步建站任务，返回 HTTP 202 与 `job` |
| `GET /api/ai/jobs` | 最近任务、状态、错误和预览链接 |
| `GET /api/spec/<slug>` | 读取生成的草稿与线上页面 |
| `POST /api/spec` | 修改单页草稿，沿用原结构编辑器接口 |
| `POST /api/publish` | 发布当前站点草稿，沿用原发布接口 |

保存兼容接口配置：

```json
{
  "action": "save",
  "id": "my-provider",
  "name": "我的建站模型",
  "protocol": "openai_chat",
  "base_url": "https://api.example.com/v1",
  "model": "服务商提供的模型ID",
  "api_key": "从服务商取得的Key",
  "timeout": 120,
  "max_tokens": 8192,
  "token_parameter": "max_tokens",
  "json_mode": false
}
```

设默认或删除：`{"action":"default","id":"my-provider"}` / `{"action":"delete","id":"my-provider"}`。测试：`{"profile_id":"my-provider"}`。

为已有站点生成草稿：

```json
{
  "mode": "existing",
  "slug": "demo",
  "profile_id": "mock",
  "language": "zh",
  "brief": "企业服务、目标客户、风格与真实联系方式……",
  "replace_draft": false
}
```

新建模式将 `mode` 改为 `new`，并增加 `company`、`domain`、`plan_id`、`industry`（例如 `tech`）。模型按行业模板或已有草稿的页面列表生成整站内容，不任意改变页面 URL。页面语言支持 `zh`、`en`。每个站点最多一个生成任务，全局最多两个并行任务。

任务状态：`queued` → `generating` → 新站点的 `provisioning` → `saving` → `completed`；异常状态为 `failed` 或 `interrupted`。HTTP 202 只表示已接收任务，应轮询任务状态。完成后发布请求为 `{"slug":"demo"}`；可以加 `page` 字段逐页发布。多页发布遇到错误时，响应会报告已发布的页数并同步这些页面的线上记录；其余页面仍保留草稿，检查错误后可重试。

生成输出采用受限 JSON 区块协议（首屏、卡片、分栏、列表、行动区、联系表单），不执行模型返回的 HTML 或代码。真实模型的输出会检查页面完整性、字段、链接与渲染结果。模型调用只发送企业名称、用户填写的要求、语言与页面标识，不发送数据库密码、后台账号或账单。

## 验证与协议参考

运行 `.venv/bin/python -m unittest discover -s tests -v`，覆盖四种真实协议的本地 HTTP 契约、模拟生成、权限、密钥脱敏、失败保护、并发冲突、新站点任务及发布交接。真实服务商能否调用仍取决于配置的 Key、模型权限和网络；无 Key 时不会声称已验证远端服务商。

协议参考：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)、[Anthropic API](https://platform.claude.com/docs/en/api/overview)、[Gemini GenerateContent](https://ai.google.dev/api/generate-content)。
