"""下单检查模块的单元测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orders_checker import (
    search_order_for_flow,
    check_single_order,
    check_orders_parallel,
    retry_async,
)


class TestSearchOrderForFlow(unittest.TestCase):
    """下单搜索功能测试。"""

    def _make_mock_page(self) -> MagicMock:
        """创建模拟页面。"""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.close = AsyncMock()
        # get_by_text 返回链式 locator
        get_by_text_result = AsyncMock()
        locator_parent = AsyncMock()
        input_first = AsyncMock()
        input_first.fill = AsyncMock()
        locator_parent.locator = MagicMock(return_value=AsyncMock())
        locator_parent.locator.return_value.first = input_first
        get_by_text_result.locator = MagicMock(return_value=locator_parent)
        page.get_by_text = MagicMock(return_value=get_by_text_result)
        page.get_by_role = MagicMock(return_value=AsyncMock())
        page.get_by_role.return_value.first.click = AsyncMock()
        # 模拟暂无数据逻辑 — 默认有数据
        no_data = AsyncMock()
        no_data.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=no_data)
        return page

    def test_order_found(self):
        """流程已下单返回 '是'。"""
        page = self._make_mock_page()
        context = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        sem = AsyncMock()

        # 模拟暂无数据不可见
        page.locator("text=暂无数据").count = AsyncMock(return_value=0)

        import asyncio
        result = asyncio.run(search_order_for_flow(context, "FLOW-001", sem))

        self.assertEqual(result, "是")

    def test_order_not_found(self):
        """流程未下单返回 '否'。"""
        page = self._make_mock_page()
        context = AsyncMock()
        context.new_page = AsyncMock(return_value=page)
        sem = AsyncMock()

        # 模拟暂无数据可见
        page.locator.return_value = AsyncMock()
        page.locator.return_value.count = AsyncMock(return_value=1)
        page.locator.return_value.first.is_visible = AsyncMock(return_value=True)

        import asyncio
        result = asyncio.run(search_order_for_flow(context, "FLOW-001", sem))

        self.assertEqual(result, "否")


class TestCheckSingleOrder(unittest.TestCase):
    """下单检查错误处理测试。"""

    def test_check_single_order_success(self):
        """检查成功时返回正确值。"""
        sem = AsyncMock()
        context = AsyncMock()

        import asyncio

        with patch("core.orders_checker.search_order_for_flow", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = "是"
            result = asyncio.run(check_single_order(context, "FLOW-001", sem))
            self.assertEqual(result, "是")


if __name__ == "__main__":
    unittest.main()
