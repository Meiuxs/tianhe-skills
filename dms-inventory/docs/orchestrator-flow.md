# 库存编排器 — 组合编排逻辑说明

> 对应文件：`scripts/inventory_orchestrator.py`

---

## 目录

1. [整体架构](#1-整体架构)
2. [主流程 `run_analysis()`](#2-主流程-run_analysis)
3. [备注过滤系统](#3-备注过滤系统)
4. [组件查询 `query_components_section()`](#4-组件查询-query_components_section)
5. [逆变器查询 `query_inverters_section()`](#5-逆变器查询-query_inverters_section)
6. [品牌分组与物料偏好](#6-品牌分组与物料偏好)
7. [组合方案生成（四步填充法）](#7-组合方案生成四步填充法)
8. [并网柜查询 `query_boxes_section()`](#8-并网柜查询-query_boxes_section)
9. [数据流汇总](#9-数据流汇总)
10. [输入输出参数](#10-输入输出参数)

---

## 1. 整体架构

```mermaid
graph TB
    LLM[LLM 调用方] -->|JSON params| Orchestrator[inventory_orchestrator.py]
    Orchestrator -->|结构化 JSON| LLM

    subgraph Orchestrator [编排器核心流程]
        Run[run_analysis] --> QueryC[组件查询]
        Run --> QueryI[逆变器查询]
        Run --> QueryB[并网柜查询]
        QueryI --> Combo[组合方案生成]
    end

    subgraph Libs [依赖模块]
        IQ[inventory_query<br/>数据加载 / 查询 / 聚合]
        IC[inverter_config<br/>范围计算 / 组合搜索]
    end

    QueryC --> IQ
    QueryI --> IQ
    QueryB --> IQ
    Combo --> IC
```

**设计原则：** 纯确定性逻辑，所有计算不依赖 LLM，结果完全可复现。LLM 只需传入结构化 JSON 参数，读取 JSON 分析结果做最终判断。

---

## 2. 主流程 `run_analysis()`

```mermaid
flowchart TD
    Start([开始]) --> Params[提取 requirements / preferences]
    Params --> Load[load_inventory<br/>加载 Excel 库存文件]
    Load --> Components[query_components_section<br/>组件分析]

    Components --> ComponentKW{组件总功率 > 0?}
    ComponentKW -->|是| Inject[注入 component_power_kw 到逆变器模块]
    ComponentKW -->|否| SkipInject

    Inject --> Inverters[query_inverters_section<br/>逆变器分析 + 组合方案]
    SkipInject --> Inverters

    Inverters --> Boxes[query_boxes_section<br/>并网柜分析]
    Boxes --> Summary[构建汇总 summary]

    Summary --> Calc{组件总功率 > 0?}
    Calc -->|是| Range[calculate_inverter_range<br/>计算 DC/AC 比约束下的逆变器需求范围]
    Calc -->|否| NoRange

    Range --> Format[组装最终 result]
    NoRange --> Format

    Format --> Output["返回结构化 JSON<br/>{version, summary, components, inverters, combiner_boxes}"]
    Output --> End([结束])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
    style Output fill:#c8e6c9
```

### 汇总字段说明

```json
{
  "summary": {
    "component_power_kw": 584.0,           // 组件总功率 (kW)
    "component_qty": 800,                   // 组件数量
    "component_power_w": 730,               // 单块组件功率 (W)
    "component_status": "sufficient",       // sufficient / insufficient / no_stock
    "existing_inverter_kw": 40,             // 已有逆变器总功率
    "inverter_need_min_kw": 446.7,          // 需要新购的最小逆变器功率
    "inverter_need_max_kw": 490.9,          // 需要新购的最大逆变器功率
    "total_inverter_target_kw": 468.8       // 推荐新购功率（平均值）
  }
}
```

---

## 3. 备注过滤系统

```mermaid
flowchart LR
    subgraph Rules [备注规则表 REMARK_RULES]
        direction TB
        R1["项目专用 → excluded"]
        R2["华电 → excluded"]
        R3["未上架 → excluded"]
        R4["原厂机 → warning"]
        R5["特价组件 → warning"]
        R6["小包装 → warning"]
        R7["常规备货 → normal"]
    end

    subgraph Logic [过滤逻辑 _filter_by_remark]
        direction TB
        L1[遍历每行] --> L2{匹配到关键词?}
        L2 -->|excluded| L3{偏好开关?}
        L3 -->|允许排除| L4[加入 excluded 列表<br/>跳过]
        L3 -->|关闭排除| L5[保留到 available]
        L2 -->|warning| L6[加入 warnings 列表<br/>保留到 available]
        L2 -->|normal/none| L5
    end

    Rules --> Logic
    Logic --> Out[返回 available / excluded / warnings 三路]
```

### 排除开关（preferences 控制）

| 关键词 | 开关 | 默认 | behavior |
|--------|------|------|----------|
| 项目专用、华电 | `exclude_project_specific` | `true` | `true`=排除，`false`=保留 |
| 未上架 | `exclude_unlisted` | `true` | `true`=排除，`false`=保留 |
| 原厂机 | `prefer_non_original` | `true` | `true`=排除，`false`=保留+警告 |
| 特价组件 | — | — | 始终保留，仅记录警告 |
| 小包装 | — | — | 始终保留，仅记录警告 |

---

## 4. 组件查询 `query_components_section()`

```mermaid
flowchart TD
    Start([开始]) --> Extract[提取 target_power / target_qty]
    Extract --> Query["query_components(df, power=target_power, has_stock=None)<br/>查全部（含零库存）"]

    Query --> Detail[记录明细 specified_detail]
    Detail --> Zero{库存=0 且<br/>未被备注排除?}
    Zero -->|是| Candidate[加入 zero_stock_candidates]
    Zero -->|否| SkipZero

    Candidate --> Agg[aggregate_stock<br/>按物料编码聚合库存]
    SkipZero --> Agg

    Agg --> Filter[_filter_by_remark<br/>备注过滤]
    Filter --> Status{可用库存 ≥ 需求?}

    Status -->|≥| Sufficient[status = 'sufficient']
    Status -->|>0| Insufficient[status = 'insufficient']
    Status -->|=0| NoStock[status = 'no_stock']

    Sufficient --> Alt[查询其他功率规格作为替代方案]
    Insufficient --> Alt
    NoStock --> Alt

    Alt --> Return["返回 {specified, specified_detail,<br/>zero_stock_candidates, alternatives,<br/>excluded, warnings}"]
    Return --> End([结束])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
```

### 替代方案扫描逻辑

对所有不同于指定功率的规格（按功率降序），逐一遍历：

```mermaid
flowchart LR
    Powers[获取所有功率规格] --> Sort[按功率降序排列]
    Sort --> Loop{遍历每个功率}
    Loop -->|跳过自身| Skip[跳过]
    Loop -->|其他| Check["query_components(power=pn)<br/>→ aggregate_stock<br/>→ _filter_by_remark"]
    Check --> Record["记录 {power, total_stock, status, best_code}"]
    Record --> Loop
    Loop -->|完毕| Done[返回 alternatives 列表]
```

---

## 5. 逆变器查询 `query_inverters_section()`

### 5.1 整体流程

```mermaid
flowchart TD
    Start([开始]) --> InvReq{requirements<br/>有 inverters 段?}
    InvReq -->|无| EarlyReturn[返回空结果]

    InvReq -->|有| Exist[处理已有逆变器<br/>_calc_existing_kw]
    Exist --> Warn{已有设备但<br/>功率解析为 0?}
    Warn -->|是| PrintWarn[打印警告到 stderr]
    Warn -->|否| SkipWarn

    PrintWarn --> Load[加载逆变器 DataFrame]
    SkipWarn --> Load

    Load --> Items["query_inverters(df, has_stock=True, brand=None)<br/>查询全部有库存的逆变器"]

    Items --> ZeroStock[查询零库存候选<br/>供用户自筹参考]

    ZeroStock --> Agg[aggregate_stock<br/>聚合库存]
    Agg --> FilterRemark[_filter_by_remark<br/>备注过滤]
    FilterRemark --> Avail{有可用物料?}
    Avail -->|无| EarlyReturn2[返回空结果]

    Avail -->|有| BrandGroup[品牌分组 + 物料偏好]
    BrandGroup --> Combo[组合方案生成<br/>四步填充法]
    Combo --> Enhance[方案增强: DC/AC 比 / 总功率 / 排序]
    Enhance --> Return[返回结构化结果]
    Return --> End([结束])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
    style EarlyReturn fill:#ffcdd2
    style EarlyReturn2 fill:#ffcdd2
```

### 5.2 已有逆变器功率解析

支持多种输入格式：

```mermaid
flowchart LR
    Input[已有设备列表] --> Parse{逐个解析}
    Parse -->|power_kw| Direct[直接取数字]
    Parse -->|power + unit| Sep[取 power 字段]
    Parse -->|power 为 40kW 字符串| Str[正则提取数字]
    Parse -->|无字段| Zero[视为 0]
    Direct --> Sum["累计 total = power * qty 之和"]
    Sep --> Sum
    Str --> Sum
    Zero --> Sum
```

### 5.3 零库存候选

> **条件：** 匹配需求功率/品牌、库存为 0、未被备注排除（不可用的直接过滤）

```
场景 1: required_new 指定 → 按指定功率+品牌查零库存型号
场景 2: 未指定 required_new → 按首选品牌查零库存型号
                                ↓
                     聚合 + 过滤 remark → 收集零库存候选
```

---

## 6. 品牌分组与物料偏好

> 注意：`aggregate_stock()` 聚合后丢弃 `厂家`、`功率`、`备注` 等列，品牌分组**必须用原始 `items` DataFrame**。

```mermaid
flowchart TD
    Start([开始品牌分组]) --> AvailCodes["avail_codes = set(available.物料编号)"]
    AvailCodes --> RawItems["raw_items = items[avail_codes]<br/>从原始数据反查完整行"]
    RawItems --> PrefFilter{prefer_material 设置?}
    PrefFilter -->|是| Filter["过滤 raw_items<br/>仅保留物料名称含关键词的行"]
    PrefFilter -->|否| Skip
    Filter --> Skip
    Skip --> StockLookup["stock_lookup = {物料编号: 库存总量}"]
    StockLookup --> BrandLoop["按 厂家 列分组 → brands 列表"]
    BrandLoop --> Done([品牌分组完成])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
```

### 输出结构示例

```json
{
  "brands": [
    {
      "name": "上能",
      "models": [
        {"code": "INV001", "power": 40, "name": "上能40kW", "stock": 5, "brand": "上能"},
        {"code": "INV003", "power": 50, "name": "上能50kW", "stock": 3, "brand": "上能"}
      ]
    },
    {
      "name": "华为",
      "models": [{"code": "INV002", "power": 40, "name": "华为40kW", "stock": 8, "brand": "华为"}]
    }
  ]
}
```

> **`prefer_material`** 在品牌分组前完成前置过滤：若设置，`raw_items` 在分组前已按物料名称关键词过滤，后续品牌分组和组合搜索均只包含匹配的型号。

---

## 7. 组合方案生成（四步填充法）

这是编排器中最复杂的逻辑。核心策略是**分步填充**，优先级递减：

```mermaid
flowchart TD
    Start([开始组合]) --> DCAC["calculate_inverter_range()<br/>DC/AC 比 1.1~1.2 → 目标功率 target_power"]

    DCAC --> Loop["遍历 brands 每个品牌<br/>same_brand=True 独立搜索"]

    Loop --> BrandAlgo["find_inverter_combinations()<br/>品牌内贪婪: 大功率优先 → 最少台数"]
    BrandAlgo --> HasResult{同品牌<br/>有方案产出?}

    HasResult -->|是| Enhance
    HasResult -->|否| Mixed["find_inverter_combinations<br/>混合品牌 same_brand=False"]

    Mixed --> Enhance

    Enhance["增强信息: dc_ac_ratio / total_units / avg_price_per_kw"]
    Enhance --> Sort["排序: (total_units ASC, total_price_rank ASC)<br/>台数少优先 → 同台数价格低优先"]
    Sort --> Label["标记 plan_label"]
    Label --> Return["返回 combinations"]
    Return --> End([结束])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
    style HasResult fill:#fff9c4
```

### 组合优先级

| 阶段 | 名称 | 数据来源 | same_brand | 触发条件 |
|------|------|---------|-----------|---------|
| **1** | 同品牌方案 | `brands` 每个品牌各自的型号 | `True` | 始终执行，每个品牌独立搜索 |
| **2** | 混合品牌方案 | 全量（`raw_items_filtered`） | `False` | 仅当阶段 1 无任何方案时触发 |

**终止条件：** 阶段 1 任一品牌产出方案 → 直接输出，不再执行阶段 2。

### 单台方案补充逻辑

```mermaid
flowchart LR
    subgraph SingleUnit [_add_single_unit_combos]
        direction TB
        S1[遍历 model_list] --> S2{单台功率在<br/>target_power ± tolerance 内?}
        S2 -->|是| S3{有库存?}
        S3 -->|是| S4{此物料编码<br/>已在 all_combos 中?}
        S4 -->|否| S5[加入作为独立方案]
        S5 --> S1
        S2 -->|否| S1
        S3 -->|否| S1
        S4 -->|是| S1
    end
```

### 组合排序规则

```
主要排序: total_price_rank（总价序，低→高）
次要排序: total_units（设备台数，少→多）

即：同等价格下，用更少设备台数完成需求的方案排在前面
```

---

## 8. 并网柜查询 `query_boxes_section()`

```mermaid
flowchart TD
    Start([开始]) --> Req[提取 requirements.combiner_boxes]
    Req --> Power["box_power = box_req.get('power', 50)<br/>默认 50kW，支持自定义"]

    Power --> DF{并网箱 DataFrame<br/>有数据?}
    DF -->|无| Empty[返回空结果]

    DF -->|有| Query["query_boxes(df, power=box_power, has_stock=True)"]
    Query --> HasStock{有库存?}
    HasStock -->|无| Empty

    HasStock -->|有| Agg[aggregate_stock]
    Agg --> Build[构建 available 列表<br/>{type, code, name, stock}]
    Build --> Return["返回 {existing, available}"]
    Return --> End([结束])

    style Start fill:#e1f5fe
    style End fill:#e1f5fe
    style Empty fill:#ffcdd2
```

---

## 9. 数据流汇总

### 整体数据流

```mermaid
flowchart LR
    subgraph Input [输入参数]
        REQ[requirements]
        PREF[preferences]
        OPT[options]
    end

    subgraph Excel [库存文件 -> load_inventory]
        C[组件 sheet]
        I[逆变器 sheet]
        B[并网箱 sheet]
    end

    subgraph Process [编排处理]
        direction TB
        P1[query_components_section]
        P2[query_inverters_section]
        P3[query_boxes_section]
    end

    subgraph Output [输出 JSON]
        S[summary]
        CP[components]
        IV[inverters]
        CB[combiner_boxes]
    end

    Input --> Process
    Excel --> Process
    Process --> Output
```

### 逆变器数据血缘

> 理解各阶段 DataFrame 包含哪些列，是正确理解编排逻辑的关键。

```mermaid
flowchart TD
    Raw["df (原始, 含所有列)<br/>物料编号, 物料名称, 功率,<br/>可用库存, 厂家, 价格排序, 备注"]

    Items["items = query_inverters(df)<br/>过滤: stock > 0<br/>选择列: 厂家, 功率, 物料编号,<br/>物料名称, 可用库存, 备注, 价格排序"]

    Agg["agg = aggregate_stock(items)<br/>按 物料编号 分组<br/>保留: 库存总量, 物料名称<br/>合并额外列: 厂家, 功率, 备注, 价格排序<br/>（每组取 first）"]

    Avail["available = filtered.available<br/>备注过滤后的聚合数据"]

    RawItems["raw_items = items[avail_codes]<br/>从原始 items 反查可用物料<br/>用于品牌分组（含 厂家 列）"]

    RawAvail["raw_available = items[avail_codes].copy()<br/>用于组合搜索<br/>含 厂家 列供同品牌过滤"]

    Raw -->|has_stock=True| Items
    Items -->|aggregate_stock| Agg
    Agg -->|_filter_by_remark| Avail
    Avail -->|avail_codes 回查| RawItems
    Avail -->|avail_codes 回查| RawAvail
    Items -->|avail_codes 回查| RawItems
    Items -->|avail_codes 回查| RawAvail
```

---

## 10. 输入输出参数

### 输入参数

| 层级 | 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|------|
| `requirements.components` | `power` | int | 是 | — | 组件功率 (W) |
| `requirements.components` | `qty` | int | 是 | — | 组件数量 |
| `requirements.inverters` | `existing` | list | 否 | `[]` | 已有逆变器列表 |
| `requirements.inverters.existing[]` | `model` | string | 否 | — | 型号名 |
| `requirements.inverters.existing[]` | `power_kw` | float | 推荐 | — | 单台功率 (kW) |
| `requirements.inverters.existing[]` | `power` | float/string | 备选 | — | `40` 或 `"40kW"` |
| `requirements.inverters.existing[]` | `qty` | int | 否 | 1 | 数量 |
| `requirements.inverters.existing[]` | `brand` | string | 否 | — | 品牌 |
| `requirements.inverters` | `required_new` | list | 否 | `[]` | 需求新购型号（用于零库存候选） |
| `requirements.combiner_boxes` | `existing` | list | 否 | `[]` | 已有并网柜列表 |
| `requirements.combiner_boxes` | `power` | int | 否 | `50` | 目标并网柜功率 (kW) |
| `preferences` | `prefer_brand` | string | 否 | — | 首选品牌（厂家列） |
| `preferences` | `prefer_material` | string | 否 | — | 物料偏好关键词（前置过滤，物料名称列匹配） |
| `preferences` | `exclude_project_specific` | bool | 否 | `true` | 排除项目专用物料 |
| `preferences` | `exclude_unlisted` | bool | 否 | `true` | 排除未上架物料 |
| `preferences` | `prefer_non_original` | bool | 否 | `true` | 优先非原厂机 |
| `preferences` | `dc_ac_ratio_range` | [float,float] | 否 | `[1.1, 1.2]` | DC/AC 比范围 |
| `preferences` | `stock_sufficient` | bool | 否 | `true` | 只推荐库存充足的方案 |
| `options` | `max_combinations` | int | 否 | `5` | 最多返回组合数 |
| `options` | `tolerance` | float | 否 | `0.15` | 组合功率容差 (15%) |

### 输出结构

```json
{
  "version": "1.0",
  "timestamp": null,
  "summary": {
    "component_power_kw": 584.0,
    "component_qty": 800,
    "component_power_w": 730,
    "component_status": "sufficient | insufficient | no_stock",
    "existing_inverter_kw": 40.0,
    "inverter_need_min_kw": 446.7,
    "inverter_need_max_kw": 490.9,
    "total_inverter_target_kw": 468.8,
    "existing_inverter_detail": "上能40kW x 1"    // 仅在有已有逆变器时
  },
  "components": {
    "specified": {
      "power": 730, "qty": 800, "total_kw": 584.0,
      "available_stock": 800, "status": "sufficient",
      "shortfall": 0
    },
    "specified_detail": [                 // 全部明细（含零库存）
      {"code": "6B001492", "name": "...", "stock": 500, "remark": null, "warehouse": "南宁仓"}
    ],
    "zero_stock_candidates": [...],       // 零库存但可用的候选
    "alternatives": [                     // 其他功率规格
      {"power": 715, "total_stock": 200, "status": "insufficient", "best_code": "..."}
    ],
    "excluded": [...],
    "warnings": [...]
  },
  "inverters": {
    "existing": [{"model": "上能40kW", "power_kw": 40, "qty": 1, "brand": "上能"}],
    "existing_total_kw": 40.0,
    "zero_stock_candidates": [...],
    "preferred_brand": {                  // 设置了 prefer_brand 时
      "name": "上能",
      "models": [{"code": "...", "power": 40, "name": "...", "stock": 5, "brand": "上能"}]
    },
    "preferred_material": {               // 设置了 prefer_material 时
      "keyword": "天合原装专用",
      "models": [                         // 物料保留实际品牌
        {"code": "...", "brand": "上能", "name": "天合原装专用40kW", ...},
        {"code": "...", "brand": "华为", "name": "天合原装专用40kW", ...}
      ]
    },
    "other_brands": [
      {"name": "华为", "models": [...]}
    ],
    "combinations": [
      {
        "plan_label": "方案1",
        "total_power": 440.0,
        "total_price_rank": 3,
        "brand": "天合原装",               // 物料偏好方案的 brand 标签
        "is_material_preferred": true,     // 物料偏好方案标记
        "dc_ac_ratio": 1.2,
        "total_inverter_kw": 480.0,
        "total_units": 2,
        "avg_price_per_kw": 0.01,
        "items": [
          {"code": "...", "power": 40, "quantity": 11, "subtotal": 440,
           "price_rank": 3, "brand": "上能"}
        ]
      }
    ],
    "excluded": [...],
    "warnings": [...]
  },
  "combiner_boxes": {
    "existing": [{"power_kw": 50, "qty": 2}],
    "available": [
      {"type": "并网柜", "code": "...", "name": "...", "stock": 10, "total_stock": 10}
    ]
  }
}
```

---

## 修订历史

| 日期 | 变更 | 说明 |
|------|------|------|
| 2026-06-12 | 初始版本 | workflow 逻辑说明 |
| 2026-06-12 | 新增 `prefer_material` | 物料偏好参数，与品牌正交；修复品牌分组用原始 DataFrame 而非聚合数据 |
