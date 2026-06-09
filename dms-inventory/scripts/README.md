# scripts/ — 脚本文件说明

## 文件清单

| 文件 | 角色 | 调用方 | 依赖 |
|:-----|:-----|:-------|:-----|
| `inventory_orchestrator.py` | **编排器** — 统一入口，执行完整库存查询/过滤/组合计算，返回结构化 JSON | SKILL.md 工作流步骤 2 | `inventory_query.py`, `inverter_config.py`, `_compat.py` |
| `inventory_query.py` | **查询引擎** — 加载 Excel、查询组件/逆变器/并网箱、聚合库存、备注过滤 | 编排器, `inverter_config.py`, `lookup_by_code.py` | `_compat.py`, pandas |
| `inverter_config.py` | **逆变器配置器** — DC/AC 范围计算、多品牌组合搜索、方案排序 | 编排器 | `inventory_query.py`, `_compat.py` |
| `lookup_by_code.py` | **快捷查询** — 按物料编号/名称跨品类搜索，支持聚合和 JSON 输出 | SKILL.md 快捷查询章节 | `inventory_query.py`, `_compat.py` |
| `_compat.py` | **兼容层** — Windows 终端中文乱码修复 | 所有其他脚本自动导入 | — |

## 调用链

```
SKILL.md 工作流
  ├── 步骤 2 → inventory_orchestrator.py
  │                ├── inventory_query.py      (加载 Excel / 查询原始数据)
  │                └── inverter_config.py      (逆变器组合计算)
  │                     └── inventory_query.py (获取逆变器型号库存)
  └── 快捷查询 → lookup_by_code.py
                   └── inventory_query.py      (查询 + 聚合)
```

## 设计原则

- **`inventory_orchestrator.py`** 是所有确定性逻辑的单一入口，LLM 只调用这一个脚本
- **`inventory_query.py`** 是数据访问层（读 Excel、查询、聚合），不包含业务决策逻辑
- **`inverter_config.py`** 封装逆变器组合搜索算法，与查询引擎解耦
- **`lookup_by_code.py`** 是独立辅助工具，不走编排器，用于快速查库存
- **`_compat.py`** 无业务逻辑，所有涉及中文输出的脚本都应导入
