"""导入预览面向创作者：风险标记是可读中文，缺参考的素材显示名称。"""
import unittest

import studio
import test_drama_import
import test_studio


class ImportPreviewWordingTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def test_risk_flags_are_readable(self):
        pv = studio.preview_drama_import(test_drama_import.bundle())
        risks = [w['message'] for w in pv['warnings'] if w['rule'] == 'source-production-risk']
        self.assertTrue(risks)
        self.assertTrue(all(m.startswith('源剧本标记的制作风险：') for m in risks))
        self.assertIn('手部精细动作', risks[0])

    def test_unknown_flag_is_kept_verbatim(self):
        import creative
        self.assertEqual(creative.risk_text('rare-thing'), '源剧本标记的制作风险：rare-thing')

    def test_missing_references_come_with_names(self):
        pv = studio.preview_drama_import(test_drama_import.bundle())
        names = pv['asset_names']
        self.assertTrue(all(isinstance(v, str) and v for v in names.values()))
        self.assertTrue(set(pv['summary']['missing_reference_assets']) <= set(names))


if __name__ == '__main__':
    unittest.main()
