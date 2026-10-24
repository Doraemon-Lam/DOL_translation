import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from dictionary import compile_dictionary, decode, encode, load

class DictionaryTests(unittest.TestCase):
    def test_utf16_roundtrip_including_surrogate_pair(self):
        entries = {'船型式とは？': '什么是船型？', '星🌟': '星星🌟'}
        self.assertEqual(decode(encode(entries)), entries)

    def test_later_override_updates_generated_colon_variant(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/'a.json', Path(folder)/'b.json']
            for path, value in zip(paths, ['下一个问题', '查看其他问题']):
                path.write_text(json.dumps({'次の質問へ': value}), encoding='utf-8')
            result = load(paths, variants=True)
            self.assertEqual(result['：次の質問へ'], '：查看其他问题')

    def test_explicit_colon_variant_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'a.json'
            path.write_text(json.dumps({'次の質問へ': '查看其他问题', '：次の質問へ': '：专用译文'}), encoding='utf-8')
            self.assertEqual(load([path], True)['：次の質問へ'], '：专用译文')

    def test_truncation_and_trailing_bytes_rejected(self):
        encoded = encode({'日本語': '中文'})
        for data in [b'', encoded[:-1], encoded+b'\0']:
            with self.assertRaises(ValueError): decode(data)

    def test_invalid_controls_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.json'
            path.write_text(json.dumps({'日本語': '中\0文'}), encoding='utf-8')
            with self.assertRaises(ValueError): load([path])

    def test_published_file_and_hash_header(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source=base/'source.json'
            source.write_text(json.dumps({'船型式とは？':'什么是船型？'}),encoding='utf-8')
            info=compile_dictionary([source],base/'overlay.bin',base/'digest.h',True,True)
            self.assertEqual(info['entries'],2)
            self.assertEqual(decode((base/'overlay.bin').read_bytes())['船型式とは？'],'什么是船型？')
            self.assertFalse((base/'overlay.bin.pending').exists())

if __name__ == '__main__': unittest.main()
