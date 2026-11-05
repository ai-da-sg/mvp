# GitHub Actions CI/CD

仓库：https://github.com/ai-da-sg/mvp 。CI 在 main 推送和 PR 时运行；生产部署仅支持 Actions 中手动运行 **Deploy production**，选择 main。普通推送不会重启现有服务器。

## 持续集成

- Ubuntu 24.04，Python 3.9 / 3.12：安装 requirements + constraints，执行 AI 接口与发布回滚测试。
- Chromium 浏览器回归：恢复码输入、二级导航与权限、编辑保留、保存失败重试、预览/发布顺序、提示词组合/版本恢复、主题/语言持久化及移动布局；使用隔离的模拟 API，不连接生产。
- 检查 Python、控制台内联 JavaScript、独立 JavaScript、Bash、PHP 语法。
- 所有检查通过后，按 Git 提交打包代码，保存 14 天的 release artifact。包内有提交号、逐文件 SHA256，旁附包校验和。
- 白名单仅包含应用代码、主题、模板和依赖清单；不包含账号、密钥、证书、站点数据、数据库或本机环境文件。

## 配置生产部署

在仓库 Settings → Secrets and variables → Actions（或 production Environment）配置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Secret | DEPLOY_HOST | 可从 GitHub hosted runner 访问的 SSH 主机名/IP |
| Secret | DEPLOY_USER | 拥有现有 systemd 用户服务的账号；当前为 ec2-user |
| Secret | DEPLOY_SSH_KEY | 此账号的专用 SSH 私钥 |
| Secret | DEPLOY_KNOWN_HOSTS | 经独立核验的 SSH 主机公钥记录；非 22 端口使用 `[host]:port` 格式 |
| Variable | DEPLOY_BASE | 当前 `/home/ec2-user/mvp/.venv/kampongflow` |
| Variable | DEPLOY_PYTHON | 当前 `/home/ec2-user/mvp/.venv/bin/python` |
| Variable | DEPLOY_PORT | SSH 端口，缺省 22 |

服务器需要已初始化的安装、用户服务 kf-console/kf-dns/kf-proxy，以及与 constraints.txt 完全一致的虚拟环境。健康检查使用当前默认端口 18090/5354/18444；其他端口需调整部署脚本参数。SSH 会话需能运行 `systemctl --user`（持久用户服务通常需要 linger）。

手动部署会重新运行同一提交的 CI，下载本次运行产物，严格验证 SSH 主机密钥、包校验和及提交号，然后停启 console/DNS 并检查 HTTP、HTTPS、DNS。workflow 的 production concurrency 串行执行部署；服务器另有文件锁。存在活动 AI 任务时拒绝更新。维护窗口操作，避免部署开始时新建任务。

失败时恢复本次替换的代码并再次检查健康；备份位于安装目录 `.code-backups/`。回滚不覆盖用户、账单、站点或数据库。强制断电/SIGKILL、主机故障、不可逆数据迁移和依赖升级不在自动回滚保证范围。依赖不匹配会在停服前拒绝部署，需先准备兼容环境；本版本没有自动虚拟环境切换。已有租户主题不自动覆盖，新主题仅用于后续初始化。

未配置上述连接信息前，CD 不可执行；不要把私钥或运行目录提交到仓库。旧 deploy.sh 为历史流程，未使用新发布包/回滚机制，不建议用于生产。新流程不依赖生产主机作为 GitHub runner。

## 方案依据与下一步

采用 GitHub hosted runner 检查代码，再通过 SSH 更新现有 systemd 服务，适合当前单机部署，避免在生产机执行不受信任 PR。Actions 使用只读 contents 权限和完整提交 SHA 固定依赖。

建议配置 main 分支保护，要求 CI 通过。可在 production Environment 增加部署分支限制和审批，但私有仓库的环境/审批功能受 GitHub 订阅方案影响；YAML 中写 environment 名称并不等于已经设置了审批保护。后续需要零停机或频繁依赖升级时，再引入独立版本目录、虚拟环境切换与应用级迁移方案。

官方参考：[部署与并发控制](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)、[Actions 安全实践](https://docs.github.com/en/actions/reference/security/secure-use)、[环境及订阅限制](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。
