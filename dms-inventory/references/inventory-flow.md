# inventory_orchestrator.py — 接口文档

## 接口概述

统一库存查询编排接口。LLM 传入结构化 JSON 参数，脚本执行所有确定性查询/过滤/计算，返回结构化 JSON 分析结果供 LLM 决策。

## 调用方式

```bash
python scripts/inventory_orchestrator.py \
  --params '<JSON>' \               # 参数直接传入
  --params-file ./input.json \       # 或从文件读取
  --file /path/to/stock.xlsx \       # 库存文件（可选，不传则自动查找）
  --output-file ./result.json        # 输出到文件（可选，默认 stdout）
```

## 输入参数

### requirements（需求参数）

| 字段 | 类型 | 必填 | 说明 |
|:----|:----|:----:|:------|
| `requirements.components.power` | int | ✅ | 组件功率（W），如 715 |
| `requirements.components.qty` | int | ✅ | 组件数量，如 800 |
| `requirements.inverters.existing` | array | | 已有逆变器清单 |
| `requirements.inverters.existing[].model` | str | | 型号名称（参考用） |
| `requirements.inverters.existing[].power_kw` | float | ✅ | 单台功率（kW） |
| `requirements.inverters.existing[].qty` | int | ✅ | 数量 |
| `requirements.inverters.existing[].brand` | str | | 品牌（厂家名），用于同品牌匹配 |
| `requirements.combiner_boxes.existing` | array | | 已有并网柜清单 |
| `requirements.combiner_boxes.existing[].power_kw` | float | ✅ | 单台功率（kW） |
| `requirements.combiner_boxes.existing[].qty` | int | ✅ | 数量 |

### preferences（偏好参数）

| 字段 | 类型 | 默认值 | 说明 |
|:----|:----|:------:|:------|
| `preferences.prefer_brand` | str | `null` | 首选品牌（厂家名），如 `"上能"`。匹配后该品牌会标记为 `preferred_brand` |
| `preferences.exclude_project_specific` | bool | `true` | 是否排除含"项目专用"/"华电"备注的物料 |
| `preferences.exclude_unlisted` | bool | `true` | 是否排除含"未上架"备注的物料 |
| `preferences.prefer_non_original` | bool | `true` | 是否排除含"原厂机"备注的物料（标记为警告，不参与组合计算） |
| `preferences.dc_ac_ratio_range` | [float,float] | `[1.1, 1.3]` | DC/AC 容配比范围。所有返回的逆变器组合均满足此约束 |

### options（查询选项）

| 字段 | 类型 | 默认值 | 说明 |
|:----|:----|:------:|:------|
| `options.max_combinations` | int | `5` | 最大返回逆变器组合方案数 |
| `options.tolerance` | float | `0.15` | 逆变器组合搜索的功率容差比例（±15%） |

### 完整示例

```json
{
  "requirements": {
    "components": {"power": 715, "qty": 800},
    "inverters": {
      "existing": [
        {"model": "TS-SN40KTL3U-S4", "power_kw": 40, "qty": 1},
        {"model": "TS-SN30KTL3P-U3", "power_kw": 30, "qty": 2, "brand": "上能"}
      ]
    },
    "combiner_boxes": {
      "existing": [{"power_kw": 50, "qty": 2}]
    }
  },
  "preferences": {
    "prefer_brand": "上能",
    "exclude_project_specific": true,
    "exclude_unlisted": true,
    "prefer_non_original": true,
    "dc_ac_ratio_range": [1.1, 1.3]
  },
  "options": {
    "max_combinations": 5,
    "tolerance": 0.15
  }
}
```

## 输出格式

### summary（汇总）

| 字段 | 类型 | 说明 |
|:----|:----|:------|
| `summary.component_power_kw` | float | 组件总功率（kW） |
| `summary.component_qty` | int | 组件数量 |
| `summary.component_power_w` | int | 组件单块功率（W） |
| `summary.component_status` | str | 组件库存状态：`sufficient` / `insufficient` / `no_stock` |
| `summary.existing_inverter_kw` | float | 已有逆变器总功率 |
| `summary.inverter_need_min_kw` | float | 需要新增的最小功率（基于 DC/AC 比范围计算） |
| `summary.inverter_need_max_kw` | float | 需要新增的最大功率 |
| `summary.total_inverter_target_kw` | float | 新增功率目标值（min 和 max 的中值） |

### components（组件）

| 字段 | 类型 | 说明 |
|:----|:----|:------|
| `components.specified` | object | 用户指定规格的查询结果 |
| `components.specified.power` | int | 功率（W） |
| `components.specified.qty` | int | 需求量 |
| `components.specified.total_kw` | float | 总功率（kW） |
| `components.specified.available_stock` | int | 可用库存（已排除备注受限物料） |
| `components.specified.status` | str | `sufficient`(够用) / `insufficient`(不足) / `no_stock`(无库存) |
| `components.specified.shortfall` | int | 缺口数量 |
| `components.specified_detail` | array | 各仓库明细（含物料编号、仓库名、库存、备注） |
| `components.alternatives` | array | 相近功率替代规格，按功率降序排列 |
| `components.alternatives[].power` | int | 功率（W） |
| `components.alternatives[].total_stock` | int | 可用库存总量 |
| `components.alternatives[].status` | str | 库存状态 |
| `components.alternatives[].best_code` | str | 库存最多的物料编号 |
| `components.excluded` | array | 因备注被排除的物料清单 |
| `components.excluded[].reason` | str | 排除原因 |
| `components.warnings` | array | 标记为警告的物料（如原厂机、特价组件） |

### inverters（逆变器）

| 字段 | 类型 | 说明 |
|:----|:----|:------|
| `inverters.existing` | array | 已有逆变器（原样返回输入） |
| `inverters.existing_total_kw` | float | 已有逆变器总功率 |
| `inverters.preferred_brand` | object | 首选品牌（`prefer_brand` 匹配到时） |
| `inverters.preferred_brand.name` | str | 品牌名（厂家） |
| `inverters.preferred_brand.models` | array | 该品牌可用型号列表 |
| `inverters.preferred_brand.models[].code` | str | 物料编号 |
| `inverters.preferred_brand.models[].power` | int | 功率（kW） |
| `inverters.preferred_brand.models[].stock` | int | 聚合库存 |
| `inverters.preferred_brand.models[].price_rank` | float | 价格排序（越低越便宜） |
| `inverters.preferred_brand.models[].remark` | str | 备注 |
| `inverters.other_brands` | array | 其他品牌列表（同 preferred_brand 结构） |
| `inverters.combinations` | array | 组合方案，按 **总价序→设备台数** 排序 |
| `inverters.combinations[].plan_label` | str | 方案序号（`方案1`, `方案2`, ...） |
| `inverters.combinations[].total_power` | float | 新增总功率（kW） |
| `inverters.combinations[].total_units` | int | 总设备台数 |
| `inverters.combinations[].items` | array | 配置明细 |
| `inverters.combinations[].items[].code` | str | 物料编号 |
| `inverters.combinations[].items[].power` | int | 单台功率（kW） |
| `inverters.combinations[].items[].quantity` | int | 数量 |
| `inverters.combinations[].items[].subtotal` | float | 小计功率（power × quantity） |
| `inverters.combinations[].items[].price_rank` | float | 单价排序 |
| `inverters.combinations[].items[].brand` | str | 厂家 |
| `inverters.combinations[].total_price_rank` | float | 总价格排序（单价×数量求和，越低越便宜） |
| `inverters.combinations[].avg_price_per_kw` | float | 平均每 kW 价格排序 |
| `inverters.combinations[].brand` | str | 组合品牌 |
| `inverters.combinations[].is_same_brand` | bool | 是否同品牌组合 |
| `inverters.combinations[].dc_ac_ratio` | float | DC/AC 容配比 |
| `inverters.combinations[].total_inverter_kw` | float | 含已有的逆变器总功率 |
| `inverters.excluded` | array | 因备注被排除的物料 |
| `inverters.warnings` | array | 标记为警告的物料 |

### combiner_boxes（并网柜）

| 字段 | 类型 | 说明 |
|:----|:----|:------|
| `combiner_boxes.existing` | array | 已有并网柜（原样返回输入） |
| `combiner_boxes.available` | array | 50kW 可用并网柜，按库存量降序排列 |
| `combiner_boxes.available[].type` | str | 并网柜类型 |
| `combiner_boxes.available[].code` | str | 物料编号 |
| `combiner_boxes.available[].name` | str | 物料名称 |
| `combiner_boxes.available[].stock` | int | 聚合库存 |

## 组合排序规则

编排器返回的 `combinations` 按以下优先级排序：

1. **总价序（低→高）** — 价格便宜的优先
2. **设备台数（少→多）** — 同价格下安装更简单的优先

> DC/AC 容配比已由 `preferences.dc_ac_ratio_range` 前置约束，所有方案均满足要求，不作为区分因素。

## 备注过滤规则

编排器内部使用以下规则自动过滤物料：

| 备注含 | 级别 | 处理方式 |
|:-------|:----|:---------|
| `项目专用` / `华电` | excluded | 直接排除，不参与任何计算 |
| `未上架` | excluded | 直接排除，不可售 |
| `原厂机` | warning | 排除（标记警告），不参与组合计算 |
| `特价组件` | warning | 保留可用，标记警告 |
| `小包装` | warning | 保留可用，标记警告 |
| `常规备货` | normal | 正常可用 |
| 无备注 | none | 正常可用 |

## 响应示例

```json
{
  "version": "1.0",
  "summary": {
    "component_power_kw": 572.0,
    "component_qty": 800,
    "component_power_w": 715,
    "component_status": "no_stock",
    "existing_inverter_kw": 100,
    "inverter_need_min_kw": 340.0,
    "inverter_need_max_kw": 420.0,
    "total_inverter_target_kw": 380.0
  },
  "components": {
    "specified": {
      "power": 715, "qty": 800, "total_kw": 572,
      "available_stock": 0, "status": "no_stock", "shortfall": 800
    },
    "specified_detail": [
      {"code": "6B001440", "name": "...", "stock": 0, "remark": null, "warehouse": "天合富家-南宁仓"}
    ],
    "alternatives": [
      {"power": 730, "total_stock": 21883, "status": "sufficient",
       "best_code": "6B001492", "best_name": "销售组件_TSM-NEG21C.20_730W_..."}
    ],
    "excluded": [
      {"code": "6B001469", "stock": 11, "power": "715W",
       "reason": "项目专用物料，不可用于其他项目", "remark": "江苏华电项目专用"}
    ],
    "warnings": []
  },
  "inverters": {
    "existing": [{"model": "TS-SN40KTL3U-S4", "power_kw": 40, "qty": 1}],
    "existing_total_kw": 100,
    "preferred_brand": {
      "name": "上能",
      "models": [
        {"code": "AB001347", "power": 50, "power_label": "50KW三相",
         "name": "组串式逆变器_TS-SN50KTL3P-U4_...", "stock": 226,
         "price_rank": 217, "remark": null}
      ]
    },
    "other_brands": [
      {"name": "首航", "models": [...]}
    ],
    "combinations": [
      {"plan_label": "方案1", "total_power": 340, "total_units": 7,
       "items": [{"code": "AB001347", "power": 50, "quantity": 6, "price_rank": 217},
                 {"code": "AB001187", "power": 40, "quantity": 1, "price_rank": 193}],
       "total_price_rank": 1495, "avg_price_per_kw": 4.4,
       "brand": "上能", "is_same_brand": true,
       "dc_ac_ratio": 1.3, "total_inverter_kw": 440},
      {"plan_label": "方案2", "total_power": 350, "total_units": 7, ...},
      {"plan_label": "方案3", "total_power": 380, "total_units": 8, ...},
      {"plan_label": "方案4", "total_power": 400, "total_units": 8, ...},
      {"plan_label": "方案5", "total_power": 420, "total_units": 9, ...}
    ],
    "excluded": [
      {"code": "AB001231", "stock": 19, "power": "50KW三相",
       "reason": "原厂机交期长，非项目强制要求尽量不用", "remark": "原厂机"}
    ],
    "warnings": []
  },
  "combiner_boxes": {
    "existing": [{"power_kw": 50, "qty": 2}],
    "available": [
      {"type": "标准一体式并网箱", "code": "AA001653",
       "name": "并网柜_50KW三相_380V_不锈钢_天合原装专用_...", "stock": 622}
    ]
  }
}
```

## 最终确认输出（inventory_result.json）

用户确认库存方案后，LLM 将最终匹配结果写入 `$TMP_DIR/inventory_result.json`，供后续 BOM 生成步骤消费。

### 字段说明

| 字段 | 类型 | 说明 |
|:----|:----|:------|
| `version` | str | 接口版本号 |
| `timestamp` | str | ISO8601 时间戳 |
| `project_summary` | str | 项目摘要（LLM 根据对话生成） |
| `requirements` | object | 原始需求（组件功率/数量） |
| `decisions` | array | 每项决策记录 |
| `decisions[].category` | str | 品类：`组件` / `逆变器` / `并网柜` / `其他` |
| `decisions[].issue` | str | 问题描述 |
| `decisions[].resolution` | str | 决策结果：`user_self` / `confirmed` / `replaced` / `deferred` |
| `decisions[].note` | str | 说明备注 |
| `inventory_result.components` | object | 组件最终方案 |
| `inventory_result.components.spec` | str | 规格 |
| `inventory_result.components.qty` | int | 数量 |
| `inventory_result.components.source` | str | 来源：`stock`(库存) / `user_self`(用户自筹) |
| `inventory_result.inverters` | object | 逆变器最终方案 |
| `inventory_result.inverters.existing` | array | 已有设备 |
| `inventory_result.inverters.new` | array | 新增设备（含物料编号、数量、品牌） |
| `inventory_result.inverters.total_power_kw` | float | 总逆变器功率 |
| `inventory_result.inverters.dc_ac_ratio` | float | DC/AC 比 |
| `inventory_result.combiner_boxes` | object | 并网柜最终方案 |

### 示例

```json
{
  "version": "1.0",
  "timestamp": "2026-06-08T12:00:00",
  "project_summary": "原装三件套，用户自行解决715W组件",
  "requirements": {
    "component_power": 715,
    "component_qty": 800
  },
  "decisions": [
    {
      "category": "组件",
      "issue": "715W库存不足",
      "resolution": "user_self",
      "note": "用户自行解决715W组件"
    },
    {
      "category": "逆变器",
      "issue": "方案选择",
      "resolution": "confirmed",
      "note": "新增 TS-SN50KTL3P-U4(50kW)×8台，物料编号 AB001347"
    },
    {
      "category": "并网柜",
      "issue": "补充",
      "resolution": "confirmed",
      "note": "新增标准一体式50kW并网柜×8台，物料编号 AA001653"
    }
  ],
  "inventory_result": {
    "components": {
      "spec": "715W",
      "qty": 800,
      "source": "user_self"
    },
    "inverters": {
      "existing": [
        {"model": "TS-SN40KTL3U-S4", "power_kw": 40, "qty": 1},
        {"model": "TS-SN30KTL3P-U3", "power_kw": 30, "qty": 2}
      ],
      "new": [
        {"code": "AB001347", "name": "TS-SN50KTL3P-U4(50kW)", "power_kw": 50, "qty": 8, "brand": "上能"}
      ],
      "total_power_kw": 500,
      "dc_ac_ratio": 1.144
    },
    "combiner_boxes": {
      "existing": [{"power_kw": 50, "qty": 2}],
      "new": [{"code": "AA001653", "type": "标准一体式并网箱", "power_kw": 50, "qty": 8}]
    }
  }
}
```

## 使用示例

### 完整调用链

```bash
# 1. LLM 构建参数文件
cat > /tmp/inventory_input.json << 'EOF'
{
  "requirements": {
    "components": {"power": 715, "qty": 800},
    "inverters": {
      "existing": [
        {"model": "TS-SN40KTL3U-S4", "power_kw": 40, "qty": 1},
        {"model": "TS-SN30KTL3P-U3", "power_kw": 30, "qty": 2, "brand": "上能"}
      ]
    },
    "combiner_boxes": {
      "existing": [{"power_kw": 50, "qty": 2}]
    }
  },
  "preferences": {
    "prefer_brand": "上能",
    "dc_ac_ratio_range": [1.1, 1.3]
  }
}
EOF

# 2. 运行编排器（自动在 assets/ 下查找库存文件）
# ⚠️ 使用 --params $(cat ...) 而非 --params-file
# 避免 Windows + MSYS2 路径翻译不一致导致读到错误文件
SKILL_DIR="$HOME/.claude/skills/dms-inventory"
TMP_DIR="/tmp/dms_inventory"
mkdir -p "$TMP_DIR"

PARAMS_JSON=$(cat /tmp/inventory_input.json)
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/inventory_orchestrator.py" \
  --params "$PARAMS_JSON" \
  --output-file "$TMP_DIR/inventory_analysis.json"

# 3. LLM 读取分析结果
python -c "
import json
with open('$TMP_DIR/inventory_analysis.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(json.dumps(data, ensure_ascii=False, indent=2))
"

# 4. LLM 分析 data → 推理决策 → AskUserQuestion → 确认
# 5. LLM 输出最终结果到 inventory_result.json
```

### 典型 LLM 处理流程

```
1. 前置检查 → 组件库存不足应对策略（接受替代/用户自筹/精确匹配）
   用户已提的直用，没提的用默认值，不重复问

2. 解析用户输入 → requirements = extract_structured(user_text)

3. 调用编排器 → analysis = orchestrator.run(requirements)

4. 分析结果
   if analysis.components.specified.status == "sufficient":
       直接进入逆变器方案展示
   elif analysis.components.specified.status in ("insufficient", "no_stock"):
       if 前置检查选了"接受替代":
           取 alternatives[0] 更新 components.power
           重跑编排器 → 展示新方案
       elif 前置检查选了"用户自筹":
           原功率参与 DC/AC 计算，标记 source: user_self
       else:  # 仅精确匹配
           终止，告知用户需自筹组件

5. 用户确认后
   → 输出 inventory_result.json
   → 进入 BOM 生成步骤
```
