# dsh-coding-preset — 开发

面向维护者。用户文档见 [README.md](./README.md)。本文件不进安装产物（`files` 里没有它）。

## 结构

```
preset.delta.yml                  # 唯一手写来源：预设身份 + replace / append
cordis.patch.yml                  # 生成物（do not edit）：完整预设声明 + 基线 sha256
tools/build-preset-patch.py       # 生成 / 校验
.agents/skills/<name>/SKILL.md    # 技能数据（17 个）
package.json                      # files 必须覆盖 .agents/skills
```

预设声明为什么是生成的：Loader 没有预设继承——被 patch 的行 `config` 整体替换，别的预设 `plugins` 里的行
根本不可寻址，所以派生预设必须重述基线。工具负责照抄 + 替换/插入，并记录基线 sha256，
上游变了 `--check` 必然失败。

## 迭代

```sh
python3 tools/build-preset-patch.py            # 改完 delta 重新生成
python3 tools/build-preset-patch.py --check    # 校验生成物 + 技能根 + files + 包名（推荐每次提交前）
python3 tools/build-preset-patch.py --baseline /path/to/standard.patch.yml   # 找不到基线时显式指定
pnpm check:preset                              # 仓库根的等价命令
```

- **加 / 删技能**：`npx skills add <pkg> -y`、`npx skills remove <name> -a pi`（会更新 `skills-lock.json`）。
  技能就是 `.agents/skills/<name>/SKILL.md`（frontmatter 至少 `name`、`description`），provider 自己解析，
  不需要改代码或重建索引；目录必须留在 `package.json` 的 `files` 里，`--check` 会拦。
- **加 / 改预设行**：在 `preset.delta.yml` 里 `replace`（按行 id **整体重述**，含 `name`）或 `append`，再重新生成。
  预设身份（`id: coding`、显示名 `Coding`、`order: 10`）也在该文件的 `preset:` 段。
- **dsh 升级后**：重新生成并 review diff（基线行可能有增删改）。

## 当前技能

三个上游来源，命令可直接重跑（会刷新 `skills-lock.json`）：

| 来源 | 技能 | 拉取 |
|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | 15 个（清单见 [README](./README.md)） | `npx skills add obra/superpowers -y` |
| [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli) | `playwright-cli` | `npx skills add microsoft/playwright-cli --skill playwright-cli -y`，另需 `npm install -g playwright @playwright/cli && playwright install chromium firefox` |
| [upstash/context7](https://github.com/upstash/context7) | `find-docs` | `npx skills add upstash/context7 --skill find-docs -y`，另需 `npx ctx7 login` |

## 两个坑

1. **`baseUrl` 是 profile 目录，不是本包目录**（bundle patch 在 profile 里求值）。所以技能根必须按包名从
   `baseUrl` 解析：`createRequire(baseUrl).resolve('dsh-coding-preset/package.json')` → `dirname` →
   `.agents/skills`。写成 `new URL('.agents/skills/', baseUrl)` 会解析到 `<profile>/.agents/skills`，
   而 provider 把"根不存在"当"空根"——**静默注册 0 个技能**。
2. **改包名要同步改表达式里的包名**，否则解析失败（`--check` 会拦这一条）。

`--check` 只做结构检查、不求值 `!!js`，所以改完表达式要在真机验证一次：

```sh
dsh --profile web --dump-config | grep -n preset-coding
ls ~/.dsh/profiles/web/node_modules/dsh-coding-preset/.agents/skills | wc -l   # 17
```

## 打包

```sh
pnpm --dir dsh-coding-preset pack
tar -tzf dsh-coding-preset/dsh-coding-preset-*.tgz | grep -c '/SKILL.md$'   # 应为 17
```

`files` 决定安装产物：`cordis.patch.yml`、`preset.delta.yml`、`tools`、`.agents/skills`、`README.md`。
预设身份 / 技能集合 / 表达式变了就 bump 版本。本地目录安装是软链（改完重启即生效），tarball 与 git 安装要重新 `add`。

## 备注

- `customSkillDirs` rank 300：项目级技能（100/200）优先于本包，本包优先于用户级技能（400/500）。
- 本包不提供任何 Cordis 服务，预设不需要 `isolate` realm。
- 技能著作权归上游项目（superpowers / context7 / playwright-cli，均 MIT）。
