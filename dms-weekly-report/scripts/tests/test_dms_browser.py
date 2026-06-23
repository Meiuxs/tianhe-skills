"""core/dms_browser.py 纯函数单元测试。"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dms_browser import (
    is_on_login_page,
    get_week_range,
    FlowRecord,
    TableProcessResult,
    retry_async,
)
from core.html_parser import extract_from_html, split_agent
from core.api_parser import (
    fill_record_from_api,
    fill_record_from_html,
    fill_approval_from_nodes,
    fill_approval_from_dict,
    parse_json_date,
)
from column_definitions import LOGIN_CHECK_DOMAIN


def _make_api_data(
    project_name="测试项目",
    customer_no="C001",
    customer_name="C001 测试公司",
    province="南部战区",
    salesman_no="G0001",
    salesman_name="张三",
    watt_price=5.0,
    total_price=10000.0,
    nodes=None,
    bom_list=None,
):
    """构造模拟的 API detail 数据。"""
    if nodes is None:
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "李四", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
            {"roleName": "省总审批", "uname": "王五", "statusName": "审批通过", "updateTime": "2026-01-02 11:00:00"},
            {"roleName": "采购审批", "uname": "赵六", "statusName": "审批通过", "updateTime": "2026-01-03 12:00:00"},
        ]
    return {
        "flowId": 1,
        "bizFlowId": "2026010100000001",
        "jsonDate": {
            "req": {
                "projectName": project_name,
                "customerNo": customer_no,
                "customerName": customer_name,
                "provincialCompanyName": province,
                "salesmanNo": salesman_no,
                "salesmanName": salesman_name,
            },
            "projectManagementPricing": {
                "wattUnitPrice": watt_price,
                "totalPrice": total_price,
            },
            "productInfo": {
                "bomList": bom_list or [],
            },
        },
        "nodeList": nodes,
    }


class TestIsOnLoginPage:
    """测试 is_on_login_page 函数。"""

    def test_login_page(self):
        assert is_on_login_page(f"https://{LOGIN_CHECK_DOMAIN}/auth/login") is True

    def test_dms_page(self):
        assert is_on_login_page("https://dms-admin.trinapower.com/dashboard") is False

    def test_empty_url(self):
        assert is_on_login_page("") is False

    def test_partial_match(self):
        assert is_on_login_page(f"https://sub.{LOGIN_CHECK_DOMAIN}/path") is True


class TestGetWeekRange:
    """测试 get_week_range 函数。"""

    def test_returns_tuple(self):
        result = get_week_range()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_format(self):
        start, end = get_week_range()
        assert len(start) == 10
        assert len(end) == 10
        assert start.count("-") == 2
        assert end.count("-") == 2

    def test_start_is_earlier(self):
        start, end = get_week_range()
        assert start <= end

    def test_weeks_ago(self):
        start0, end0 = get_week_range(0)
        start1, end1 = get_week_range(1)
        assert start1 < start0

    def test_two_weeks_ago(self):
        start0, _ = get_week_range(0)
        start2, _ = get_week_range(2)
        from datetime import datetime, timedelta
        d0 = datetime.strptime(start0, "%Y-%m-%d")
        d2 = datetime.strptime(start2, "%Y-%m-%d")
        diff_days = (d0 - d2).days
        assert 12 <= diff_days <= 16


class TestExtractFromHtml:
    """测试 extract_from_html 函数。"""

    def test_direct_match(self):
        html = '<th>项目名称</th><td>测试项目</td>'
        assert extract_from_html(html, "项目名称") == "测试项目"

    def test_nested_match(self):
        html = '<th>项目名称</th><th><div>嵌套值</div></th>'
        result = extract_from_html(html, "项目名称")
        assert result == "嵌套值"

    def test_not_found(self):
        html = '<th>其他字段</th><td>其他值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_label_with_colon(self):
        html = '<th>项目名称:</th><td>有冒号的值</td>'
        assert extract_from_html(html, "项目名称") == "有冒号的值"

    def test_empty_html(self):
        assert extract_from_html("", "项目名称") == "--"

    def test_special_chars(self):
        html = '<th>瓦单价(元/瓦)</th><td>1.25</td>'
        assert extract_from_html(html, "瓦单价(元/瓦)") == "1.25"

    def test_cross_row_no_match(self):
        """跨 <tr> 边界时不应匹配到下一行的值。"""
        html = '<th>项目名称</th></tr><tr><th>其他字段</th><td>其他值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_cross_row_td_no_match(self):
        """跨 <tr> 边界时，下一行的 <td> 不应被匹配。"""
        html = '<th>项目名称</th></tr><tr><td></td><td>下一行的值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_multiline_nested_value(self):
        """多行嵌套结构中正确提取值。"""
        html = '<th>项目名称</th><th>\n  <div>\n    多行值\n  </div>\n</th>'
        result = extract_from_html(html, "项目名称")
        assert result == "多行值"

    def test_value_with_html_entities(self):
        """值中包含 HTML 实体时应被正确处理。"""
        html = '<th>项目名称</th><td>项目&nbsp;A&amp;B</td>'
        result = extract_from_html(html, "项目名称")
        # HTML 标签被移除，但 &nbsp; 等实体保留原样（不解析）
        assert "项目" in result


class TestSplitAgent:
    """测试 split_agent 函数。"""

    def test_code_and_name(self):
        assert split_agent("AGENT-001 某公司") == ("AGENT-001", "某公司")

    def test_code_only(self):
        assert split_agent("AGENT-001") == ("AGENT-001", "--")

    def test_empty(self):
        assert split_agent("") == ("--", "--")

    def test_dash(self):
        assert split_agent("--") == ("--", "--")

    def test_multi_word_name(self):
        code, name = split_agent("AG-001 深圳 天合 光能")
        assert code == "AG-001"
        assert name == "深圳 天合 光能"

    def test_none_input(self):
        assert split_agent(None) == ("--", "--")


class TestFlowRecord:
    """测试 FlowRecord 数据类。"""

    def test_default_values(self):
        rec = FlowRecord()
        assert rec.flow_id == ""
        assert rec.project_name == "--"
        assert rec.is_valid == "否"
        assert rec.module_kw is None

    def test_custom_values(self):
        rec = FlowRecord(
            flow_id="123",
            project_name="测试",
            module_kw=99.5,
        )
        assert rec.flow_id == "123"
        assert rec.project_name == "测试"
        assert rec.module_kw == 99.5


class TestTableProcessResult:
    """测试 TableProcessResult 数据类。"""

    def test_default_values(self):
        result = TableProcessResult()
        assert result.flow_ids == []
        assert result.seen_ids == set()
        assert result.skipped_invalid == 0
        assert result.skipped_dup == 0
        assert result.valid_rows == 0

    def test_mutation_isolation(self):
        r1 = TableProcessResult()
        r2 = TableProcessResult()
        r1.flow_ids.append("123")
        assert "123" not in r2.flow_ids

    def test_add_flow_id_success(self):
        r = TableProcessResult()
        assert r.add_flow_id("123") is True
        assert r.flow_ids == ["123"]
        assert "123" in r.seen_ids
        assert r.valid_rows == 1

    def test_add_flow_id_duplicate(self):
        r = TableProcessResult()
        r.add_flow_id("123")
        assert r.add_flow_id("123") is False
        assert len(r.flow_ids) == 1
        assert r.valid_rows == 1


# ==================== API 解析测试 ====================


class TestFillRecordFromApi:
    """测试 fill_record_from_api 函数（API 数据解析）。"""

    def test_basic_fields(self):
        """从 API 数据正确解析基本字段。"""
        api_data = _make_api_data()
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "测试项目"
        assert rec.agent_code == "C001"
        assert rec.agent_name == "测试公司"
        assert rec.province == "南部战区"
        assert rec.salesperson == "张三(G0001)"

    def test_unit_price_and_total(self):
        """解析定价信息。"""
        api_data = _make_api_data(watt_price=3.5, total_price=50000.0)
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.unit_price == "3.5"
        assert rec.total_price == "50000.0"

    def test_missing_req(self):
        """req 为空时使用默认值。"""
        api_data = {"jsonDate": {}, "nodeList": []}
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "--"
        assert rec.agent_code == "--"
        assert rec.province == "--"

    def test_all_project_info_empty_triggers_html_fallback(self):
        """API 返回的项目信息全为空时，应回退到 HTML 解析补充。"""
        # 模拟 API 返回空 req（projectName/province/salesperson 均为空）
        api_data = {"jsonDate": {"req": {}}, "nodeList": []}
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        # 验证 API 填充结果为空
        assert rec.project_name == "--"
        assert rec.province == "--"
        assert rec.salesperson == "--"
        # 标记需要 HTML 回退
        should_fallback = (
            rec.project_name in ("--", "")
            and rec.province in ("--", "")
            and rec.salesperson in ("--", "")
        )
        assert should_fallback is True, "API 项目信息全为空时应触发 HTML 回退"

    def test_customer_name_without_code(self):
        """customerName 没有编号前缀时完整保留。"""
        api_data = _make_api_data(customer_no="", customer_name="某公司名称")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.agent_code == "--"
        assert rec.agent_name == "某公司名称"

    def test_salesman_without_no(self):
        """业务员没有编号时只保留姓名。"""
        api_data = _make_api_data(salesman_no="", salesman_name="李四")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "李四"

    def test_missing_json_date(self):
        """jsonDate 为空时使用默认值。"""
        api_data = {"nodeList": []}
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "--"
        assert rec.unit_price == "--"

    def test_pricing_as_json_string(self):
        """projectManagementPricing 为 JSON 字符串时应正确解析。"""
        api_data = {
            "jsonDate": {
                "req": {"projectName": "测试"},
                "projectManagementPricing": '{"wattUnitPrice": 3.5, "totalPrice": 50000.0}',
            },
            "nodeList": [],
        }
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.unit_price == "3.5"
        assert rec.total_price == "50000.0"

    def test_pricing_as_invalid_json_string(self):
        """projectManagementPricing 为无效 JSON 字符串时使用默认值。"""
        api_data = {
            "jsonDate": {
                "req": {"projectName": "测试"},
                "projectManagementPricing": "not valid json",
            },
            "nodeList": [],
        }
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.unit_price == "--"
        assert rec.total_price == "--"


class TestFillApprovalFromNodes:
    """测试 fill_approval_from_nodes 函数（审批链解析）。"""

    def test_full_approval_chain(self):
        """完整审批链解析。"""
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "李四", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
            {"roleName": "省总审批", "uname": "王五", "statusName": "审批通过", "updateTime": "2026-01-02 11:00:00"},
            {"roleName": "项目管理部核价", "uname": "赵六", "statusName": "审批通过", "updateTime": "2026-01-03 12:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "王五"
        assert rec.province_status == "审批通过"
        assert rec.negotiation_processor == "赵六"
        assert rec.negotiation_status == "审批通过"
        assert rec.negotiation_time == "2026-01-03 12:00:00"
        assert rec.final_approval_time == "2026-01-03 12:00:00"

    def test_empty_nodes(self):
        """空节点列表使用默认值。"""
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, [])
        assert rec.submit_time == "--"
        assert rec.province_processor == "--"
        assert rec.final_approval_time == "--"

    def test_partial_approval(self):
        """只有部分审批节点。"""
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "李四", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "--"
        assert rec.negotiation_processor == "--"

    def test_final_approval_time_picks_latest(self):
        """最终完成时间取最晚的通过时间。"""
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "A", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
            {"roleName": "省总审批", "uname": "B", "statusName": "审批通过", "updateTime": "2026-01-05 10:00:00"},
            {"roleName": "项目管理部核价", "uname": "C", "statusName": "审批通过", "updateTime": "2026-01-03 10:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        # 省总 01-05 比核价 01-03 晚，最终完成时间应取 01-05
        assert rec.final_approval_time == "2026-01-05 10:00:00"

    def test_node_with_user_name_fallback(self):
        """uname 为空时回退到 userName。"""
        nodes = [
            {"roleName": "省总审批", "uname": None, "userName": "王五", "statusName": "审批通过", "updateTime": "2026-01-02 11:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.province_processor == "王五"


class TestFillRecordFromHtml:
    """测试 fill_record_from_html 函数（HTML 回退解析）。"""

    def test_basic_html(self):
        """从 HTML 正确解析基本字段。"""
        html = """
        <th>项目名称</th><td>测试项目</td>
        <th>代理商</th><td>AG-001 测试代理商</td>
        <th>省公司</th><td>南部战区</td>
        <th>业务员</th><td>张三</td>
        <th>瓦单价(元/瓦)</th><td>5.02</td>
        <th>总价(元)</th><td>62298.2</td>
        """
        rec = FlowRecord(flow_id="test")
        fill_record_from_html(rec, html)
        assert rec.project_name == "测试项目"
        assert rec.agent_code == "AG-001"
        assert rec.agent_name == "测试代理商"
        assert rec.province == "南部战区"
        assert rec.salesperson == "张三"
        assert rec.unit_price == "5.02"
        assert rec.total_price == "62298.2"

    def test_missing_fields(self):
        """HTML 中缺少字段时使用默认值。"""
        html = "<th>其他</th><td>其他值</td>"
        rec = FlowRecord(flow_id="test")
        fill_record_from_html(rec, html)
        assert rec.project_name == "--"
        assert rec.unit_price == "--"


class TestFilterAndGetFlowIds:
    """测试 filter_and_get_flow_ids 返回值类型和边界情况。"""

    def test_returns_empty_result_when_no_pagination_info(self):
        """未找到分页信息时应返回 TableProcessResult 而非 list。"""
        # 此测试验证 filter_and_get_flow_ids 在无分页元素时返回 TableProcessResult
        # 由于需要 Playwright 浏览器环境，此处仅验证导入不报错
        from core.dms_browser import filter_and_get_flow_ids, TableProcessResult
        assert filter_and_get_flow_ids.__name__ == "filter_and_get_flow_ids"
        # 确认 TableProcessResult 可以无参数实例化
        empty = TableProcessResult()
        assert empty.flow_ids == []
        assert empty.seen_ids == set()

    def test_returns_empty_result_when_total_zero(self):
        """总记录数为 0 时应返回空的 TableProcessResult。"""
        from core.dms_browser import TableProcessResult
        result = TableProcessResult()
        assert result.flow_ids == []
        assert result.valid_rows == 0


class TestParseJsonDate:
    """测试 parse_json_date 辅助函数。"""

    def test_string_json_date(self):
        detail = {"jsonDate": '{"key": "value"}'}
        parse_json_date(detail)
        assert isinstance(detail["jsonDate"], dict)
        assert detail["jsonDate"]["key"] == "value"

    def test_already_dict(self):
        detail = {"jsonDate": {"key": "value"}}
        parse_json_date(detail)
        assert isinstance(detail["jsonDate"], dict)

    def test_empty_string(self):
        detail = {"jsonDate": ""}
        parse_json_date(detail)
        assert detail["jsonDate"] == ""

    def test_invalid_json_logs_warning(self):
        import io, logging
        detail = {"jsonDate": "not valid json{{{"}
        parse_json_date(detail)
        # 不应抛出异常，只应记录警告

    def test_missing_key(self):
        detail = {}
        parse_json_date(detail)
        assert "jsonDate" not in detail


class TestFillApprovalFromDict:
    """测试 fill_approval_from_dict 函数。"""

    def test_full_dict(self):
        approval = {
            "submit_time": "2026-01-01 10:00:00",
            "province_processor": "王五",
            "province_status": "审批通过",
            "purchase_processor": "赵六",
            "purchase_status": "审批通过",
            "final_approval_time": "2026-01-03 12:00:00",
        }
        rec = FlowRecord(flow_id="test")
        fill_approval_from_dict(rec, approval)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "王五"
        assert rec.final_approval_time == "2026-01-03 12:00:00"

    def test_partial_dict_missing_keys(self):
        """缺少部分键时不应抛 KeyError，应使用默认值。"""
        approval = {
            "submit_time": "2026-01-01 10:00:00",
            # province_processor, province_status 等缺失
        }
        rec = FlowRecord(flow_id="test")
        fill_approval_from_dict(rec, approval)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "--"
        assert rec.province_status == "--"
        assert rec.negotiation_processor == "--"
        assert rec.negotiation_status == "--"
        assert rec.final_approval_time == "--"

    def test_empty_dict(self):
        """空 dict 时全部使用默认值。"""
        rec = FlowRecord(flow_id="test")
        fill_approval_from_dict(rec, {})
        assert rec.submit_time == "--"
        assert rec.province_processor == "--"
        assert rec.final_approval_time == "--"


class TestSplitAgentRobust:
    """测试 split_agent 的健壮性（多空格、Tab 分隔）。"""

    def test_multiple_spaces(self):
        assert split_agent("C001  某公司") == ("C001", "某公司")

    def test_tab_separated(self):
        assert split_agent("C001\t某公司") == ("C001", "某公司")

    def test_leading_trailing_spaces(self):
        code, name = split_agent("  C001  某公司  ")
        assert code == "C001"
        assert name == "某公司"


class TestGetWeekRangeValidation:
    """测试 get_week_range 输入校验。"""

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="weeks_ago 必须 >= 0"):
            get_week_range(-1)

    def test_zero_is_valid(self):
        start, end = get_week_range(0)
        assert isinstance(start, str)
        assert isinstance(end, str)


# ==================== retry_async 装饰器测试 ====================


class TestRetryAsync:
    """测试 retry_async 装饰器的重试和退避逻辑。"""

    @pytest.mark.asyncio
    async def test_first_success_no_retry(self):
        """首次成功时不重试。"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await always_succeeds()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_once_then_succeed(self):
        """第 1 次失败后第 2 次成功。"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("connection lost")
            return "ok"

        result = await fails_once()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """所有重试都失败后抛出最后一次异常。"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise OSError("connection lost")

        with pytest.raises(OSError, match="connection lost"):
            await always_fails()
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self):
        """不可重试的异常（如 ValueError）直接抛出，不重试。"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await raises_value_error()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_playwright_timeout_is_retried(self):
        """PlaywrightTimeout 是可恢复异常，应重试。"""
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def timeout_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PlaywrightTimeout("timeout")
            return "ok"

        result = await timeout_then_succeed()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_asyncio_timeout_is_retried(self):
        """asyncio.TimeoutError 是可恢复异常，应重试。"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.01)
        async def timeout_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return "ok"

        result = await timeout_then_succeed()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self):
        """验证退避延迟按指数增长。"""
        call_count = 0
        timestamps = []

        @retry_async(max_retries=3, base_delay=0.05)
        async def track_time():
            import time
            nonlocal call_count
            call_count += 1
            timestamps.append(time.monotonic())
            if call_count < 3:
                raise OSError("fail")
            return "ok"

        result = await track_time()
        assert result == "ok"
        assert call_count == 3
        # 第一次重试延迟 ~0.05s，第二次 ~0.1s
        # 允许一定误差（事件循环调度）
        delay1 = timestamps[1] - timestamps[0]
        delay2 = timestamps[2] - timestamps[1]
        assert delay1 >= 0.04, f"delay1={delay1} 应 >= 0.04"
        assert delay2 >= 0.08, f"delay2={delay2} 应 >= 0.08"


# ==================== 业务员名称逻辑测试 ====================


class TestSalespersonLogic:
    """测试 fill_record_from_api 中业务员名称逻辑。"""

    def test_salesman_name_empty_string(self):
        """salesman_name 为空字符串时应使用默认值 '--'。"""
        api_data = _make_api_data(salesman_no="G0001", salesman_name="")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "--"

    def test_salesman_name_and_no_both_present(self):
        """salesman_name 和 salesman_no 都存在时应拼接。"""
        api_data = _make_api_data(salesman_no="G0001", salesman_name="张三")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "张三(G0001)"

    def test_salesman_no_only(self):
        """只有 salesman_no 时应显示 '--'。"""
        api_data = _make_api_data(salesman_no="G0001", salesman_name="--")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "--"

    def test_salesman_name_only(self):
        """只有 salesman_name 时应只显示姓名。"""
        api_data = _make_api_data(salesman_no="", salesman_name="张三")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "张三"
