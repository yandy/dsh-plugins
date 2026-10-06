# dsh-plugins

个人维护的 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（dsh）插件合集：monorepo，
一包一插件，独立版本、独立安装，零依赖、无构建。

| 包 | 做什么 | 文档 |
|---|---|---|
| `dsh-coding-preset` | Coding agent 预设 + 随包技能包（17 个技能） | [用户](./dsh-coding-preset/README.md) · [开发](./dsh-coding-preset/DEVELOPMENT.md) |
| `dsh-web-fetch-http-fakeip` | 让 `web_fetch` 在 Clash/mihomo fake-ip DNS 下可用 | [用户](./dsh-web-fetch-http-fakeip/README.md) · [开发](./dsh-web-fetch-http-fakeip/DEVELOPMENT.md) |

安装（安装/卸载需要 `pnpm`，装完重启 dsh；细节见各包 README）：

```sh
dsh plugin --profile web add 'github:yandy/dsh-plugins#main&path:<包目录名>'
```

## 开发

```sh
pnpm check        # 预设漂移 + JS 语法检查（提交前跑）
pnpm test:fakeip  # fake-ip provider 的真实抓取 smoke（需要网络）
pnpm pack:all     # 两个包各自打 tarball 到包目录
```

需要 Node ≥ 20.16；预设生成/校验还需要 Python 3 + PyYAML。仓库无依赖，不必 `pnpm install`。
实测环境：dsh `0.2.0-rc.2`、Node 24.15、pnpm 11.7；宿主兼容范围写在各包 `package.json` 的
`peerDependencies` 里，dsh 会按它做启动闸门。

迭代流程、实现约束与坑写在**各包的 DEVELOPMENT.md**，根 README 只保留跨包规范：

- **目录**：仓库根下一级、`dsh-<name>`。它同时决定 workspace 成员和安装用的 `path:`。
- **固定文件**：`package.json`、`cordis.patch.yml`、`.gitignore`、`README.md`（面向用户）、
  `DEVELOPMENT.md`（面向开发）；代码按类型放 `index.js`、`test/`、`tools/`。
- **package.json**：`"type": "module"`；`dsh: { manifestVersion: 1, bundle: { patch: "./cordis.patch.yml" } }`；
  `repository` 指到本仓库对应目录；`files` 列全运行时文件（`README.md` 进、`DEVELOPMENT.md` 不进）；
  `license: MIT`（LICENSE 只在仓库根，打包时自动带上）。
- **兼容声明**：宿主版本范围写进 `peerDependencies` 并标 `optional`——dsh 用它对 bundle 做启动闸门。
- **代码**：顶层只 `import 'node:...'`；宿主包用 `createRequire` 从运行中的 dsh 解析，零依赖。
- **文档**：README 讲装/用/验/排错，DEVELOPMENT 讲结构、迭代命令、约束；同一件事只写一处。
- **新增包**：在根 `package.json` 登记 `pack:<name>` 脚本（必要时也登记它的 check）。

## 许可

[MIT](./LICENSE)。`dsh-coding-preset/.agents/skills/` 内的技能正文与资源著作权归各上游项目（均 MIT）。
