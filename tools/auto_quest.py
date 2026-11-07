"""Translate quest-like Japanese text using DeepSeek or local Ollama."""
import argparse
import json
import msvcrt
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dictionary import compile_dictionary, load

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / 'bin' if (ROOT / 'bin' / 'manifest.json').is_file() else ROOT / 'build' / 'bin'
LOG = BIN / 'missing-text.jsonl'
CACHE = ROOT / 'dictionaries' / 'supplement-000-auto.json'
MODEL = 'deepseek-flash'
LOCAL_MODEL = 'qwen2.5:7b'
FAST_MODEL = 'demonbyron/HY-MT1.5-1.8B'
KEY_PATH = ROOT / 'deepseek.key.protected'


def load_key():
    # ConvertFrom-SecureString is protected by Windows for this user account.
    command = ("$s=(Get-Content -LiteralPath $env:DOL_DEEPSEEK_KEY_FILE -Raw).Trim() | ConvertTo-SecureString; "
               "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); "
               "try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))} "
               "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}")
    env = dict(os.environ, DOL_DEEPSEEK_KEY_FILE=str(KEY_PATH),
        PSModulePath=str(Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'Modules'))
    return subprocess.check_output(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
        env=env, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8').strip()


def say(message):
    print(time.strftime('%H:%M:%S'), message, flush=True)


def candidate(text):
    # The verified quest description arrived as one multiline layout string.
    # This heuristic is not a definitive way to distinguish quests from chat.
    return len(text) >= 40 and text.count('\n') >= 2 and bool(re.search(r'[\u3041-\u3096\u30a1-\u30fa]', text))


def translate(text, key='', provider='deepseek'):
    glossary = {'サンフアン': '圣胡安', 'リスボン': '里斯本', 'ロンドン': '伦敦', 'アゾレス': '亚速尔群岛', '交易所': '交易所', '海事ギルド': '海事公会', 'ナポリ': '那不勒斯', '王宮': '王宫'}
    terms = '，'.join(k + '=' + v for k, v in glossary.items() if k in text.replace('\n', ''))
    messages = [{'role': 'system', 'content': '你是大航海时代Online的日中翻译。将用户给出的任务准确翻译成简体中文，只输出译文，保留地名、人名和数字，不要解释。所有数字必须原样使用阿拉伯数字，不能转成汉字。交易所店主=交易所老板。' + terms},
                {'role': 'user', 'content': text.replace('\n', '')}]
    if provider == 'deepseek':
        body = {'model': MODEL, 'stream': False, 'thinking': {'type': 'disabled'},
                'messages': messages, 'temperature': 0.1, 'max_tokens': 600}
        url = 'https://api.deepseek.com/chat/completions'
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
    elif provider == 'local':
        body = {'model': LOCAL_MODEL, 'stream': False, 'messages': messages,
                'options': {'temperature': 0.1, 'num_predict': 600}}
        url = 'http://127.0.0.1:11434/api/chat'
        headers = {'Content-Type': 'application/json'}
    elif provider == 'local-fast':
        plain = text.replace('\n', '')
        terms_hint = '\n'.join(k + ' 翻译成 ' + v for k, v in glossary.items() if k in plain)
        prompt = (('参考下面的翻译：\n' + terms_hint + '\n\n') if terms_hint else '') + '将以下文本翻译为简体中文，注意只需要输出翻译后的结果，不要额外解释：\n' + plain
        body = {'model': FAST_MODEL, 'stream': False, 'messages': [{'role': 'user', 'content': prompt}],
                'options': {'temperature': 0.1, 'num_predict': 600}}
        url = 'http://127.0.0.1:11434/api/chat'
        headers = {'Content-Type': 'application/json'}
    else:
        raise ValueError('未知翻译模式')
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    if provider == 'deepseek':
        choice = result['choices'][0]
        answer = (choice.get('message', {}).get('content') or '').strip()
        finished = choice.get('finish_reason') == 'stop'
    else:
        answer = (result.get('message', {}).get('content') or '').strip()
        finished = result.get('done') is True and result.get('done_reason') != 'length'
    if not finished or not answer or '<think>' in answer or len(answer) > 800:
        raise ValueError('模型输出为空、截断或格式异常')
    if any(v in answer and k not in text.replace('\n', '') for k, v in glossary.items()):
        raise ValueError('模型输出含原文没有的已知地名')
    if set(re.findall(r'\d+', text.replace('\n', ''))) != set(re.findall(r'\d+', answer)):
        raise ValueError('模型输出中的数字与原文不一致')
    # Keep a conservative width for the game's fixed quest panel.
    answer = re.sub(r'\s+', '', answer)
    lines = []
    while answer:
        end = min(15, len(answer))
        while 0 < end < len(answer) and answer[end-1].isascii() and answer[end-1].isalnum() and answer[end].isascii() and answer[end].isalnum():
            end -= 1
        if end == 0:
            end = min(15, len(answer))
        lines.append(answer[:end])
        answer = answer[end:]
    return '\n'.join(lines)


def publish(cache):
    temp = CACHE.with_suffix('.json.pending')
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(CACHE)
    inputs = [CACHE] + sorted(p for p in (ROOT / 'dictionaries').glob('supplement-*.json') if p != CACHE)
    compile_dictionary(inputs, BIN / 'live-overlay.bin', variants=True, overlay=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=('deepseek', 'local', 'local-fast'), default='deepseek')
    provider = parser.parse_args().provider
    lock = (BIN / 'auto-quest.lock').open('a+b')
    try:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        say('自动翻译已经在运行。')
        return
    key = ''
    if provider == 'deepseek':
        try:
            key = load_key()
            if not key:
                raise ValueError('密钥为空')
        except (OSError, subprocess.SubprocessError, ValueError):
            say('无法读取本机加密的 DeepSeek 密钥。')
            return
    cache = json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}
    known = load(sorted((ROOT / 'dictionaries').glob('supplement-*.json')))
    seen = set(known)
    # Only process new observations; old logs can contain unrelated chat.
    offset = LOG.stat().st_size if LOG.exists() else 0
    previous = ''
    say(({'deepseek': 'DeepSeek', 'local': '本地 Qwen 7B', 'local-fast': '本地混元翻译 1.8B'}[provider]) + ' 任务翻译已启动；完成后请重新打开任务面板。')
    while True:
        if LOG.exists():
            try:
                with LOG.open('r', encoding='utf-8') as f:
                    f.seek(offset)
                    while True:
                        start = f.tell()
                        line = f.readline()
                        if not line:
                            break
                        if not line.endswith('\n'):
                            f.seek(start)
                            break
                        try:
                            text = json.loads(line).get('text', '')
                        except (ValueError, AttributeError):
                            previous = ''
                            continue
                        if not isinstance(text, str):
                            previous = ''
                            continue
                        title = previous
                        previous = text
                        if not candidate(text):
                            continue
                        # A title immediately followed by a quest-like body is
                        # the association observed in this client, not a parser.
                        if (title not in seen and 2 <= len(title) <= 32 and
                            '\n' not in title and not title.startswith(('：', ':')) and
                            not re.search(r'[。！？!?]|(?:です|ます|ました)$', title) and
                            re.search(r'[\u3041-\u3096\u30a1-\u30fa]', title)):
                            try:
                                say('发现任务标题，正在翻译……')
                                cache[title] = translate(title, key, provider)
                                publish(cache)
                                seen.add(title)
                            except (OSError, ValueError, urllib.error.URLError) as exc:
                                say('标题翻译失败：' + str(exc))
                        if text in seen:
                            continue
                        say('发现可能的任务正文，正在翻译……')
                        try:
                            last_error = None
                            for attempt in range(3):
                                try:
                                    result = translate(text, key, provider)
                                    break
                                except (OSError, ValueError, urllib.error.URLError) as exc:
                                    last_error = exc
                                    say('翻译未通过检查，重试中：' + str(exc))
                            else:
                                raise last_error
                            cache[text] = result
                            publish(cache)
                            seen.add(text)
                            say('翻译已更新，请重新打开任务面板。')
                        except (OSError, ValueError, urllib.error.URLError) as exc:
                            say('翻译失败，将在下次启动时重试：' + str(exc))
                    offset = f.tell()
            except OSError as exc:
                say('读取日志失败：' + str(exc))
        time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
