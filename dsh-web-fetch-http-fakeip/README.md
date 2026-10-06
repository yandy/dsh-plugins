# dsh-web-fetch-http-fakeip

让 DeepSeek Harness 的 **`web_fetch` 在 Clash/mihomo fake-ip DNS 下继续可用**的 Cordis 插件。

- **做法**：只包一层内置 provider 的解析器 `resolveAddresses`，把本地 fake-ip 段加入白名单；传输、重定向、上限、解码、地址钉住、超时全部沿用内置实现。
- **不加依赖、不走代理**：运行时的 `@deepseek-ai/dsh-web-fetch-http` 与 `ipaddr.js` 从**运行中的 dsh 安装树**解析，拿到的是宿主自己的模块实例。
- **例外是网段级**：只有你写进 `fakeIpRanges` 的段被放行，私有段 / 环回 / 链路本地 / CGNAT / Teredo 照旧被拒；IP 字面量永不因段放行。

## 为什么需要它

内置的 `@deepseek-ai/dsh-web-fetch-http` 会自己解析域名，并要求应答里**每个地址都是公网单播**，否则直接抛 `WEB_BLOCKED_URL`，连接根本不会发出。而 fake-ip 模式下 DNS 返回的是 Clash 的地址池地址：

| 你的配置 | 实际解析结果 |
|---|---|
| `dns.fake-ip-range: 198.18.0.1/16` | `198.18.0.17`（IANA Benchmarking，`ipaddr.js` 判 `reserved`） |
| `dns.fake-ip-range6: fdfe:dcba:9876::1/64` | `fdfe:dcba:9876::12`（ULA，判 `uniqueLocal`） |

这些地址**不是真实目的地**：连接进入 TUN 后，Clash 会把 fake IP 反查回域名，再按你的规则分流——这正是 `curl` 一直正常的原因。所以放行它们不是"信任一个可疑地址"，而是让 `web_fetch` 和其它程序走同一条路。

## 行为

每次抓取：

```
内置校验（公网单播）  ──拒绝──▶  段匹配（全部非公网地址都在 fakeIpRanges 内？）──▶  放行并钉住这组地址
```

- 内置解析器**先跑**，成功就原样返回，插件不介入；
- 只有 `WEB_BLOCKED_URL` 这一种拒绝才进入段匹配：用同一套 `dns.lookup` 重新解析一次，逐个地址判定"公网单播 **或** 落在配置段内"，**全部通过**才放行；
- 段没覆盖到的地址，**原样抛出内置的错误对象**，所以模型看到的信息、错误码语义与未装插件时一致；
- IP 字面量（`http://127.0.0.1:...`、`http://10.0.0.5/`）永不因段放行，即使它正好落在你写的段里。

## 安装

```sh
# 从插件仓库装（bundle 层会自动禁用内置的 web-fetch-http 行并插入本插件行）
dsh plugin --profile web add 'github:yandy/dsh-plugins#main&path=dsh-web-fetch-http-fakeip'

# 本地开发
dsh plugin --profile web add file:/absolute/path/to/dsh-web-fetch-http-fakeip
```

管理命令需要 `pnpm`；运行 dsh 不需要。装完重启 dsh。

> pnpm 对 `file:` 是**拷贝**而非软链：改了源码要重跑一次 `add` 才生效，重启不够。

## 配置

| 字段 | 默认 | 说明 |
|---|---|---|
| `fakeIpRanges` | 必填 | CIDR 列表，**必须与 Clash 的 `dns.fake-ip-range` / `fake-ip-range6` 一致**。 |
| `id` | `http` | provider 注册 id；内置 web 行本来就 pin 了 `http`，改了要同步改 web 行的 `fetchProvider`。 |
| `debug` | `false` | 每次放行/拒绝向 stderr 打一行日志——**这是发现"Clash 改了段但插件没改"的手段**。 |
| `maxResponseBytes` | `5000000` | 响应体字节上限（与内置默认一致）。 |
| `maxBodyChars` | `100000` | 解码后字符上限。 |
| `timeoutMs` | `30000` | 抓取超时。 |
| `maxRedirects` | `5` | 同源重定向跳数上限（`0` 为不跟随）。 |
| `userAgent` | 内置产品 UA | 请求的 `User-Agent`。 |

内置 `web-fetch-http` 行会被禁用，所以它原来的 5 个配置项在这里保持同样的名字与默认值，不会丢配置能力。

## 安全边界

- **段必须窄且专属**：这些段应当只被本地 Clash 的 fake-ip 占用。不要写 `fc00::/7`、`198.0.0.0/8` 这类大段——`fdfe:dcba:9876::/64` 之所以安全，是因为它不会与真实的内网 IPv6 服务冲突。
- **最终目的地交给 Clash 决定**：放行之后，连接去哪里由 fake-ip 反查与你的规则决定。这与"给 dsh 配代理"是同一类信任转移，区别是本插件不改变流量的出口路径（仍走 TUN 与正常分流）。
- 其它非公网范围不受影响：私有、环回、链路本地、CGNAT、Teredo 等照旧被内置校验拒绝。

## 验证

**1. 组合是否生效**（重启前也能看，注意它会写 profile 的 `cordis.yml`）：

```sh
dsh --profile web --dump-config | grep -B3 -A10 -E "web-fetch-http-fakeip|web-fetch-http"
```

期望：`web-fetch-http` 带 `disabled: true`，旁边有 `web-fetch-http-fakeip` 行及其 `fakeIpRanges`。

**2. 模块能否从 profile 目录加载**（只读）：

```sh
cd ~/.dsh/profiles/web && node --input-type=module -e "
  const m = await import('dsh-web-fetch-http-fakeip')
  console.log('模块加载 OK:', m.name, m.inject, typeof m.apply)
"
```

**3. 逻辑与网络通路**（不经过 dsh，直接跑本包自带的 smoke，会打印每一跳决策）：

```sh
DSH_MODULES=$(for d in ~/.npm/_npx/*/node_modules; do [ -d "$d/@deepseek-ai/dsh" ] && echo "$d"; done | head -1)
WEB_FETCH_FAKEIP_PEER_ROOT="$DSH_MODULES" node test/smoke.mjs https://example.com/ https://www.google.com/
```

期望输出：

```
[logger] web_fetch accepts fake-ip ranges [198.18.0.1/16, fdfe:dcba:9876::1/64] (id=http)
dsh-web-fetch-http-fakeip: accepted example.com from fake-ip ranges: fdfe:dcba:9876::10, 198.18.0.15
OK   https://example.com/ => HTTP 200 html chars=577 title="Example Domain"
```

启动后日志里的注册行是：

```
web_fetch accepts fake-ip ranges [198.18.0.1/16, fdfe:dcba:9876::1/64] (id=http)
```

## 排错

| 现象 | 处理 |
|---|---|
| 仍报 `resolves to a non-public IP address` | 段不匹配。开 `debug: true`，日志会给出 `refused <host>: <地址…> outside <你的段>`，拿这个地址核对 Clash 的 `dns.fake-ip-range` / `fake-ip-range6`。 |
| 只配了 IPv4 段却仍不生效 | 规则是"**整组应答**都要被放行"：Clash 开着 `dns.ipv6` 时 AAAA 也会给 fake 地址，不覆盖它就会整组被拒。把 `fake-ip-range6` 也写进 `fakeIpRanges`，或在 Clash 里关掉 `dns.ipv6`。 |
| 段配错但没开 `debug` | 现象与没装插件一样（这是刻意的：不伪造错误类型）。 |
| `fakeIpRanges is required` | 没配段；插件没有"什么都不做"的静默模式。 |
| `fakeIpRanges entry is not a CIDR` | 段必须带前缀长度（照 Clash 的写法，如 `198.18.0.1/16`）。 |
| `fetch provider id "http" is already registered` | 内置 `web-fetch-http` 行还挂着：确认 bundle 层生效（见"验证 1"），或改用独立 `id` 并让 web 行的 `fetchProvider` 指过来。 |
| `cannot load @deepseek-ai/dsh-web-fetch-http` / `ipaddr.js` | 运行时包解析不到：在启动 dsh 的 shell 里 `export DSH_WEB_FETCH_FAKEIP_PEER_ROOT=<dsh 安装>/node_modules`，或在 `~/.dsh/.env` 写 `WEB_FETCH_FAKEIP_PEER_ROOT=…`（`DSH_` 前缀是 bootstrap-only，不能进 `.env`）。 |

## 已知无关报错

`dsh --profile web --dump-config-schema` 在 0.2.0-rc.2 的 shipped `web` profile 上**本来就 exit 1**，与本插件无关：会打印 4 条 `unrecognized Loader tree carrier`（来自 shipped 的 4 个 agent preset 声明 `preset-standard` / `preset-ptc` / `preset-minimal` / `preset-cordis`——它们的 `config.plugins` 里有 `name: cordis:group` 的子行，schema 走查器认不出该 carrier），以及 `config/contactFormUrl`、`config/transcriptView` 两条 warning。装了 `dsh-coding-preset` 会再多一条（`preset-coding`）。**它不能当作"插件是否加载成功"的判据**，请用上面的"验证 2"。

## 实现约束

- 模块顶层**只 import `node:` 内置模块**。外部插件在 profile 目录里无法静态解析运行时的包，所以 `@deepseek-ai/dsh-web-fetch-http` 与 `ipaddr.js` 都通过锚点动态解析（`process.argv[1]`＝运行中的 dsh 入口 → 向上查找 `node_modules`；可用环境变量兜底）。
- 因此本包**不导出 `Config`**（schemastery 也需要静态 import），改由 `apply()` 校验并给出可操作的报错。行配置因此不出现在配置 schema 目录里。
- 不覆盖任何类方法：`provider.resolveAddresses` 是内置类暴露的公开字段，插件只把它换成包装版；`provider.id` 是自有字段，直接赋值。
