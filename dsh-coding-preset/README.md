# dsh-coding-preset

DeepSeek Harness 的 **Coding agent 预设**：内置「标准模式」（standard）的全部能力，外加随包分发的 17 个技能。

## 安装

```sh
# 从仓库装（推荐）
dsh plugin --profile web add 'github:yandy/dsh-plugins#main&path:dsh-coding-preset'

# 本地目录（软链，改完重启即生效）/ tarball（离线，按 files 裁剪）
dsh plugin --profile web add file:/abs/path/dsh-coding-preset
pnpm --dir dsh-coding-preset pack && dsh plugin --profile web add /abs/path/dsh-coding-preset-1.1.0.tgz
```

装完重启 dsh。包零依赖、离线可装。

## 使用

新建或切换会话时选 **Coding** 预设。技能注册在预设自己的作用域层，只有绑定该预设的会话能看到，
其它预设不受影响。技能菜单输入 `/` 打开。

优先级：**项目级**技能（`.dsh/skills`、`.agents/skills`）> 本包 > **用户级**技能（`~/.dsh/skills`、`~/.agents/skills`），
同名时前面的赢。

## 技能（17 个）

| 来源 | 技能 |
|---|---|
| [superpowers](https://github.com/obra/superpowers)（15） | `brainstorming`、`writing-plans`、`executing-plans`、`subagent-driven-development`、`test-driven-development`、`systematic-debugging`、`verification-before-completion`、`requesting-code-review`、`receiving-code-review`、`finishing-a-development-branch`、`using-git-worktrees`、`dispatching-parallel-agents`、`writing-skills`、`using-superpowers`、`diagnosing-superpowers` |
| [context7](https://github.com/upstash/context7)（1） | `find-docs` |
| [playwright-cli](https://github.com/microsoft/playwright-cli)（1） | `playwright-cli` |

后两个依赖外部工具，不装只是这两个技能跑不起来：

```sh
npm install -g playwright @playwright/cli && playwright install chromium firefox   # playwright-cli
npx ctx7 login                                                                    # find-docs
```

## 验证

```sh
dsh --profile web --dump-config | grep -n preset-coding
ls ~/.dsh/profiles/web/node_modules/dsh-coding-preset/.agents/skills | wc -l   # 应为 17
```

## 排错

| 现象 | 处理 |
|---|---|
| 预设列表里没有 Coding | 先重启 dsh；确认上面 `dump-config` 能搜到 `preset-coding`。 |
| 选了 Coding 但技能菜单是空的 | 上面第二条命令应为 17；为空说明安装产物没带技能目录，用 git `path:` 方式重装。 |
| 某个技能看不到 | 可能被项目级同名技能覆盖（优先级见上）。 |
| `--dump-config-schema` 退出码 1 | 与插件无关，是 shipped profile 自带的 schema 走查报错（本包只多一条 `preset-coding`）。 |

## 卸载

```sh
dsh plugin --profile web remove dsh-coding-preset
```

加技能、改预设行、重新生成声明等开发事项见 [DEVELOPMENT.md](./DEVELOPMENT.md)。
