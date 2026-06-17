"""core/dms_browser.py 异步函数单元测试（Playwright mock）。"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.dms_browser  # noqa: F401 — 用于重置模块级 token 缓存
from core.dms_browser import (
    FlowRecord,
    TableProcessResult,
    get_access_token,
    do_login,
    ensure_logged_in,
    extract_all_parallel,
    filter_and_get_flow_ids,
    filter_and_get_flow_ids_via_api,
)
from core.detail_extractor import extract_detail_by_url
from core.html_parser import extract_bom
from core.detail_extractor import extract_approval_info
from core.filtering import _process_table_rows
from playwright.async_api import TimeoutError as PlaywrightTimeout

from column_definitions import DMS_URL, LOGIN_CHECK_DOMAIN, TARGET_FLOW_TYPE


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

        with patch("core.dms_browser._load_dms_credentials", return_value=("user", "pass")):
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

        # Mock API response
        api_response_data = {
            "data": {
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
        assert rec.flow_id == "20260616000000001"
        assert rec.project_name == "API项目"
        assert rec.agent_code == "C001"
        assert rec.agent_name == "某公司"
        assert rec.province == "广东"
        assert rec.salesperson == "张三(G001)"
        assert rec.unit_price == "1.5"
        assert rec.total_price == "20000.0"
        assert rec.submit_time == "2026-06-01 10:00:00"
        assert rec.province_processor == "王五"
        assert rec.province_status == "审批通过"

    async def test_api_data_empty_falls_back_to_html(self):
        """API 数据存在但项目信息为空时回退到 HTML 解析。"""
        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

        # API 返回空的 req
        api_response_data = {
            "data": {
                "bizFlowId": "20260616000000001",
                "jsonDate": {
                    "req": {},
                    "projectManagementPricing": {},
                    "productInfo": {"bomList": []},
                },
                "nodeList": [],
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

        html = """
        <th>项目名称:</th><td>HTML项目</td>
        <th>代理商:</th><td>AG-001 某公司</td>
        <th>省公司:</th><td>广东</td>
        <th>业务员:</th><td>张三</td>
        <th>瓦单价(元/瓦):</th><td>1.2</td>
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
                    rec = await extract_detail_by_url(context, "20260616000000001", sem, page=page)

        assert rec is not None
        # API 项目信息为空，应回退到 HTML 解析
        assert rec.project_name == "HTML项目"
        assert rec.province == "广东"
        assert rec.salesperson == "张三"


# ==================== _process_table_rows 批量获取测试 ====================


@pytest.mark.asyncio
class TestProcessTableRows:
    """测试 _process_table_rows 使用 all_text_contents 批量获取 cell。"""

    async def test_batch_cell_fetch(self):
        """验证 all_text_contents 被调用（而非逐个 text_content）。"""
        from core.dms_browser import _process_table_rows, TableProcessResult, SELECTORS
        from column_definitions import TARGET_FLOW_TYPE

        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=["123456789012345", TARGET_FLOW_TYPE])

        mock_row = MagicMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock(return_value=[]))

        # filtering.py 直接调用 page.locator(SELECTORS["table_tbody"]).all()
        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])

        page = MagicMock()
        page.locator = MagicMock(return_value=table_tbody_locator)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)

        # 验证 flow_id 被正确提取
        assert "123456789012345" in result.flow_ids
        # 验证 all_text_contents 被调用（批量获取，而非逐个 text_content）
        td_locator.all_text_contents.assert_called_once()


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

        async def mock_extract(ctx, fid, sem, **kwargs):
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

        async def mock_extract(ctx, fid, sem, **kwargs):
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
        assert rec.module_kw is None
        assert rec.inverter_kw is None
        assert rec.battery_kwh is None
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


# ==================== ensure_logged_in 测试 ====================


@pytest.mark.asyncio
class TestEnsureLoggedIn:
    """测试 ensure_logged_in 函数。"""

    async def test_skip_when_already_at_target_url(self):
        """已在目标页面时，不触发登录，不导航。"""
        page = make_mock_page(url=f"{DMS_URL}/#/process/process_center")
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")

        mock_login.assert_not_called()
        page.goto.assert_not_called()

    async def test_skip_when_url_contains_target(self):
        """URL 包含目标路径时（容忍 trailing slash），不导航。"""
        page = make_mock_page(url=f"{DMS_URL}/#/process/process_center/")
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")

        mock_login.assert_not_called()
        page.goto.assert_not_called()

    async def test_login_then_navigate(self):
        """在登录页面时触发登录，然后导航到目标。"""
        page = make_mock_page(url=f"https://{LOGIN_CHECK_DOMAIN}/login")
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")

        mock_login.assert_called_once_with(page)
        page.goto.assert_called_once()

    async def test_navigate_without_login(self):
        """在非登录页面但不在目标页面时，仅导航不登录。"""
        page = make_mock_page(url="https://dms-admin.trinapower.com/dashboard")
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")

        mock_login.assert_not_called()
        page.goto.assert_called_once()

    async def test_skip_detail_same_biz_flow_id(self):
        """详情页 bizFlowId 一致时跳过导航。"""
        flow_id = "20260616123456789"
        current_url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
        page = make_mock_page(url=current_url)
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            await ensure_logged_in(page, current_url)

        mock_login.assert_not_called()
        page.goto.assert_not_called()

    async def test_navigate_detail_different_biz_flow_id(self):
        """详情页 bizFlowId 不一致时应导航。"""
        flow_id = "20260616123456789"
        page = make_mock_page(
            url=f"{DMS_URL}/#/process/process_detail?bizFlowId=00000000000000000&flowStatus=1"
        )
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        with patch("core.dms_browser.do_login", new_callable=AsyncMock) as mock_login:
            target_url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
            await ensure_logged_in(page, target_url)

        mock_login.assert_not_called()
        page.goto.assert_called_once_with(target_url, timeout=30000)


# ==================== extract_bom 测试 ====================


@pytest.mark.asyncio
class TestExtractBom:
    """测试 extract_bom 函数。"""

    async def test_api_bom_data(self):
        """API BOM 数据可用时正确提取。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "M001", "materialName": "组件A", "num": 10, "unitName": "块"},
                        {"materialNo": "M002", "materialName": "逆变器B", "num": 2, "unitName": "台"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_detail_data=api_data)

        assert len(bom_items) == 2
        assert bom_items[0].code == "M001"
        assert bom_items[0].name == "组件A"
        assert bom_items[0].qty == 10
        assert bom_items[0].unit == "块"

    async def test_api_bom_empty(self):
        """API 无 BOM 数据时返回空列表。"""
        page = make_mock_page()
        bom_items = await extract_bom(page, api_detail_data={"jsonDate": {}})
        assert bom_items == []

    async def test_api_bom_none(self):
        """api_detail_data 为 None 时返回空列表。"""
        page = make_mock_page()
        bom_items = await extract_bom(page, api_detail_data=None)
        assert bom_items == []

    async def test_api_bom_duplicate_dedup(self):
        """BOM 去重：相同物料编号只保留一条。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "M001", "materialName": "组件A", "num": 10, "unitName": "块"},
                        {"materialNo": "M001", "materialName": "组件A", "num": 5, "unitName": "块"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_data)
        assert len(bom_items) == 1
        assert bom_items[0].code == "M001"

    async def test_api_bom_invalid_qty(self):
        """数量字段无效时跳过该行。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "M001", "materialName": "组件A", "num": "invalid", "unitName": "块"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_data)
        assert len(bom_items) == 0

    async def test_api_bom_missing_code(self):
        """物料编号为空时跳过。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "", "materialName": "组件A", "num": 10, "unitName": "块"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_data)
        assert bom_items == []

    async def test_api_bom_float_qty(self):
        """数量是 float 时，round() 四舍五入（而非 int() 截断）。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "M001", "materialName": "组件A", "num": 10.5, "unitName": "块"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_data)
        assert len(bom_items) == 1
        # round(10.5) = 10（Python 银行家舍入），round(10.6) = 11
        assert bom_items[0].qty == 10

    async def test_api_bom_float_qty_round_up(self):
        """float 数量 >= x.5 时 round 向上舍入。"""
        page = make_mock_page()
        api_data = {
            "jsonDate": {
                "productInfo": {
                    "bomList": [
                        {"materialNo": "M001", "materialName": "组件A", "num": 10.6, "unitName": "块"},
                    ]
                }
            }
        }
        bom_items = await extract_bom(page, api_data)
        assert len(bom_items) == 1
        assert bom_items[0].qty == 11


# ==================== extract_approval_info 测试 ====================


@pytest.mark.asyncio
class TestExtractApprovalInfo:
    """测试 extract_approval_info 函数。"""

    async def test_calls_approval_parser(self):
        """验证 extract_approval_info 调用 approval_parser 并返回其结果。"""
        page = make_mock_page()
        expected = {"submit_time": "2026-01-01", "province_processor": "王五"}

        # _extract_approval 在 extract_approval_info 内部 from core.approval_parser 导入
        # patch 导入目标（被 patch 的模块位置）
        with patch("core.approval_parser.extract_approval_info", new_callable=AsyncMock, return_value=expected):
            result = await extract_approval_info(page)
            assert result == expected


# ==================== _process_table_rows 边界场景测试 ====================


@pytest.mark.asyncio
class TestProcessTableRowsEdgeCases:
    """测试 _process_table_rows 的边界场景。"""

    async def test_skip_invalid_flow_id(self):
        """流程编号不匹配正则时跳过（不增加 skipped_invalid 计数器）。"""
        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=["abc-invalid", TARGET_FLOW_TYPE])

        mock_row = MagicMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])

        page = MagicMock()
        page.locator = MagicMock(return_value=table_tbody_locator)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)

        assert result.flow_ids == []
        # 流程编号未匹配时直接 continue，不增加 skipped_invalid
        assert result.skipped_invalid == 0
        assert result.valid_rows == 0

    async def test_skip_cancelled_flow(self):
        """作废流程被跳过。"""
        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, "作废"
        ])

        mock_row = MagicMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])

        page = MagicMock()
        page.locator = MagicMock(return_value=table_tbody_locator)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)

        assert result.flow_ids == []
        assert result.skipped_invalid == 1

    async def test_skip_duplicate_flow(self):
        """重复流程编号被跳过。"""
        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, ""
        ])

        mock_row1 = MagicMock()
        mock_row1.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())
        mock_row2 = MagicMock()
        mock_row2.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row1, mock_row2])

        page = MagicMock()
        page.locator = MagicMock(return_value=table_tbody_locator)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)

        assert len(result.flow_ids) == 1
        assert result.skipped_dup == 1

    async def test_skip_short_columns(self):
        """列数不足 2 的行被跳过。"""
        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=["12345678901234567"])

        mock_row = MagicMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])

        page = MagicMock()
        page.locator = MagicMock(return_value=table_tbody_locator)

        result = TableProcessResult()
        result = await _process_table_rows(page, result)

        assert result.flow_ids == []
        assert result.skipped_invalid == 0
        assert result.valid_rows == 0


# ==================== filter_and_get_flow_ids 测试 ====================


@pytest.mark.asyncio
class TestFilterAndGetFlowIds:
    """测试 filter_and_get_flow_ids 完整流程。"""

    async def test_no_records(self):
        """无记录时返回空 TableProcessResult。"""
        page = MagicMock()
        page.url = f"{DMS_URL}/#/process/process_center"
        page.wait_for_load_state = AsyncMock()

        total_el_mock = MagicMock()
        total_el_mock.count = AsyncMock(return_value=1)
        total_el_mock.first = total_el_mock
        total_el_mock.text_content = AsyncMock(return_value="共 0 条记录")

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[])

        def locator_side_effect(sel):
            if "共.*条记录" in sel or "text=" in sel:
                return total_el_mock
            if "el-table__body" in sel:
                return table_tbody_locator
            return MagicMock()

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.get_by_role = MagicMock(side_effect=lambda *a, **kw: AsyncMock(click=AsyncMock()))
        page.get_by_placeholder = MagicMock(side_effect=lambda *a, **kw: AsyncMock(fill=AsyncMock()))
        page.wait_for_timeout = AsyncMock()

        result = await filter_and_get_flow_ids(page, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []

    async def test_single_page(self):
        """单页记录正确处理。"""
        page = MagicMock()
        page.url = f"{DMS_URL}/#/process/process_center"
        page.wait_for_load_state = AsyncMock()

        total_el_mock = MagicMock()
        total_el_mock.count = AsyncMock(return_value=1)
        total_el_mock.first = total_el_mock
        total_el_mock.text_content = AsyncMock(return_value="共 5 条记录")

        td_locator = MagicMock()
        td_locator.all_text_contents = AsyncMock(return_value=[
            "12345678901234567", TARGET_FLOW_TYPE, "进行中"
        ])

        mock_row = MagicMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else MagicMock())

        table_tbody_locator = MagicMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])

        def locator_side_effect(sel):
            if "共.*条记录" in sel or "text=" in sel:
                return total_el_mock
            if "el-table__body" in sel:
                return table_tbody_locator
            return MagicMock()

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.get_by_role = MagicMock(side_effect=lambda *a, **kw: AsyncMock(click=AsyncMock()))
        page.get_by_placeholder = MagicMock(side_effect=lambda *a, **kw: AsyncMock(fill=AsyncMock()))
        page.wait_for_timeout = AsyncMock()

        result = await filter_and_get_flow_ids(page, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert "12345678901234567" in result.flow_ids

    async def test_pagination_failure(self):
        """翻页失败时终止并返回已收集结果。"""
        # 验证 TableProcessResult 可无参数实例化
        empty = TableProcessResult()
        assert isinstance(empty, TableProcessResult)

    async def test_multi_page_pagination(self):
        """多页翻页：两页数据正确合并。"""
        page = AsyncMock()
        page.url = f"{DMS_URL}/#/process/process_center"
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        # 总记录 15 条，每页 10 条 → 需要 2 页
        total_el_mock = AsyncMock()
        total_el_mock.count = AsyncMock(return_value=1)
        total_el_mock.first = total_el_mock
        total_el_mock.text_content = AsyncMock(return_value="共 15 条记录")

        # 翻页按钮
        page_2_btn = AsyncMock()
        pagination_locator = MagicMock()
        pagination_locator.get_by_text = MagicMock(return_value=page_2_btn)

        # 用 side_effect 来区分翻页前后的 locator 调用
        # 第 1 次调用 locator("table.el-table__body tbody") → 第 1 页数据
        # 翻页后再次调用 → 第 2 页数据
        page_call_count = {"table_tbody": 0}

        def make_table_tbody_locator(flow_id):
            """为指定 flow_id 创建 table_tbody mock（直接有 .all() 和 .first.wait_for()）。"""
            td = AsyncMock()
            td.all_text_contents = AsyncMock(return_value=[flow_id, TARGET_FLOW_TYPE, "进行中"])

            row = AsyncMock()
            row.locator = MagicMock(side_effect=lambda sel: td if sel == "td" else AsyncMock(return_value=[]))

            rows_locator = AsyncMock()
            rows_locator.all = AsyncMock(return_value=[row])

            tbody_first = AsyncMock()
            tbody_first.wait_for = AsyncMock()

            body = AsyncMock()
            body.all = AsyncMock(return_value=[row])
            body.first = tbody_first
            return body

        tb1 = make_table_tbody_locator("20260616000000001")
        tb2 = make_table_tbody_locator("20260616000000002")

        def locator_side_effect(sel):
            if "共.*条记录" in sel or "text=" in sel:
                return total_el_mock
            if "el-pager" in sel:
                return pagination_locator
            if "el-table__body" in sel:
                page_call_count["table_tbody"] += 1
                if page_call_count["table_tbody"] <= 1:
                    return tb1
                return tb2
            return AsyncMock()

        page.locator = MagicMock(side_effect=locator_side_effect)

        mock_menu_item = AsyncMock()
        mock_menu_item.click = AsyncMock()
        page.get_by_role = MagicMock(return_value=mock_menu_item)

        mock_input = AsyncMock()
        mock_input.click = AsyncMock()
        mock_input.press = AsyncMock()
        mock_input.fill = AsyncMock()
        page.get_by_placeholder = MagicMock(return_value=mock_input)

        result = await filter_and_get_flow_ids(page, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert "20260616000000001" in result.flow_ids
        assert "20260616000000002" in result.flow_ids
        # 验证翻页按钮被点击
        pagination_locator.get_by_text.assert_called_with("2", exact=True)
        page_2_btn.click.assert_called_once()

    async def test_pagination_timeout_breaks_loop(self):
        """翻页超时时终止循环并返回已收集结果。"""
        page = AsyncMock()
        page.url = f"{DMS_URL}/#/process/process_center"
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        total_el_mock = AsyncMock()
        total_el_mock.count = AsyncMock(return_value=1)
        total_el_mock.first = total_el_mock
        total_el_mock.text_content = AsyncMock(return_value="共 25 条记录")

        td_locator = AsyncMock()
        td_locator.all_text_contents = AsyncMock(return_value=[
            "20260616000000001", TARGET_FLOW_TYPE, "进行中"
        ])

        mock_row = AsyncMock()
        mock_row.locator = MagicMock(side_effect=lambda sel: td_locator if sel == "td" else AsyncMock(return_value=[]))

        table_tbody_locator = AsyncMock()
        table_tbody_locator.all = AsyncMock(return_value=[mock_row])
        table_tbody_locator.first = AsyncMock()
        table_tbody_locator.first.wait_for = AsyncMock()

        # 翻页按钮点击时抛出超时
        page_2_btn = AsyncMock()
        page_2_btn.click = AsyncMock(side_effect=PlaywrightTimeout("page navigation timeout"))
        pagination_locator = MagicMock()
        pagination_locator.get_by_text = MagicMock(return_value=page_2_btn)

        def locator_side_effect(sel):
            if "共.*条记录" in sel or "text=" in sel:
                return total_el_mock
            if "el-pager" in sel:
                return pagination_locator
            if "el-table__body" in sel:
                return table_tbody_locator
            return AsyncMock()

        page.locator = MagicMock(side_effect=locator_side_effect)

        mock_menu_item = AsyncMock()
        mock_menu_item.click = AsyncMock()
        page.get_by_role = MagicMock(return_value=mock_menu_item)

        mock_input = AsyncMock()
        mock_input.click = AsyncMock()
        mock_input.press = AsyncMock()
        mock_input.fill = AsyncMock()
        page.get_by_placeholder = MagicMock(return_value=mock_input)

        result = await filter_and_get_flow_ids(page, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        # 第 1 页的数据应该被保留
        assert "20260616000000001" in result.flow_ids


# ==================== filter_and_get_flow_ids_via_api 测试 ====================


@pytest.mark.asyncio
class TestFilterAndGetFlowIdsViaApi:
    """测试 filter_and_get_flow_ids_via_api 函数（API 筛选方案）。"""

    async def _make_mock_context(self, response_data=None, status=200):
        """创建带 mock request 的 BrowserContext。"""
        context = AsyncMock()
        context.cookies = AsyncMock(return_value=[
            {"name": "dms_admin_token", "value": "test_token_123"}
        ])

        if response_data is None:
            response_data = {
                "code": 1,
                "data": {
                    "total": 2,
                    "records": [
                        {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                        {"bizFlowId": "20260616000000002", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                    ],
                }
            }

        mock_resp = AsyncMock()
        mock_resp.ok = 200 <= status < 400
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=response_data)

        context.request = MagicMock()
        context.request.post = AsyncMock(return_value=mock_resp)
        return context, mock_resp

    async def test_basic_pagination(self):
        """基本分页：两页数据正确合并。"""
        # 第 1 页返回满页（500 条，API_FILTER_PAGE_SIZE）才能触发翻页
        page1_rows = [
            {"bizFlowId": f"20260616000000{i:04d}", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"}
            for i in range(1, 501)
        ]
        page1_data = {
            "code": 1,
            "data": {
                "total": 502,
                "records": page1_rows,
            }
        }
        page2_data = {
            "code": 1,
            "data": {
                "total": 502,
                "records": [
                    {"bizFlowId": "202606160000000501", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                    {"bizFlowId": "202606160000000502", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                ],
            }
        }

        context = AsyncMock()
        context.cookies = AsyncMock(return_value=[
            {"name": "dms_admin_token", "value": "test_token_123"}
        ])

        mock_resp_page1 = AsyncMock()
        mock_resp_page1.ok = True
        mock_resp_page1.status = 200
        mock_resp_page1.json = AsyncMock(return_value=page1_data)

        mock_resp_page2 = AsyncMock()
        mock_resp_page2.ok = True
        mock_resp_page2.status = 200
        mock_resp_page2.json = AsyncMock(return_value=page2_data)

        context.request = MagicMock()
        context.request.post = AsyncMock(side_effect=[mock_resp_page1, mock_resp_page2])

        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert len(result.flow_ids) == 502
        assert "202606160000000001" in result.flow_ids
        assert "202606160000000502" in result.flow_ids
        assert context.request.post.call_count == 2

    async def test_skip_wrong_type(self):
        """跳过非目标流程类型。"""
        data = {
            "code": 1,
            "data": {
                "total": 3,
                "records": [
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                    {"bizFlowId": "20260616000000002", "flowName": "其他流程", "statusName": "进行中"},
                    {"bizFlowId": "20260616000000003", "flowName": "户用小型工商业询价流程", "statusName": "作废"},
                ],
            }
        }
        context, _ = await self._make_mock_context(data)
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert len(result.flow_ids) == 1
        assert "20260616000000001" in result.flow_ids
        assert result.skipped_wrong_type == 1
        assert result.skipped_invalid == 1

    async def test_skip_invalid_flow_id(self):
        """流程编号不是至少 15 位数字时跳过。"""
        data = {
            "code": 1,
            "data": {
                "total": 3,
                "records": [
                    {"bizFlowId": "12345", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                    {"bizFlowId": "abc", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                    {"bizFlowId": "", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                ],
            }
        }
        context, _ = await self._make_mock_context(data)
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert len(result.flow_ids) == 1
        assert "20260616000000001" in result.flow_ids

    async def test_api_returns_not_ok(self):
        """API 返回非 200 状态码时终止循环。"""
        context, mock_resp = await self._make_mock_context(status=500)
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []
        # 只调用了一次就 break
        assert context.request.post.call_count == 1

    async def test_api_malformed_response(self):
        """API 响应格式异常时终止循环。"""
        context, _ = await self._make_mock_context(response_data={"code": 1, "data": "unexpected"})
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []

    async def test_api_exception_during_request(self):
        """API 请求抛异常时终止循环。"""
        context = AsyncMock()
        context.cookies = AsyncMock(return_value=[
            {"name": "dms_admin_token", "value": "test_token_123"}
        ])
        context.request = MagicMock()
        context.request.post = AsyncMock(side_effect=Exception("Network error"))

        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []

    async def test_dedup_within_api(self):
        """API 返回重复流程编号时去重。"""
        data = {
            "code": 1,
            "data": {
                "total": 3,
                "records": [
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                ],
            }
        }
        context, _ = await self._make_mock_context(data)
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert len(result.flow_ids) == 1
        assert result.skipped_dup == 1

    async def test_empty_rows(self):
        """API 返回空 records 时终止循环。"""
        context, _ = await self._make_mock_context(response_data={"code": 1, "data": {"total": 0, "records": []}})
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []
        assert context.request.post.call_count == 1

    async def test_headers_contain_authorization(self):
        """请求头应包含 bearer token。"""
        data = {
            "code": 1,
            "data": {
                "total": 1,
                "records": [
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                ],
            }
        }
        context, _ = await self._make_mock_context(data)
        await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        call_kwargs = context.request.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers is not None
        assert "Authorization" in headers
        assert "bearer test_token_123" in headers["Authorization"]

    async def test_no_token_returns_none_headers(self):
        """未登录时 headers 为 None，不发起 API 请求。"""
        # 重置模块级 token 缓存，确保测试独立
        import core.dms_browser as _mod
        _mod._cached_token = None

        context = AsyncMock()
        context.cookies = AsyncMock(return_value=[])
        context.request = MagicMock()
        mock_resp = AsyncMock()
        mock_resp.ok = True
        mock_resp.json = AsyncMock(return_value={"data": {"total": 0, "records": []}})
        context.request.post = AsyncMock(return_value=mock_resp)

        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert isinstance(result, TableProcessResult)
        assert result.flow_ids == []
        # 无 token 时应直接返回，不发起 API 请求
        context.request.post.assert_not_called()

    async def test_flow_id_field_names(self):
        """兼容 bizFlowId 和 flowId 两种字段名。"""
        data = {
            "code": 1,
            "data": {
                "total": 2,
                "records": [
                    {"bizFlowId": "20260616000000001", "flowName": "户用小型工商业询价流程", "statusName": "审批通过"},
                    {"flowId": "20260616000000002", "flowName": "户用小型工商业询价流程", "statusName": "进行中"},
                ],
            }
        }
        context, _ = await self._make_mock_context(data)
        result = await filter_and_get_flow_ids_via_api(context, "2026-06-01", "2026-06-15")

        assert len(result.flow_ids) == 2


# ==================== remove_listener 异常捕获测试 ====================


@pytest.mark.asyncio
class TestRemoveListenerException:
    """测试 _capture_detail_api 中 remove_listener 的异常捕获。"""

    async def test_remove_listener_after_page_close(self):
        """页面关闭后 remove_listener 不应抛出异常。"""
        from playwright._impl._errors import TargetClosedError

        context = make_mock_context()
        page = make_mock_page()
        context.new_page = AsyncMock(return_value=page)

        # 模拟 API 响应
        api_response_data = {
            "data": {
                "jsonDate": {
                    "req": {"projectName": "测试"},
                    "projectManagementPricing": {"wattUnitPrice": 1.0, "totalPrice": 100.0},
                    "productInfo": {"bomList": []},
                },
                "nodeList": [],
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

        # 模拟 remove_listener 抛出 TargetClosedError
        async def remove_listener_side_effect(event, handler):
            raise TargetClosedError("Page closed")

        page.remove_listener = AsyncMock(side_effect=remove_listener_side_effect)

        sem = asyncio.Semaphore(5)

        with patch("core.dms_browser._load_dms_credentials", return_value=("user", "pass")):
            with patch("core.html_parser.extract_bom", return_value=[]):
                rec = await extract_detail_by_url(context, "20260616000000001", sem, page=page)

        # 即使 remove_listener 抛出异常，提取仍应成功
        assert rec is not None
        assert rec.project_name == "测试"


# ==================== extract_all_parallel 错误统计测试 ====================


@pytest.mark.asyncio
class TestExtractAllParallelErrorStats:
    """测试 extract_all_parallel 的错误统计。"""

    async def test_error_count_in_logs(self):
        """验证错误任务被正确统计。"""
        context = make_mock_context()

        async def mock_extract(ctx, fid, sem, **kwargs):
            if fid == "11111111111111111":
                raise Exception("Unexpected error")
            return FlowRecord(flow_id=fid)

        with patch("core.dms_browser.extract_detail_by_url", side_effect=mock_extract):
            with patch("core.dms_browser.logger") as mock_logger:
                records = await extract_all_parallel(
                    context, ["11111111111111111", "22222222222222222"], workers=2
                )

        # 验证成功记录数
        assert len(records) == 1
        assert records[0].flow_id == "22222222222222222"

        # 验证日志中包含错误统计
        # 查找包含 "提取完成" 的日志调用
        info_calls = [call for call in mock_logger.info.call_args_list]
        completion_log = None
        for call in info_calls:
            if len(call.args) > 0 and "提取完成" in str(call.args[0]):
                completion_log = call
                break

        assert completion_log is not None
        # 日志格式应包含错误计数
        log_format = str(completion_log.args[0])
        log_args = completion_log.args[1:]
        # 检查格式化后的消息是否包含错误计数
        formatted_message = log_format % log_args
        assert "1 条异常" in formatted_message
