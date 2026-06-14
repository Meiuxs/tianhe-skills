"""core/dms_browser.py 异步函数单元测试（Playwright mock）。"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dms_browser import (
    FlowRecord,
    TableProcessResult,
    get_access_token,
    do_login,
    extract_detail_by_url,
    extract_all_parallel,
)
from column_definitions import DMS_URL, LOGIN_CHECK_DOMAIN


# ==================== Mock 工具 ====================


def make_mock_page(url="https://dms-admin.trinapower.com/dashboard"):
    """创建模拟的 Playwright Page 对象。"""
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.content = AsyncMock(return_value="<html></html>")
    page.close = AsyncMock()
    return page


def make_mock_context():
    """创建模拟的 Playwright BrowserContext 对象。"""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=make_mock_page())
    context.cookies = AsyncMock(return_value=[
        {"name": "dms_admin_token", "value": "test_token_123"}
    ])
    return context


# ==================== get_access_token 测试 ====================


@pytest.mark.asyncio
class TestGetAccessToken:
    """测试 get_access_token 函数。"""

    async def test_token_found(self):
        context = make_mock_context()
        token = await get_access_token(context)
        assert token == "test_token_123"

    async def test_token_not_found(self):
        context = make_mock_context()
        context.cookies = AsyncMock(return_value=[])
        token = await get_access_token(context)
        assert token is None

    async def test_wrong_token_name(self):
        context = make_mock_context()
        context.cookies = AsyncMock(return_value=[
            {"name": "other_token", "value": "value"}
        ])
        token = await get_access_token(context)
        assert token is None


# ==================== do_login 测试 ====================


@pytest.mark.asyncio
class TestDoLogin:
    """测试 do_login 函数。"""

    async def test_successful_login(self):
        page = make_mock_page()
        page.wait_for_selector = AsyncMock()

        # 创建 mock locator chain
        mock_locator = AsyncMock()
        mock_locator.fill = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        # 创建 mock button
        mock_button = AsyncMock()
        mock_button.click = AsyncMock()
        page.get_by_role = MagicMock(return_value=mock_button)

        page.wait_for_url = AsyncMock()

        with patch("core.dms_browser._get_credentials", return_value=("user", "pass")):
            await do_login(page)

        # 验证填写了用户名和密码
        assert mock_locator.fill.call_count == 2
        # 验证点击了登录按钮
        mock_button.click.assert_called_once()


# ==================== extract_detail_by_url 测试 ====================


@pytest.mark.asyncio
class TestExtractDetailByUrl:
    """测试 extract_detail_by_url 函数。"""

    async def test_successful_extraction(self):
        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

        # Mock HTML content with fields
        html = """
        <th>项目名称:</th><td>测试项目</td>
        <th>代理商:</th><td>AGENT-001 某公司</td>
        <th>省公司:</th><td>广东</td>
        <th>业务员:</th><td>张三</td>
        <th>瓦单价(元/瓦):</th><td>1.2</th>
        <th>总价(元):</th><td>10000</td>
        """
        page.content = AsyncMock(return_value=html)
        page.locator.return_value.all = AsyncMock(return_value=[])

        sem = asyncio.Semaphore(5)

        with patch("core.dms_browser._get_credentials", return_value=("user", "pass")):
            with patch("core.dms_browser._extract_bom", return_value=[]):
                with patch("core.dms_browser._extract_approval_info", return_value={
                    "submit_time": "2026-06-01",
                    "province_processor": "--",
                    "province_status": "--",
                    "purchase_processor": "--",
                    "purchase_status": "--",
                    "final_approval_time": "--",
                }):
                    rec = await extract_detail_by_url(context, "12345678901234567", sem)

        assert rec is not None
        assert rec.flow_id == "12345678901234567"
        assert rec.project_name == "测试项目"
        assert rec.province == "广东"
        assert rec.salesperson == "张三"
        assert rec.unit_price == "1.2"
        assert rec.total_price == "10000"

    async def test_returns_none_on_network_error(self):
        context = make_mock_context()
        page = make_mock_page()
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        context.new_page = AsyncMock(return_value=page)

        sem = asyncio.Semaphore(5)
        rec = await extract_detail_by_url(context, "12345678901234567", sem)
        assert rec is None

    async def test_page_closed_after_extraction(self):
        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

        page.content = AsyncMock(return_value="<html></html>")
        page.locator.return_value.all = AsyncMock(return_value=[])

        sem = asyncio.Semaphore(5)

        with patch("core.dms_browser._get_credentials", return_value=("user", "pass")):
            with patch("core.dms_browser._extract_bom", return_value=[]):
                with patch("core.dms_browser._extract_approval_info", return_value={
                    "submit_time": "--",
                    "province_processor": "--",
                    "province_status": "--",
                    "purchase_processor": "--",
                    "purchase_status": "--",
                    "final_approval_time": "--",
                }):
                    await extract_detail_by_url(context, "12345678901234567", sem)

        # 验证页面最终被关闭
        page.close.assert_called_once()


# ==================== extract_all_parallel 测试 ====================


@pytest.mark.asyncio
class TestExtractAllParallel:
    """测试 extract_all_parallel 函数。"""

    async def test_empty_flow_ids(self):
        context = make_mock_context()
        records = await extract_all_parallel(context, [], workers=3)
        assert records == []

    async def test_all_success(self):
        context = make_mock_context()
        mock_rec = FlowRecord(flow_id="12345678901234567")

        with patch("core.dms_browser.extract_detail_by_url", return_value=mock_rec):
            records = await extract_all_parallel(
                context, ["12345678901234567"], workers=1
            )

        assert len(records) == 1
        assert records[0].flow_id == "12345678901234567"

    async def test_partial_failure(self):
        context = make_mock_context()
        mock_rec = FlowRecord(flow_id="11111111111111111")

        async def mock_extract(ctx, fid, sem):
            if fid == "11111111111111111":
                return mock_rec
            return None

        with patch("core.dms_browser.extract_detail_by_url", side_effect=mock_extract):
            records = await extract_all_parallel(
                context, ["11111111111111111", "22222222222222222"], workers=2
            )

        assert len(records) == 1
        assert records[0].flow_id == "11111111111111111"

    async def test_exception_in_task(self):
        context = make_mock_context()

        async def mock_extract(ctx, fid, sem):
            if fid == "11111111111111111":
                raise Exception("Unexpected error")
            return FlowRecord(flow_id=fid)

        with patch("core.dms_browser.extract_detail_by_url", side_effect=mock_extract):
            records = await extract_all_parallel(
                context, ["11111111111111111", "22222222222222222"], workers=2
            )

        # 异常的被跳过，正常的被保留
        assert len(records) == 1
        assert records[0].flow_id == "22222222222222222"


# ==================== FlowRecord 数据类测试 ====================


class TestFlowRecordExtended:
    """扩展的 FlowRecord 测试。"""

    def test_all_default_values(self):
        rec = FlowRecord()
        assert rec.flow_id == ""
        assert rec.project_name == "--"
        assert rec.agent_code == "--"
        assert rec.agent_name == "--"
        assert rec.province == "--"
        assert rec.salesperson == "--"
        assert rec.module_kw == 0.0
        assert rec.inverter_kw == 0.0
        assert rec.battery_kwh == 0.0
        assert rec.unit_price == "--"
        assert rec.total_price == "--"
        assert rec.submit_time == "--"
        assert rec.remark == "无"
        assert rec.ordered == "否"
        assert rec.province_processor == "--"
        assert rec.province_status == "--"
        assert rec.purchase_processor == "--"
        assert rec.purchase_status == "--"
        assert rec.final_approval_time == "--"

    def test_custom_values(self):
        rec = FlowRecord(
            flow_id="123",
            project_name="测试项目",
            module_kw=99.5,
            inverter_kw=80.0,
            battery_kwh=50.0,
        )
        assert rec.flow_id == "123"
        assert rec.project_name == "测试项目"
        assert rec.module_kw == 99.5
        assert rec.inverter_kw == 80.0
        assert rec.battery_kwh == 50.0

    def test_has_all_attributes(self):
        rec = FlowRecord(flow_id="456")
        assert hasattr(rec, 'flow_id')
        assert hasattr(rec, 'project_name')
