# orders_checker API 改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 orders_checker.py 从 Playwright 页面逐条搜索改为 httpx API 批量拉取 + 内存匹配

**Architecture:** 利用 DMS 后端 `getOrderHistoryList` API，在已登录的浏览器会话中提取 access_token，一次性拉取日期范围内的所有订单 bizFlowId，构建 set 后对每条记录做 O(1) 成员判断。查询终点扩展 31 天以覆盖下单延迟。

**Tech Stack:** Python 3.10+, httpx 0.28+, Playwright

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `scripts/column_definitions.py` | 修改 | 增加 `ORDER_CHECK_EXTEND_DAYS = 31` 常量 |
| `scripts/core/orders_checker.py` | 重写 | 移除 Playwright，新增 `fetch_ordered_flow_ids` + `check_orders_parallel` |
| `scripts/run_weekly_report.py` | 修改 | 提取 token，调用新签名的 `check_orders_parallel` |
| `scripts/tests/test_orders_checker.py` | 重写 | Mock httpx，测试空/分页/异常/匹配场景 |

---

### Task 1: 添加日期扩展常量

**Files:**
- Modify: `scripts/column_definitions.py:64`
- Test: 已存在 `scripts/tests/test_column_definitions.py`（自动覆盖常量导入）

- [ ] **Step 1: 在 column_definitions.py 末尾添加常量**

```python
# ==================== 下单检查配置 ====================

ORDER_CHECK_EXTEND_DAYS = 31  # 下单检查日期范围扩展天数（覆盖审批周期）
```

插入在 `# ==================== DMS 配置 ====================` 区块之后、文件末尾之前。

- [ ] **Step 2: 验证常量导入可用**

```bash
cd dms-weekly-report/scripts
python -c "from column_definitions import ORDER_CHECK_EXTEND_DAYS; print(ORDER_CHECK_EXTEND_DAYS)"
```
期望输出: `31`

---

### Task 2: 重写 orders_checker.py（API 版本）

**Files:**
- Create: `scripts/core/orders_checker.py`（全量重写）
- Test: `scripts/tests/test_orders_checker.py`

- [ ] **Step 1: 重写 orders_checker.py**

```python
"""下单检查模块。

通过 DMS 后端 API 批量拉取订单数据，在内存中匹配流程编号。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from column_definitions import ORDER_CHECK_EXTEND_DAYS

logger = logging.getLogger("dms_report")

API_URL = "https://apigw.trinablue.com/dms-admin/orderHistory/getOrderHistoryList"
MAX_RETRIES = 2
PAGE_SIZE = 500


async def fetch_ordered_flow_ids(
    token: str,
    start_date: str,
    end_date: str,
) -> set[str]:
    """调用订单 API，返回所有已下单的流程编号集合。

    查询范围从 start_date 到 end_date + ORDER_CHECK_EXTEND_DAYS 天，
    支持分页拉取（每页 500 条）。

    Args:
        token: access_token（从已登录页面 URL 提取）
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD

    Returns:
        已下单的流程编号集合，API 异常时返回空集合并记录日志。
    """
    # 计算扩展后的结束日期
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)
    extended_end = end_dt.strftime("%Y-%m-%d")

    logger.info("拉取订单数据：%s ~ %s（扩展 %d 天）", start_date, extended_end, ORDER_CHECK_EXTEND_DAYS)

    all_ids: set[str] = set()
    page_num = 1

    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                resp = await client.post(
                    API_URL,
                    json={
                        "createTime": start_date,
                        "toCreateTime": extended_end,
                        "pageNum": page_num,
                        "pageSize": PAGE_SIZE,
                    },
                    headers=headers,
                )
                data = resp.json()

                if data.get("code") != 1:
                    logger.warning("订单 API 返回异常 code=%s: %s", data.get("code"), data.get("errMsg", ""))
                    break

                records = data.get("data", {}).get("records", [])
                for record in records:
                    flow_id = record.get("bizFlowId")
                    if flow_id:
                        all_ids.add(str(flow_id).strip())

                logger.debug("第 %d 页: 获取 %d 条", page_num, len(records))

                if len(records) < PAGE_SIZE:
                    break

                page_num += 1

            except httpx.TimeoutException:
                logger.warning("订单 API 第 %d 页超时，终止分页", page_num)
                break
            except httpx.HTTPStatusError as e:
                logger.warning("订单 API HTTP 错误: %s", e)
                break
            except Exception as e:
                logger.warning("订单 API 请求异常: %s", e)
                break

    logger.info("订单 API 拉取完成：共 %d 条已下单记录", len(all_ids))
    return all_ids


async def check_orders_parallel(
    token: str,
    records: list,
    start_date: str,
    end_date: str,
) -> list:
    """并行检查所有记录的下单状态。

    Args:
        token: access_token
        records: 包含 flow_id 属性的对象列表
        start_date: 查询开始日期
        end_date: 查询结束日期

    Returns:
        records（ordered 字段被更新）
    """
    logger.info("下单检查 %d 条（API 批量模式）...", len(records))

    ordered_ids = await fetch_ordered_flow_ids(token, start_date, end_date)

    for record in records:
        flow_id = getattr(record, "flow_id", "")
        record.ordered = "是" if flow_id in ordered_ids else "否"

    ordered_count = sum(1 for r in records if r.ordered == "是")
    logger.info("下单检查完成：%d 条已下单，%d 条未下单", ordered_count, len(records) - ordered_count)
    return records
```

- [ ] **Step 2: 验证新模块可导入**

```bash
cd dms-weekly-report/scripts
python -c "from core.orders_checker import fetch_ordered_flow_ids, check_orders_parallel; print('OK')"
```
期望输出: `OK`

---

### Task 3: 修改 run_weekly_report.py 调用方式

**Files:**
- Modify: `scripts/run_weekly_report.py:165-166`

- [ ] **Step 1: 添加 import re 到文件顶部**

```python
import re  # 添加到已有 import 段中
```

确认 `import re` 已在文件顶部（第 28 行附近的 `from datetime import datetime` 之后）。如果没有则添加。

- [ ] **Step 2: 在页面关闭前提取 access_token**

在 `await page.close()`（第 157 行）之前添加 token 提取，因为 close 后 `page.url` 可能不可靠：

```python
# 在 step 2 和 close 之间插入（约第 157 行）：
            # 提取 access_token（供后续下单检查使用）
            access_token_match = re.search(r"access_token=([^&]+)", page.url)
            access_token = access_token_match.group(1) if access_token_match else None
            if not access_token:
                logger.warning("未获取到 access_token，后续下单检查将跳过")

            # 关闭初始 page，释放资源供并行 Tab 使用
            await page.close()

            # 3. 并行提取详情
            ...
```

- [ ] **Step 3: 修改下单检查调用（第 165-166 行）**

```python
# 旧代码（约第 164-166 行）:
#            # 4. 并行检查下单
#            all_details = await check_orders_parallel(context, all_details, args.workers)
#            records = all_details

# 新代码:
            # 4. 下单检查（通过 API 批量拉取）
            if access_token:
                all_details = await check_orders_parallel(
                    access_token, all_details, start_date, end_date,
                )
            else:
                logger.warning("access_token 缺失，全部标记为未下单")
                for r in all_details:
                    r.ordered = "否"
            records = all_details
```

---

### Task 4: 重写测试

**Files:**
- Modify: `scripts/tests/test_orders_checker.py`（全量重写）

- [ ] **Step 1: 重写测试文件**

```python
"""下单检查模块的单元测试（API 版本）。"""

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orders_checker import (
    fetch_ordered_flow_ids,
    check_orders_parallel,
)


@dataclass
class MockRecord:
    """模拟 FlowRecord，仅包含下单检查需要的字段。"""
    flow_id: str = ""
    ordered: str = "否"


class TestFetchOrderedFlowIds(unittest.TestCase):
    """fetch_ordered_flow_ids 测试。"""

    @patch("core.orders_checker.httpx.AsyncClient")
    def test_single_page(self, mock_client):
        """单页数据能正确提取 bizFlowId。"""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "code": 1,
            "data": {
                "records": [
                    {"bizFlowId": "FLOW001"},
                    {"bizFlowId": "FLOW002"},
                    {"bizFlowId": "FLOW003"},
                ],
            },
        })
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__.return_value = mock_instance

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids("fake-token", "2026-06-01", "2026-06-07"))

        self.assertEqual(result, {"FLOW001", "FLOW002", "FLOW003"})

    @patch("core.orders_checker.httpx.AsyncClient")
    def test_empty_response(self, mock_client):
        """无订单数据返回空集合。"""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "code": 1,
            "data": {"records": []},
        })
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__.return_value = mock_instance

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids("fake-token", "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    @patch("core.orders_checker.httpx.AsyncClient")
    def test_api_error_code(self, mock_client):
        """API 返回错误 code 时返回空集合并记录日志。"""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "code": -1,
            "errMsg": "非法用户",
        })
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value.__aenter__.return_value = mock_instance

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids("invalid-token", "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    @patch("core.orders_checker.httpx.AsyncClient")
    def test_exception_returns_empty_set(self, mock_client):
        """网络异常时返回空集合（不崩溃）。"""
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.return_value.__aenter__.return_value = mock_instance

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids("fake-token", "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    def test_extended_end_date(self):
        """验证日期扩展逻辑正确（集成测试级别的校验）。"""
        from datetime import datetime, timedelta
        from column_definitions import ORDER_CHECK_EXTEND_DAYS

        end_date = "2026-06-07"
        extended = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)).strftime("%Y-%m-%d")
        # 31 天后是 2026-07-08（6月30天）
        self.assertIn("2026-07-", extended)


class TestCheckOrdersParallel(unittest.TestCase):
    """check_orders_parallel 测试。"""

    @patch("core.orders_checker.fetch_ordered_flow_ids")
    def test_matched_flow_id_found(self, mock_fetch):
        """流程在订单集合中返回 '是'。"""
        mock_fetch.return_value = {"FLOW001", "FLOW002"}
        records = [MockRecord(flow_id="FLOW001"), MockRecord(flow_id="FLOW003")]

        import asyncio
        result = asyncio.run(check_orders_parallel("token", records, "2026-06-01", "2026-06-07"))

        self.assertEqual(result[0].ordered, "是")
        self.assertEqual(result[1].ordered, "否")

    @patch("core.orders_checker.fetch_ordered_flow_ids")
    def test_all_not_found(self, mock_fetch):
        """所有流程都不在订单中时全部返回 '否'。"""
        mock_fetch.return_value = set()
        records = [MockRecord(flow_id="FLOW001"), MockRecord(flow_id="FLOW002")]

        import asyncio
        result = asyncio.run(check_orders_parallel("token", records, "2026-06-01", "2026-06-07"))

        self.assertEqual(result[0].ordered, "否")
        self.assertEqual(result[1].ordered, "否")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证全部通过**

```bash
cd dms-weekly-report/scripts
python tests/test_orders_checker.py -v
```

期望输出: 6 个测试全部 `ok`

---

### Task 5: 运行完整测试套件

- [ ] **Step 1: 运行所有相关测试**

```bash
cd dms-weekly-report/scripts
python -m pytest tests/ -v
```

期望输出: 所有测试通过，`test_orders_checker.py` 包含 6 个测试

---

### Task 6: 同步到 ~/.claude/skills/

- [ ] **Step 1: 按 CLAUDE.md 同步规则复制**

```bash
rm -rf "$HOME/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "$HOME/.claude/skills/dms-weekly-report/"
```

---

### Task 7: 提交变更

- [ ] **Step 1: 暂存并提交**

```bash
cd "D:\Code\Skills开发\tianhe-skills"
git add dms-weekly-report/scripts/core/orders_checker.py
git add dms-weekly-report/scripts/run_weekly_report.py
git add dms-weekly-report/scripts/column_definitions.py
git add dms-weekly-report/scripts/tests/test_orders_checker.py
git add docs/orders-checker-api-design.md
git add docs/superpowers/plans/2026-06-12-orders-checker-api-refactor.md
git commit -m "refactor(weekly-report): 订单检查改为 API 批量拉取替代浏览器逐条搜索

- 重写 orders_checker.py：使用 httpx 调用 getOrderHistoryList API
- 一次性拉取日期范围（+31天扩展）内的所有 bizFlowId
- 内存 set 匹配替代 N 次页面打开搜索
- 更新 test_orders_checker.py：Mock httpx 响应，6 个测试
- column_definitions.py 增加 ORDER_CHECK_EXTEND_DAYS=31"
```
