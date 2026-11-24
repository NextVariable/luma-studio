from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import art, domestic_media, sample_scene, studio


class ArtDirectionTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.files = patch.multiple(studio, DATA=Path(self.tmp.name),
                                    MEDIA=Path(self.tmp.name) / 'media', DB=Path(self.tmp.name) / 'studio.sqlite')
        self.files.start()
        self.network = patch('socket.socket.connect', side_effect=AssertionError('unexpected network'))
        self.network.start()
        studio.init()
        self.p = sample_scene.create(studio.MEDIA, studio.save)

    def tearDown(self):
        self.network.stop()
        self.files.stop()
        self.tmp.cleanup()

    def character(self):
        return next(a for a in self.p['assets'] if a['kind'] == 'character')

    def with_style(self, style, art_style=None):
        p = studio.project(self.p['id'])
        p['creative_brief']['style'] = style
        if art_style:
            p['creative_brief']['art_style'] = art_style
        else:
            p['creative_brief'].pop('art_style', None)
        return studio.save(p, p['revision'])

    def packet(self, p):
        char = self.character()
        return studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=char['selected_version'],
                                                 instruction='保持构图'))

    def test_explicit_style_wins_and_empty_style_uses_neutral_constraints(self):
        self.assertEqual(art.resolve(dict(art_style='anime', style='电影写实'))['key'], 'anime')
        self.assertEqual(art.resolve(dict(style='赛璐璐动画，冷色夜景'))['key'], 'anime')
        self.assertEqual(art.resolve(dict(style='国漫插画，厚涂'))['key'], 'comic')
        self.assertEqual(art.resolve(dict(style='实拍电影，低饱和'))['key'], 'cinematic')
        self.assertEqual(art.resolve(dict(style=''))['key'], 'custom')
        self.assertEqual(art.resolve(dict(style='水墨留白，宣纸质感'))['key'], 'custom')

    def test_anime_prompt_never_demands_photoreal_skin(self):
        p = self.with_style('赛璐璐动画，冷色夜景')
        prompt = self.packet(p)['instruction']
        self.assertIn('赛璐璐分层上色', prompt)
        self.assertIn('禁止低多边形', prompt)
        for forbidden in ('真实皮肤', '摄影级写实', '皮肤与布料有真实质感', '电影级实拍'):
            self.assertNotIn(forbidden, prompt)
        self.assertNotIn('动漫式简化', prompt)
        self.assertEqual(self.packet(p)['art_label'], '精致二维动画 / 赛璐璐')

    def test_cinematic_keeps_live_action_craft(self):
        p = self.with_style('实拍电影，雨夜', 'cinematic')
        prompt = self.packet(p)['instruction']
        self.assertIn('电影级实拍光影', prompt)
        self.assertIn('可信的材质和细节', prompt)
        self.assertNotIn('赛璐璐分层上色', prompt)

    def test_custom_style_respects_author_wording(self):
        p = self.with_style('水墨留白，宣纸质感', 'custom')
        prompt = self.packet(p)['instruction']
        self.assertIn('遵循用户风格描述：水墨留白，宣纸质感', prompt)
        self.assertNotIn('赛璐璐分层上色', prompt)
        self.assertNotIn('电影级实拍光影', prompt)

    def test_storyboard_and_video_receive_the_same_style(self):
        p = self.with_style('赛璐璐动画')
        shot = p['shots'][1]
        packet = studio.storyboard_packet(p, shot['id'], domestic_media.FLASH)
        self.assertIn('赛璐璐分层上色', packet['instruction'])
        self.assertNotIn('真实皮肤', packet['instruction'])
        clause = art.video_clause(p['creative_brief'])
        self.assertIn('精致二维动画 / 赛璐璐', clause)
        self.assertIn('保持首帧', clause)

    def test_invalid_art_style_is_rejected(self):
        p = studio.project(self.p['id'])
        p['creative_brief']['art_style'] = 'oil-painting'
        with self.assertRaisesRegex(ValueError, '美术风格'):
            studio.save(p, p['revision'])
