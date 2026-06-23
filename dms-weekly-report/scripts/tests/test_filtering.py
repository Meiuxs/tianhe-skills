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

    table_body_locator = MagicMock()
    table_body_locator.all = AsyncMock(return_value=rows)

    page = MagicMock()
    page.locator = MagicMock(return_value=table_body_locator)
    return page


def _make_page_with_locator(selector_rows: dict[str, list]) -> MagicMock:
    """构建按选择器返回不同行数据的 mock page。"""
    page = MagicMock()

    def locator_side_effect(selector):
        result = MagicMock()
        if selector in selector_rows:
            result.all = AsyncMock(return_value=selector_rows[selector])
        else:
            result.all = AsyncMock(return_value=[])
        return result

    page.locator = MagicMock(side_effect=locator_side_effect)
    return page


@pytest.mark.asyncio
class TestProcessTableRows:
    """测试 _process_table_rows 函数。"""

    async def test_batch_cell_fetch(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["12345678901234567", TARGET_FLOW_TYPE])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert len(result.flow_ids) == 1

    async def test_skip_invalid_flow_id(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["abc-invalid", TARGET_FLOW_TYPE])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []
        assert result.skipped_invalid == 0

    async def test_include_cancelled_flow(self):
        """默认包含作废流程，skipped_invalid 仅记录计数"""
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, "作废"
        ])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        # 默认包含作废流程
        assert result.flow_ids == ["12345678901234567"]
        assert result.skipped_invalid == 1

    async def test_skip_duplicate_flow(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, ""
        ])
        row1 = MagicMock()
        row1.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        row2 = MagicMock()
        row2.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row1, row2]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert len(result.flow_ids) == 1
        assert result.skipped_dup == 1

    async def test_skip_short_columns(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["12345678901234567"])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []

    async def test_skip_wrong_type(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", "其他流程类型", ""
        ])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        page = _make_page_with_locator({SELECTORS["table_tbody"]: [row]})
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert result.flow_ids == []
        assert result.skipped_wrong_type == 1

    async def test_fallback_to_tr(self):
        from core.dms_browser import SELECTORS
        td = MagicMock()
        td.all_text_contents = AsyncMock(return_value=["12345678901234567", TARGET_FLOW_TYPE])
        row = MagicMock()
        row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else MagicMock())
        table_body_tr = f"{SELECTORS['table_body']} tr"
        page = _make_page_with_locator({
            SELECTORS["table_tbody"]: [],
            table_body_tr: [row],
        })
        result = TableProcessResult()
        result = await _process_table_rows(page, result)
        assert len(result.flow_ids) == 1
