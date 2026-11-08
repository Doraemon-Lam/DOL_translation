"""Local, read-only subtitles for newly appended DOL chat logs."""
import html
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
import urllib.request
from auto_quest import load_key
from dictionary import compile_dictionary

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Documents' / 'KOEI' / 'GV Online' / 'Log' / 'Chat'
CACHE_PATH = ROOT / 'dictionaries' / 'supplement-000-story.json'
STATS_PATH = ROOT / 'userdata' / 'story-usage.json'
BIN = ROOT / 'bin' if (ROOT / 'bin' / 'manifest.json').is_file() else ROOT / 'build' / 'bin'
MODEL = 'deepseek-flash'
FONT = re.compile(r'<font\b([^>]*)>(.*?)</font\s*>', re.I | re.S)
COLOR = re.compile(r'color\s*=\s*["\']?\s*#([0-9a-f]{6})', re.I)
TAGS = re.compile(r'<[^>]*>')
JAPANESE = re.compile(r'[\u3041-\u3096\u30a1-\u30fa]')


def parse_records(data, colors=None):
    """Return complete light-gray/white Japanese entries and consumed offset."""
    records, end = [], 0
    for m in FONT.finditer(data):
        end = m.end()
        c = COLOR.search(m.group(1))
        if not c:
            continue
        rgb = [int(c.group(1)[i:i+2], 16) for i in (0, 2, 4)]
        if colors is not None and c.group(1).lower() not in colors:
            continue
        if colors is None and c.group(1).lower() not in ('80aaff', '7bedb6') and (min(rgb) < 180 or max(rgb) - min(rgb) > 30):
            continue
        raw = re.sub(r'<br\s*/?\s*>', '\n', m.group(2), flags=re.I)
        raw = html.unescape(TAGS.sub('', raw)).strip()
        speaker, sep, message = raw.partition('>')
        if not sep:
            speaker, message = '', raw
        if JAPANESE.search(message) and len(message.strip()) >= 2:
            records.append((speaker.strip(), message.strip()))
    return records, end


def translate(text, key, on_usage=None):
    lines = text.split('\n')
    prompt = ('将游戏日文翻成简体中文，保留人名地名和阿拉伯数字。返回JSON对象：'
              'full为整段自然译文；lines为逐行对应的中文字符串数组，长度与原文行数一致。'
              '逐行译文按照上下文连起来通顺，不要增删行。原文：\n' + text)
    body = json.dumps({'model': MODEL, 'stream': False, 'thinking': {'type': 'disabled'},
                       'response_format': {'type': 'json_object'}, 'temperature': 0.1,
                       'max_tokens': 1000, 'messages': [{'role': 'user', 'content': prompt}]}).encode('utf-8')
    req = urllib.request.Request('https://api.deepseek.com/chat/completions', body,
                                 {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.load(response)
    if on_usage is not None:
        on_usage(result.get('usage'))
    choice = result['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('模型未返回完整译文')
    obj = json.loads(choice['message']['content'])
    answer, segments = obj.get('full'), obj.get('lines')
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('模型没有返回完整译文')
    answer = answer.strip()
    if sorted(re.findall(r'\d+', text)) != sorted(re.findall(r'\d+', answer)):
        raise ValueError('译文中的数字与原文不一致')
    valid_segments = (isinstance(segments, list) and len(lines) == len(segments)
                      and all(isinstance(s, str) and s.strip() and '\n' not in s and '\r' not in s for s in segments))
    if valid_segments:
        valid_segments = sorted(re.findall(r'\d+', text)) == sorted(re.findall(r'\d+', ''.join(segments)))
    # A valid whole translation remains useful even if the model split the
    # output differently. Only publish per-line mappings when alignment is safe.
    return answer, [s.strip() for s in segments] if valid_segments else None


def record_usage(stats, usage):
    stats['api_responses'] = stats.get('api_responses', 0) + 1
    if not isinstance(usage, dict) or any(not isinstance(usage.get(k), int) or usage[k] < 0 for k in ('prompt_tokens', 'completion_tokens')):
        stats['usage_missing'] = stats.get('usage_missing', 0) + 1
        return
    prompt = usage['prompt_tokens']
    hit = usage.get('prompt_cache_hit_tokens', usage.get('prompt_tokens_details', {}).get('cached_tokens'))
    if not isinstance(hit, int) or not 0 <= hit <= prompt:
        stats['cache_split_missing'] = stats.get('cache_split_missing', 0) + 1
        hit = 0
    stats['input_tokens'] = stats.get('input_tokens', 0) + prompt
    stats['output_tokens'] = stats.get('output_tokens', 0) + usage['completion_tokens']
    stats['provider_hit_tokens'] = stats.get('provider_hit_tokens', 0) + hit
    stats['provider_miss_tokens'] = stats.get('provider_miss_tokens', 0) + prompt - hit


def save_stats(stats):
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATS_PATH.with_suffix('.pending')
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(STATS_PATH)


def publish_story(text, answer, segments):
    lines = text.split('\n')
    if segments is not None and len(lines) != len(segments):
        raise ValueError('原文和译文行数不一致')
    entries = json.loads(CACHE_PATH.read_text(encoding='utf-8')) if CACHE_PATH.exists() else {}
    entries[text] = answer
    for source, target in zip(lines, segments or []):
        if len(lines) > 1 and len(source.strip()) >= 4 and JAPANESE.search(source):
            entries[source] = target
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE_PATH.with_suffix('.pending')
    temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(CACHE_PATH)
    inputs = sorted((ROOT / 'dictionaries').glob('supplement-*.json'))
    compile_dictionary(inputs, BIN / 'live-overlay.bin', variants=True, overlay=True)


class Reader:
    def __init__(self, directory):
        self.directory = directory
        self.offsets = {p: p.stat().st_size for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ('.html', '.txt')} if directory.exists() else {}
        # The game inserts new entries before the existing </BODY></HTML> tail.
        # Anchor after the last complete entry instead of after the closing tags.
        for p in list(self.offsets):
            if p.suffix.lower() == '.html':
                try:
                    with p.open('rb') as f:
                        data = f.read()
                    end = data.lower().rfind(b'</font>')
                    self.offsets[p] = end + len(b'</font>') if end >= 0 else 0
                except OSError:
                    pass
        self.buffers = {}
        self.pending = {}
        self.colors = None
        self.format = 'html'

    def flush(self, path):
        speaker, lines, _ = self.pending.pop(path)
        text = '\n'.join(lines).strip()
        return [(speaker, text)] if len(text) >= 2 and JAPANESE.search(text) else []

    def poll(self):
        found = []
        if not self.directory.exists():
            return found
        for p in sorted((x for x in self.directory.iterdir() if x.is_file() and x.suffix.lower() == '.' + self.format), key=lambda x: x.stat().st_mtime):
            try:
                size = p.stat().st_size
                offset = self.offsets.get(p, 0)
                if size < offset:
                    offset, self.buffers[p] = 0, b''
                    self.pending.pop(p, None)
                with p.open('rb') as f:
                    f.seek(offset)
                    block = f.read()
                    if p.suffix.lower() == '.txt': self.offsets[p] = f.tell()
                if p.suffix.lower() == '.html':
                    # Re-read the uncommitted tail: closing tags may be replaced
                    # by a newly appended FONT element between polls.
                    end = block.lower().rfind(b'</font>')
                    if end >= 0:
                        end += len(b'</font>')
                        records, _ = parse_records(block[:end].decode('utf-8', errors='replace'), self.colors)
                        found.extend(records)
                        self.offsets[p] = offset + end
                    continue
                buf = self.buffers.get(p, b'') + block
                if p.suffix.lower() == '.txt':
                    parts = buf.split(b'\n')
                    self.buffers[p] = parts.pop()[-262144:]
                    for part in parts:
                        line = part.rstrip(b'\r').decode('gb18030', errors='replace').strip()
                        if not line:
                            continue
                        speaker, sep, body = line.partition('>')
                        if sep:
                            if p in self.pending: found.extend(self.flush(p))
                            self.pending[p] = (speaker.strip(), [body.strip()], time.monotonic())
                        elif p in self.pending:
                            name, lines, _ = self.pending[p]
                            lines.append(line)
                            self.pending[p] = (name, lines, time.monotonic())
                        else:
                            self.pending[p] = ('', [line], time.monotonic())
                    if p in self.pending and time.monotonic() - self.pending[p][2] >= 1.5:
                        found.extend(self.flush(p))
                    continue
            except OSError:
                continue
        return found


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('大航海时代剧情字幕 · DeepSeek Flash')
        self.root.geometry('800x400')
        self.root.attributes('-topmost', True)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.configure(bg='#182039')
        self.status = tk.StringVar(value='DeepSeek Flash：默认监听白、蓝、绿色，内容会发送至 DeepSeek。')
        self.usage_text = tk.StringVar()
        self.original = tk.StringVar(value='等待新的日文对话……')
        self.answer = tk.StringVar(value='翻译会显示在这里。')
        tk.Label(self.root, textvariable=self.status, bg='#182039', fg='#9fc2ff', anchor='w', wraplength=650, justify='left').pack(fill='x', padx=14, pady=(10, 4))
        tk.Label(self.root, textvariable=self.original, bg='#182039', fg='#c5cede', anchor='nw', justify='left', wraplength=650, font=('Microsoft YaHei UI', 11)).pack(fill='both', padx=14, pady=4)
        tk.Label(self.root, textvariable=self.answer, bg='#182039', fg='white', anchor='nw', justify='left', wraplength=650, font=('Microsoft YaHei UI', 15)).pack(fill='both', expand=True, padx=14, pady=8)
        self.history = tk.Text(self.root, height=5, bg='#11182c', fg='#dde6f5', wrap='word', font=('Microsoft YaHei UI', 10))
        self.history.pack(fill='both', expand=True, padx=14)
        self.history.configure(state='disabled')
        tk.Label(self.root, textvariable=self.usage_text, bg='#182039', fg='#b8d6ad', anchor='w', justify='left', wraplength=770).pack(fill='x', padx=14)
        controls = tk.Frame(self.root, bg='#182039'); controls.pack(fill='x', padx=14, pady=5)
        self.top = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text='窗口置顶', variable=self.top, command=lambda: self.root.attributes('-topmost', self.top.get())).pack(side='left')
        ttk.Label(controls, text='颜色（留空=白/蓝/绿；逗号分隔）').pack(side='left', padx=(10, 3))
        self.color_input = ttk.Entry(controls, width=18)
        self.color_input.pack(side='left')
        ttk.Button(controls, text='应用', command=self.set_colors).pack(side='left', padx=4)
        self.format_choice = ttk.Combobox(controls, values=('网页 HTML', '文本 TXT'), state='readonly', width=10)
        self.format_choice.current(0)
        self.format_choice.pack(side='right')
        self.format_choice.bind('<<ComboboxSelected>>', self.set_format)
        self.events = queue.Queue(); self.jobs = queue.Queue(maxsize=100); self.stop = threading.Event()
        try:
            self.cache = json.loads(CACHE_PATH.read_text(encoding='utf-8')) if CACHE_PATH.exists() else {}
            if not isinstance(self.cache, dict): self.cache = {}
            self.key = load_key()
            if not self.key: raise ValueError('密钥为空')
        except Exception:
            self.cache, self.key = {}, ''
            self.status.set('无法读取 DeepSeek 密钥，请运行设置DeepSeek密钥.cmd。')
        try:
            self.stats = json.loads(STATS_PATH.read_text(encoding='utf-8')) if STATS_PATH.exists() else {}
            if not isinstance(self.stats, dict): self.stats = {}
        except (OSError, ValueError): self.stats = {}
        self.show_usage()
        self.reader = Reader(LOG_DIR)
        threading.Thread(target=self.watch, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        self.root.after(150, self.update)

    def set_colors(self):
        value = self.color_input.get().strip()
        items = [s.strip().lstrip('#').lower() for s in value.split(',') if s.strip()]
        if any(not re.fullmatch(r'[0-9a-f]{6}', s) for s in items):
            self.status.set('颜色格式错误，请使用例如 d4d4d4,ffffff。')
            return
        self.reader.colors = set(items) if items else None
        self.status.set('颜色筛选已更新；仅影响之后新增的网页日志。')

    def show_usage(self):
        s = self.stats
        hit, miss, out = (s.get('provider_hit_tokens', 0), s.get('provider_miss_tokens', 0), s.get('output_tokens', 0))
        maximum = (hit * .006 + miss * .3 + out * 1.2) / 1000000
        minimum = maximum / 2
        incomplete = s.get('usage_missing', 0) + s.get('cache_split_missing', 0)
        note = '；%d 次用量不完整，估算仅供参考' % incomplete if incomplete else ''
        self.usage_text.set('本地缓存命中 %d 次 | API 返回 %d 次 | 输入 %d token（服务端缓存 %d） | 输出 %d token\n估算 $%.6f–$%.6f（高峰/低谷；不含启用前和其他程序调用%s）' % (s.get('local_hits', 0), s.get('api_responses', 0), s.get('input_tokens', 0), hit, out, minimum, maximum, note))

    def note_api_usage(self, usage):
        record_usage(self.stats, usage)
        save_stats(self.stats)
        self.events.put(('usage', None))

    def set_format(self, _event):
        fmt = 'html' if self.format_choice.current() == 0 else 'txt'
        self.reader.format = fmt
        self.status.set('已切换日志格式；文本日志不包含颜色信息。')

    def watch(self):
        while not self.stop.is_set():
            for speaker, text in self.reader.poll():
                try: self.jobs.put_nowait((speaker, text))
                except queue.Full: self.events.put(('status', '待翻译内容过多，部分新消息已跳过。'))
            self.stop.wait(1)

    def worker(self):
        while not self.stop.is_set():
            try: speaker, text = self.jobs.get(timeout=.5)
            except queue.Empty: continue
            self.events.put(('start', (speaker, text, self.jobs.qsize())))
            try:
                result = self.cache.get(text)
                if not isinstance(result, str) or not result:
                    if not self.key: raise ValueError('未设置 DeepSeek 密钥')
                    result, segments = translate(text, self.key, self.note_api_usage)
                    publish_story(text, result, segments)
                    self.cache[text] = result
                else:
                    self.stats['local_hits'] = self.stats.get('local_hits', 0) + 1
                    save_stats(self.stats)
                    self.events.put(('usage', None))
                self.events.put(('result', result))
            except Exception as exc:
                self.events.put(('result', '翻译失败：' + str(exc)))
            finally: self.jobs.task_done()

    def update(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'start':
                    speaker, text, remaining = value
                    self.original.set((speaker + '：' if speaker else '') + text)
                    self.answer.set('正在翻译……')
                    self.status.set('DeepSeek 翻译中；队列剩余 %d 条。' % remaining)
                elif kind == 'result':
                    self.answer.set(value)
                    self.history.configure(state='normal')
                    self.history.insert('end', self.original.get() + '\n' + value + '\n\n')
                    self.history.see('end')
                    self.history.configure(state='disabled')
                    self.status.set('DeepSeek 字幕；新译文已写入汉化词库，游戏内效果需实测。' if not value.startswith('翻译失败：') else '翻译失败，请检查密钥、余额或网络。')
                elif kind == 'usage': self.show_usage()
                else: self.status.set(value)
        except queue.Empty: pass
        self.root.after(150, self.update)

    def close(self):
        self.stop.set(); self.root.destroy()


if __name__ == '__main__':
    App().root.mainloop()
