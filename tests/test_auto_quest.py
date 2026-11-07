import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import auto_quest


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.data).encode('utf-8')


class TranslationTests(unittest.TestCase):
    def test_local_modes_only_send_to_loopback(self):
        for mode in ('local', 'local-fast'):
            with self.subTest(mode=mode), patch('urllib.request.urlopen') as send:
                send.return_value = Response({'done': True, 'done_reason': 'stop', 'message': {'content': '请在10天内抵达。'}})
                self.assertEqual(auto_quest.translate('10日以内に到着してください。', provider=mode), '请在10天内抵达。')
                req = send.call_args.args[0]
                self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/chat')
                self.assertIsNone(req.get_header('Authorization'))

    def test_deepseek_disables_thinking_and_rejects_changed_numbers(self):
        with patch('urllib.request.urlopen') as send:
            send.return_value = Response({'choices': [{'finish_reason': 'stop', 'message': {'content': '请在11天内抵达。'}}]})
            with self.assertRaises(ValueError):
                auto_quest.translate('10日以内に到着してください。', key='test-key')
            req = send.call_args.args[0]
            self.assertEqual(json.loads(req.data)['thinking'], {'type': 'disabled'})


if __name__ == '__main__':
    unittest.main()
