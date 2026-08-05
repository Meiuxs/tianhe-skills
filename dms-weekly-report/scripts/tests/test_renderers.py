"""renderers/ 新模块单元测试（aggregations, context_builder）。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from renderers.data_transform import compute_aggregations, compute_rows_detail
from renderers.context_builder import ReportContextBuilder, _serialize_aggregations
from renderers.data_reader import XlsxDataReader, read_rows_from_xlsx


# ==================== 测试数据 ====================

SAMPLE_ROWS = [
    [  # 有效询价
        12345678901234567, "测试项目A", "--", "--", "广东", "张三",
        100.5, 80.0, 50.0, "--", "--", "2026-06-01 10:00", "--",
        "是", "李四", "审批通过",
        "区域人A", "区域通过", "2026-06-02 11:30",
        "王五", "审批通过", "2026-06-02 12:00",
        "2026-06-03 15:30", "审批通过",
    ],
    [  # 无效询价（作废）
        22345678901234567, "测试项目B", "--", "--", "江苏", "李四",
        50.0, 40.0, 25.0, "--", "--", "2026-06-02 14:00", "--",
        "否", "赵六", "退回修改",
        "--", "--", "--",
        "--", "--", "--",
        "--", "作废",
    ],
    [  # 有效询价（同上省份）
        32345678901234567, "测试项目C", "--", "--", "广东", "王五",
        200.0, 150.0, 100.0, "--", "--", "2026-06-03 09:00", "--",
        "是", "钱七", "审批通过",
        "区域人C", "区域通过", "2026-06-04 09:30",
        "孙八", "审批通过", "2026-06-04 10:00",
        "2026-06-05 11:00", "审批通过",
    ],
]


# ==================== compute_aggregations ====================


class TestComputeAggregations:

    @pytest.fixture
    def rd(self):
        return compute_rows_detail(SAMPLE_ROWS)

    def test_basic_counts(self, rd):
        a = compute_aggregations(rd)
        assert a["totalProjects"] == 3
        assert a["validProjects"] == 2
        assert a["invalidProjects"] == 1

    def test_power_totals(self, rd):
        a = compute_aggregations(rd)
        assert a["totalModuleKw"] == 350.5
        assert a["totalInverterKw"] == 270.0
        assert a["totalBatteryKwh"] == 175.0

    def test_province_summary(self, rd):
        a = compute_aggregations(rd)
        assert a["provinceSummary"]["广东"]["count"] == 2
        assert a["provinceSummary"]["江苏"]["count"] == 1
        # 按项目数降序
        assert list(a["provinceSummary"].keys()) == ["广东", "江苏"]

    def test_empty_input(self):
        a = compute_aggregations([])
        assert a["totalProjects"] == 0
        assert a["provinceSummary"] == {}

    def test_zero_inverter_ratio(self):
        """逆变器总功率为 0 时容配比返回 0.0。"""
        custom = [
            {
                "flowId": "123",
                "projectName": "T",
                "province": "省",
                "salesperson": "人",
                "modulePower": 100.0,
                "inverterPower": 0.0,
                "batteryCapacity": 0.0,
                "isValid": "是",
                "isInvalid": False,
                "submitDate": "2026-06-01",
                "finalDate": "",
                "negotiationApprover": "",
                "negotiationStatus": "",
                "provinceApprover": "",
                "provinceStatus": "",
                "flowStatus": "审批通过",
            }
        ]
        a = compute_aggregations(custom)
        assert a["moduleToInverterRatio"] == 0.0


# ==================== Serialize Aggregations ====================


class TestSerializeAggregations:

    def test_valid_json(self):
        d = compute_rows_detail(SAMPLE_ROWS)
        s = _serialize_aggregations(d)
        p = json.loads(s)
        assert p["totalProjects"] == 3

    def test_xss_escaping(self):
        d = compute_rows_detail(SAMPLE_ROWS)
        s = _serialize_aggregations(d)
        assert "\\u003c" in s or "<" not in s


# ==================== ReportContextBuilder ====================


class TestReportContextBuilder:

    def test_build_contains_aggregations(self):
        from datetime import datetime
        b = ReportContextBuilder()
        d = compute_rows_detail(SAMPLE_ROWS)
        ctx = b.build(d, "2026-06-01 ~ 2026-06-07", now=datetime(2026, 6, 24, 12, 0))
        assert "AGGREGATIONS_JSON" in ctx
        assert "ROWS_DETAIL_JSON" in ctx
        assert ctx["QUERY_START_DATE"] == "2026-06-01"
        assert ctx["QUERY_END_DATE"] == "2026-06-07"
        p = json.loads(ctx["AGGREGATIONS_JSON"])
        assert p["totalProjects"] == 3

    def test_empty_detail(self):
        ctx = ReportContextBuilder().build([], "2026-06-01 ~ 2026-06-07")
        p = json.loads(ctx["AGGREGATIONS_JSON"])
        assert p["totalProjects"] == 0

    def test_no_date_in_query_range(self):
        d = compute_rows_detail(SAMPLE_ROWS)
        ctx = ReportContextBuilder().build(d, "本周")
        assert ctx["QUERY_START_DATE"] == ""
        assert ctx["QUERY_END_DATE"] == ""


# ==================== XlsxDataReader basic ====================


class TestXlsxDataReader:

    def test_read_rows_success(self):
        import tempfile, os, openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "询价汇总"
        ws.append(["流程编号", "项目名称"])
        ws.append(["12345", "测试"])
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "t.xlsx")
            wb.save(p)
            rows = XlsxDataReader(p).read()
            assert len(rows) == 1
            assert rows[0][0] == "12345"

    def test_function_alias(self):
        assert callable(read_rows_from_xlsx)
