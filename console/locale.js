/* UI translations only. User-entered content and website copy are never machine-translated. */
window.KF_MESSAGES = Object.fromEntries(`
KampongFlow 控制台|KampongFlow Console
登录 · KampongFlow|Sign in · KampongFlow
员工登录|Staff sign in
登录|Sign in
用户名|Username
密码|Password
验证码或恢复码（已开启两步验证时填写）|Verification or recovery code (if enabled)
无法使用验证器？使用恢复码|Cannot use your authenticator? Use a recovery code
输入验证器中的 6 位数字，或粘贴一枚完整恢复码（xxxx-xxxx）。恢复码只能使用一次。|Enter the 6-digit authenticator code or paste a complete recovery code (xxxx-xxxx). Each recovery code can only be used once.
主题|Theme
深色|Dark
浅色|Light
跟随系统|System
语言|Language
中文|中文
一次性交付：域名 · 建站 · 邮箱 · 托管|Domains · Websites · Email · Hosting
退出|Sign out
跳转到主要内容|Skip to main content
控制台导航|Console navigation
主导航与二级菜单|Primary and secondary navigation
导航菜单|Navigation
站点运营|Site operations
站点总览|Site overview
域名管理|Domains
搜索域名、机构、用户名或配置|Search domains, providers, usernames or configuration
添加管理机构|Add provider
管理机构账号|Provider account
添加管理机构账号|Add provider account
编辑管理机构账号|Edit provider account
所属域名|Domain
机构类型|Provider type
域名注册商|Domain registrar
DNS 服务商|DNS provider
托管服务商|Hosting provider
其他机构|Other provider
管理机构名称|Provider name
管理后台地址|Management URL
用户名 / 登录邮箱|Username / sign-in email
设置新密码（留空保留已保存密码）|New password (leave blank to keep existing)
清除已保存的密码|Clear saved password
配置信息|Configuration
保存管理账号|Save provider account
TOTP 验证后显示|Verify TOTP to reveal
验证 TOTP 后显示密码|Verify TOTP to reveal password
当前 MVP 账号的 6 位 TOTP 验证码|Current MVP account's 6-digit TOTP code
验证并显示|Verify and reveal
已保存密码（30 秒后自动隐藏）|Saved password (hidden after 30 seconds)
立即隐藏|Hide now
恢复码不能用于显示密码。同一枚验证码只能成功使用一次。|Recovery codes cannot reveal passwords. Each TOTP code can be used successfully once.
配置信息可直接查询，请勿在此填写密码、API 密钥或恢复码。|Configuration is directly searchable. Do not enter passwords, API keys or recovery codes here.
查询域名、管理机构、后台地址、账号与配置信息。已保存密码只在 TOTP 验证成功后显示。|Search domains, providers, management URLs, accounts and configuration. Saved passwords are revealed only after TOTP verification.
DNS 解析|DNS records
运行维护|Maintenance
内容建站|Website content
参考网站与风格模板|Reference website and style templates
参考网站地址|Reference website URL
分析参考风格|Analyze reference style
本次生成使用的风格|Style for this generation
保持站点当前风格|Keep current site style
刚分析的参考风格|Latest reference analysis
管理风格模板|Manage style templates
分析依据|Analysis evidence
编辑并保存为模板|Edit and save as template
风格模板管理|Style template library
搜索模板名称或分类|Search template names or categories
刷新模板|Refresh templates
编辑风格模板|Edit style template
模板名称|Template name
参考来源|Reference source
风格说明|Style description
内容生成指导|Content generation guidance
标题字体|Heading font
无衬线|Sans serif
衬线|Serif
圆润|Rounded
等宽|Monospace
卡片圆角（px）|Card radius (px)
区块间距（px）|Section spacing (px)
启用此模板|Enable template
保存风格模板|Save style template
读取公开页面与样式，提取颜色、字体和布局线索。不复制原站品牌或图片；动态页面可能无法完整分析。|Read public HTML and CSS for colors, fonts and layout clues. Original branding and images are not copied. Dynamic pages may yield incomplete results.
风格随生成内容一起保存到草稿，预览确认后发布；模板更新不会改变已经生成的网站。|The style is saved with the draft and applied when published. Updating a template does not change existing generated sites.
进入 WordPress 后台|Open WordPress admin
AI 建站|AI builder
提示词库|Prompt library
页面编辑|Page editor
视觉设计|Visual design
媒体素材|Media library
预览分享|Preview sharing
客户与财务|Customers & billing
客户管理|Customers
咨询线索|Enquiries
账单收款|Invoices & payments
套餐设置|Plans
系统管理|Administration
系统设置|System settings
设置 LLM|LLM settings
MCP 管理|MCP management
运营助手|Operations assistant
工具来源|Tool source
MVP 内置业务|MVP built-in operations
生成操作预览|Prepare operation preview
刷新记录|Refresh history
操作记录|Operation history
查看 / 确认|Review / approve
创建网站交付流程|Create website delivery workflow
交付流程|Delivery workflows
创建交付流程|Create delivery workflow
开始 / 继续|Start / resume
重试当前步骤|Retry current step
DNS 执行服务商（管理员）|DNS provider for changes (admin)
保存 DNS 执行配置|Save DNS provider
建站参考资料（已有站点，可选）|Reference data (existing sites, optional)
客户资料|Client information
品牌与风格|Brand and design
现有页面|Existing pages
素材目录|Media inventory
从运营助手选择 MCP 资料|Choose MCP references in Operations
允许 AI 自动查询已授权的 MCP 只读资料（最多 4 次）|Allow AI to query approved read-only MCP references (up to 4 calls)
所选资料会发送至当前模型服务商，并随任务记录来源。外部资料仅作为参考，不能覆盖基本原则与美学标准。|Selected data is sent to the chosen model provider and its sources are recorded. External data cannot override the project's principles and design standards.
允许使用范围|Allowed usage
允许访问的站点（可多选）|Allowed sites (multiple selection)
每小时调用上限|Calls per hour
调用超时（秒）|Call timeout (seconds)
工具与资料白名单|Tool and reference allowlist
工具规则（JSON 数组）|Tool rules (JSON array)
允许读取的资源 URI（每行一项）|Allowed resource URIs (one per line)
允许获取的提示词名称（每行一项）|Allowed prompt names (one per line)
查看建站任务与预览|View build jobs and previews
用于 AI 建站资料|Use as AI website reference
编辑并预览发送|Edit and review sending
参数定义|Input schema
搜索 MCP 名称、地址或说明|Search MCP names, URLs or descriptions
添加 MCP 服务|Add MCP server
MCP 服务配置|MCP server settings
服务名称|Server name
MCP 服务地址|MCP endpoint URL
Bearer Token（留空保留原凭据）|Bearer token (leave blank to keep existing)
清除已保存凭据|Clear saved credential
服务说明|Server description
启用此服务|Enable this server
保存 MCP 服务|Save MCP server
测试连接与能力|Test connection and capabilities
已保存凭据|Credential saved
无认证|No authentication
没有匹配的 MCP 服务。|No matching MCP servers.
管理远程 MCP 服务，测试连接并查看工具、资源及提示词。当前仅用于连接管理与能力查询，尚未接入 AI 建站调用。|Manage remote MCP servers, test connections and inspect tools, resources and prompts. Connections are not yet used by the AI builder.
支持公开 HTTPS（443 端口）的 Streamable HTTP，协议 2025-06-18 / 2025-03-26；认证支持无认证或 Bearer Token。暂不支持本地 stdio、旧 SSE 端点或 OAuth 登录。|Supports public HTTPS on port 443 with Streamable HTTP, protocol 2025-06-18 or 2025-03-26, and optional bearer authentication. Local stdio, legacy SSE endpoints and OAuth sign-in are not supported.
团队与安全|Team & security
站点|Site
客户 / 域名|Customer / domain
负责人|Owner
套餐|Plan
状态|Status
账单|Invoice
到期|Expiry
操作|Actions
只看我负责的|Only my sites
客户名称|Customer name
域名|Domain
站点标识（自动建议，可修改）|Site ID (suggested, editable)
行业模板|Industry template
下单并开通|Order and provision
账单号|Invoice number
客户|Customer
金额|Amount
时间|Time
价格|Price
规格|Specifications
套餐 ID|Plan ID
名称|Name
价格 (SGD)|Price (SGD)
周期|Period
首年|First year
规格说明|Plan details
保存套餐|Save plan
AI 自动建站|AI website builder
描述企业、服务与风格，自动生成整站页面草稿。预览、调整后发布到网站。|Describe your business, services and style to generate website drafts. Preview and edit before publishing.
GPT 模拟模式无需密钥；真实模型请由管理员配置。|Mock mode needs no key. An administrator can configure a live model.
建站方式|Build mode
为已有站点生成|Generate for an existing site
新建站点并生成|Create a site and generate
选择站点|Select a site
模型配置|Model profile
页面语言|Website content language
企业名称|Business name
站点标识|Site ID
行业与视觉模板|Industry and visual template
新站点会开通 WordPress 和数据库，并生成套餐账单。生成的 AI 内容先保存为草稿；域名解析可在交付前配置。|A new site provisions WordPress and a database and creates a plan invoice. AI content is saved as a draft; domain records can be set before handover.
提示词方案|Prompt recipe
场景分类|Scenario category
全部场景|All scenarios
选择模板|Select a template
自由输入（不使用模板）|Free-form (no template)
选择场景模板后，填写真实业务资料并调整模块组合。|Select a scenario, provide real business information and adjust the modules.
目标客户|Target audience
主要转化目标|Primary conversion goal
主营服务 / 产品（必填）|Services / products (required)
品牌语气|Brand voice
已核实资料与联系方式（选填）|Verified facts and contact details (optional)
调整模块与顺序|Adjust modules and order
预览组合后的提示词|Preview assembled prompt
最终提示词预览|Final prompt preview
组合后的提示词|Assembled prompt
模板影响内容结构与语气；配色、字体仍由视觉模板负责。模拟模式用于流程验证，不代表真实模型效果。|Prompts guide content structure and tone; the visual template controls colors and fonts. Mock mode validates the workflow, not live model quality.
建站要求 / 额外补充|Business brief / additional requirements
如果已有未发布草稿，我确认用本次结果替换（系统会备份原草稿）|Replace any unpublished draft with this result (the previous draft will be backed up).
生成整站草稿|Generate website draft
建站任务|Build jobs
服务商与模型配置（管理员）|Providers and models (admin)
可保存多套模型。API 地址支持服务商 Base URL 或完整接口地址；模型 ID 按服务商提供的名称填写。密钥仅保存在服务器。|Save multiple model profiles. Use a provider base URL or full endpoint and its model ID. Keys are stored only on the server.
快速填写|Preset
自定义配置|Custom profile
配置 ID|Profile ID
显示名称|Display name
接口协议|API protocol
OpenAI 兼容 Chat Completions|OpenAI-compatible Chat Completions
API Base URL / 完整接口地址|API base URL / full endpoint
模型 ID|Model ID
API Key（留空保留原密钥）|API key (leave blank to keep existing)
请求超时（秒）|Request timeout (seconds)
最大输出 Token|Maximum output tokens
Chat 接口输出长度参数|Chat output-length parameter
max_tokens（常见兼容接口）|max_tokens (common compatible APIs)
不发送（使用服务商默认值）|Omit (use provider default)
启用 JSON 输出模式（仅在服务商支持时勾选）|Enable JSON output mode (only if supported)
清除已保存密钥|Remove saved key
保存配置|Save profile
新建配置|New profile
查看|View
场景模板|Scenario templates
可复用模块|Reusable modules
搜索名称、分类或用途|Search name, category or purpose
刷新|Refresh
导出提示词库|Export prompt library
新建|New
编辑条目|Edit item
分类|Category
用途说明|Purpose
提示词内容|Prompt instructions
默认模块（按下列顺序组合）|Default modules (in composition order)
默认业务变量（JSON，可留空）|Default business variables (JSON, optional)
启用|Enabled
停用|Disabled
保存新版本|Save new version
取消编辑|Cancel editing
设计依据与使用边界|Sources and scope
模板定义场景，模块组织目标、结构、风格、文案与检查标准。运营可选择使用；管理员可编辑、复制、停用并恢复历史版本。|Templates define scenarios; modules organize goals, structure, style, copy and quality checks. Operators can use them; admins can edit, duplicate, disable and restore versions.
这些模板是根据公开实践整理的起点，并非经过模型效果排名的“最佳提示词”。请用真实业务资料生成草稿，核对事实和页面后再发布。模板只生成当前平台支持的内容，不实现支付、库存或预约系统。|These templates are starting points based on public guidance, not ranked model benchmarks. Generate with real business information and review drafts before publishing. They do not implement payments, inventory or booking systems.
可用变量：{{audience}}、{{services}}、{{goal}}、{{tone}}、{{facts}}。不在提示词中保存密钥或私人资料。|Variables: {{audience}}, {{services}}, {{goal}}, {{tone}}, {{facts}}. Do not store keys or private information in prompts.
页面|Page
新增区块|Add a section
添加|Add
高级：直接编辑 JSON|Advanced: edit JSON
从 JSON 覆盖表单|Apply JSON to form
保存与发布|Save and publish
保存全部改动|Save all changes
保存并预览|Save and preview
查看改动|View changes
发布本页|Publish this page
全部发布|Publish all pages
上传图片|Upload image
有效天数|Validity (days)
生成预览链接|Create preview link
立即检查|Check now
重建过期站点|Rebuild outdated sites
发送方式|Delivery method
API Key（选 API 时填）|API key (for API delivery)
SMTP 主机|SMTP host
端口|Port
发件人|Sender
使用 STARTTLS|Use STARTTLS
测试收件地址|Test recipient
保存|Save
发送测试|Send test
立即发送日报|Send daily report now
预付款余额|Prepaid balance
每个员工一个账号，所有写操作都会记进审计日志。只有管理员能管理账号。|Each staff member has an account. All changes are audited. Only administrators can manage accounts.
新建账号|Create account
显示名|Display name
角色|Role
运营|Operations
财务|Finance
管理员|Administrator
旧密码|Current password
新密码（至少 10 位）|New password (at least 10 characters)
修改密码|Change password
操作日志|Audit log
操作人|Actor
关键词|Keyword
起|From
止|To
查询|Search
写入权限（每行一条路径前缀，留空=全禁，管理员固定全开）|Write permissions (one path prefix per line; empty denies all; admins always have full access)
令牌说明|Token description
全部|All
预设|Preset
主色|Primary color
强调色|Accent color
背景色|Background
标题字体|Heading font
无衬线|Sans-serif
衬线|Serif
圆润|Rounded
卡片圆角|Card corner radius
按钮|Button
胶囊|Pill
圆角|Rounded
方正|Square
应用设计|Apply design
主色决定首屏、页脚、按钮与卡片色条；|The primary color affects the hero, footer, buttons and card accents;
背景色影响整页底色；|the background color affects the page surface;
圆角同时作用于卡片与图片；|corner radius applies to cards and images;
字体只换标题，正文保持不变。|font selection changes headings only.
加载中…|Loading…
运行中|Running
开通中|Provisioning
失败|Failed
已停止|Stopped
HTTP 正常|HTTP healthy
运行详情|Runtime details
已付|Paid
待付|Unpaid
已付款|Paid
待付款|Unpaid
已收款|Collected
待收款|Outstanding
账单数|Invoice count
开票|Issue invoice
打开|Open
交接单|Handover PDF
续费|Renew
暂停|Suspend
恢复|Restore
标记已付|Mark as paid
编辑|Edit
暂无账单|No invoices yet
还没有站点，先开通一个|No sites yet. Create your first site.
开通站点|Create site
最后刷新|Last refreshed
点上面的区块开始编辑|Select a section above to start editing
该类型暂无可视化表单，请用下面的 JSON|No visual editor for this section. Use JSON below.
删除此项|Delete item
上移此项|Move item up
下移此项|Move item down
改动尚未保存，线上内容未变。|Changes are not saved. The live site is unchanged.
页面编辑有未保存内容|The page editor has unsaved changes
草稿已保存 · 未发布|Draft saved · unpublished
已与线上一致|Up to date with live site
正在处理…|Working…
全部改动已保存到草稿，线上未变。|All changes saved to the draft. The live site is unchanged.
草稿已保存，预览已打开；线上未变。|Draft saved and preview opened. The live site is unchanged.
正在比较已保存草稿与线上内容|Comparing the saved draft with the live site
这一页没有未发布的改动|This page has no unpublished changes
这是一个尚未发布的页面|This page has not been published yet
读取失败|Unable to load
模拟|Mock
排队中|Queued
生成中|Generating
开通站点中|Provisioning site
保存中|Saving
草稿已就绪|Draft ready
已中断|Interrupted
预览草稿|Preview draft
编辑页面|Edit pages
发布当前草稿|Publish current draft
还没有建站任务。填写上方要求，开始生成第一份草稿。|No build jobs yet. Complete the brief above to generate your first draft.
当前为 GPT 模拟模式：按企业信息与需求生成示例草稿，不调用真实 GPT、不产生模型费用。|GPT mock mode: creates example drafts from your brief. No live GPT call or model charge.
当前角色无权使用自动建站|Your role cannot use the AI builder
正在提交任务…|Submitting job…
任务已提交，进度显示在下方。可以离开本页，任务会继续执行。|Job submitted. Progress appears below. You may leave this page while it runs.
创建站点并生成草稿|Create site and generate draft
测试连接|Test connection
设为默认|Set as default
删除|Delete
默认|Default
已配置密钥|Key configured
无密钥|No key
正在测试接口…|Testing connection…
配置已更新|Profile updated
配置已保存，可点击“测试连接”验证。|Profile saved. Use Test connection to verify it.
直接填写完整建站要求，或选择一个场景模板。|Enter a full brief or select a scenario template.
资料或模块已变化，可重新预览；生成时会校验最新组合。|Inputs or modules changed. Preview again; the latest combination is validated when generating.
用于建站|Use for building
编辑与历史|Edit and history
复制为新条目|Duplicate as new item
查看提示词内容|View prompt instructions
没有符合条件的条目。|No matching items.
提示词库已刷新|Prompt library refreshed
新版本已保存；已创建任务的提示词不受影响。|New version saved. Existing jobs retain their prompt snapshots.
历史内容已恢复为新版本。|Historical content restored as a new version.
恢复为新版本|Restore as new version
童趣教育|Warm early learning
精密科技|Precision technology
草木静雅|Calm botanical
UI 基本原则与可访问性|UI principles and accessibility
UI 美学标准与视觉一致性|UI aesthetics and visual consistency
幼儿园视觉：温暖与探索|Preschool visuals: warmth and exploration
机器人视觉：精密与秩序|Robotics visuals: precision and order
中医视觉：草木与静雅|Clinic visuals: natural calm
幼儿园展示与参考站改编|Preschool showcase and reference adaptation
机器人科技展示|Robotics showcase
中医诊所展示|Traditional Chinese medicine clinic showcase
健康服务|Health services
参考站结构与平台适配|Reference structure and platform constraints
演示站事实与发布检查|Demo facts and publication checks
机器人方案与工程流程|Robotics solutions and delivery process
中医诊所信息与咨询边界|Clinic information and enquiry boundaries
参考页面结构，呈现课程、理念与家长咨询|Adapt reference structure for programmes, philosophy and parent enquiries
呈现应用场景、方案边界与工程合作流程|Present use cases, scope and engineering collaboration
清晰介绍机构、服务范围与咨询流程|Explain the practice, service scope and enquiry process
企业服务官网|Business services website
SaaS 产品介绍|SaaS product website
本地服务预约|Local service enquiries
设计工作室与作品集|Design studio and portfolio
教育与课程介绍|Education and courses
产品目录与 B2B 询价|Product catalog and B2B enquiries
活动推广落地页|Campaign landing page
专业咨询品牌|Professional consulting
展示服务能力，引导客户咨询|Present service capabilities and invite enquiries
说明产品价值与使用场景，获取演示咨询|Explain product value and use cases, and invite demo enquiries
服务介绍与预约咨询，不模拟预约系统|Describe services and invite booking enquiries
突出方法、真实案例与合作方式|Highlight your process, real work and collaboration
解释课程与适合人群，引导课程咨询|Explain courses and their audience, and invite enquiries
清晰分类、产品对比与询价入口|Organize products, comparisons and enquiry options
围绕一个行动组织活动介绍|Present a campaign around one primary action
解释服务方法与合作流程，建立可信预期|Explain your approach and process with realistic expectations
Vercel v0：产品界面、使用场景、约束与偏好|Vercel v0: product surfaces, context, constraints and preferences
Lovable：先规划、按组件组织、使用真实内容|Lovable: plan first, use components and real content
Anthropic：定义成功标准并验证效果|Anthropic: define success criteria and evaluate results
企业服务|Business services
数字产品|Digital products
本地生活|Local services
创意设计|Creative services
教育培训|Education
产品展示|Product showcase
营销活动|Campaigns
专业咨询|Consulting
目标与转化|Goals and conversion
页面结构|Page structure
视觉方向|Visual direction
内容表达|Copywriting
质量约束|Quality constraints
单一主要行动|One primary action
服务介绍与流程|Services and process
产品价值与使用场景|Product value and use cases
作品与案例叙事|Portfolio and case studies
预约咨询流程|Enquiry workflow
产品目录与询价|Catalog and enquiries
简洁可信|Clear and trustworthy
温暖亲和|Warm and approachable
真实且具体的文案|Factual, specific copy
发布前内容检查|Pre-publication checks
本地服务信任|Local service trust
课程与学习路径|Courses and learning paths
例如 tanjong|e.g. tanjong
例如：海湾设计工作室|e.g. Bay Design Studio
我的建站模型|My website model
填写服务商提供的模型 ID|Enter the provider's model ID
本地服务可留空|Optional for local services
留空则不修改|Leave blank to keep existing
填写真实提供的服务或产品|List services or products you actually provide
仅填写可公开且已核实的案例、地址、时间、价格或联系方式|Only include verified, public case studies, addresses, times, prices and contact details
1 个站点 · 5 个邮箱 · 20GB|1 website · 5 mailboxes · 20GB
2–20 位小写字母、数字或连字符，以字母开头|2–20 lowercase letters, digits or hyphens; start with a letter
用户名或密码不正确|Incorrect username or password
两步验证码不正确|Incorrect verification or recovery code
登录已过期，请刷新页面重新登录|Session expired. Refresh and sign in again.
服务响应异常，请稍后重试|Unexpected server response. Try again later.
操作失败|Action failed
JSON 格式错误|Invalid JSON
保存失败，请重试|Save failed. Please retry.
请先修正 JSON|Please correct the JSON first
区块类型无效|Invalid section type
读取草稿失败，请重试|Unable to load the draft. Please retry.
正在保存或发布，请稍候再切换页面。|Saving or publishing. Please wait before navigating.
当前站点还有未保存内容。载入其他草稿将丢弃这些改动，是否继续？|This site has unsaved edits. Loading another draft will discard them. Continue?
删除这个区块？保存前可以重新载入草稿恢复。|Delete this section? Before saving, you can reload the draft to restore it.
草稿已保存，请允许浏览器打开预览窗口后重试。|Draft saved. Allow pop-ups and try opening the preview again.
将该站点当前草稿发布到线上？请先完成预览检查。|Publish this site's current draft? Please review the preview first.
删除这个模型配置和保存的密钥？|Delete this model profile and its saved key?
提示词库已更新，请刷新后重试；本次修改未写入|The prompt library changed. Refresh and retry; your edit was not saved.
提示词库已更新，请重新选择或预览后生成|The prompt library changed. Select or preview again before generating.
至少选择一个模块|Select at least one module
模板不存在或已停用|The template is missing or disabled
所选模块不存在或已停用|A selected module is missing or disabled
请填写目标客户|Enter the target audience
请填写主营服务/产品|Enter the services or products
请填写主要转化目标|Enter the primary conversion goal
`.trim().split('\n').map(line=>{const i=line.indexOf('|');return [line.slice(0,i),line.slice(i+1)];}));
Object.assign(window.KF_MESSAGES,Object.fromEntries(`
云主机通常封了 587/465，建议用 HTTPS 邮件 API（Resend / SendGrid）|Cloud hosts often block ports 587/465. Consider an HTTPS email API such as Resend or SendGrid.
介绍企业和主营服务、目标客户、网站风格、要突出的信息，以及真实的联系方式。例：新加坡室内设计工作室，服务住宅与小型办公室。风格简洁温暖，突出设计咨询、空间规划、施工跟进，希望访客通过联系表单预约。|Describe your business, services, audience, preferred style, key information and real contact details. Example: a Singapore interior design studio serving homes and small offices; warm, simple copy about design consultation, space planning and project coordination, with a contact form for enquiries.
本地模拟：浏览器用 hosts 把域名指向本机，请求经隧道进入后台，再按 Host 头转发到对应站点。证书是自签的，浏览器会提示不安全，点继续即可。|Local preview: a hosts entry points the domain to this machine; the tunnel forwards requests by Host header. This preview uses a self-signed certificate.
邮件发送|Email delivery
镜像更新检查：拉取 wordpress / mariadb / wp-cli 三个镜像，比对运行中容器的 image ID。定时任务每周一 09:00 自动执行。|Check WordPress, MariaDB and WP-CLI images against running containers. Scheduled checks run Mondays at 09:00.
上传|Upload
上传中…|Uploading…
上传失败|Upload failed
从未|Never
以此历史内容创建新版本？|Create a new version from this historical content?
企业邮箱|Business email
作废这个链接？客户将无法再打开。|Revoke this link? Customers will no longer be able to open it.
全部账号状态正常|All accounts are healthy
内容维护|Content maintenance
删除这条记录？|Delete this record?
协议编号|Agreement ID
图片超过 8MB，请先压缩|Image exceeds 8MB. Compress it first.
域名代管|Managed domain
域名信息已保存|Domain information saved
复制失败，请手动选择|Copy failed. Select the text manually.
复制失败，请长按选择|Copy failed. Press and hold to select.
完成|Done
客户档案已保存|Customer record saved
密码已修改|Password changed
对使用旧镜像的站点重建容器？期间站点会短暂不可用（约 10-30 秒）。|Rebuild sites using older images? Sites will be briefly unavailable (about 10–30 seconds).
已作废|Revoked
已保存|Saved
已停用|Disabled
已关闭|Disabled
已删除|Deleted
已失效|Expired
已应用到站点，刷新页面即可看到|Applied to the site. Refresh to see the changes.
已开启两步验证|Two-step verification enabled
已更新|Updated
已生成新恢复码|New recovery codes generated
已记账|Transaction recorded
已过期|Expired
年费 (SGD)|Annual fee (SGD)
建站|Website setup
恢复该站点？|Restore this site?
所选服务商|Selected provider
托管|Hosting
技术支持|Technical support
按钮文字|Button text
提交中…|Submitting…
支出|Expense
收入|Income
暂停该站点？客户将无法访问。|Suspend this site? Customers will be unable to access it.
暂时无法获取状态|Status is temporarily unavailable
最新|Up to date
有更新|Update available
有账号密码超过 180 天未更换|Some account passwords are over 180 days old
服务到期|Service expiry
服务开始|Service start
未登记|Not registered
检查中…|Checking…
检查中（要拉镜像，可能要几分钟）…|Checking images (may take a few minutes)…
正在发布页面…|Publishing pages…
正在生成并发送…|Generating and sending…
正常|Healthy
此字段|This field
电话 / WhatsApp|Phone / WhatsApp
登录已过期，请重新登录|Session expired. Sign in again.
签署日|Signed on
续费几年？（1-5）|Renew for how many years? (1–5)
联系人|Contact person
自定义场景|Custom scenario
解析托管|Managed DNS
记录已添加|Record added
请重试|Please retry
读取中…|Loading…
邮箱|Email
重建中…|Rebuilding…
链接已复制|Link copied
需重建|Rebuild required
首年服务费|First-year service fee
+ 添加一条|+ Add item
6 位数字|6 digits
@ 或 www|@ or www
UEN / 注册号|UEN / registration number
(全部允许)|(All allowed)
(无)|(None)
1. 在验证器 App（Google Authenticator / 1Password）里选择扫描二维码|1. Choose Scan QR code in your authenticator (Google Authenticator / 1Password)
2. 扫描下方二维码；也可以手动输入密钥：|2. Scan the QR code below, or enter the key manually:
3. 输入 App 显示的 6 位验证码完成绑定|3. Enter the 6-digit code to finish setup
DNSSEC：未启用（演示解析器不支持签名，生产接 PowerDNS 后可开）|DNSSEC: disabled (the demo resolver does not support signing; a production PowerDNS setup can enable it)
两步验证已开启|Two-step verification is enabled
两步验证未开启|Two-step verification is not enabled
作废|Revoke
保存客户档案|Save customer record
值|Value
公网委托检测|Check public delegation
关闭两步验证|Disable two-step verification
其他|Other
到期日|Expiry date
启用 DNS 托管|Enable managed DNS
在客户账户|In customer's account
在我们账户（代管）|In our managed account
备注|Notes
复制 hosts 行|Copy hosts entry
复制全部恢复码|Copy all recovery codes
复制地址|Copy address
复制网址|Copy URL
工时|Labor
已上传|Uploaded
已下单|Ordered
已开|Enabled
已锁定|Locked
开启两步验证|Enable two-step verification
归属|Ownership
当前演示端口|Current preview port
恢复码（只显示这一次）|Recovery codes (shown only once)
手机丢失或换机时，用任一码代替验证码登录，每码只能用一次。请打印或存进密码管理器。|If you lose or replace your phone, use a recovery code to sign in. Each code works once. Print them or save them in a password manager.
把域名的 NS 改成下面两条，解析就由我们接管。|Set the domain's nameservers to the two entries below to delegate DNS to us.
新增|Added
无|None
服务|Services
服务器|Server
服务范围|Service scope
服务费|Service fee
未开|Disabled
本机解析检查|Check local DNS
注册商|Registrar
添加记录|Add record
类别|Category
类型|Type
系统|System
自动续费|Auto-renew
记一笔|Add transaction
证书|Certificate
账号安全总览|Account security overview
这个站点还没有托管 DNS。启用后会自动创建区，并把 @ 与 www 指到服务器。|Managed DNS is not enabled. Enabling it creates a zone and points @ and www to the server.
邮件未发送|Email not sent
重新生成恢复码|Regenerate recovery codes
重置密码|Reset password
镜像|Image
验证码|Verification code
（或粘贴下面的链接）|(or paste the link below)
（约 60 秒）|(about 60 seconds)
背景|Background
浅色交替|Alternate light surface
紧凑|Compact
首屏|Hero
顶部小字|Eyebrow text
主标题|Main heading
说明文字|Description
标签胶囊|Badges
显示宝石插画|Show gem illustration
卡片网格|Card grid
小标题|Eyebrow
大标题|Heading
引导文字|Introductory text
卡片|Cards
标题|Title
说明|Description
标题居中|Center heading
品牌色顶条|Brand accent border
左右分栏|Split layout
正文|Body copy
右侧要点|Right-side points
改用图片（留空则显示要点）|Use an image (leave blank to show points)
数字条|Statistics row
数字|Statistics
数值|Value
行动区|Call to action
按钮链接|Button link
整幅照片|Full-width photo
图片地址|Image URL
图片说明|Image caption
替代文字（无障碍）|Alt text (accessibility)
图片网格|Image grid
图片|Images
底部备注|Footer note
评价|Testimonials
三列网格|Three-column grid
评价条目|Testimonial items
内容|Content
署名|Attribution
头像字母|Avatar initials
表格|Table
表格内容|Table content
要点列表|Key points
要点|Points
联系表单|Contact form
自定义 HTML|Custom HTML
HTML 内容|HTML content
`.trim().split('\n').map(line=>{const i=line.indexOf('|');return [line.slice(0,i),line.slice(i+1)];})));
