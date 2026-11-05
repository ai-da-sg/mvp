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

生成输出采用受限 JSON 区块协议（首屏、卡片、分栏、列表、行动区、联系表单），不执行模型返回的 HTML 或代码。真实模型的输出会检查页面完整性、字段、链接与渲染结果。模型调用只发送企业名称、用户填写的要求、选定的提示词模块与业务变量、语言与页面标识，不发送数据库密码、后台账号或账单。

## 验证与协议参考

运行 `.venv/bin/python -m unittest discover -s tests -v`，覆盖四种真实协议的本地 HTTP 契约、模拟生成、权限、密钥脱敏、失败保护、并发冲突、新站点任务及发布交接。真实服务商能否调用仍取决于配置的 Key、模型权限和网络；无 Key 时不会声称已验证远端服务商。

协议参考：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)、[Anthropic API](https://platform.claude.com/docs/en/api/overview)、[Gemini GenerateContent](https://ai.google.dev/api/generate-content)。


## 模块化提示词库

「内容建站 → 提示词库」提供 11 类初始方案：企业服务、SaaS、本地服务预约、设计作品集、教育课程、B2B 产品询价、活动落地页、专业咨询、幼儿园参考站改编、机器人科技及中医诊所；由 21 个模块组合。它们是公开实践的应用起点，不是经过真实模型效果排名的万能提示词。

在 AI 建站中选择场景与模板，填写目标客户、服务/产品、转化目标、语气和已核实资料；可勾选模块、上下调整顺序，预览最终组合。额外要求独立保留。选择模板后，服务、客户、目标为必填；自由输入模式仍可直接填写原有建站要求。

管理员可新建、编辑、复制、启用/停用模板与模块，查看并恢复最近 10 个历史版本，导出 JSON 备份。停用被启用模板引用的模块会被拒绝，需先修改或停用依赖模板。运营可读取、组合和预览；财务无权访问。默认变量支持 `{{audience}}`、`{{services}}`、`{{goal}}`、`{{tone}}`、`{{facts}}`，不执行任意表达式或代码。

- `GET /api/ai/prompts`：库、模块、变量定义、来源；管理员可见历史及停用条目。
- `POST /api/ai/prompts/preview`：`{selection, brief}`，只组合与校验，不调用模型或修改数据。
- `POST /api/ai/prompts`：管理员使用 `save`、`toggle`、`restore`，指定 `kind`（`templates` / `modules`）、`id`、库 `revision`。更新冲突返回 409，避免覆盖别人的修改。
- `POST /api/ai/build`：可附加 `prompt_selection`，含 `revision`、`template_id`、有序 `module_ids`、`variables`。未提供 `module_ids` 时使用模板默认组合。

示例：

```json
{
  "mode": "existing", "slug": "demo", "profile_id": "mock", "language": "en",
  "brief": "突出真实服务能力，不使用客户评价。",
  "prompt_selection": {
    "revision": 1, "template_id": "company",
    "variables": {"services": "设计咨询与空间规划", "audience": "新加坡小型办公室业主", "goal": "提交项目咨询"}
  }
}
```

`revision` 应使用 GET 返回值。自定义配置存于 `console/ai-prompts.json`，每次更新使用文件锁和原子写入，发布包不覆盖此运行数据。任务和草稿 `ai.prompt` 会保存模板/模块版本及组合快照，之后编辑库不会改变已创建任务。提示词内容与业务资料会发送给选定模型，因此不要放入密钥或不应公开的资料。

系统输出约束独立于可编辑提示词：仍仅生成平台支持的 JSON 区块，严格校验页面、字段和链接。模板不实现支付/购物车/库存/实际预约功能，也不直接修改 CSS、字体或配色；视觉设置仍由「视觉设计」管理。模拟模式验证流程，不验证模型遵循模板的效果；上线前仍需真实模型评估和人工预览。

整理日期：2026-11-04。参考 [Vercel v0 的界面、场景和约束框架](https://vercel.com/blog/how-to-prompt-v0)、[Lovable 的组件化提示与真实内容建议](https://docs.lovable.dev/prompting/prompting-one)、[Anthropic 的成功标准与评估方法](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview)。


## UI 基本原则与美学标准

所有内置方案默认组合 `ui-principles` 与 `ui-aesthetics`。三个展示方案分别增加 `ui-nursery`、`ui-robotics`、`ui-wellness`，对应「视觉设计」中的童趣教育（nursery）、精密科技（robotics）、草木静雅（wellness）预设。已保存的自定义库不会被升级覆盖；可在提示词库创建这些模块并更新自己的模板组合。

基本原则涵盖清晰层级、单一主要行动、键盘操作、焦点、标签与反馈、44px 操作目标、正文对比度 4.5:1，以及四个响应式检查宽度。美学标准约束主色与强调色、字体数量、8px 间距节奏、有限圆角、自然换行、图标一致性和克制动效。模型只输出内容区块；实际尺寸、色彩与交互由视觉预设和主题实现，提示词预览通过不代表视觉验收通过。

规则经三个展示站的浏览器检查迭代：普通标题字段不写 HTML，表单回执不承诺未经确认的回复时限，演示内容不沿用模板中的虚构费用、评价或联系方式。真实模型效果仍需单独评估。

## 参考网站与可管理风格模板

在「AI 建站 → 参考网站与风格模板」输入公开 HTTP/HTTPS 网址，点击「分析参考风格」。系统读取 HTML 与最多 4 个外部样式文件，展示颜色、字体方向、布局线索、来源与限制；当前页面使用的选择器和语义设计变量优先于框架预置颜色。浅色按钮会按白字对比度调整。

可以直接使用分析结果生成，也可以选择「编辑并保存为模板」，设置名称、分类、配色、标题字体、卡片圆角、区块间距和内容生成指导。管理区支持搜索、编辑、复制、停用、删除。管理员管理模板，运营可分析和使用启用模板，财务无访问权限。每次修改增加版本，旧版本提交返回 409，避免覆盖其他人的修改。

选择风格后填写新企业的真实业务资料并生成。风格指导发送给所选模型，经过校验的设计参数独立保存在草稿 `design` 中，不依赖模型输出 CSS。草稿预览使用这些参数，发布才同步 WordPress；生成阶段不改变已有线上视觉。任务和草稿 `ai.style` 保存模板快照，修改或删除模板不影响已生成内容。后续手动修改「视觉设计」会取代对应草稿的设计参数。

- `POST /api/ai/styles/analyze`：`{"url":"https://example.com"}`，返回 `tokens`、`summary`、`guidance`、`evidence`、`warnings` 和来源。
- `GET /api/ai/styles`：模板列表及 `can_manage`。
- `POST /api/ai/styles`：保存使用 `name/category/tokens/source_url/summary/guidance/enabled`；已有模板还需 `id/version`。`action` 支持 `save/duplicate/delete`。
- `POST /api/ai/build`：附加 `style_template_id` 使用已保存模板，或附加分析返回的 `reference_style` 使用本次参考风格。

模板保存在 `console/ai-styles.json`，原子写入、权限 0600，代码发布包不会覆盖。模板上限 100 个；同时最多 2 个参考分析任务；网页上限 2 MiB，单个 CSS 上限 512 KiB。每次重定向重新检查公网地址，连接固定到经过检查的 IP，HTTPS 仍校验域名证书；拒绝内网、回环、链路本地、保留地址和非标准端口。不携带登录凭据或执行参考站脚本。

这是公开 HTML/CSS 的静态风格分析，不是截图视觉理解或像素级复刻。登录页、反爬页面、脚本动态样式、超过限制的资源可能无法分析；界面显示失败或降级说明。原站文案、图片、品牌和联系方式不自动复制。模拟模式仍生成示例文案，但设计参数真实作用于预览和发布；真实模型的内容质量需要单独评估。

参考风格发布时会安装两个专用文件到站点的 `wp-content/mu-plugins/`（`kf-reference-style.php` 和 `kf-reference-style.css`），只在 `preset=reference` 时启用。这样已有站点也能覆盖旧主题的固定装饰颜色，无需替换其主题文件；切换为其他视觉预设后这些规则不再生效。
