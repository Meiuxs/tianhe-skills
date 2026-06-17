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
                "total": 3,
                "pages": 1,
            },
        })

        import asyncio
        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))
        self.assertEqual(ordered_ids, {"FLOW001", "FLOW002", "FLOW003"})
        self.assertEqual(api_total, 3)

    def test_multi_page_partial_last(self):
        """多页拉取：后端返回 pages=4，只拉第 2~4 页。"""
        import asyncio

        call_count = [0]

        async def mock_post(url, data=None, headers=None):
            call_count[0] += 1
            page_num = data.get("pageNum", 1)
            total = 1579
            pages = 4

            if page_num == 1:
                records = [{"bizFlowId": f"FLOW{i:04d}"} for i in range(1, 499 + 1)]
            elif page_num == 2:
                records = [{"bizFlowId": f"FLOW{i:04d}"} for i in range(499 + 1, 499 + 500 + 1)]
            elif page_num == 3:
                records = [{"bizFlowId": f"FLOW{i:04d}"} for i in range(999 + 1, 999 + 500 + 1)]
            elif page_num == 4:
                records = [{"bizFlowId": f"FLOW{i:04d}"} for i in range(1499 + 1, 1499 + 81 + 1)]
            else:
                raise AssertionError(f"不应请求第 {page_num} 页（后端 pages={pages}）")

            mock_resp = AsyncMock()
            mock_resp.json = AsyncMock(return_value={
                "code": 1,
                "data": {"records": records, "total": total, "pages": pages},
            })
            return mock_resp

        ctx = _make_mock_context(post_result=None)
        ctx.request.post = mock_post

        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))

        self.assertEqual(api_total, 1579)
        expected_count = 499 + 500 + 500 + 81
        self.assertEqual(len(ordered_ids), expected_count)
        for i in range(1, expected_count + 1):
            self.assertIn(f"FLOW{i:04d}", ordered_ids)
        self.assertEqual(call_count[0], 4)

    def test_empty_response(self):
        """无订单数据返回空集合。"""
        ctx = _make_mock_context(post_result={
            "code": 1,
            "data": {"records": [], "total": 0, "pages": 0},
        })

        import asyncio
        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))
        self.assertEqual(ordered_ids, set())
        self.assertEqual(api_total, 0)

    def test_api_error_code(self):
        """API 返回错误 code 时返回空集合并记录日志。"""
        ctx = _make_mock_context(post_result={
            "code": -1,
            "errMsg": "非法用户",
        })

        import asyncio
        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))
        self.assertEqual(ordered_ids, set())
        self.assertEqual(api_total, 0)

    def test_exception_returns_empty_set(self):
        """网络异常时返回空集合（不崩溃）。"""
        ctx = MagicMock()
        ctx.cookies = AsyncMock(return_value=[
            {"name": "dms_admin_token", "value": "fake-token"},
        ])
        ctx.request.post = AsyncMock(side_effect=Exception("Connection failed"))

        import asyncio
        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))
        self.assertEqual(ordered_ids, set())
        self.assertEqual(api_total, 0)

    def test_no_token_returns_empty(self):
        """无 access_token 时返回空集合。"""
        ctx = MagicMock()
        ctx.cookies = AsyncMock(return_value=[])  # 无 cookie

        import asyncio
        ordered_ids, api_total = asyncio.run(fetch_ordered_flow_ids(ctx, "2026-06-01", "2026-06-07"))
        self.assertEqual(ordered_ids, set())
        self.assertEqual(api_total, 0)

    def test_extended_end_date(self):
        """验证日期扩展逻辑正确。"""
        from datetime import datetime, timedelta
        from core.orders_checker import ORDER_CHECK_EXTEND_DAYS

        end_date = "2026-06-07"
        extended = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)).strftime("%Y-%m-%d")
        # ORDER_CHECK_EXTEND_DAYS=14，2026-06-07 + 14 = 2026-06-21
        self.assertEqual(extended, "2026-06-21")


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
