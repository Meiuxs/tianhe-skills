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
  version: 1.11.0
  updated: 2026-08-04
---

# DMS 非标询价周报生成器

## Overview

一键从 DMS 流程中心筛选已办询价流程，自动登录、提取项目详情和 BOM 清单、检查下单状态，生成含 **4 个 Sheet** 的格式化 Excel 汇总报告（询价汇总/询价统计/日期查询/数据看板）。支持仅统计模式（`--stats-only`）跳过浏览器操作直接重算统计。使用 Playwright 自动化浏览器操作，支持多 Tab 并行提取和会话持久化。

> **日期口径：** 周报的日期范围以 **「区域技术」审批节点的审批时间** 为参考标准，而非提交时间。完整模式先按宽范围拉取流程（列表接口按提交时间筛选），提取详情后在本地按区域技术审批时间过滤；仅统计模式同样按区域技术审批时间列筛选。
>
> **输出列：** Excel「询价汇总」Sheet 包含区域技术的审批人、审批状态、审批时间三列（位于项目管理部核价审批时间之后），HTML 报表详情亦同步展示。

> **仅统计模式输入规则：** 默认在 `--output-dir` 目录中自动查找 `询价汇总_{时间戳}.xlsx`、`询价汇总.xlsx` 或 `询价汇总_v2.xlsx`（按优先级）。可通过 `--input-xlsx FILE` 显式指定输入文件。未找到则终止执行，提示先运行完整模式。

## When to Use

用户说以下内容时直接触发：

| 场景 | 用户可能说 |
|------|--------|
| **定期周报** | "帮我做周报" / "这周询价汇总一下" / "做本周询价周报" |
| **临时查询 / 批量获取** | "查一下上周的询价" / "看看这个月的流程" / "把最近两周的都提取出来" |
| **导出汇总** | "导出询价明细到Excel" / "把已办询价整理成表格" / "出个报表" |
| **有效性检查** | "检查哪些询价有效" / "哪些询价通过了核价审批" |

## When NOT to Use

- ❌ **审批/驳回流程** — 本 skill 只读，不执行任何写入操作
- ❌ **创建新的询价流程** — 需要手动在 DMS 中填写
- ❌ **修改已有数据** — 不在本 skill 范围内
- ❌ **非 DMS 系统的数据提取** — 本 skill 仅针对 DMS 流程中心

## 使用流程（步骤 0 → 步骤 3）

> **路径说明：** 以下命令中的 `$SKILL_DIR` 指向本 skill 的安装目录。Agent 执行前自动检测路径

> **快速路径：** 如果环境已通过检查（上次运行成功过）且用户说"本周"/"本周周报"等标准关键词，可跳过步骤 0-1，直接执行步骤 2 快速路径命令（详见下方「快速路径」）。

### 步骤 0：检查运行环境

> **Fail-fast 原则：** 环境检查放在最开始，避免执行中途因环境问题失败。
> **已安装跳过：** 如果 `python "$SKILL_DIR/scripts/check_environment.py" --quick` 返回 exit(0)，说明环境已就绪，可直接跳过本步骤进入步骤 1。

**检查流程（仅首次或检查时执行）：**

**0.1 检测 Python：**

```bash
python --version 2>/dev/null || python3 --version 2>/dev/null || py --version 2>/dev/null
```

- **命令不存在** → 向用户说明情况，根据检测到的操作系统给出**一键安装命令**（自动同意协议），用户复制粘贴执行后重新检测。详见 `references/installation.md`。
- **Python 可用** → 进入 0.2。

**0.2 安装前置依赖（首次使用前）：**

```bash
pip install playwright openpyxl -i https://mirrors.aliyun.com/pypi/simple/ && playwright install chromium
```

> ⚠️ **国内网络提示：** 详见 `references/installation.md` 镜像源说明。

**0.3 统一环境检查：**

```bash
python "$SKILL_DIR/scripts/check_environment.py"
```

- ✅ 全部通过 → 进入**步骤 1**
- ❌ **任一失败** → Agent 根据每项失败的 `fix_hint` **自动执行修复命令**，修复后重新运行检查，直至全部通过

**0.4 检查登录凭据：**

```bash
python "$SKILL_DIR/scripts/check_environment.py" --quick
```

- ✅ 凭据就绪 + 浏览器正常 → 进入**步骤 1**
- ❌ 凭据缺失 → 提示用户配置，详见 `references/login_config.md`，用户回复"已配置"后重新检测确认

### 步骤 1：解析日期范围（仅非标表述时执行）

**标准关键词无需预解析：** `run_weekly_report.py` 已内置 `--date-label` 参数，会自动调用 `resolve_date_range.py` 解析。标准关键词（本周/上周/本月/上月/本季度/上季度/今年/去年）以及"最近N天/周"（如"最近20天""近两周"）直接在步骤 2 中使用 `--date-label` 即可。

**仅当用户说了脚本无法解析的非标表述时执行本步骤**，手动确认后传入日期：

```bash
python "$SKILL_DIR/scripts/resolve_date_range.py" "上个月12号到现在" --json
```

> 输出示例：`{"start": "2026-05-12", "end": "2026-06-12", "range_str": "2026-05-12 ~ 2026-06-12"}`

**支持的标签类型（如参数不确定可运行 `--help` 查阅）：**

| 类型 | 示例 |
|------|------|
| 标准关键词 | 本周、上周、本月、上月、本季度、上季度、今年、去年 |
| 相对天数 | 最近20天、近3天、过去七天、最近三十日（支持中文数字和"两"） |
| 相对周数 | 最近2周、近两周、过去三周 |
| 相对月+日 | 上个月12号到现在、本月10号、上月至今 |
| 中文日期范围 | 6月1号到6月7号、六月一号到六月七号 |
| 标准日期 | 2026-06-01 ~ 2026-06-07 |

### 步骤 2：运行脚本

**（如参数不确定可运行 `--help` 查阅：`python "$SKILL_DIR/scripts/run_weekly_report.py" --help`）**

根据步骤 1 的日期，直接用日期字符串传参（不依赖 Shell 变量）：

```bash
SCRIPT="$SKILL_DIR/scripts/run_weekly_report.py"

# 标准关键词直接用 --date-label（推荐）
python "$SCRIPT" --output-dir "$PWD" --date-label "本周" --headless

# 非标表述用步骤 1 解析出的日期值
python "$SCRIPT" --output-dir "$PWD" --start-date "2026-05-12" --end-date "2026-06-12" --headless
```

**常用模式速查：**

| 场景 | 命令 |
|------|------|
| 本周数据 | `python "$SCRIPT" --output-dir "$PWD" --date-label "本周" --headless` |
| 上周数据 | `python "$SCRIPT" --output-dir "$PWD" --weeks 1` |
| 本月数据 | `python "$SCRIPT" --output-dir "$PWD" --date-label "本月" --headless` |
| 上月数据 | `python "$SCRIPT" --output-dir "$PWD" --date-label "上月" --headless` |
| 本季度数据 | `python "$SCRIPT" --output-dir "$PWD" --date-label "本季度" --headless` |
| 今年数据 | `python "$SCRIPT" --output-dir "$PWD" --date-label "今年" --headless` |
| 自定义日期 | `python "$SCRIPT" --output-dir "$PWD" --start-date "2026-05-12" --end-date "2026-06-12" --headless` |
| 最近N天 | `python "$SCRIPT" --output-dir "$PWD" --date-label "最近20天" --headless` |
| 最近N周 | `python "$SCRIPT" --output-dir "$PWD" --date-label "最近两周" --headless` |
| 仅统计（跳过浏览器） | `python "$SCRIPT" --output-dir "$PWD" --stats-only --date-label "本月"` |

---

#### 快速路径（满足以下条件时跳过步骤 0-1）

如果同时满足：
- 环境已通过检查（上次运行成功过，或 `check_environment.py --quick` 返回 exit(0)）
- 用户说"本周"/"本周周报"等标准关键词（无需解析确认）

则直接执行：
```bash
python "$SKILL_DIR/scripts/run_weekly_report.py" --output-dir "$PWD" --date-label "本周" --headless
```

> **提示：** `--output-dir` 建议用当前工作目录。bash/zsh 用 `"$PWD"`，PowerShell 用 `"$(Get-Location)"`，或直接省略（默认当前目录）。

### 步骤 3：呈现结果

脚本执行后会在终端打印摘要并生成 Excel，直接向用户报告。

**标准呈现格式（推荐）：**

```
✅ 周报生成完成！

📊 查询范围：{start_date} ~ {end_date}
📁 输出文件：询价汇总_{时间戳}.xlsx

| 指标 | 数值 |
|------|------|
| 有效询价 | {有效数} 条 🟢 |
| 无效询价 | {无效数} 条 🔴 |
| 有效率 | {有效率}% |

📎 Excel：{output_dir}/询价汇总_{时间戳}.xlsx
📎 HTML：{output_dir}/询价周报报表_{时间戳}.html
```

> **说明：** 有效率 = 有效询价数 / 总询价数。有效询价指项目管理部核价审批节点审核通过的流程。若数据为 0 或明显偏少，主动提示用户确认日期范围是否合理。

### 步骤 3 附：错误恢复决策树

脚本失败时，Agent 按以下决策表操作：

| 错误类型 | Agent 操作 |
|---------|---------|
| 登录失败（账号密码错误）| 提示用户检查凭据，引导到 `references/login_config.md` |
| 登录失败（验证码）| 去掉 `--headless`，提示手动完成验证码 |
| API 筛选返回空 | 自动切换到 HTML 解析模式（脚本已内置回退） |
| 0 条记录 | 确认日期范围是否正确，建议扩大范围重试 |
| 页面超时 | 加 `--verbose` 重新运行，检查网络 |
| Excel 保存失败 | 提示关闭占用的程序，或自动使用备用文件名 |
| 浏览器启动失败 | 运行 `playwright install chromium` 修复 |

### 日志记录

周报生成完成后，Agent **自动记录执行日志**，仅在遇到明显异常时才与用户交互。

**自动记录内容：**
- 执行时间、日期范围、提取记录数
- 遇到的问题（脚本报错、数据异常、登录失败等）
- 数据完整性检查结果

**异常处理：** 遇到以下情况时，主动告知用户并给出建议：
- 提取记录数为 0 或明显偏少
- 登录失败或页面选择器失效
- 脚本报错无法完成

> **原则：** 正常执行时静默记录，仅在异常或用户主动询问时才输出详细信息。

## Quick Reference

### 参数速查

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--output-dir DIR` | 输出目录 | 当前工作目录 |
| `--headless` | 无头模式（不显示浏览器） | 显示浏览器 |
| `--weeks N` | 最近 N 周（0=本周, 1=上周） | 0 |
| `--start-date YYYY-MM-DD` | 自定义开始日期 | 本周一 |
| `--end-date YYYY-MM-DD` | 自定义结束日期 | 今天 |
| `--wide-days N` | 宽范围拉取跨度（天）。完整模式列表接口按提交时间筛选，需扩大范围后按区域技术审批时间本地二次过滤 | 180（约半年） |
| `--date-label LABEL` | 中文日期标签（自动解析，如"本月"/"上个月到现在"） | 无 |
| `--workers N` | 并行并发数（1-8） | 6 |
| `--verbose` | 详细日志输出 | 仅 info |
| `--stats-only` | 仅统计模式：从已有 Excel 读取数据，按日期范围重新统计，跳过浏览器操作 | — |
| `--input-xlsx FILE` | 仅统计模式下显式指定输入的询价汇总 Excel 文件路径 | 自动查找 |
| `--this-month` | 快捷统计本月（配合 `--stats-only` 使用） | 无 |
| `--dry-run` | 预演模式：打印完整执行计划但不启动浏览器 | — |
| `--include-invalid` | 显式包含作废流程（默认行为，通常无需指定） | 无 |
| `--exclude-invalid` | 排除作废流程 | — |

### 输出文件

> ⚠️ 每次运行自动生成带时间戳文件（`YYYYMMDD_HHMMSS`），避免覆盖历史数据。

- `{output_dir}/询价汇总_{时间戳}.xlsx`
- 
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

列定义详见脚本 `column_definitions.py` 源码。

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

## 登录配置

DMS 登录凭据通过环境变量读取，**不硬编码密码**。详见 `references/login_config.md`。

