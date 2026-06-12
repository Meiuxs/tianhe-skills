"""下单检查模块的单元测试（API 版本，使用 Playwright APIRequestContext）。"""

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_mock_context(token: str = "fake-token", post_result: dict | None = None) -> MagicMock:
    """创建模拟的 Playwright BrowserContext。"""
    context = MagicMock()
    # get_access_token 需要 context.cookies()
    context.cookies = AsyncMock(return_value=[
        {"name": "dms_admin_token", "value": token},
    ])
    # fetch_ordered_flow_ids 需要 context.request.post()
    if post_result is not None:
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=post_result)
        context.request.post = AsyncMock(return_value=mock_resp)
    return context


class TestFetchOrderedFlowIds(unittest.TestCase):
    """fetch_ordered_flow_ids 测试。"""

    def test_single_page(self):
        """单页数据能正确提取 bizFlowId。"""
        ctx = _make_mock_context(post_result={
            "code": 1,
            "data": {
                "records": [
                    {"bizFlowId": "FLOW001"},
                    {"bizFlowId": "FLOW002"},
                    {"bizFlowId": "FLOW003"},
                ],
            },
        })

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(result, {"FLOW001", "FLOW002", "FLOW003"})

    def test_empty_response(self):
        """无订单数据返回空集合。"""
        ctx = _make_mock_context(post_result={
            "code": 1,
            "data": {"records": []},
        })

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    def test_api_error_code(self):
        """API 返回错误 code 时返回空集合并记录日志。"""
        ctx = _make_mock_context(post_result={
            "code": -1,
            "errMsg": "非法用户",
        })

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    def test_exception_returns_empty_set(self):
        """网络异常时返回空集合（不崩溃）。"""
        ctx = MagicMock()
        ctx.cookies = AsyncMock(return_value=[
            {"name": "dms_admin_token", "value": "fake-token"},
        ])
        ctx.request.post = AsyncMock(side_effect=Exception("Connection failed"))

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    def test_no_token_returns_empty(self):
        """无 access_token 时返回空集合。"""
        ctx = MagicMock()
        ctx.cookies = AsyncMock(return_value=[])  # 无 cookie

        import asyncio
        result = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(result, set())

    def test_extended_end_date(self):
        """验证日期扩展逻辑正确。"""
        from datetime import datetime, timedelta
        from core.orders_checker import ORDER_CHECK_EXTEND_DAYS

        end_date = "2026-06-07"
        extended = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)).strftime("%Y-%m-%d")
        self.assertIn("2026-07-", extended)


class TestCheckOrdersParallel(unittest.TestCase):
    """check_orders_parallel 测试。"""

    @patch("core.orders_checker.fetch_ordered_flow_ids")
    def test_matched_flow_id_found(self, mock_fetch):
        """流程在订单集合中返回 '是'。"""
        mock_fetch.return_value = {"FLOW001", "FLOW002"}
        ctx = _make_mock_context()
        records = [MockRecord(flow_id="FLOW001"), MockRecord(flow_id="FLOW003")]

        import asyncio
        result = asyncio.run(check_orders_parallel(ctx, records, "2026-06-01", "2026-06-07"))

        self.assertEqual(result[0].ordered, "是")
        self.assertEqual(result[1].ordered, "否")

    @patch("core.orders_checker.fetch_ordered_flow_ids")
    def test_all_not_found(self, mock_fetch):
        """所有流程都不在订单中时全部返回 '否'。"""
        mock_fetch.return_value = set()
        ctx = _make_mock_context()
        records = [MockRecord(flow_id="FLOW001"), MockRecord(flow_id="FLOW002")]

        import asyncio
        result = asyncio.run(check_orders_parallel(ctx, records, "2026-06-01", "2026-06-07"))

        self.assertEqual(result[0].ordered, "否")
        self.assertEqual(result[1].ordered, "否")


if __name__ == "__main__":
    unittest.main()
