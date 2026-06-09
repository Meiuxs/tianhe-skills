# 快捷查询脚本使用说明

## 概述

`lookup_by_code.py` 是独立于编排器的快捷查询脚本，用于快速定位某个具体物料的库存信息。

## 基本用法

```bash
SKILL_DIR="$HOME/.claude/skills/dms-inventory"
TMP_DIR="/tmp/dms_inventory"
mkdir -p "$TMP_DIR"

# 按物料编号精确查询（聚合所有仓库）
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/lookup_by_code.py" \
  --code 6B001492 --aggregate

# 按型号/名称关键词模糊查询
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/lookup_by_code.py" \
  --name "天合原装" --category 逆变器 --aggregate

# JSON 输出供程序消费（使用 TMP_DIR 固定路径避免乱码）
PYTHONIOENCODING=utf-8 python "$SKILL_DIR/scripts/lookup_by_code.py" \
  --code AB001347 --aggregate --json --output-file "$TMP_DIR/lookup_result.json"
```

## 参数说明

| 参数 | 说明 | 必填 |
|:-----|:------|:----:|
| `--code CODE` | 物料编号精确查询 | ⭕ |
| `--name NAME` | 物料名称模糊查询 | ⭕ |
| `--category CAT` | 品类筛选（组件/逆变器/并网柜） | ⭕ |
| `--aggregate` | 按物料编号聚合所有仓库数量 | ⭕ |
| `--json` | JSON 格式输出 | ⭕ |
| `--output-file PATH` | 输出到文件（配合 `--json`） | ⭕ |

> `--code` 和 `--name` 至少指定一个。

## 适用场景对比

| 场景 | 用编排器 `orchestrator` | 用快捷查询 `lookup_by_code` |
|:----|:----------------------|:---------------------------|
| 完整方案匹配（组件+逆变器+并网柜） | ✅ | ❌ |
| 查某个具体物料编码的库存 | ❌ | ✅ |
| DC/AC 配比计算 | ✅ | ❌ |
| 物料名称关键词模糊搜索 | ❌ | ✅ |
