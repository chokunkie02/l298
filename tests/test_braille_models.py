"""ทดสอบ braille_models.py: bitmask 0-63 ครบทุกค่า, การแปลง dot-number/pattern,
เซลล์ว่าง, การปฏิเสธค่าที่ไม่ถูกต้อง, และการแปลง Unicode Braille -> เซลล์
"""

import unittest

import braille_models as bm


class BitmaskExhaustiveTests(unittest.TestCase):
    """ตรวจ mask 0-63 ทุกค่า (2^6 = 64 ค่า) ให้ครบตามที่โจทย์กำหนด"""

    def test_all_64_masks_produce_valid_cells(self):
        for mask in range(64):
            cell = bm.make_cell(mask, mask)
            self.assertEqual(cell.bitmask, mask)
            self.assertEqual(len(cell.bit_pattern), 6)
            self.assertTrue(set(cell.bit_pattern).issubset({"0", "1"}))
            # round-trip: pattern -> bitmask ต้องได้ค่าเดิม
            self.assertEqual(bm.bitmask_from_bit_pattern(cell.bit_pattern), mask)
            # round-trip: unicode -> bitmask ต้องได้ค่าเดิม
            self.assertEqual(ord(cell.unicode_braille) - bm.BRAILLE_UNICODE_BASE, mask)

    def test_dot_numbers_match_bit_pattern_for_every_mask(self):
        for mask in range(64):
            dots = bm.dots_from_bitmask(mask)
            pattern = bm.bit_pattern_from_bitmask(mask)
            expected_dots = tuple(d for d in range(1, 7) if pattern[d - 1] == "1")
            self.assertEqual(dots, expected_dots)

    def test_dots_are_always_ascending_and_within_1_to_6(self):
        for mask in range(64):
            dots = bm.dots_from_bitmask(mask)
            self.assertEqual(list(dots), sorted(dots))
            self.assertTrue(all(1 <= d <= 6 for d in dots))


class BitOrderingTests(unittest.TestCase):
    """ยืนยันลำดับบิต: bit0=dot1 ... bit5=dot6 และ bit_pattern เรียง dot 1..6"""

    def test_bit0_is_dot1(self):
        self.assertEqual(bm.bit_pattern_from_bitmask(0b000001), "100000")
        self.assertEqual(bm.dots_from_bitmask(0b000001), (1,))

    def test_bit5_is_dot6(self):
        self.assertEqual(bm.bit_pattern_from_bitmask(0b100000), "000001")
        self.assertEqual(bm.dots_from_bitmask(0b100000), (6,))

    def test_each_bit_maps_to_the_documented_dot(self):
        for bit_index, dot in enumerate(bm.DOT_NUMBERS_IN_ORDER):
            mask = 1 << bit_index
            self.assertEqual(bm.dots_from_bitmask(mask), (dot,))

    def test_full_mask_63_is_all_six_dots_and_pattern_111111(self):
        cell = bm.make_cell(0, 63)
        self.assertEqual(cell.dot_numbers, (1, 2, 3, 4, 5, 6))
        self.assertEqual(cell.bit_pattern, "111111")
        self.assertEqual(cell.unicode_braille, "⠿")


class BlankCellTests(unittest.TestCase):
    def test_bitmask_zero_is_blank_cell(self):
        cell = bm.make_cell(0, 0)
        self.assertEqual(cell.bit_pattern, "000000")
        self.assertEqual(cell.dot_numbers, ())
        self.assertEqual(cell.unicode_braille, bm.BLANK_CELL_UNICODE)
        self.assertEqual(cell.unicode_braille, "⠀")

    def test_blank_cell_is_preserved_in_conversion_not_dropped(self):
        cells, diagnostics = bm.convert_unicode_braille_string("⠀")
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].bitmask, 0)
        self.assertEqual(diagnostics, [])

    def test_blank_cell_between_real_cells_keeps_its_position(self):
        cells, _ = bm.convert_unicode_braille_string("⠁⠀⠂")
        self.assertEqual([c.bitmask for c in cells], [1, 0, 2])
        self.assertEqual([c.index for c in cells], [0, 1, 2])


class InvalidMaskRejectionTests(unittest.TestCase):
    def test_rejects_bool_true(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, True)

    def test_rejects_bool_false(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, False)

    def test_rejects_float(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, 12.0)

    def test_rejects_string(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, "12")

    def test_rejects_negative(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, -1)

    def test_rejects_above_63(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, 64)

    def test_rejects_none(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.make_cell(0, None)

    def test_boundary_63_is_accepted(self):
        bm.make_cell(0, 63)  # ไม่ควร raise

    def test_boundary_0_is_accepted(self):
        bm.make_cell(0, 0)  # ไม่ควร raise


class BitPatternValidationTests(unittest.TestCase):
    def test_rejects_wrong_length(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.bitmask_from_bit_pattern("101")

    def test_rejects_non_binary_characters(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.bitmask_from_bit_pattern("10102x")

    def test_rejects_non_string(self):
        with self.assertRaises(bm.InvalidBrailleMaskError):
            bm.bitmask_from_bit_pattern(101010)


class UnicodeBrailleConversionTests(unittest.TestCase):
    def test_single_valid_braille_character(self):
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, "⠁")
        self.assertIsNone(diagnostic)
        self.assertEqual(cell.bitmask, 1)

    def test_non_braille_output_is_detected_not_dropped_silently(self):
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, "A")
        self.assertIsNone(cell)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic.severity, bm.DiagnosticSeverity.ERROR)
        self.assertEqual(diagnostic.code, "non_braille_output")
        self.assertEqual(diagnostic.character, "A")
        self.assertEqual(diagnostic.source_index, 0)

    def test_dot_7_produces_diagnostic_and_still_yields_six_dot_cell(self):
        # dot 7 = bit 6 (ค่า 64)
        char = chr(bm.BRAILLE_UNICODE_BASE + 0b01000001)  # dot1 + dot7
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, char)
        self.assertIsNotNone(cell)
        self.assertEqual(cell.bit_pattern, "100000")  # เฉพาะ dot1 (dot7 ถูกตัดออกจากเซลล์ 6 จุด)
        self.assertIsNotNone(diagnostic)
        self.assertEqual(diagnostic.severity, bm.DiagnosticSeverity.WARNING)
        self.assertEqual(diagnostic.code, "unsupported_dots_7_or_8")
        self.assertIn("7", diagnostic.description)

    def test_dot_8_produces_diagnostic(self):
        char = chr(bm.BRAILLE_UNICODE_BASE + 0b10000000)  # dot8 เท่านั้น
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, char)
        self.assertEqual(cell.bit_pattern, "000000")
        self.assertEqual(diagnostic.code, "unsupported_dots_7_or_8")
        self.assertIn("8", diagnostic.description)

    def test_both_dot_7_and_dot_8_are_reported_together(self):
        char = chr(bm.BRAILLE_UNICODE_BASE + 0b11000000)
        _, diagnostic = bm.unicode_braille_char_to_cell(0, 0, char)
        self.assertIn("7", diagnostic.description)
        self.assertIn("8", diagnostic.description)

    def test_codepoint_outside_braille_block_entirely(self):
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, "A")  # 'A'
        self.assertIsNone(cell)
        self.assertEqual(diagnostic.code, "non_braille_output")

    def test_codepoint_just_below_braille_block(self):
        char = chr(bm.BRAILLE_UNICODE_BASE - 1)
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, char)
        self.assertIsNone(cell)
        self.assertEqual(diagnostic.code, "non_braille_output")

    def test_codepoint_just_above_braille_block(self):
        char = chr(bm.BRAILLE_UNICODE_MAX + 1)
        cell, diagnostic = bm.unicode_braille_char_to_cell(0, 0, char)
        self.assertIsNone(cell)
        self.assertEqual(diagnostic.code, "non_braille_output")


class MultiCellFromOneSourceCharacterTests(unittest.TestCase):
    """หนึ่งตัวอักษรต้นทางอาจสร้างหลายเซลล์ (เช่น capital sign + ตัวอักษร) -
    ฟังก์ชันแปลงต้องไม่สมมติว่าจำนวนเซลล์ผลลัพธ์เท่ากับจำนวนตัวอักษรอินพุต
    """

    def test_two_cells_from_capital_indicator_plus_letter(self):
        # จำลองผลลัพธ์ดิบสำหรับ 'A' ตัวพิมพ์ใหญ่: capital-sign cell + letter cell
        raw = "⠠⠁"  # dot6 (capital sign แบบสมมติ) + dot1
        cells, diagnostics = bm.convert_unicode_braille_string(raw)
        self.assertEqual(len(cells), 2)
        self.assertEqual(diagnostics, [])
        self.assertEqual([c.index for c in cells], [0, 1])

    def test_cell_count_can_exceed_character_count_of_short_input(self):
        raw = "⠁⠂⠃⠄"  # 4 cells จากอินพุตต้นทางที่อาจสั้นกว่านี้มาก
        cells, _ = bm.convert_unicode_braille_string(raw)
        self.assertEqual(len(cells), 4)


class ConvertUnicodeBrailleStringIndexingTests(unittest.TestCase):
    def test_start_cell_index_offsets_indices_for_multi_line_accumulation(self):
        cells, _ = bm.convert_unicode_braille_string("⠁⠂", start_cell_index=5)
        self.assertEqual([c.index for c in cells], [5, 6])

    def test_diagnostics_use_output_string_position_not_cell_index(self):
        _, diagnostics = bm.convert_unicode_braille_string("⠁XY", start_cell_index=10)
        self.assertEqual([d.source_index for d in diagnostics], [1, 2])

    def test_empty_string_produces_no_cells_and_no_diagnostics(self):
        cells, diagnostics = bm.convert_unicode_braille_string("")
        self.assertEqual(cells, [])
        self.assertEqual(diagnostics, [])


class SerializationTests(unittest.TestCase):
    def test_braille_cell_to_dict_shape(self):
        cell = bm.make_cell(0, 63)
        payload = cell.to_dict()
        self.assertEqual(
            set(payload.keys()), {"index", "unicode_braille", "dot_numbers", "bitmask", "bit_pattern"}
        )
        self.assertEqual(payload["dot_numbers"], [1, 2, 3, 4, 5, 6])
        self.assertIsInstance(payload["dot_numbers"], list)

    def test_diagnostic_to_dict_shape(self):
        diagnostic = bm.TranslationDiagnostic(
            severity="warning", code="x", description="y", source_index=1, character="a"
        )
        payload = diagnostic.to_dict()
        self.assertEqual(
            set(payload.keys()), {"severity", "code", "description", "source_index", "character"}
        )

    def test_translation_to_dict_shape_and_cell_count(self):
        cell = bm.make_cell(0, 1)
        translation = bm.BrailleTranslation(
            source_text="a", normalized_text="a", cells=(cell,), line_boundaries=(),
            diagnostics=(), engine="fake", engine_version="1", table="t.utb",
            changed_by_normalization=False,
        )
        payload = translation.to_dict()
        self.assertEqual(payload["cell_count"], 1)
        self.assertEqual(len(payload["cells"]), 1)
        self.assertIn("line_boundaries", payload)
        self.assertIn("engine", payload)
        self.assertIn("table", payload)


class ImmutabilityTests(unittest.TestCase):
    def test_braille_cell_is_frozen(self):
        cell = bm.make_cell(0, 1)
        with self.assertRaises(Exception):
            cell.bitmask = 5

    def test_translation_diagnostic_is_frozen(self):
        diagnostic = bm.TranslationDiagnostic(severity="info", code="x", description="y")
        with self.assertRaises(Exception):
            diagnostic.severity = "error"


class NoSerialCouplingTests(unittest.TestCase):
    """ตรวจจาก "หลักฐานการเชื่อมต่อจริง" ไม่ใช่การห้ามคำว่า "/send" แบบเหมารวม
    เพราะ docstring ของโมดูลนี้ตั้งใจอ้างถึง endpoint /send เดิมเพื่ออธิบายว่า
    ลำดับบิตตรงกันโดยเจตนา (ดูเหตุผลใน docstring ด้านบนของ braille_models.py)
    ซึ่งเป็นคำอธิบายที่ดี ไม่ใช่การเชื่อมต่อจริง
    """

    def test_module_has_no_serial_esp32_or_flask_coupling(self):
        import ast
        import pathlib

        source = pathlib.Path(bm.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        self.assertNotIn("serial", imported_modules)
        self.assertNotIn("flask", imported_modules)
        self.assertNotIn("easyocr", imported_modules)
        self.assertNotIn("app", imported_modules)
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("app.route", source)


if __name__ == "__main__":
    unittest.main()
