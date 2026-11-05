# MVP 统一管理入口

运营人员只登录 MVP（含该账号已启用的两步验证），在「站点总览」点击「进入 WordPress 后台」。管理员对应独立 WordPress 管理员账号，运营角色对应编辑账号；财务无权进入。也可以在团队角色权限中撤销 `/api/wordpress/login` 权限。

接入后的站点不再接受 WordPress 本地密码、找回密码、注册、Application Passwords 或 XML-RPC 登录。原有 WordPress 会话在接入时撤销，旧账号密码不能用于网页登录。原站点数据和主题保留；专用 `mvp_…` 账号由 MVP 身份建立，不同步密码。WordPress 登录地址会跳转 MVP，后台有「返回 MVP 管理」链接，退出链接指向 MVP。

## 会话与安全边界

1. 浏览器在目标站点获得 180 秒的随机校验值（`__Host-`、Secure、HttpOnly、SameSite=None），仅其 SHA-256 值送到 MVP。
2. MVP 验证当前浏览器的登录会话和权限，签发 60 秒、一次性、绑定站点和浏览器的凭证。凭证通过 POST 表单传递，不出现在地址栏或访问日志中。
3. WordPress 使用独立站点密钥签名请求，到 MVP 消耗凭证。返回的授权绑定 MVP 会话和账号安全版本。
4. WordPress 每次认证请求都在线核验授权，不缓存认证结果；退出 MVP、停用账号、重置密码/MFA、角色或权限变化、会话过期后，后续受保护请求失效。已发起的请求不能被追溯撤销。
5. MVP 不可用时拒绝后台认证，不降级为本地密码登录。访客匿名网页与公开咨询表单继续使用原有流程。

服务端请求使用每站独立 HMAC-SHA256 密钥、时间戳和一次性随机值，拒绝过期、篡改、重复及跨站点请求。凭证和授权在 MVP 中只保存散列值；配置和状态文件权限 0600，代码发布不覆盖。

## 接入和维护

在已部署的新版本上执行（用可控制且已配置 HTTPS 的真实站点 URL）：

```sh
python tools/kf_sso_install.py \
  --base /path/to/kampongflow \
  --slug example \
  --console-url https://mvp.example.com \
  --site-url https://example.com
```

安装器只写入专用 MU 插件 `wp-content/mu-plugins/kf-mvp-sso.php` 和 WordPress 的 `kf_mvp_sso` 选项，并撤销旧会话；不替换站点主题。独立密码说明会从交接单移除。MVP 的 `console/wordpress-sso.json` 保存统一入口和每站密钥，`console/wordpress-sso-state.json` 保存短期凭证、授权与防重放状态。不要将这些文件或 WordPress 数据库备份公开。

配置统一入口后，MVP 新建站点会自动接入同一机制；站点域名和 HTTPS 可用后才能从浏览器进入后台。接入失败会明确显示站点开通失败，必须修复后才能交付。

没有隐藏的公网密码恢复入口。维护人员仍可通过服务器终端与 WP-CLI 修复配置和服务；WP-CLI 不使用浏览器单点登录。生产 MVP 已启用的 MFA 不会被迁移脚本关闭。

## 接口与验证

- `GET /api/wordpress/sites`：当前用户可用的站点入口，不返回密钥。
- `GET /wordpress/authorize`：必须具有有效 MVP 浏览器会话；拒绝仅 Basic Auth 的请求。
- `POST /api/wordpress/callback`：仅接受经站点密钥签名的限定大小请求，操作为 `consume/check`。

测试覆盖单次使用、并发消耗、浏览器绑定、签名/重放、跨站点、到期、账号/会话撤销、权限过滤、跳转地址，以及真实 WordPress 浏览器登录和关闭旧入口。
