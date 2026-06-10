---
name: dms-inquiry-bom
version: 1.4.1
description: >
  Use when the user mentions DMS pending tasks, workflow approval, BOM generation,
  non-standard inquiry, or asks about "待办流程", "询价需求", "做BOM", "BOM清单",
  "查库存", "选逆变器", "导入BOM", "上传物料", "非标询价", "看下待办", "有什么需求",
  "全款自投", "原装三件套", "配置逆变器", "已有设备".
  Not for approving/rejecting DMS workflows, modifying existing data, or order placement.
metadata:
  author: Meiux
  updated: 2026-06-08

---

# DMS 非标询价 — 交互式工作流

## 概述

自动提取 DMS 待办流程 → 逐步骤用户确认 → 库存匹配 → 生成 BOM → 填写产品信息。
**流程灵活性：** 若用户主动提供详细需求（组件规格、已有设备等），可直接跳过步骤 1（提取待办）从步骤 2 开始。

## 何时使用

| 使用场景 | 不使用场景 |
|---------|-----------|
| 提取 DMS 待办流程 | 审批通过/驳回流程 |
| 查询库存匹配物料方案 | 修改或删除 DMS 数据 |
| 生成非标询价 BOM | 创建采购订单 |
| 填写产品信息到 DMS | 执行下单操作 |
| 配置逆变器/并网柜方案 | 修改用户密码或配置 |

## 核心规则

**每步必须使用 `AskUserQuestion` 确认后方可继续。** 展示结果 → 等用户明确回复 → 确认后才进入下一步。不得仅打印到终端。

> ⚠️ `AskUserQuestion` options 上限 4 个，≥5 个方案时先分组展示大类再细选。

**临时文件规则：** JSON 中间缓存用 `$TMP_DIR/`，BOM 交付物存当前工作目录。流程结束前清理 `$TMP_DIR/*.json`。

### 三步确认法

```
[提取待办] → AskUserQuestion 确认需求
  → [调用 dms-inventory Skill] → AskUserQuestion 确认方案
  → [生成BOM] → AskUserQuestion 确认BOM
  → [填写产品信息] → [回顾反馈]
```

**跳步变体（用户主动提供需求时）：**
```
用户带需求 → [跳过待办提取] → [调用 dms-inventory Skill] → AskUserQuestion 确认方案 → ...
```

## 步骤概览

| 步骤 | 脚本 | 确认点 | 预估耗时 |
|------|------|--------|---------|
| 0. 检查环境 | `scripts/dms_credentials.py --check-browser` | — | ~5 秒 |
| 1. 提取待办 | `scripts/run_inquiry_extract.py` | 展示待办列表 | ~30-60 秒 |
| 2. 库存匹配 | `Skill` 调用 `dms-inventory` | 确认匹配方案 | ~20-40 秒 |
| 3. 生成 BOM | `scripts/generate_bom.py` | 确认 BOM 文件 | ~5 秒 |
| 4. 填写产品信息 | `scripts/fill_product_info.py` | 保持浏览器打开 | ~30-60 秒 |
| 5. 回顾反馈 | `AskUserQuestion` | 提出优化建议 | ~2 分钟 |

## Quick Reference

| 操作 | 命令 |
|------|------|
| 检查环境 | `python $SKILL_DIR/scripts/dms_credentials.py --check-browser` |
| 提取待办 | `python $SKILL_DIR/scripts/run_inquiry_extract.py --output-file "$TMP_DIR/inquiry_data.json"` |
| 库存匹配 | 调用 `Skill` 工具执行 `dms-inventory` |
| 生成 BOM | `python $SKILL_DIR/scripts/generate_bom.py --name "张三" --components 800 --items '6B001492:800,AB001347:8' --project "项目名" --output-dir "."` |
| 填写产品信息 | `python $SKILL_DIR/scripts/fill_product_info.py --flow-id <ID> --component-power 730 --component-count 800` |

## 执行步骤

### 步骤 0：检查环境

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inquiry-bom"
python "$SKILL_DIR/scripts/dms_credentials.py" --check-browser
```

| 结果 | 处理 |
|------|------|
| Chromium ❌ | `AskUserQuestion` 询问是否运行 `playwright install chromium` |
| `NOT_FOUND` | 向用户展示凭据配置步骤（见 `references/credentials-setup.md`） |

**JSON 编码 & 路径规则：**

| 规则 | 说明 |
|:----|:------|
| 输出方式 | `--output-file` 替代管道传 JSON（避免中文乱码） |
| 临时目录 | `$TMP_DIR` = `python -c "import tempfile; print(tempfile.gettempdir())"` |
| 最终交付物 | BOM Excel 存当前工作目录（**禁止用 `$PWD`**，含中文时路径被破坏） |
| Windows bash | 复杂 Python 写成独立 `.py` 文件执行，避免 `python -c` 内联反斜杠转义问题 |
| 清理 | 流程结束前清理 `$TMP_DIR/*.json` 和 Playwright 用户数据目录（`browser-data-*`），保留 BOM |

### 步骤 1：提取待办流程

```bash
python "$SKILL_DIR/scripts/run_inquiry_extract.py" --output-file "$TMP_DIR/inquiry_data.json"
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--headless` | 无头模式（不显示浏览器窗口） | 显示浏览器 |
| `--workers N` | 并行并发数 | 3 |
| `--output-file PATH` | 输出 JSON 路径 | stdout |

读取 `$TMP_DIR/inquiry_data.json`，**用 `AskUserQuestion` 展示待办摘要**：

```
待办流程 1: {flow_id}
  项目名称: {project_name}
  代理商: {agent_code} {agent_name}
  省公司: {province}
  业务员: {salesperson}
  备注: {remark}
  BOM清单:
    {code} {name} x {qty} (已指定)
    [待选] {name} x {qty} (未指定物料编号)
  审批意见:
    {node}: "{opinion}"
```

> ⚠️ BOM 清单中 `code` 为空的项标记为 `[待选]`（未指定物料编号），反之为 `(已指定)`。`bom_items` 可能为空数组。`remark` 包含关键需求信息。审批意见提取所有历史节点及批复内容。

**确认要点：** 信息是否准确 → 多流程时选优先处理哪个 → 哪些物料需查库存 → 有无特殊要求。

### 步骤 2：库存匹配

> 使用 `Skill` 工具调用 `dms-inventory` 技能完成库存查询与匹配

```bash
# 调用 dms-inventory Skill（在对话中执行）
Skill: dms-inventory
```

`dms-inventory` 技能会处理：
- 解析需求 → 构建参数 → 查询库存 → 匹配方案 → 返回结果

调用后读取其结果存入 `$TMP_DIR/inventory_result.json`，然后继续后续步骤。

**关键确认点：** 用 `AskUserQuestion` 展示匹配方案给用户确认后，写入 `$TMP_DIR/inventory_result.json`。

### 步骤 3：生成 BOM

```bash
python "$SKILL_DIR/scripts/generate_bom.py" \
  --name "张三" --components 800 \
  --items '6B001492:800,AB001347:8,AA001653:8' \
  --project "项目名" --output-dir "."
```

`--items` 格式：`<编码>:<数量>,<编码>:<数量>,...`（也支持 `[["6B001492",800],["AB001347",8]]` JSON 数组格式）

**批量模式：** 将 `--name`/`--components`/`--items` 替换为 `--bom-list` 传入 JSON 数组，一次生成多个 BOM：
```bash
python "$SKILL_DIR/scripts/generate_bom.py" \
  --bom-list '[
    {"name": "张三", "components": 800, "items": [["6B001492",800],["AB001347",8]]},
    {"name": "李四", "components": 300, "items": [["6B001492",300],["AA001653",2]]}
  ]' --output-dir "."
```

生成的 BOM Excel 文件结构（`张三800块组件{项目名}20260608.xlsx`）：

| 列 | 内容 | 示例 |
|:---|:-----|:-----|
| A1 | 物料编号 | 6B001492 |
| B1 | 数量 | 800 |

**用 `AskUserQuestion` 展示生成的 BOM 文件给用户确认。**

### 步骤 4：填写产品信息（BOM 确认后）

```bash
python "$SKILL_DIR/scripts/fill_product_info.py" \
  --flow-id <流程ID> \
  --component-power 730 --component-count 800
```

| 参数 | 说明 |
|------|------|
| `--flow-id` | 流程 ID（必需）|
| `--component-power` | 组件功率(W)（必需）|
| `--component-count` | 组件片数（必需） |
| `--headless` | 无头模式，不显示浏览器窗口（默认：显示浏览器） |

> ⚠️ 必须 BOM 确认后执行。填写后浏览器保持打开，供用户手动检查审批。**不会自动审批/关闭浏览器。**

### 步骤 5：回顾与反馈（流程完成后）

**反思清单：**
1. 本次遇到哪些问题（脚本报错、数据异常、流程卡住）？
2. SKILL.md 能否覆盖这些场景？脚本是否有 bug？
3. 哪些交互点可以优化？

**流程结束前清理临时文件：** `rm -f "$TMP_DIR"/*.json`（保留 BOM `.xlsx`）。

**将反思提炼为具体建议，用 `AskUserQuestion` 向用户提出**，确认后更新 SKILL.md。

## 多流程处理策略

1. 一次性展示全部流程摘要
2. 让用户选优先处理哪个（`AskUserQuestion` 提供选项）
3. 当前流程完成后询问是否继续处理下一个
4. 已处理的流程标记状态避免重复

## 异常处理

| 场景 | 处理方式 |
|------|---------|
| Chromium 未安装 | `AskUserQuestion` 询问是否运行 `playwright install chromium` |
| 凭据 `NOT_FOUND` | 展示配置步骤（见 `references/credentials-setup.md`） |
| 提取/库存/BOM 脚本报错 | 重试 1 次，再次失败则 `AskUserQuestion` 是否跳过 |
| 填写产品信息报错 | **不重试**，告知用户手动操作 |
| 待办提取数为 0 | 正常展示结果，执行回顾环节 |
| 页面加载超时 | 重试 1 次，再次失败则 `AskUserQuestion` 是否继续 |
| `inquiry_data.json` 字段缺失或格式异常 | `AskUserQuestion` 展示原始 JSON 让用户判断，不直接丢弃 |
| 用户要求中断/跳步 | 停止当前步骤，从指定点继续或执行回顾 |
| `AskUserQuestion` 方案数 > 4 | 先分大类展示，选类后再展示子方案 |
| 组件无库存 | 查看 `alternatives` 推荐相近功率，`AskUserQuestion` 确认 |
| 混品牌方案未提示用户 | 同品牌不满足时列出混合方案供选择 |

> **原则：** 脚本报错时优先展示原始错误信息，不自行修改用户配置或凭据。

## 安全约束

| 允许 | 禁止 |
|------|------|
| 登录、导航页面、筛选查询、读取内容 | 审批通过/驳回、提交表单、删除记录 |
| 填写产品信息（仅填写字段） | 点击审批/提交/下单按钮 |
| 保持浏览器打开供用户检查 | 自动关闭浏览器或执行审批 |

如意外跳转到审批/修改页面，立即返回并在终端提示用户。

> ⚠️ **凭据安全：** 请勿在 `~/.bashrc` 或配置文件中明文存储密码。DMS 凭据应使用环境变量或密钥管理器注入。

## 常见错误

| 错误 | 正确做法 |
|------|---------|
| BOM 确认前填写产品信息 | 严格按顺序执行 |
| 跳过用户确认直接下一步 | 每步必须 `AskUserQuestion` |
| 仅打印到终端 | 所有确认点用 `AskUserQuestion` 工具 |
| 自动关闭浏览器 | 填写后保持打开 |
| 忽略库存预警/停产标记 | 必须展示给用户决定 |

## 参考文档

| 文档 | 位置 |
|:----|:-----|
| 凭据配置 | `references/credentials-setup.md` |
| 浏览器管理 | `references/browser-manager.md` |
| 库存查询 | `dms-inventory` Skill（含编排器与快捷查询） |
| 脚本 --help | 各脚本的 docstring 和 `--help` 参数 |
