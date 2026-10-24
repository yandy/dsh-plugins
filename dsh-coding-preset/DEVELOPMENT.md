# dsh-coding-preset — 开发

面向维护者。用户文档见 [README.md](./README.md)。本文件不进安装产物（`files` 里没有它）。

## 结构

```
preset.delta.yml                  # 唯一手写来源：预设身份 + replace / append
cordis.patch.yml                  # 生成物（do not edit）：完整预设声明 + 基线 sha256
tools/build-preset-patch.py       # 生成 / 校验
tools/sync-superpowers.py         # 从上游同步 superpowers 技能（supo- 前缀）
skills.config.json                # superpowers 上游 repo / ref / 技能清单
.agents/skills/<name>/SKILL.md    # skills CLI 管理的技能（1 个：find-docs）
supo-skills/supo-<name>/SKILL.md  # superpowers 生成物（15 个，do not edit）
.skills-ref                       # 上次同步的 ref（本地状态，gitignore）
package.json                      # files 必须覆盖两个技能根
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

- **加 / 删 superpowers 技能**：改 `skills.config.json` 的 `skills` 清单，再 `uv run tools/sync-superpowers.py`；
  上游新增/删除技能时连 `ref` 一起改。生成物 `supo-skills/` 要一起提交。
- **加 / 删其他技能**：`npx skills add <pkg> -y -a codex`、`npx skills remove <name> -a codex`（会更新 `skills-lock.json`）。
  技能就是 `.agents/skills/<name>/SKILL.md`（frontmatter 至少 `name`、`description`），provider 自己解析，
  不需要改代码或重建索引；目录必须留在 `package.json` 的 `files` 里，`--check` 会拦。
- **加 / 改预设行**：在 `preset.delta.yml` 里 `replace`（按行 id **整体重述**，含 `name`）或 `append`，再重新生成。
  预设身份（`id: coding`、显示名 `Coding`、`order: 10`）也在该文件的 `preset:` 段。
- **dsh 升级后**：重新生成并 review diff（基线行可能有增删改）。

## Superpowers 同步

superpowers 技能是 vendored 产物，由 `tools/sync-superpowers.py` 从上游拉取（`pi-packages/pi-superpowers`
`scripts/download-skills.mjs` 的 Python 移植，落点为本包独占的 `supo-skills/`）：

- `skills.config.json` 固定上游 `repo`、`ref`（当前 `v7.0.1`）与 `skills` 清单；升级 = 改 `ref`（必要时同步清单）后重跑。
- 上游仓库缓存在 `/tmp/dsh-coding-preset-superpowers-cache`：首次 clone，之后 `git fetch`；已在该 ref 上就跳过
  git 操作。
- 每个技能复制到 `supo-skills/supo-<name>/`，只改写文本文件：`SKILL.md` frontmatter 的 `name:` 加 `supo-`、
  `superpowers:<skill>` → `supo-<skill>`、跨技能相对路径 `../<skill>` → `../supo-<skill>`；脚本的可执行位保留。
- `supo-skills/` 是同步专用目录：清单里删掉的技能，对应目录会被清理；`.agents/skills/`（skills CLI 管理）
  完全不受影响。
- `.skills-ref` 记录上次成功同步的 ref（gitignore），别手改；ref 未变且技能齐全时脚本只做清理。
- 两个技能根都登记在 `preset.delta.yml` 的 `customSkillDirs`；新增根要同时进 `package.json` 的 `files`，否则
  `--check` 会拦。
- 同步后 review diff（上游会移动文件、删文档），再把 `supo-skills/` 与 `skills.config.json` 一起提交。

## 当前技能

2 个上游来源。superpowers 走本仓库脚本（带 `supo-` 前缀，不写 `skills-lock.json`），
context7 走 skills CLI（会刷新 `skills-lock.json`）：

| 来源 | 技能 | 拉取 |
|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | 15 个 `supo-*`（`supo-skills/`，清单见 [README](./README.md)） | `uv run tools/sync-superpowers.py`（ref 见 `skills.config.json`） |
| [upstash/context7](https://github.com/upstash/context7) | `find-docs` | `npx skills add upstash/context7 --skill find-docs -y -a codex`，另需 `npx ctx7 login` |

## 两个坑

1. **`baseUrl` 是 profile 目录，不是本包目录**（bundle patch 在 profile 里求值）。所以技能根必须按包名从
   `baseUrl` 解析：`createRequire(baseUrl).resolve('dsh-coding-preset/package.json')` → `dirname` →
   `.agents/skills` / `supo-skills`。写成 `new URL('.agents/skills/', baseUrl)` 会解析到 `<profile>/.agents/skills`，
   而 provider 把"根不存在"当"空根"——**静默注册 0 个技能**。
2. **改包名要同步改表达式里的包名**，否则解析失败（`--check` 会拦这一条）。

`--check` 只做结构检查、不求值 `!!js`，所以改完表达式要在真机验证一次：

```sh
dsh --profile web --dump-config | grep -n preset-coding
ls ~/.dsh/profiles/web/node_modules/dsh-coding-preset/supo-skills | wc -l        # 15（superpowers）
ls ~/.dsh/profiles/web/node_modules/dsh-coding-preset/.agents/skills | wc -l     # 1（find-docs）
```

## 打包

```sh
pnpm --dir dsh-coding-preset pack
tar -tzf dsh-coding-preset/dsh-coding-preset-*.tgz | grep -c '/SKILL.md$'   # 应为 16
```

`files` 决定安装产物：`cordis.patch.yml`、`preset.delta.yml`、`skills.config.json`、`tools`、`.agents/skills`、`supo-skills`、`README.md`。
预设身份 / 技能集合 / 表达式变了就 bump 版本。本地目录安装是软链（改完重启即生效），tarball 与 git 安装要重新 `add`。

## 备注

- `customSkillDirs` rank 300：项目级技能（100/200）优先于本包，本包优先于用户级技能（400/500）。
- 本包不提供任何 Cordis 服务，预设不需要 `isolate` realm。
- 技能著作权归上游项目（superpowers / context7，均 MIT）。
