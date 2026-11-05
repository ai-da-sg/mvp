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
DNS 解析|DNS records
运行维护|Maintenance
内容建站|Website content
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
