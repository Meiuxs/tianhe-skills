"""core/detail_extractor.py 单元测试。"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.detail_extractor import extract_detail_by_url, extract_approval_info
from core.dms_browser import FlowRecord
from column_definitions import DMS_URL


def make_mock_page(url="https://dms-admin.trinapower.com/dashboard"):
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.content = AsyncMock(return_value="<html></html>")
    page.close = AsyncMock()
    return page


def make_mock_context():
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=make_mock_page())
    context.cookies = AsyncMock(return_value=[
        {"name": "dms_admin_token", "value": "test_token_123"}
    ])
    return context


@pytest.mark.asyncio
class TestExtractApprovalInfo:
    async def test_calls_approval_parser(self):
        page = make_mock_page()
        expected = {"submit_time": "2026-01-01", "province_processor": "王五"}

        with patch("core.approval_parser.extract_approval_info", new_callable=AsyncMock, return_value=expected):
            result = await extract_approval_info(page)
            assert result == expected


@pytest.mark.asyncio
class TestExtractDetailByUrl:
    async def test_successful_extraction(self):
        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

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

        with patch("core.dms_browser._load_dms_credentials", return_value=("user", "pass")):
            with patch("core.html_parser.extract_bom", return_value=[]):
                with patch("core.detail_extractor.extract_approval_info", return_value={
                    "submit_time": "2026-06-01",
                    "province_processor": "--",
                    "province_status": "--",
                    "purchase_processor": "--",
                    "purchase_status": "--",
                    "final_approval_time": "--",
                }):
                    rec = await extract_detail_by_url(context, "12345678901234567", sem, page=page)

        assert rec is not None
        assert rec.flow_id == "12345678901234567"
        assert rec.project_name == "测试项目"
        assert rec.province == "广东"

    async def test_returns_none_on_network_error(self):
        context = make_mock_context()
        page = make_mock_page()
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        context.new_page = AsyncMock(return_value=page)

        sem = asyncio.Semaphore(5)
        rec = await extract_detail_by_url(context, "12345678901234567", sem, page=page)
        assert rec is None

    async def test_api_data_path(self):
        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

        api_response_data = {
            "data": {
                "bizFlowId": "20260616000000001",
                "jsonDate": {
                    "req": {
                        "projectName": "API项目",
                        "customerNo": "C001",
                        "customerName": "C001 某公司",
                        "provincialCompanyName": "广东",
                        "salesmanNo": "G001",
                        "salesmanName": "张三",
                    },
                    "projectManagementPricing": {
                        "wattUnitPrice": 1.5,
                        "totalPrice": 20000.0,
                    },
                    "productInfo": {"bomList": []},
                },
                "nodeList": [
                    {"roleName": "流程发起人提交审核", "uname": "李四", "statusName": "提交审核", "updateTime": "2026-06-01 10:00:00"},
                    {"roleName": "省总审批", "uname": "王五", "statusName": "审批通过", "updateTime": "2026-06-02 11:00:00"},
                ],
            }
        }

        mock_resp = AsyncMock()
        mock_resp.url = f"{DMS_URL}/api/newFlow/flowDetails"
        mock_resp.json = AsyncMock(return_value=api_response_data)

        captured_handlers = []

        def capture_on(event, handler):
            if event == "response":
                captured_handlers.append(handler)

        page.on = capture_on

        async def goto_and_trigger(url, **kwargs):
            for handler in captured_handlers:
                await handler(mock_resp)

        page.goto = AsyncMock(side_effect=goto_and_trigger)

        sem = asyncio.Semaphore(5)

        with patch("core.dms_browser._load_dms_credentials", return_value=("user", "pass")):
            with patch("core.html_parser.extract_bom", return_value=[]):
                rec = await extract_detail_by_url(context, "20260616000000001", sem, page=page)

        assert rec is not None
        assert rec.project_name == "API项目"
        assert rec.agent_code == "C001"
        assert rec.salesperson == "张三(G001)"
        assert rec.submit_time == "2026-06-01 10:00:00"
