# dsh-web-fetch-http-fakeip — 开发

面向维护者。用户文档见 [README.md](./README.md)。本文件不进安装产物（`files` 里没有它）。

## 结构

```
index.js          # 全部实现：Cordis plugin（name / inject / apply）
cordis.patch.yml  # bundle 层：disabled 内置行 + insert 本插件行
test/smoke.mjs    # 真实抓取 smoke：替身 ctx.web 走真实 apply()
```

## 关键约束

改动这几条会直接坏掉，不是风格问题：

- **顶层只 `import 'node:...'`**：插件装在 profile 目录里，静态解析不到宿主包。
- **宿主包动态解析**：bare specifier → `process.argv[1]` 向上找 `node_modules` → 环境变量
  `WEB_FETCH_FAKEIP_PEER_ROOT`（`DSH_` 前缀那只不能进 `.env`）。必须拿到宿主**同一份**实例，
  进程级代理策略在它里面。
- **不导出 `Config`**（schemastery 也需要静态 import）：由 `apply()` 校验配置并给可操作的报错。
- **不动类方法**：只替换公开字段 `provider.resolveAddresses` 与 `provider.id`；传输、重定向、上限、解码、
  地址钉住、超时仍走内置实现。
- **错误透传**：只有 `WEB_BLOCKED_URL` 进入段匹配；段外原样抛内置错误对象，IP 字面量永不因段放行。

## 迭代

```sh
pnpm test:fakeip        # 仓库根：真实抓取，逐跳打印决策；有失败则退出码 1
pnpm check:syntax       # node --check index.js + test/smoke.mjs

# 反向验证：段外的地址应被拒
node test/smoke.mjs --ranges 10.0.0.0/8 https://example.com/
```

- 只有 fake-ip 环境下才会走到放行分支（输出里出现 `accepted <host> from fake-ip ranges: ...`）；
  普通环境下内置解析器直接成功，smoke 通过只说明"没被弄坏"。
- 改了段匹配 / 解析逻辑，务必在 fake-ip 机器上跑一次真实抓取；目前没有单元测试。
- 用 `--ranges` 可以不改配置直接试段；`debug` 在 smoke 里固定开启。

## 打包

```sh
pnpm --dir dsh-web-fetch-http-fakeip pack    # tgz 落在包目录内
```

`files`：`index.js`、`cordis.patch.yml`、`README.md`（`test/` 与本文件不进安装产物）。

宿主兼容范围写在 `peerDependencies`（标 `optional`），dsh 会按它做启动闸门。要放宽范围
（`>=0.2.0-rc.1 <0.3.0` → 更高）之前，先核对这四处契约：`HttpFetchProvider` 类导出、
`resolveAddresses(hostname, signal)` 字段、`DEFAULT_USER_AGENT`、错误码 `WEB_BLOCKED_URL` /
`WEB_DUPLICATE_PROVIDER`。
