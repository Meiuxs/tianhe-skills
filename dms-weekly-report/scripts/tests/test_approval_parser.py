"""审批链解析模块的单元测试。"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.approval_parser import extract_approval_info


def _await_result(coro):
    """辅助函数：等待异步函数执行完成。"""
    return asyncio.run(coro)


class TestExtractApprovalInfo(unittest.TestCase):
    """审批链解析测试。"""

    def _make_cell_mock(self, text: str) -> MagicMock:
        """创建模拟的单元格。"""
        cell = AsyncMock()
        cell.text_content = AsyncMock(return_value=text)
        return cell

    def _make_row_with_cells(self, texts: list[str]) -> MagicMock:
        """创建包含多个单元格的模拟行。"""
        row = AsyncMock()
        cells = [self._make_cell_mock(t) for t in texts]
        row.locator = MagicMock(return_value=AsyncMock())
        row.locator.return_value.all = AsyncMock(return_value=cells)
        return row

    def _make_table_with_approval_rows(self, rows_data: list[list[str]]) -> AsyncMock:
        """创建一个包含审批节点的模拟表格。"""
        table = AsyncMock()
        # thead mock — 返回 "审批节点"
        thead = AsyncMock()
        thead.count = AsyncMock(return_value=1)
        thead.text_content = AsyncMock(return_value="审批节点")

        # body table mock
        body_table = AsyncMock()
        body_table.count = AsyncMock(return_value=1)
        rows = [self._make_row_with_cells(r) for r in rows_data]
        body_table.locator = MagicMock(return_value=AsyncMock())
        body_table.locator.return_value.all = AsyncMock(return_value=rows)

        def _side_effect(sel: str):
            if "thead" in sel:
                return thead
            if ".//tbody" in sel:
                return body_table
            return AsyncMock()

        table.locator = MagicMock(side_effect=_side_effect)
        return table

    def _make_page_with_tables(self, tables: list) -> AsyncMock:
        """创建包含多个表格的模拟 page。"""
        page = AsyncMock()
        page.locator = MagicMock(return_value=AsyncMock())
        page.locator.return_value.all = AsyncMock(return_value=tables)
        return page

    def test_basic_extraction(self):
        """基础提取流程发起人、省总、采购审批信息。"""
        table = self._make_table_with_approval_rows([
            ["流程发起人", "张三", "提交审核", "2026-06-01 10:00"],
            ["省总审批", "李四", "已批准", "2026-06-02 14:00"],
            ["采购审批", "王五", "已批准通过", "2026-06-03 15:30"],
        ])
        page = self._make_page_with_tables([table])

        result = _await_result(extract_approval_info(page))

        self.assertEqual(result["submit_time"], "2026-06-01 10:00")
        self.assertEqual(result["province_processor"], "李四")
        self.assertEqual(result["province_status"], "已批准")
        self.assertEqual(result["purchase_processor"], "王五")
        self.assertEqual(result["purchase_status"], "已批准通过")
        self.assertEqual(result["final_approval_time"], "2026-06-03 15:30")

    def test_returns_defaults_on_no_table(self):
        """无审批表时返回默认值。"""
        page = self._make_page_with_tables([])

        result = _await_result(extract_approval_info(page))

        self.assertEqual(result["submit_time"], "--")
        self.assertEqual(result["province_processor"], "--")
        self.assertEqual(result["purchase_processor"], "--")

    def test_missing_cells(self):
        """行不足 4 个单元格时应该跳过。"""
        table = self._make_table_with_approval_rows([
            ["流程发起人", "张三"],  # 只有 2 个单元格，应跳过
        ])
        page = self._make_page_with_tables([table])

        result = _await_result(extract_approval_info(page))
        self.assertEqual(result["submit_time"], "--")

    def test_final_approval_time_picks_latest(self):
        """最终审批时间取最晚的通过时间。"""
        table = self._make_table_with_approval_rows([
            ["流程发起人", "张三", "提交审核", "2026-06-01 10:00"],
            ["省总审批", "李四", "已批准通过", "2026-06-02 14:00"],
            ["采购审批", "王五", "已批准通过", "2026-06-05 09:00"],
        ])
        page = self._make_page_with_tables([table])

        result = _await_result(extract_approval_info(page))
        self.assertEqual(result["final_approval_time"], "2026-06-05 09:00")

    def test_only_procurement_approval(self):
        """仅有采购审批节点时应正确提取。"""
        table = self._make_table_with_approval_rows([
            ["流程发起人", "张三", "提交审核", "2026-06-01 10:00"],
            ["采购审批", "王五", "已批准通过", "2026-06-05 09:00"],
        ])
        page = self._make_page_with_tables([table])

        result = _await_result(extract_approval_info(page))
        self.assertEqual(result["submit_time"], "2026-06-01 10:00")
        self.assertEqual(result["purchase_processor"], "王五")
        self.assertEqual(result["purchase_status"], "已批准通过")
        self.assertEqual(result["province_processor"], "--")


if __name__ == "__main__":
    unittest.main()
