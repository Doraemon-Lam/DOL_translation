import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from translation_hub import QuestReader


class HubTests(unittest.TestCase):
    def test_new_quest_preserves_title_and_partial_record(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'log.jsonl'
            p.write_text(json.dumps({'text': '古い内容'}) + '\n', encoding='utf8')
            r = QuestReader(p)
            title = json.dumps({'text': '新しい依頼'}) + '\n'
            body = 'リスボンの交易所へ行ってください。\n必要な物を確認してください。\n依頼人に報告してください。'
            record = json.dumps({'text': body}) + '\n'
            with p.open('a', encoding='utf8') as f: f.write(title + record[:-5])
            self.assertEqual(r.poll(), [])
            with p.open('a', encoding='utf8') as f: f.write(record[-5:])
            self.assertEqual(r.poll(), [('任务标题', '新しい依頼'), ('任务正文', body)])
            self.assertEqual(r.poll(), [])

    def test_truncated_log_does_not_reuse_old_title(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'log.jsonl'
            p.write_text('x' * 300, encoding='utf8')
            r = QuestReader(p); r.previous = '古い依頼'
            p.write_text(json.dumps({'text': '新しい内容'}) + '\n', encoding='utf8')
            self.assertEqual(r.poll(), [])
            self.assertEqual(r.previous, '新しい内容')
