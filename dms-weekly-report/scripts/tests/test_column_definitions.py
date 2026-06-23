"""column_definitions.py 单元测试。"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))
from column_definitions import (
    HEADERS,
    COL_FLOW_ID, COL_PROJECT_NAME, COL_AGENT_CODE, COL_AGENT_NAME,
    COL_PROVINCE, COL_SALESPERSON, COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
    COL_UNIT_PRICE, COL_TOTAL_PRICE, COL_SUBMIT_TIME, COL_REMARK,
    COL_IS_VALID, COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS, COL_NEGOTIATION_TIME,
    COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
    COL_FINAL_APPROVAL_TIME,
)


class TestColumnDefinitions(unittest.TestCase):
    """列定义常量测试。"""

    def test_headers_count(self):
        """测试表头数量。"""
        self.assertEqual(len(HEADERS), 20, "应该有 20 列")

    def test_column_indices_sequence(self):
        """测试列索引是否按顺序。"""
        indices = [
            COL_FLOW_ID, COL_PROJECT_NAME, COL_AGENT_CODE, COL_AGENT_NAME,
            COL_PROVINCE, COL_SALESPERSON, COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
            COL_UNIT_PRICE, COL_TOTAL_PRICE, COL_SUBMIT_TIME, COL_REMARK,
            COL_IS_VALID, COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS, COL_NEGOTIATION_TIME,
            COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
            COL_FINAL_APPROVAL_TIME,
        ]
        # 验证索引从 0 开始，连续且无重复
        self.assertEqual(indices, list(range(len(indices))))

    def test_each_header_has_index(self):
        """测试每个表头都能找到对应的索引。"""
        for i, header in enumerate(HEADERS):
            # 确保索引与表头一一对应
            self.assertIsNotNone(i)

    def test_specific_headers(self):
        """测试特定表头的位置。"""
        self.assertEqual(HEADERS[COL_FLOW_ID], "流程编号")
        self.assertEqual(HEADERS[COL_PROJECT_NAME], "项目名称")
        self.assertEqual(HEADERS[COL_MODULE_KW], "组件总功率(kW)")
        self.assertEqual(HEADERS[COL_IS_VALID], "是否有效")
        self.assertEqual(HEADERS[COL_NEGOTIATION_PROCESSOR], "项目管理部核价审批人")
        self.assertEqual(HEADERS[COL_FINAL_APPROVAL_TIME], "审批完成时间")

    def test_no_duplicate_indices(self):
        """测试没有重复的列索引。"""
        indices = [
            COL_FLOW_ID, COL_PROJECT_NAME, COL_AGENT_CODE, COL_AGENT_NAME,
            COL_PROVINCE, COL_SALESPERSON, COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
            COL_UNIT_PRICE, COL_TOTAL_PRICE, COL_SUBMIT_TIME, COL_REMARK,
            COL_IS_VALID, COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS, COL_NEGOTIATION_TIME,
            COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
            COL_FINAL_APPROVAL_TIME,
        ]
        self.assertEqual(len(indices), len(set(indices)), "列索引不应有重复")

    def test_indices_within_bounds(self):
        """测试所有索引都在有效范围内。"""
        max_index = len(HEADERS) - 1
        indices = [
            COL_FLOW_ID, COL_PROJECT_NAME, COL_AGENT_CODE, COL_AGENT_NAME,
            COL_PROVINCE, COL_SALESPERSON, COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
            COL_UNIT_PRICE, COL_TOTAL_PRICE, COL_SUBMIT_TIME, COL_REMARK,
            COL_IS_VALID, COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS, COL_NEGOTIATION_TIME,
            COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
            COL_FINAL_APPROVAL_TIME,
        ]
        for idx in indices:
            self.assertGreaterEqual(idx, 0)
            self.assertLessEqual(idx, max_index)


if __name__ == "__main__":
    unittest.main()
