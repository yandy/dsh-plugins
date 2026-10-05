# dsh-coding-preset

DeepSeek Harness 的 **Coding agent preset**：内置「标准模式」的全部能力，外加一个**可扩展的内置技能包**。
当前技能包是 [obra/superpowers](https://github.com/obra/superpowers) 的 15 个 skill；以后加技能不需要改预设名、
不需要改包名，也不需要手抄插件列表。

- **预设**：`id: coding`，显示名 `Coding`，`order: 10`。
- **声明**：`cordis.patch.yml` 由 `preset.delta.yml` + 上游基线**生成**（不要手改）。
- **技能**：包内 `skills/`，由内置 `@deepseek-ai/dsh-skill-filesystem` 直接读取；声明里没有任何设备路径
  （用的是 `baseUrl` 相对表达式，见下）。
- **作用域**：技能注册在 Coding 预设自己的作用域层，只有绑定该预设的会话能看到，其他预设不受影响。

## 重新生成 / 漂移校验

```bash
python3 tools/build-preset-patch.py            # 重新生成 cordis.patch.yml（需要 PyYAML）
python3 tools/build-preset-patch.py --check     # 与磁盘上的文件比对；上游基线变了就退出码 1 并打印 diff
python3 tools/build-preset-patch.py --baseline /path/to/standard.patch.yml   # 显式指定基线
```

生成文件头部记录了基线的 **sha256**，所以 DSH 升级导致 `standard` 变化时，`--check` 一定会失败，
diff 里能直接看到新增/改动的行。建议放进 pre-commit 或发布前的检查。

基线自动发现顺序：`$DSH_HOME/profiles/*/node_modules/...`（向上逐级查找）→ `~/.npm/_npx/*/node_modules` →
`PATH` 上 `dsh` 所在安装的 `node_modules`。

## 当前差异（相对 standard）

只有一行不同：`skill-filesystem` 增加 `customSkillDirs`，指向本包自带的 `skills/`：

```yaml
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              customSkillDirs:
                - !!js >-
                  process.getBuiltinModule('node:url').fileURLToPath(new URL('skills/', baseUrl))
```

`baseUrl` 是**声明文件自己的 URL**，因此解析结果永远落在"这个包被安装到的地方"，与设备、路径、安装方式无关。

## 新增技能

### A. 打包进本包（推荐，随包分发）

```bash
# 1) 放入 skills/<name>/SKILL.md（frontmatter 至少含 name、description，name 为 kebab-case）
#    资源文件（references、scripts 等）放同一目录
# 2) 重新打包并重装
pnpm pack
dsh plugin --profile web add /path/to/dsh-coding-preset-<version>.tgz
```

不需要改 `plugin.js`、不需要重建索引：内置 provider 自己解析 frontmatter 与 `whenToUse`/invocation 字段。
（用 `dsh plugin add <目录>` 以 link 安装时，丢进目录即生效，无需重装。）

### B. 给预设再加插件行

在 `preset.delta.yml` 里启用 `append`，然后重新生成：

```yaml
append:
  after: skill-filesystem     # 或 end
  rows: |
    - id: skill-office
      name: '@deepseek-ai/dsh-skill-office'
```

### C. 改上游某行

在 `preset.delta.yml` 的 `replace` 下按行 id 重述该行（必须整体重述，包括 `name`）。

## 安装与分享

```bash
dsh plugin --profile web add /path/to/dsh-coding-preset-1.1.0.tgz   # tarball，离线可用
dsh plugin --profile web add /path/to/dsh-coding-preset             # 本地目录（link，开发用）
dsh plugin --profile web add 'github:yandy/dsh-plugins#main&path:dsh-coding-preset'  # github
```

也可以在 Web 界面「设置 → 插件 → 安装 bundle」里填路径或 git 规格。包没有任何 npm 依赖，离线可装。
安装后 profile 的 `dsh.profile.bundles` 会加入 `dsh-coding-preset`。

## 结构

```
package.json            # dsh.bundle.patch → cordis.patch.yml
preset.delta.yml        # 唯一手写来源：预设身份 + replace / append
cordis.patch.yml        # 生成物：完整预设声明（do not edit）
skills/<name>/SKILL.md  # 技能包（数据）
tools/build-preset-patch.py
README.md
```

## 打包技能管理

### 添加技能

```sh
npx skills add <package> --skill <skills> -y
```

### 删除技能

```sh
npx skills remove <skills> -a pi
```

### 列举技能

```sh
npx skills ls -a pi
```

### 现有技能

- [superpowers](https://github.com/obra/superpowers)
```sh
# npx skills add obra/superpowers -y
```

- browser automation
```sh
npm install -g playwright @playwright/cli
playwright install chromium firefox
# npx skills add microsoft/playwright-cli --skill playwright-cli -y
```

- [context7](https://github.com/upstash/context7)
```sh
npx ctx7 login
# npx skills add upstash/context7 --skill find-docs -y
```

## 备注

- 技能正文与资源著作权归上游项目（MIT）。
- 走 `customSkillDirs`（rank 300）意味着：**项目级**技能（`.dsh/skills`、`.agents/skills`，rank 100/200）
  仍优先，而**用户级**技能（`~/.dsh/skills`、`~/.agents/skills`，rank 400/500）同名时会输给本包。
- 本包不提供任何 Cordis 服务，因此预设不需要 `isolate` realm。
