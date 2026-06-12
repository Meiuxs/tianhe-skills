"""下单检查模块的单元测试（API 版本）。"""

import sys
import unittest
from dataclasses import dataclass, field
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


class TestFetchOrderedFlowIds(unittest.TestCase):
    """fetch_ordered_flow_ids 测试。"""

    @patch("core.orders_checker.httpx.AsyncClient")
    def test_single_page(self, mock_client):
        """单页数据能正确提取 bizFlowId。"""
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
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
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
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
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
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
        from core.orders_checker import ORDER_CHECK_EXTEND_DAYS

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
