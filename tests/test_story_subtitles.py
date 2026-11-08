import tempfile
import unittest
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
from story_subtitles import Reader, parse_records
import story_subtitles
from dictionary import decode
from unittest.mock import patch


class StorySubtitlesTests(unittest.TestCase):
    def test_html_color_speaker_and_multiline(self):
        data = '<FONT color="#d4d4d4">船大工&gt;設計図は<BR>使えます</FONT><FONT color="#80aaff">通知です</FONT>'
        entries, end = parse_records(data)
        self.assertEqual(entries, [('船大工', '設計図は\n使えます'), ('', '通知です')])
        self.assertEqual(end, len(data))
        self.assertEqual(parse_records(data, {'80aaff'})[0], [('', '通知です')])
        self.assertEqual(parse_records('<FONT color="#7bedb6">こんにちは</FONT>')[0], [('', 'こんにちは')])

    def test_token_usage_and_missing_response(self):
        stats = {}
        story_subtitles.record_usage(stats, {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_cache_hit_tokens': 30})
        story_subtitles.record_usage(stats, None)
        self.assertEqual((stats['api_responses'], stats['usage_missing'], stats['provider_hit_tokens'], stats['provider_miss_tokens'], stats['output_tokens']), (2, 1, 30, 70, 20))

    def test_only_new_data_and_split_utf8_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.html'
            path.write_bytes(b'<FONT color="#ffffff">old</FONT>')
            reader = Reader(Path(directory))
            line = '<FONT color="#d4d4d4">船大工&gt;船を<BR>修理します</FONT>'.encode('utf-8')
            cut = line.index('船'.encode()) + 1
            with path.open('ab') as f: f.write(line[:cut])
            self.assertEqual(reader.poll(), [])
            with path.open('ab') as f: f.write(line[cut:])
            self.assertEqual(reader.poll(), [('船大工', '船を\n修理します')])
            self.assertEqual(reader.poll(), [])

    def test_text_log_combines_speaker_and_wrapped_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.txt'
            path.touch()
            reader = Reader(Path(directory))
            reader.format = 'txt'
            with path.open('ab') as f:
                f.write('船大工>各種の設計図は使用することで\r\n選択した船の経験が\r\n増加する\r\n'.encode('gb18030'))
            with patch('story_subtitles.time.monotonic', return_value=10):
                self.assertEqual(reader.poll(), [])
            with patch('story_subtitles.time.monotonic', return_value=12):
                self.assertEqual(reader.poll(), [('船大工', '各種の設計図は使用することで\n選択した船の経験が\n増加する')])

    def test_game_inserts_before_existing_closing_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.html'
            first = '<HTML><FONT color="#d4d4d4">船大工&gt;古い話です</FONT><BR>\r\n'
            tail = '</BODY>\r\n</HTML>\r\n'
            path.write_text(first + tail, encoding='utf-8')
            reader = Reader(Path(directory))
            self.assertEqual(reader.poll(), [])
            second = '<FONT color="#d4d4d4">船大工&gt;修理します</FONT><BR>\r\n'
            path.write_text(first + second + tail, encoding='utf-8')
            self.assertEqual(reader.poll(), [('船大工', '修理します')])
            self.assertEqual(reader.poll(), [])

    def test_publish_story_includes_fragments_and_manual_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'dictionaries').mkdir()
            (root / 'bin').mkdir()
            (root / 'dictionaries' / 'supplement-001.json').write_text(json.dumps({'船を修理します': '人工译文'}, ensure_ascii=False), encoding='utf-8')
            with patch.object(story_subtitles, 'ROOT', root), patch.object(story_subtitles, 'BIN', root / 'bin'), patch.object(story_subtitles, 'CACHE_PATH', root / 'dictionaries' / 'supplement-000-story.json'):
                story_subtitles.publish_story('船を修理します\n港に向かいます', '修好船后前往港口', ['修理船只', '前往港口'])
                entries = decode((root / 'bin' / 'live-overlay.bin').read_bytes())
                self.assertEqual(entries['船を修理します'], '人工译文')
                self.assertEqual(entries['港に向かいます'], '前往港口')
                self.assertEqual(entries['：港に向かいます'], '：前往港口')
                story_subtitles.publish_story('これは\n別の文章です', '这是另一段文字', None)
                entries = decode((root / 'bin' / 'live-overlay.bin').read_bytes())
                self.assertEqual(entries['これは\n別の文章です'], '这是另一段文字')
                self.assertNotIn('別の文章です', entries)


if __name__ == '__main__':
    unittest.main()
