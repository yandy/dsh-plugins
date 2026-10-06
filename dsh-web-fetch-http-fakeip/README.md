# dsh-web-fetch-http-fakeip

让 `web_fetch` 在 **Clash/mihomo fake-ip DNS** 下继续可用的 Cordis 插件。

内置 provider 要求解析结果**全是公网单播**，而 fake-ip 模式返回的是 Clash 地址池地址（`198.18.x.x`、
`fdfe:dcba:9876::/64`…），于是每次抓取都在连接前被拒。本插件把这些地址加入白名单——**只有你写的段被放行**：
传输、重定向、上限、解码、超时全部沿用内置实现，私有段 / 环回 / 链路本地 / CGNAT 照旧被拒，IP 字面量永不因段放行。

## 安装

```sh
# 从仓库装（推荐）
dsh plugin --profile web add 'github:yandy/dsh-plugins#main&path:dsh-web-fetch-http-fakeip'

# 本地目录（软链，改完重启即生效）/ tarball（离线，按 files 裁剪）
dsh plugin --profile web add file:/abs/path/dsh-web-fetch-http-fakeip
pnpm --dir dsh-web-fetch-http-fakeip pack && dsh plugin --profile web add /abs/path/dsh-web-fetch-http-fakeip-0.1.0.tgz
```

装完重启 dsh。bundle 层会自动禁用内置的 `web-fetch-http` 行并插入本插件行（否则 provider id 撞车）。

## 配置

bundle 自带的默认段是 `198.18.0.1/16` + `fdfe:dcba:9876::1/64`（Clash Verge 常见配置）。要改就在 profile
自己的 patch 层里按行 id 重述——它在所有 bundle **之后**应用，且行配置是整体替换的，所以 `name` 要一起写：

```yaml
# ~/.dsh/profiles/web/cordis.patch.yml
- id: web-fetch-http-fakeip
  name: 'dsh-web-fetch-http-fakeip'
  config:
    fakeIpRanges:            # 必填，必须与 Clash 的 dns.fake-ip-range / fake-ip-range6 一致
      - 198.18.0.1/16
      - fdfe:dcba:9876::1/64
    debug: true              # 每次放行/拒绝打一行 stderr 日志
```

其余字段默认值与内置 provider 一致：`id`（`http`）、`maxResponseBytes`（5e6）、`maxBodyChars`（1e5）、
`timeoutMs`（30000）、`maxRedirects`（5）、`userAgent`（内置 UA）。

安全边界：段要**窄且专属**（别写 `fc00::/7`、`198.0.0.0/8`）；放行之后目的地由 Clash 反查与你的规则决定，
等价于把出口信任交给 Clash 规则。

## 验证

```sh
# 组合是否生效：web-fetch-http 带 disabled，旁边是本插件行
dsh --profile web --dump-config | grep -B3 -A10 -E "web-fetch-http(-fakeip)?"

# 真实抓取（仓库内执行；会逐跳打印决策）
pnpm test:fakeip
```

## 排错

| 现象 | 处理 |
|---|---|
| 仍报 `resolves to a non-public IP address` | 段不匹配：开 `debug`，按日志里的 `refused <host>: <地址>` 核对 Clash 的 `fake-ip-range` / `fake-ip-range6`。 |
| 只配了 IPv4 段不生效 | 规则是**整组应答**都要放行：把 v6 段也写进去，或关掉 Clash 的 `dns.ipv6`。 |
| `fakeIpRanges is required` / `entry is not a CIDR` | 段必须写、且带前缀长度（照 Clash 的写法，如 `198.18.0.1/16`）。 |
| `cannot load @deepseek-ai/dsh-web-fetch-http` / `ipaddr.js` | 在启动 shell 里 `export DSH_WEB_FETCH_FAKEIP_PEER_ROOT=<dsh 安装>/node_modules`（`DSH_` 前缀那只不能进 `.env`）。 |
| 改了源码没反应 | 先重启 dsh（模块在启动时加载）；tarball / git 安装还要重新 `add`。 |
| `--dump-config-schema` 退出码 1 | 与插件无关（shipped profile 自带的 schema 走查报错），别当作"插件是否加载成功"的判据。 |

## 卸载

```sh
dsh plugin --profile web remove dsh-web-fetch-http-fakeip
```

实现约束、smoke 用法、与宿主版本的关系见 [DEVELOPMENT.md](./DEVELOPMENT.md)。
