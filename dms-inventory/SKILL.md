---
name: dms-inventory
description: >
  Use when the user asks about checking inventory, matching components/inverters/boxes,
  querying stock quantities, or mentions "查库存", "库存匹配", "库存查询", "物料数量",
  "库存不足", "库存可用", "库存情况", "够不够用". Also applies when configuring inverter
  ratios or checking warehouse stock distribution.
  Not for modifying inventory data, creating purchase orders, or managing warehouse entries.
metadata:
  author: Meiux
  version: 2.5.0
  updated: 2026-06-10
---

# DMS 库存查询 & 匹配

## 概述

从 DMS 库存 Excel 中查询组件/逆变器/并网箱的可用库存，按规则匹配并展示给用户确认。

采用 **LLM + 编排器** 双层架构：
- **`inventory_orchestrator.py`（编排器）** — 确定性操作：查询、聚合、备注过滤、组合计算
- **LLM** — 不确定性操作：解析自然语言、推理决策、用户交互

> 架构说明、JSON 格式、完整输出字段见 `references/inventory-flow.md`

## 快速参考

| 项目 | 说明 |
|:-----|:------|
| 核心脚本 | `scripts/inventory_orchestrator.py` — 编排器 |
| 快捷查询 | `scripts/lookup_by_code.py` — 按物料编码/名称查询 |
| 架构文档 | `references/inventory-flow.md` |
| 异常处理 | `references/error-handling.md` |
| 临时目录 | `/tmp/dms_inventory/`（固定路径） |
| 库存文件 | `assets/` 目录下的 Excel 文件 |

> **⚠️ 强制性规范：禁止在 `python -c` 内使用 `/tmp/` 路径**
>
> **原理：** 在 Git Bash (MSYS2) 环境下，`/tmp/` 只在**命令行参数**中被自动翻译为 Windows 临时目录；
> `python -c "..."` 代码字符串**内部**的 `/tmp/` **不会被翻译**，Python 会解析为 `C:\tmp\...`。
>
> **安全用法（MSYS2 会翻译命令行参数，放心使用）：**
> ```bash
> --output-file "$TMP_DIR/analysis.json"    # ✅ 命令行参数，MSYS2 自动翻译
> --params "$(cat "$TMP_DIR/input.json")"   # ✅ 同上
> ```
>
> **不安全用法（MSYS2 不翻译 `-c` 内的字符串）：**
> ```bash
> python -c "open('/tmp/dms_inventory/analysis.json')"   # ❌ 不会被翻译
> ```
>
> **两种正确做法（二选一）：**
> 1. **`cat | python`（推荐）** — 通过 stdin 传递文件内容，避开文件路径：
>    ```bash
>    cat /tmp/dms_inventory/analysis.json | PYTHONIOENCODING=utf-8 python -c "
>    import json, sys
>    d = json.load(sys.stdin)
>    "
>    ```
> 2. **`python -c` 内用 `os.environ['TMP']`** — 动态获取 Windows 临时目录：
>    ```python
>    import os, json
>    TMP = os.environ.get('TMP', '/tmp')
>    d = json.load(open(os.path.join(TMP, 'dms_inventory', 'analysis.json')))
>    ```
>
> 以下所有代码块已按此规范编写，**LLM 自行编写 `python -c` 命令时必须遵守此规则**。

## 何时使用 / 何时不使用

| 使用场景 | 不使用场景 |
|---------|-----------|
| 查询组件/逆变器/并网箱库存 | 修改或导入库存数据 |
| 匹配物料方案给用户确认 | 创建采购订单 |
| 检查仓库库存分布和可用量 | 管理仓库入库出库操作 |
| 配置逆变器 DC/AC 比值 | 查看非 DMS 系统库存 |

## 核心原则

1. **物料编号是唯一标识** — 每次展示方案必须带物料编号
2. **备注决定可用性** — 项目专用/未上架直接排除，原厂机标记警告
3. **不可擅自替代** — 用户指定规格不足时由用户决定
4. **聚合仓库数量** — 编排器自动加总多仓库同一物料编码
5. **不阻塞流程** — 品类不在库存中告知用户，继续其他部分；若**所有品类均无可用库存**则终止流程
6. **"天合原装专用"在物料名称列** — 非 `厂家` 列；编排器 `prefer_brand: "天合"` 已适配

## 工作流

> **核心串行规则：必须先确认组件方案（DC 容量）才能跑编排器匹配逆变器/并网柜（DC/AC 比）。**
> 组件功率决定 DC 总容量 → DC 容量决定 DC/AC 比 → DC/AC 比决定编排器推荐的逆变器组合。
> **三步必须串行，禁止并行提问。**

### 阶段一：确认物料方案（组件 + 指定逆变器）

先确认组件方案（确定 DC 容量），再检查用户是否指定了逆变器，最后构造 `input.json`。

#### 子步骤 1：确认组件方案

用 `quick_query.py` 查询指定组件的库存：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inventory"

# 按功率关键词模糊查询组件库存（如 715W、550W）
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" \
  --power "${功率}W" --category 组件 --aggregate
```

根据查询结果分支：

| 结果 | 处理 |
|:----|:-----|
| **有库存且满足需求（`库存总量 >= qty`）** | → 保留原功率，进入**子步骤 2** |
| **无库存或不足（`库存总量 == 0` 或 `库存总量 < qty`）** | → 用 `AskUserQuestion` 确认应对策略（见下方表格） |

**⚠️ 此阶段只问物料策略，不问容配比/组合方案。DC 容量未确定前不能跑编排器。**

| 选项 | 说明 | 后续影响（DC 容量） |
|:----|:------|:-------------------|
| **接受替代功率** | 推荐库存最足的相近功率 | DC = 替代功率 × 数量，需重跑编排器 |
| **用户自筹** | 组件自行解决 | DC = 原需求功率 × 数量，**仍要跑编排器**匹配逆变器 |
| **仅精确匹配** | 指定功率无库存则终止 | 流程终止 |

> **⚠️ 禁止提前问用户容配比：** 组件确认后直接继续，容配比由编排器自动处理。编排器的 `preferences.dc_ac_ratio_range` 已预设合理范围（默认 `[1.0, 1.3]`），会自动计算最优组合。

#### 子步骤 2：检查指定逆变器库存（如用户已指定）

若用户在项目描述中已指定逆变器型号/功率/数量（如"2台110KW天合逆变器"），用 `quick_query.py` 查询库存：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inventory"

PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" \
  --power "${功率}KW" --category 逆变器 --aggregate
```

查询结果分支：

| 结果 | 处理 |
|:----|:-----|
| **有库存且满足需求（`库存总量 >= qty`）** | → 保留原指定规格，进入**子步骤 3** |
| **无库存或不足（`库存总量 == 0` 或 `库存总量 < qty`）** | → 用 `AskUserQuestion` 确认应对策略（见下方表格） |

| 选项 | 说明 | 后续操作 |
|:----|:------|:---------|
| **接受替代方案** | 编排器自动从库存中推荐其他品牌/型号的可用组合 | `input.json` 中**不设** `required_new`，让编排器自由推荐 |
| **用户自筹** | 逆变器用户自行解决，不通过 DMS 库存采购 | `input.json` 中**不设** `required_new`，仅保留 `existing` 信息（如有） |
| **仅精确匹配** | 指定型号无库存则终止流程 | 流程终止 |

> ⚠️ 子步骤 2 只问逆变器策略（接受替代/自筹/终止），不要在这里让用户选具体组合方案（那是阶段三的任务）。

若用户未指定逆变器型号/功率，则跳过此子步骤。

#### 子步骤 3：构造 input.json

组件和逆变器方案确认后，构造 `input.json` 传入编排器：

**参数说明：**

| 参数路径 | 说明 | 必填 |
|----------|------|:----:|
| `requirements.components.power` | 组件功率（W） | ✅ |
| `requirements.components.qty` | 组件需求数量 | ✅ |
| `requirements.components.source` | `dms_stock`（库存采购）或 `user_self`（用户自筹） | ✅ |
| `requirements.inverters.existing` | 已有逆变器 `[{model, power, qty}]` | ⭕ |
| `requirements.inverters.required_new` | 指定新增逆变器 `[{model, power, qty}]`，不指定则由编排器推荐 | ⭕ |
| `requirements.combiner_boxes.existing` | 已有并网柜 `[{power, qty}]` | ⭕ |
| `requirements.combiner_boxes.required_new` | 指定新增并网柜 `[{power, qty}]`，不指定则由编排器推荐 | ⭕ |
| `preferences.prefer_brand` | 优先品牌，匹配 `厂家` 列 | ⭕ |
| `preferences.exclude_project_specific` | 排除项目专用物料，默认 `true` | ⭕ |
| `preferences.exclude_unlisted` | 排除未上架物料，默认 `true` | ⭕ |
| `preferences.dc_ac_ratio_range` | DC/AC 比范围 `[min, max]`，默认 `[1.1, 1.2]` | ⭕ |

完整 JSON 格式和示例见 `references/inventory-flow.md`。阶段一完成后进入**阶段二**。

### 阶段二：运行编排器（匹配逆变器/并网柜）

**组件确认后、DC 容量确定后，才能运行编排器。**

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inventory"
TMP_DIR="/tmp/dms_inventory"
mkdir -p "$TMP_DIR"

# ⚠️ 使用 --params $(cat ...) 而非 --params-file
# 避免 Windows MSYS2 路径翻译不一致
PARAMS_JSON=$(cat "$TMP_DIR/input.json")

PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/inventory_orchestrator.py" \
  --params "$PARAMS_JSON" \
  --output-file "$TMP_DIR/analysis.json"
```

编排器自动完成：查询 → 聚合 → 备注过滤 → 组合计算 → 排序。

> ⚠️ **LLM 执行规范**
> - ❌ 不得用 `find /` `find .` 全盘搜索
> - ✅ 编排器打印 `[完成]` 后直接 `cat` 该路径
> - ✅ 需 Python 处理 JSON 时用 `cat | python` 或 `os.environ['TMP']`

### 阶段三：展示编排器结果并确认

**读取 analysis.json（二选一）：**
```bash
# 方式一（推荐）：cat 直接读取，LLM 阅读 JSON 文本
cat /tmp/dms_inventory/analysis.json

# 方式二（需 Python 处理时）：cat + stdin 传入
cat /tmp/dms_inventory/analysis.json | PYTHONIOENCODING=utf-8 python -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps(d, ensure_ascii=False, indent=2))
"
```

编排器输出含 `inverters.combinations`、`combiner_boxes.available`、`warnings`。

**根据 combinations 结果分支：**

| 条件 | 处理 |
|:----|:-----|
| **combinations 非空** | 取 2-3 方案，用 AskUserQuestion 让用户选（见下方模板） |
| **combinations 为空** | 提示用户调整 `dc_ac_ratio_range` 或品牌偏好后重跑编排器；或终止流程 |

**AskUserQuestion 模板（逆变器 + 并网柜合并提问）：**
```
推荐几个方案供您选择：
- 方案 A：50kW×N（DC/AC=X.XXX，库存充足）
- 方案 B：50kW×M + 40kW×K（DC/AC=X.XXX）
- 方案 C：...
并网柜方面，已有 X 台，是否需要新增？（库存充足）
```
> ⚠️ 可以和逆变器+并网柜合并问，**绝不可以和组件方案合并**（DC 容量未定则 DC/AC 比不准）。

**用户选完后反悔/想修改组件方案：**
> 如果用户在看到逆变器方案后想换组件功率 → 返回**阶段一**重新确认组件方案，更新 `input.json` 后重跑编排器。

**组件替代后重跑编排器：** 更新 `input.json` 中的 `components.power`，其余字段照抄上一轮，重新跑阶段二的命令即可（编排器执行 <1s）。

### 阶段四：用户确认 → 输出最终结果

```bash
TMP_DIR="/tmp/dms_inventory"
analysis=$(cat "$TMP_DIR/analysis.json")

cat "$TMP_DIR/analysis.json" | PYTHONIOENCODING=utf-8 python -c "
import json, sys, os
analysis = json.load(sys.stdin)
TMP_DIR = os.environ.get('TMP', '/tmp') + '/dms_inventory'
os.makedirs(TMP_DIR, exist_ok=True)

# 从 analysis 中提取摘要信息动态填充
summary = analysis.get('summary', {})
inverters = analysis.get('inverters', {})
combos = inverters.get('combinations', [])
boxes = analysis.get('combiner_boxes', {})

result = {
    'version': '1.0',
    'timestamp': None,
    'project_summary': {
        'dc_capacity_kw': summary.get('component_power_kw', 0),
        'existing_inverter_kw': summary.get('existing_inverter_kw', 0),
        'selected_combination': combos[0] if combos else None,
    },
    'decisions': [
        {'item': '组件', 'decision': f\"{analysis['components']['specified']['power']}W×{analysis['components']['specified']['qty']}张\"},
        {'item': '新增逆变器', 'decision': '用户已选方案，详见 analysis.json'},
        {'item': '并网柜', 'decision': '详见 analysis.json'},
    ],
    'inventory_result': TMP_DIR + '/analysis.json'
}
out = os.path.join(TMP_DIR, 'inventory_result.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('最终结果已写入:', out)
"
```

### 阶段五：回顾与反思

流程完成后主动复盘：
1. 本次执行遇到了哪些问题？
2. 数据是否完整合理？
3. 当前 SKILL.md 是否能覆盖所有场景？
4. 脚本是否有 bug 或功能缺失？

使用 `AskUserQuestion` 向用户提出优化建议，确认后更新 SKILL.md。

## 安全约束

| 类别 | 允许 | 禁止 |
|:----|:-----|:-----|
| 物料替代 | 用户确认后推荐替代方案 | ❌ 未经同意擅自换规格 |
| 备注处理 | 编排器自动过滤/标记警告 | ❌ 忽略备注直接推荐 |
| 流程控制 | 品类不在库存时继续其他部分 | ❌ 非标品类卡死流程 |

## 异常处理

| 常见场景 | 快速处理 | 详见 |
|:---------|:---------|:-----|
| 编排器报错 | 检查输出是否含 `Traceback`，确认 JSON 格式正确 | `references/error-handling.md` |
| Excel 缺失/损坏 | 确认 `assets/` 目录有 `.xlsx` 文件（异常时再检查，不要提前确认） | `references/error-handling.md` |
| `python -c` 读不到文件 | MSYS2 不翻译 `-c` 内 `/tmp/` → 改用 `cat \| python` 或 `os.environ['TMP']` | 本文件"强制性规范" |
| 逆变器组合为空 | 提示用户调整 `dc_ac_ratio_range` 或品牌偏好后重跑 | 阶段三 |
| 终端中文乱码 | 加 `PYTHONIOENCODING=utf-8` | `references/error-handling.md` |

## 快捷查询（按物料编号/名称/功率）

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inventory"
# 按物料编号查询
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --code 6B001492 --aggregate
# 按物料名称模糊查询（搜物料名称列）
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --name "天合原装" --category 逆变器 --aggregate
# 按功率列搜索（组件或逆变器功率）
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --power "730W" --category 组件 --aggregate
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --power "110KW" --category 逆变器 --aggregate
# 多条件交集：天合原装 且 功率110KW
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --name "天合原装" --power "110KW" --category 逆变器 --aggregate
# JSON 输出到文件
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/quick_query.py" --code AB001347 --aggregate --json --output-file /tmp/dms_inventory/lookup_result.json
```

> `--name` 搜物料名称列，`--power` 搜功率列，语义隔离。同时使用为 **AND（交集）**。完整参数说明见 `references/quick-query.md`

## 参考文档

| 文档 | 位置 |
|:----|:-----|
| 架构说明 & JSON 格式 | `references/inventory-flow.md` |
| 异常处理 | `references/error-handling.md` |
| 快捷查询详解 | `references/quick-query.md` |
