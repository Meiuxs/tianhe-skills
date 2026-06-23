"""core/api_parser.py 单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.api_parser import (
    parse_json_date,
    mask_salesperson,
    fill_record_from_api,
    fill_approval_from_nodes,
    fill_record_from_html,
    fill_approval_from_dict,
)
from core.dms_browser import FlowRecord


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


class TestParseJsonDate:
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
        detail = {"jsonDate": "not valid json{{{"}
        parse_json_date(detail)

    def test_missing_key(self):
        detail = {}
        parse_json_date(detail)
        assert "jsonDate" not in detail


class TestMaskSalesperson:
    """测试 mask_salesperson 函数（原代码无独立测试，新增覆盖）。"""

    def test_normal_with_id(self):
        assert mask_salesperson("张三(G0001)") == "张***(0001)"

    def test_long_id(self):
        assert mask_salesperson("张三(G00001)") == "张***(0001)"

    def test_short_id(self):
        assert mask_salesperson("张三(G01)") == "张***(G01)"

    def test_no_parentheses(self):
        assert mask_salesperson("张三") == "张***"

    def test_single_char(self):
        assert mask_salesperson("张") == "张"

    def test_empty(self):
        assert mask_salesperson("") == "--"

    def test_dash(self):
        assert mask_salesperson("--") == "--"

    def test_none_like(self):
        assert mask_salesperson(None) == "--"


class TestFillRecordFromApi:
    def test_basic_fields(self):
        api_data = _make_api_data()
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "测试项目"
        assert rec.agent_code == "C001"
        assert rec.agent_name == "测试公司"
        assert rec.province == "南部战区"
        assert rec.salesperson == "张三(G0001)"

    def test_unit_price_and_total(self):
        api_data = _make_api_data(watt_price=3.5, total_price=50000.0)
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.unit_price == "3.5"
        assert rec.total_price == "50000.0"

    def test_missing_req(self):
        api_data = {"jsonDate": {}, "nodeList": []}
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "--"

    def test_customer_name_without_code(self):
        api_data = _make_api_data(customer_no="", customer_name="某公司名称")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.agent_code == "--"
        assert rec.agent_name == "某公司名称"

    def test_salesman_without_no(self):
        api_data = _make_api_data(salesman_no="", salesman_name="李四")
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.salesperson == "李四"

    def test_missing_json_date(self):
        api_data = {"nodeList": []}
        rec = FlowRecord(flow_id="test")
        fill_record_from_api(rec, api_data, "test")
        assert rec.project_name == "--"

    def test_pricing_as_json_string(self):
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
    def test_full_approval_chain(self):
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
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, [])
        assert rec.submit_time == "--"
        assert rec.province_processor == "--"
        assert rec.final_approval_time == "--"

    def test_partial_approval(self):
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "李四", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "--"
        assert rec.negotiation_processor == "--"

    def test_final_approval_time_picks_latest(self):
        nodes = [
            {"roleName": "流程发起人提交审核", "uname": "A", "statusName": "提交审核", "updateTime": "2026-01-01 10:00:00"},
            {"roleName": "省总审批", "uname": "B", "statusName": "审批通过", "updateTime": "2026-01-05 10:00:00"},
            {"roleName": "采购审批", "uname": "C", "statusName": "审批通过", "updateTime": "2026-01-03 10:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.final_approval_time == "2026-01-05 10:00:00"

    def test_node_with_user_name_fallback(self):
        nodes = [
            {"roleName": "省总审批", "uname": None, "userName": "王五", "statusName": "审批通过", "updateTime": "2026-01-02 11:00:00"},
        ]
        rec = FlowRecord(flow_id="test")
        fill_approval_from_nodes(rec, nodes)
        assert rec.province_processor == "王五"


class TestFillRecordFromHtml:
    def test_basic_html(self):
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
        html = "<th>其他</th><td>其他值</td>"
        rec = FlowRecord(flow_id="test")
        fill_record_from_html(rec, html)
        assert rec.project_name == "--"
        assert rec.unit_price == "--"


class TestFillApprovalFromDict:
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
        approval = {"submit_time": "2026-01-01 10:00:00"}
        rec = FlowRecord(flow_id="test")
        fill_approval_from_dict(rec, approval)
        assert rec.submit_time == "2026-01-01 10:00:00"
        assert rec.province_processor == "--"

    def test_empty_dict(self):
        rec = FlowRecord(flow_id="test")
        fill_approval_from_dict(rec, {})
        assert rec.submit_time == "--"
        assert rec.final_approval_time == "--"
