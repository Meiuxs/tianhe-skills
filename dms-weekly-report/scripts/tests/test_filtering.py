"""core/filtering.py 单元测试。"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.filtering import _process_table_rows
from core.dms_browser import TableProcessResult
from column_definitions import TARGET_FLOW_TYPE


def _make_page_with_rows(flow_ids_and_types: list[tuple[str, str]]) -> MagicMock:
    """构建带指定行数据的 mock page。"""
    td_locators = []
    for flow_id, flow_type in flow_ids_and_types:
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[flow_id, flow_type])
        td_locators.append(td)

    rows = []
    for td in td_locators:
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel, _td=td: _td if sel == "td" else MagicMock())
        rows.append(row)

    tbody_rows_locator = MagicMock()
    tbody_rows_locator.all = AsyncMock(return_value=rows)

    tbody_locator_first = MagicMock()
    tbody_locator_first.locator = MagicMock(return_value=tbody_rows_locator)

    table_body_locator = MagicMock()
    table_body_locator.first = tbody_locator_first

    page = MagicMock()
    page.locator = MagicMock(return_value=table_body_locator)
    return page


@pytest.mark.asyncio
class TestProcessTableRows:
    """测试 _process_table_rows 函数。"""

    async def test_batch_cell_fetch(self):
        page = _make_page_with_rows([("12345678901234567", TARGET_FLOW_TYPE)])
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert len(result.flow_ids) == 1

    async def test_skip_invalid_flow_id(self):
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["abc-invalid", TARGET_FLOW_TYPE])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        tbody = MagicMock()
        tbody.all = AsyncMock(return_value=[row])
        first = MagicMock()
        first.locator = MagicMock(return_value=tbody)
        body = MagicMock()
        body.first = first
        page = MagicMock()
        page.locator = MagicMock(return_value=body)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []
        assert result.skipped_invalid == 0

    async def test_skip_cancelled_flow(self):
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, "作废"
        ])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        tbody = MagicMock()
        tbody.all = AsyncMock(return_value=[row])
        first = MagicMock()
        first.locator = MagicMock(return_value=tbody)
        body = MagicMock()
        body.first = first
        page = MagicMock()
        page.locator = MagicMock(return_value=body)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []
        assert result.skipped_invalid == 1

    async def test_skip_duplicate_flow(self):
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, ""
        ])
        row1 = MagicMock()
        row1.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        row2 = MagicMock()
        row2.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        tbody = MagicMock()
        tbody.all = AsyncMock(return_value=[row1, row2])
        first = MagicMock()
        first.locator = MagicMock(return_value=tbody)
        body = MagicMock()
        body.first = first
        page = MagicMock()
        page.locator = MagicMock(return_value=body)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert len(result.flow_ids) == 1
        assert result.skipped_dup == 1

    async def test_skip_short_columns(self):
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["12345678901234567"])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        tbody = MagicMock()
        tbody.all = AsyncMock(return_value=[row])
        first = MagicMock()
        first.locator = MagicMock(return_value=tbody)
        body = MagicMock()
        body.first = first
        page = MagicMock()
        page.locator = MagicMock(return_value=body)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []

    async def test_skip_wrong_type(self):
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", "其他流程类型", ""
        ])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        tbody = MagicMock()
        tbody.all = AsyncMock(return_value=[row])
        first = MagicMock()
        first.locator = MagicMock(return_value=tbody)
        body = MagicMock()
        body.first = first
        page = MagicMock()
        page.locator = MagicMock(return_value=body)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []
        assert result.skipped_wrong_type == 1
