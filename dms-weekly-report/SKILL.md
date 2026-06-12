---
name: dms-weekly-report
description: >
  Use when the user asks for DMS weekly report, inquiry summary, completed inquiry
  extraction, or mentions "自动周报", "周报生成", "询价汇总", "本周询价", "已办询价",
  "做周报", "一键周报", "导出询价明细", "帮我做一下周报", "出个报表", "汇总一下询价",
  "看一下询价进度".
  Not for modifying or approving DMS data.
metadata:
  author: Meiuxs
  version: 1.3.0
  updated: 2026-06-10
---

# DMS 非标询价周报生成器

## Overview

一键从 DMS 流程中心筛选已办询价流程，自动登录、提取项目详情和 BOM 清单、检查下单状态，生成含 **4 个 Sheet** 的格式化 Excel 汇总报告（询价汇总/询价统计/日期查询/数据看板）。支持仅统计模式（`--stats-only`）跳过浏览器操作直接重算统计。使用 Playwright 自动化浏览器操作，支持多 Tab 并行提取和会话持久化。

> **仅统计模式输入规则：** 默认在 `--output-dir` 目录中自动查找 `询价汇总_{时间戳}.xlsx`、`询价汇总.xlsx` 或 `询价汇总_v2.xlsx`（按优先级）。可通过 `--input-xlsx FILE` 显式指定输入文件。未找到则终止执行，提示先运行完整模式。

## When to Use

用户说以下内容时直接触发：

| 场景 | 用户可能说 |
|------|-----------|
| **定期周报** | "帮我做周报" / "这周询价汇总一下" / "做本周询价周报" |
| **临时查询 / 批量获取** | "查一下上周的询价" / "看看这个月的流程" / "把最近两周的都提取出来" |
| **导出汇总** | "导出询价明细到Excel" / "把已办询价整理成表格" / "出个报表" |
| **下单核查** | "检查哪些询价已下单了" / "哪些还没下单" |

## When NOT to Use

- ❌ **审批/驳回流程** — 本 skill 只读，不执行任何写入操作
- ❌ **创建新的询价流程** — 需要手动在 DMS 中填写
- ❌ **修改已有数据** — 不在本 skill 范围内
- ❌ **非 DMS 系统的数据提取** — 本 skill 仅针对 DMS 流程中心

## 使用流程

> **路径说明：** 以下命令中的 `$SKILL_DIR` 指向本 skill 的安装目录。Agent 执行前自动检测路径（兼容 Claude Code 的 `~/.claude/skills/`、WorkBuddy 的 `~/.workbuddy/skills/` 等）：
> ```bash
> if [ -d "$HOME/.workbuddy/skills/dms-weekly-report" ]; then
>   SKILL_DIR="$HOME/.workbuddy/skills/dms-weekly-report"
> else
>   SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
> fi
> ```

### 步骤 1：解析并确认日期范围

先运行 `--help` 查看脚本支持的日期标签和参数说明：

```bash
python "$SKILL_DIR/scripts/resolve_date_range.py" --help
```

确认支持的格式后，选择合适的标签传给脚本，用 `--json` 输出解析结果：

```bash
python "$SKILL_DIR/scripts/resolve_date_range.py" "上个月到现在" --json
```

> 输出示例：`{"start": "2026-05-12", "end": "2026-06-12", "range_str": "2026-05-12 ~ 2026-06-12"}`
>
> 此步骤用于**确认日期解析是否正确**。Agent 会根据输出的日期值，在**步骤 3** 中直接填入命令，不依赖 Shell 跨步骤变量。

### 步骤 2：检查运行环境

确认日期范围后，先检查 DMS 登录凭据和浏览器环境：

```bash
python "$SKILL_DIR/scripts/dms_credentials.py" --check-browser
```

- 检测来源：当前环境变量、bash 系（.bashrc/.bash_profile/.profile）、zsh 系（.zshenv/.zprofile/.zshrc）、Windows 注册表/PowerShell
- 同时验证 Playwright Chromium 是否已安装

**检查结果分支：**
- ✅ 凭据就绪 + 浏览器正常 → 直接进入**步骤 3**
- ❌ 凭据缺失 → 提示用户配置环境变量 `DMS_USER` / `DMS_PASSWORD`，用户回复“已配置”后重新执行 `dms_credentials.py` 确认，再进入**步骤 3**

### 步骤 3：运行脚本

先用 `--help` 查看 `run_weekly_report.py` 的全部参数说明和使用示例：

```bash
python "$SKILL_DIR/scripts/run_weekly_report.py" --help
```

Agent 根据**步骤 1** 解析出的日期，直接用日期字符串传参（不依赖 Shell 变量）：

```bash
SCRIPT="$SKILL_DIR/scripts/run_weekly_report.py"

# 用步骤 1 确认的日期值直接传参 + 无头模式
python "$SCRIPT" --output-dir "$PWD" --start-date "2026-05-12" --end-date "2026-06-12" --headless
```

> **注意：** Agent 会在步骤 1 输出后自动将日期值填入步骤 3 的命令中，用户无需手动操作。

**常用模式速查：**

| 场景 | 命令 |
|------|------|
| 本月数据（无头模式） | `python "$SCRIPT" --output-dir "$PWD" --start-date "2026-06-01" --end-date "2026-06-12" --headless` |
| 自定义日期 | `python "$SCRIPT" --output-dir "$PWD" --start-date "2026-05-12" --end-date "2026-06-12" --headless` |
| 上周数据 | `python "$SCRIPT" --output-dir "$PWD" --weeks 1` |
| 仅统计（跳过浏览器） | `python "$SCRIPT" --output-dir "$PWD" --stats-only --start-date "2026-06-01" --end-date "2026-06-12"` |

> **提示：** `--output-dir` 建议用 `"$PWD"` 输出到用户当前目录。
>
> **注意：** 流程编号在 Excel 中显示不正确时，见 FAQ「流程编号显示为不正确的数字」。

### 步骤 4：呈现结果

脚本执行后会在终端打印摘要并生成 Excel，直接向用户报告：

```
✅ 周报生成完成！
📊 查询范围：2026-06-01 ~ 2026-06-06
📝 共 12 条询价记录
🟢 已下单 5 条 | 🔴 未下单 7 条
📎 Excel文件已保存到：{output_dir}/询价汇总_{时间戳}.xlsx
📎 HTML 报表已保存到：{output_dir}/询价周报报表_{时间戳}.html
```

### 步骤 5：回顾与反思（流程完成后）

周报生成完成后（或过程中出现问题导致卡住时），**agent 主动自我反思本次执行过程**：

**反思清单：**
1. 本次执行中遇到了哪些问题（脚本报错、数据异常、登录失败、下单检查超时等）？
2. 数据是否完整合理（提取条数是否符合预期、日期范围是否正确）？
3. 当前 SKILL.md 的说明是否能覆盖这些场景？
4. 脚本是否有 bug 或功能缺失（选择器失效、超时过短、并发控制等）？
5. 用户操作过程中有哪些可以优化的交互点？

**将反思结果提炼为具体优化建议，使用 `AskUserQuestion` 主动向用户提出：**

```markdown
AskUserQuestion:
  "本次周报执行中发现了以下问题，建议优化：
   1. [问题1] → 建议 [优化方案]
   2. [问题2] → 建议 [优化方案]
   您是否有补充？确认后我将更新 SKILL.md。"
```

**根据用户确认/补充后：**
- ✅ 更新 SKILL.md 中的说明、注意事项、常见错误
- ✅ 修改脚本或参考文件后，按项目 CLAUDE.md 同步规则复制到对应 skill 目录

> **原则：** 先自行反思提炼，再给用户确认补充。

## Quick Reference

### 参数速查

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--output-dir DIR` | 输出目录 | 当前工作目录 |
| `--headless` | 无头模式（不显示浏览器） | 显示浏览器 |
| `--weeks N` | 最近 N 周（0=本周, 1=上周） | 0 |
| `--start-date YYYY-MM-DD` | 自定义开始日期 | 本周一 |
| `--end-date YYYY-MM-DD` | 自定义结束日期 | 今天 |
| `--date-label LABEL` | 中文日期标签（自动解析，如"本月"/"上个月到现在"） | 无 |
| `--workers N` | 并行并发数 | 4 |
| `--verbose` | 详细日志输出 | 仅 info |
| `--stats-only` | 仅统计模式：从已有 Excel 读取数据，按日期范围重新统计，跳过浏览器操作 | 自动查找 |
| `--input-xlsx FILE` | 仅统计模式下显式指定输入的询价汇总 Excel 文件路径 | 自动查找 |
| `--this-month` | 快捷统计本月（配合 `--stats-only` 使用） | 无 |

### 输出文件

> ⚠️ 每次运行自动生成带时间戳文件（`YYYYMMDD_HHMMSS`），避免覆盖历史数据。
> 详见 `references/output_format.md`。

- `{output_dir}/询价汇总_{时间戳}.xlsx`
- `{output_dir}/询价汇总_{时间戳}_v2.xlsx`（文件被占用时的备用）
- `{output_dir}/询价周报报表_{时间戳}.html`

### HTML 独立生成（无需浏览器）

从已有 xlsx 单独生成 HTML 报表（不经过 DMS 登录流程）：

```bash
python "$SKILL_DIR/scripts/generate_html_report.py" \
  --xlsx "询价汇总.xlsx" \
  --range "2026-06-01 ~ 2026-06-07"
```

详见 `scripts/generate_html_report.py` 模块文档和 `references/report_template.html`。

### Excel 列定义

详见 `references/excel_columns.md`。

## 前置依赖

首次使用前安装必要依赖。详见 `references/installation.md`（含环境要求、虚拟环境、代理配置、版本锁定、常见失败处理）：

```bash
pip install playwright openpyxl && playwright install chromium
```

## 登录配置

DMS 登录凭据通过环境变量读取，**不硬编码密码**。详见 `references/login_config.md`（含检测顺序、持久化机制）：

```bash
python "$SKILL_DIR/scripts/dms_credentials.py" --check-browser
```

**配置方式（二选一）：**

```bash
# 临时（当前会话）
export DMS_USER="your_email@trinapower.com" DMS_PASSWORD="your_password"

# 永久（推荐）：追加到 ~/.bashrc 后 source
echo -e 'export DMS_USER="your_email@trinapower.com"\nexport DMS_PASSWORD="your_password"' >> ~/.bashrc
source ~/.bashrc
```

**检查结果分支：**
- ✅ 凭据就绪 + 浏览器正常 → 进入**步骤 3**
- ❌ 凭据缺失 → 提示用户配置，用户回复"已配置"后重新检测确认，再进入**步骤 3**

## 安全约束

**本 skill 仅执行查询和数据提取操作，严格遵守以下规则：**

- **禁止：** 审批通过/驳回、提交表单、删除记录、修改数据、执行下单、发送邮件等任何写入/修改类操作
- **允许：** 登录、导航页面、筛选查询、读取页面内容
- 页面出现审批、提交、删除等按钮 → **一律忽略不点击**
- 意外跳转到审批/修改页面 → 立即返回，终端提示用户
- 所有浏览器操作仅限于读取页面内容，不做任何数据变更
- 使用 `ignore_https_errors=True` 仅用于内部 DMS 系统，不适用于生产环境

## 常见问题

详见 `references/faq.md`（覆盖：环境变量检测、0 条记录、选择器失效、Excel 保存失败、验证码、流程编号精度丢失）。
## 脚本架构

核心模块：
- **完整模式：** 配置 → 登录 → 筛选 → 提取 → 下单检查 → Excel（4 Sheet） → 终端摘要
- **仅统计模式：** 配置 → 读取已有 Excel → 按日期筛选 → 更新统计 Sheet → 终端输出

详细实现见 `scripts/run_weekly_report.py`。
