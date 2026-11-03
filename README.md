# KampongFlow

面向新加坡中小企业的**多租户建站与代管平台**：域名、建站、DNS、账单、客户管理，一套后台全包。

客户只签服务协议、付一次钱，剩下的全部由运营方完成——**客户不需要登录任何平台**。

```
客户签协议 → 收款记账 → 开通站点 → 建站 → DNS → 交付
                ↓
        每天 09:00 一封邮件：谁要到期、谁余额不足、谁提交了线索
```

## 特性

| 模块 | 能力 |
|---|---|
| 站点 | 每站点独立 WordPress + MariaDB 容器，一键开通/暂停/续费 |
| 建站 | 12 类区块、5 套行业模板、结构化编辑器、图片自动转 WebP + srcset |
| 发布 | 草稿/预览/发布分离，逐页发布，发布前校验与回滚 |
| DNS | 自建权威解析，按站点托管区，记录增删、健康检查、公网委托检测 |
| 账单 | 一次性交付账单、续费账单、中文 PDF、到期自动延期 |
| 客户 | 客户档案、协议、服务期、预付款账本、负责人 |
| 团队 | 多账号、三角色（管理员/运营/财务）、写操作审计、登录锁定 |
| 安全 | TOTP 两步验证、恢复码、密码策略、会话持久化、操作留痕 |
| 通知 | 每日摘要：到期、低余额、新线索（Resend / SendGrid / SMTP） |

## 快速开始

```bash
git clone https://gitee.com/wesouler/mvp.git
cd mvp
chmod +x install.sh
./install.sh
```

安装脚本会问你要：安装目录、控制台端口、主域名、管理员密码、通知邮箱。
不知道填什么就一路回车，脚本会给默认值。

装完打开 `http://127.0.0.1:18090`，用 `admin` 和你设的密码登录。

非交互安装：

```bash
./install.sh -y --dir /opt/kampongflow \
  --admin-pass 'MyStr0ng-Pass-2026' \
  --email ops@example.sg --demo
```

只装控制台、不碰 Docker：

```bash
./install.sh -y --no-docker -d ./kf
```

完整参数见 `./install.sh --help`。

## 目录结构

```
.
├── install.sh              一键安装（交互 + 参数）
├── console/kf_console.py   管理后台：HTTP 服务、API、单页界面
├── core/
│   ├── kf_sections.py      区块渲染、表单 schema、图片处理
│   ├── kf_dns.py           权威 DNS 服务与区数据
│   └── kf_template.py      站点初始化、设计令牌、行业模板
├── tools/
│   ├── kf_provision.sh     开通一个站点（容器 + 数据库 + 主题）
│   ├── kf_update.py        镜像更新检查与滚动升级
│   └── kf_notify.py        每日摘要邮件
├── theme/kampong/          WordPress 主题
├── templates/              套餐与设置的初始值
└── docs/                   部署、运维、安全
```

运行数据（`sites/`、`console/*.json`、`assets/`）不进入版本库。

## 环境要求

- Linux（systemd 可选）
- Python 3.8+
- Docker + Docker Compose（启用容器站点时）
- 端口：控制台 18090、站点 18080 起、DNS 5354

## 文档

- [部署](docs/部署.md) — 端口、服务、首次配置
- [运维](docs/运维.md) — 日常操作、备份、排障
- [安全](docs/安全.md) — 账号、权限、MFA 与恢复

## 许可

私有项目，未经授权请勿分发。
