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

### 步骤 1：解析日期范围

直接根据用户话语中的时段词调用日期解析脚本：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
RANGE=$(python "$SKILL_DIR/scripts/resolve_date_range.py" "本周" --json)
START=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['start'])")
END=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['end'])")
RANGE_STR=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['range_str'])")
```

> 以上命令将日期范围信息存入 `$START`（开始日期）、`$END`（结束日期）和 `$RANGE_STR`（显示用范围文本）三个 Shell 变量，后续步骤直接使用。

**匹配规则（从用户话语中提取时段词）：**

| 用户说... | 传给脚本的标签 | 行为 |
|-----------|---------------|------|
| "帮我把本周的询价做一下周报" | `"本周"` | 本周一到今天 |
| "做上周的周报" / "做上一周的" | `"上周"` | 上周一到上周日 |
| "查一下这个月的情况" / "做本月统计" | `"本月"` | 本月一号到今天 |
| "上个月的询价汇总一下" | `"上月"` | 上个月整月 |
| "做本季度的报表" | `"本季度"` | 本季度第一天到今天 |
| "看看去年全年的数据" | `"去年"` | 去年1月1日到12月31日 |
| "查 6月1号到6月7号的数据" | `"6月1号到6月7号"` | 自动解析中文日期格式 |
| 用户没说任何时段（只说"做周报"） | `"本周"` | 默认本周 |

**提取方法：** 从用户话语中按优先级匹配关键词
1. 先检查 "去年"/"上季度"/"本季度"/"上月"/"本月"/"上周"/"本周"
2. 再检查中文日期范围 `\d{1,2}月\d{1,2}号?\s*(到|~)\s*...`
3. 最后检查 `YYYY-MM-DD ~ YYYY-MM-DD`
4. 都无匹配 → 默认 `"本周"`，**然后向用户说一句**：
   > "没检测到时段时间，默认按本周（本周一~今天）统计。如果需要其他时段请告诉我。"

> 不再使用 `AskUserQuestion` 方式让用户三选一确认，直接用脚本解析。只有在解析失败时（`resolve_date_range.py` 退出码非 0）才回退询问用户。

### 步骤 2：检查运行环境

确认日期范围后，先检查 DMS 登录凭据和浏览器环境：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
python "$SKILL_DIR/scripts/dms_credentials.py" --check-browser
```

- 检测来源：当前环境变量、bash 系（.bashrc/.bash_profile/.profile）、zsh 系（.zshenv/.zprofile/.zshrc）、Windows 注册表/PowerShell
- 同时验证 Playwright Chromium 是否已安装

**检查结果分支：**
- ✅ 凭据就绪 + 浏览器正常 → 直接进入**步骤 3**
- ❌ 凭据缺失 → 提示用户配置环境变量 `DMS_USER` / `DMS_PASSWORD`，用户回复“已配置”后重新执行 `dms_credentials.py` 确认，再进入**步骤 3**

### 步骤 3：运行脚本

本 skill 目录下的 `scripts/run_weekly_report.py` 执行实际工作。使用**步骤 1** 解析出的日期变量：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
SCRIPT="$SKILL_DIR/scripts/run_weekly_report.py"

# 使用步骤 1 解析的日期范围
python "$SCRIPT" --output-dir "$PWD" --start-date "$START" --end-date "$END"

# 无头模式（不显示浏览器）
python "$SCRIPT" --output-dir "$PWD" --start-date "$START" --end-date "$END" --headless

# 仅统计模式（跳过浏览器，从已有 Excel 重算统计）
python "$SCRIPT" --output-dir "$PWD" --stats-only --start-date "$START" --end-date "$END"

# 查上周（快捷方式，无需步骤 1）
python "$SCRIPT" --output-dir "$PWD" --weeks 1
```

> **提示：** `--output-dir` 建议用 `"$PWD"` 输出到用户当前目录，方便查找。
>
> **注意：** 如果生成的报表中流程编号最后几位不正确，说明 Excel 中该列以数字格式存储而非文本。详见 FAQ「流程编号显示为不正确的数字」。

### 步骤 4：呈现结果

脚本执行后会在终端打印摘要并生成 Excel，直接向用户报告：

```
✅ 周报生成完成！
📊 查询范围：2026-06-01 ~ 2026-06-06
📝 共 12 条询价记录
🟢 已下单 5 条 | 🔴 未下单 7 条
📎 Excel文件已保存到：{output_dir}/询价汇总_{时间戳}.xlsx
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
- ✅ 修改脚本或参考文件后，按 CLAUDE.md 同步规则复制到 `~/.claude/skills/`

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
| `--workers N` | 并行并发数 | 4 |
| `--verbose` | 详细日志输出 | 仅 info |
| `--stats-only` | 仅统计模式：从已有Excel读取数据，按日期范围重新统计，跳过浏览器操作 | 无 |
| `--this-month` | 快捷统计本月（配合`--stats-only`使用） | 无 |

### 输出文件

> ⚠️ 每次运行自动生成带时间戳文件（`YYYYMMDD_HHMMSS`），避免覆盖历史数据。
> 详见 `references/output_format.md`。

- `{output_dir}/询价汇总_{时间戳}.xlsx`
- `{output_dir}/询价汇总_{时间戳}_v2.xlsx`（文件被占用时的备用）
- `{output_dir}/询价周报报表_{时间戳}.html`

### HTML 独立生成（无需浏览器）

从已有 xlsx 单独生成 HTML 报表（不经过 DMS 登录流程）：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
python "$SKILL_DIR/scripts/generate_html_report.py" \
  --xlsx "询价汇总.xlsx" \
  --range "2026-06-01 ~ 2026-06-07"
```

详见 `scripts/generate_html_report.py` 模块文档和 `references/report_template.html`。

### Excel 列定义

详见 `references/excel_columns.md`。

## 前置依赖

首次使用安装一次，之后无需重复：
```bash
pip install playwright openpyxl && playwright install chromium
```

## 登录配置

DMS 登录凭据通过环境变量读取，**不硬编码密码**。使用 `dms_credentials.py` 检测：

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

检测顺序（实现见 `scripts/dms_credentials.py`）：进程环境变量 → `~/.bashrc`/`~/.bash_profile`/`~/.profile` → PowerShell 用户变量。全部未找到时暂停，提示用户配置，回复"已配置"后继续。

**登录持久化：** 使用 `launch_persistent_context` 保存登录状态到 `~/.dms_browser_data/`，首次登录后后续运行自动复用会话，无需重复登录。会话过期时自动重新登录。

## 安全约束

**本 skill 仅执行查询和数据提取操作，严格遵守以下规则：**

- **禁止：** 审批通过/驳回、提交表单、删除记录、修改数据、执行下单、发送邮件等任何写入/修改类操作
- **允许：** 登录、导航页面、筛选查询、读取页面内容
- 页面出现审批、提交、删除等按钮 → **一律忽略不点击**
- 意外跳转到审批/修改页面 → 立即返回，终端提示用户
- 所有浏览器操作仅限于读取页面内容，不做任何数据变更
- 使用 `ignore_https_errors=True` 仅用于内部 DMS 系统，不适用于生产环境

## 常见问题

### Q: 脚本报"未配置环境变量"但实际已配置

```
原因：当前 shell 未加载 profile 文件
解决：
  source ~/.bashrc    # Bash
  或重启终端后重试
  或用完整命令：bash -c 'source ~/.bashrc && python ...'
```

### Q: 提取到 0 条记录

```
可能原因：
  - 本周确实没有已办结的询价
  - 日期范围不对（用 --start-date 放大范围排查）
  - DMS 页面"已办流程"菜单选择器失效
```

### Q: DMS 页面结构变化导致选择器失效

```
现象：脚本能登录但提取不到数据
解决：需要更新 run_weekly_report.py 中的选择器常量
      主要关注：表格行选择器、表单字段选择器
      开启 --verbose 查看详细调试输出
```

### Q: Excel 文件保存失败

```
原因：目标文件被 Excel 或其他程序占用
解决：脚本自动使用 "{文件名}_v2.xlsx" 作为备用文件名
      关闭原文件后删除旧文件再运行
```

### Q: 登录提示验证码

```
DMS 偶尔触发验证码验证，此时需要手动操作：
  1. 去掉 --headless 参数（显示浏览器）
  2. 在浏览器窗口中手动完成验证码
  3. 脚本会自动继续
```

### Q: 流程编号显示为不正确的数字

```
现象：报表中的流程编号最后几位与 DMS 系统中不一致。
原因：Excel 中该列以数字格式存储，而非文本。Excel 的 IEEE 754 双精度
     浮点数约 15-16 位有效数字，超过此范围的长编号精度丢失。
解决：在 Excel 中将该列格式设为「文本」后重新导出 xlsx。
     本 skill 运行时会检测此情况并输出 stderr 提醒。
```
## 脚本架构

核心模块：
- **完整模式：** 配置 → 登录 → 筛选 → 提取 → 下单检查 → Excel（4 Sheet） → 终端摘要
- **仅统计模式：** 配置 → 读取已有 Excel → 按日期筛选 → 更新统计 Sheet → 终端输出

详细实现见 `scripts/run_weekly_report.py`。
