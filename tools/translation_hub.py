"""Unified task and story translation desktop interface."""
import json
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import msvcrt
import auto_quest as quest
import story_subtitles as story
from dictionary import load

SETTINGS = story.ROOT / 'userdata' / 'hub-settings.json'


class QuestReader:
    def __init__(self, path):
        self.path, self.previous = path, ''
        self.offset = path.stat().st_size if path.exists() else 0

    def poll(self):
        result = []
        if not self.path.exists(): return result
        if self.path.stat().st_size < self.offset:
            self.offset, self.previous = 0, ''
        with self.path.open('r', encoding='utf-8') as f:
            f.seek(self.offset)
            while True:
                start = f.tell(); line = f.readline()
                if not line.endswith('\n'):
                    f.seek(start); break
                try: text = json.loads(line).get('text', '')
                except (ValueError, AttributeError): self.previous = ''; continue
                if not isinstance(text, str): self.previous = ''; continue
                title, self.previous = self.previous, text
                if not quest.candidate(text): continue
                if (2 <= len(title) <= 32 and '\n' not in title and not title.startswith(('：', ':'))
                    and not re.search(r'[。！？!?]|(?:です|ます|ました)$', title)
                    and story.JAPANESE.search(title)):
                    result.append(('任务标题', title))
                result.append(('任务正文', text))
            self.offset = f.tell()
        return result


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError): return {}


class Hub(story.App):
    def __init__(self):
        self.root = tk.Tk(); self.root.title('大航海时代 · 翻译中心')
        self.root.geometry('1080x760'); self.root.minsize(900, 650)
        self.root.configure(bg='#101827')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.stop = threading.Event(); self.events = queue.Queue(); self.jobs = queue.Queue(100)
        self.active = False; self.busy = False; self.pending = set()
        self.stats = read_json(story.STATS_PATH)
        self.config = read_json(SETTINGS)
        self.reader = story.Reader(story.LOG_DIR); self.quest_reader = QuestReader(quest.LOG)
        self.known = load(sorted((story.ROOT / 'dictionaries').glob('supplement-*.json')))
        self.task_cache = read_json(quest.CACHE)
        self.key = ''
        style = ttk.Style(self.root); style.theme_use('clam')
        style.configure('TFrame', background='#101827')
        style.configure('TLabel', background='#101827', foreground='#e5edf9', font=('Microsoft YaHei UI', 10))
        style.configure('TCheckbutton', background='#101827', foreground='#e5edf9')
        style.configure('TButton', padding=(12, 7), font=('Microsoft YaHei UI', 10))
        base = ttk.Frame(self.root, padding=20); base.pack(fill='both', expand=True)
        ttk.Label(base, text='翻译中心', font=('Microsoft YaHei UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(base, text='任务与剧情统一处理 · 精确匹配词库 · DeepSeek Flash 非思考模式').pack(anchor='w', pady=(2, 14))
        bar = ttk.Frame(base); bar.pack(fill='x')
        self.task_on = tk.BooleanVar(value=self.config.get('task', True))
        self.story_on = tk.BooleanVar(value=self.config.get('story', True))
        ttk.Checkbutton(bar, text='任务翻译', variable=self.task_on).pack(side='left')
        ttk.Checkbutton(bar, text='剧情 / 聊天字幕', variable=self.story_on).pack(side='left', padx=15)
        self.provider = ttk.Combobox(bar, state='readonly', values=('DeepSeek Flash', '本地混元 1.8B'), width=22)
        self.provider.set(self.config.get('provider', 'DeepSeek Flash')); self.provider.pack(side='left', padx=10)
        self.toggle = ttk.Button(bar, text='开始监听', command=self.toggle_run); self.toggle.pack(side='right')
        settings = ttk.Frame(base); settings.pack(fill='x', pady=12)
        ttk.Label(settings, text='剧情颜色').pack(side='left')
        self.color_input = ttk.Entry(settings, width=27); self.color_input.pack(side='left', padx=8)
        self.color_input.insert(0, self.config.get('colors', ''))
        self.format_choice = ttk.Combobox(settings, state='readonly', values=('网页 HTML', '文本 TXT'), width=12)
        self.format_choice.set(self.config.get('format', '网页 HTML')); self.format_choice.pack(side='left')
        ttk.Button(settings, text='加载游戏汉化', command=lambda: self.run_script('Load.ps1', True)).pack(side='right')
        ttk.Button(settings, text='设置密钥', command=self.set_key).pack(side='right', padx=8)
        ttk.Label(base, text='颜色留空：白 / 浅灰、蓝 80aaff、绿 7bedb6。DeepSeek 会接收筛选文字，可能含玩家聊天，并产生费用。', wraplength=1000).pack(anchor='w')
        self.status = tk.StringVar(value='已就绪。先登录游戏并加载汉化，再开始监听。')
        ttk.Label(base, textvariable=self.status, wraplength=1000, foreground='#8dc6ff').pack(fill='x', pady=12)
        self.usage_text = tk.StringVar(); ttk.Label(base, textvariable=self.usage_text, wraplength=1000, foreground='#b3d7ba').pack(fill='x', pady=(0, 12))
        panels = ttk.Panedwindow(base, orient='horizontal'); panels.pack(fill='both', expand=True)
        self.views = []
        for title in ('日文原文', '中文译文'):
            frame = ttk.Frame(panels); panels.add(frame, weight=1)
            ttk.Label(frame, text=title, font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=6)
            text = tk.Text(frame, bg='#1b2940', fg='#edf3ff', insertbackground='white', wrap='word', height=8, font=('Microsoft YaHei UI', 13), relief='flat', padx=12, pady=12)
            text.pack(fill='both', expand=True); text.configure(state='disabled'); self.views.append(text)
        ttk.Label(base, text='运行记录', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=(12, 6))
        self.history = tk.Text(base, height=6, bg='#152033', fg='#bacce5', wrap='word', font=('Microsoft YaHei UI', 10), relief='flat', state='disabled')
        self.history.pack(fill='x')
        footer = ttk.Frame(base); footer.pack(fill='x', pady=(10, 0))
        self.top = tk.BooleanVar(value=False)
        ttk.Checkbutton(footer, text='窗口置顶', variable=self.top, command=lambda: self.root.attributes('-topmost', self.top.get())).pack(side='left')
        ttk.Button(footer, text='打开词库目录', command=lambda: os.startfile(story.ROOT / 'dictionaries')).pack(side='right')
        self.show_usage()
        threading.Thread(target=self.watch, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        self.root.after(100, self.update)

    def run_script(self, name, quiet=False):
        def run():
            args = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(story.ROOT / 'scripts' / name)]
            if quiet: args.append('-NoUi')
            try:
                code = subprocess.call(args, creationflags=subprocess.CREATE_NO_WINDOW if quiet else 0)
                self.events.put(('status', ('汉化加载完成；重开对话查看效果。' if quiet else '密钥设置窗口已关闭，下次开始监听时读取。') if code == 0 else '操作未完成，请检查游戏是否启动及权限。'))
            except Exception as exc: self.events.put(('status', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def set_key(self):
        key = simpledialog.askstring('DeepSeek 密钥', '输入密钥，仅以当前 Windows 账户加密保存：', show='*', parent=self.root)
        if not key: return
        command = "$s=ConvertTo-SecureString ([Console]::In.ReadToEnd().Trim()) -AsPlainText -Force; ConvertFrom-SecureString $s"
        try:
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command], input=key, text=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            quest.KEY_PATH.write_text(result.stdout.strip(), encoding='ascii')
            self.status.set('密钥已加密保存；下次开始监听时生效。')
        except Exception:
            self.status.set('密钥保存失败，请检查当前账户权限后重新点击设置密钥。')

    def toggle_run(self):
        if self.active:
            self.active = False; self.toggle.configure(text='开始监听')
            self.status.set('已暂停接收新文字；已开始的请求会完成并保存。'); return
        if self.busy or not self.jobs.empty():
            self.status.set('请等待上一批请求完成后再修改设置并开始。'); return
        colors = [s.strip().lstrip('#').lower() for s in self.color_input.get().split(',') if s.strip()]
        if any(not re.fullmatch('[0-9a-f]{6}', s) for s in colors):
            self.status.set('颜色请填写六位代码，用英文逗号分隔。'); return
        self.mode = 'deepseek' if self.provider.get() == 'DeepSeek Flash' else 'local-fast'
        if self.mode == 'deepseek':
            try: self.key = quest.load_key()
            except Exception: self.status.set('无法读取密钥，请点击设置密钥。'); return
        self.channels = (self.task_on.get(), self.story_on.get())
        if not any(self.channels): self.status.set('请至少启用一个翻译频道。'); return
        self.reader = story.Reader(story.LOG_DIR); self.reader.colors = set(colors) if colors else None
        self.reader.format = 'txt' if self.format_choice.get() == '文本 TXT' else 'html'
        self.quest_reader = QuestReader(quest.LOG)
        self.config = dict(task=self.channels[0], story=self.channels[1], provider=self.provider.get(), colors=self.color_input.get(), format=self.format_choice.get())
        SETTINGS.parent.mkdir(parents=True, exist_ok=True); SETTINGS.write_text(json.dumps(self.config, ensure_ascii=False), encoding='utf-8')
        self.active = True; self.toggle.configure(text='暂停监听'); self.status.set('监听中，仅处理此刻之后出现的文字。设置修改在下次开始时生效。')

    def watch(self):
        while not self.stop.wait(.8):
            if not self.active: continue
            try:
                items = self.quest_reader.poll() if self.channels[0] else []
                if self.channels[1]: items += [('剧情 · ' + speaker, text) for speaker, text in self.reader.poll()]
                for channel, text in items:
                    if text in self.pending: continue
                    try: self.jobs.put_nowait((channel, text)); self.pending.add(text)
                    except queue.Full: self.events.put(('status', '队列已满，已跳过部分消息。'))
            except Exception as exc: self.events.put(('status', '读取日志失败：' + str(exc)))

    def worker(self):
        while not self.stop.is_set():
            try: channel, text = self.jobs.get(timeout=.5)
            except queue.Empty: continue
            self.busy = True; self.events.put(('start', (channel, text)))
            try:
                result = self.known.get(text)
                cached = bool(result)
                if cached:
                    self.stats['local_hits'] = self.stats.get('local_hits', 0) + 1; story.save_stats(self.stats)
                elif channel.startswith('任务'):
                    result = quest.translate(text, self.key, self.mode, self.note_api_usage)
                    self.task_cache[text] = result; quest.publish(self.task_cache)
                else:
                    if self.mode == 'deepseek': result, segments = story.translate(text, self.key, self.note_api_usage)
                    else: result, segments = quest.translate(text, provider='local-fast'), None
                    story.publish_story(text, result, segments)
                self.known[text] = result
                self.events.put(('done', (result, '缓存命中 · 未调用模型' if cached else '翻译完成 · 词库已保存')))
            except Exception as exc: self.events.put(('done', ('翻译失败：' + str(exc), '失败；请检查模型、网络或密钥')))
            finally:
                self.pending.discard(text); self.busy = False; self.jobs.task_done()

    def update(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'start':
                    channel, text = value; self.status.set(channel + ' · 处理中')
                    self.write(self.views[0], text); self.write(self.views[1], '正在处理……')
                elif kind == 'done':
                    result, status = value; self.write(self.views[1], result); self.status.set(status)
                    self.history.configure(state='normal'); self.history.insert('end', status + '\n' + self.views[0].get('1.0', 'end').strip() + '\n' + result + '\n\n'); self.history.see('end'); self.history.configure(state='disabled'); self.show_usage()
                elif kind == 'usage': self.show_usage()
                else: self.status.set(value)
        except queue.Empty: pass
        self.root.after(100, self.update)

    @staticmethod
    def write(widget, text):
        widget.configure(state='normal'); widget.delete('1.0', 'end'); widget.insert('end', text); widget.configure(state='disabled')

    def close(self):
        if self.busy or not self.jobs.empty():
            messagebox.showinfo('请求处理中', '请先暂停监听，等待当前队列处理完毕再关闭。'); return
        self.stop.set(); self.root.destroy()


if __name__ == '__main__':
    story.BIN.mkdir(parents=True, exist_ok=True)
    lock = (story.BIN / 'translation-hub.lock').open('a+b')
    try:
        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        tk.Tk().withdraw(); messagebox.showinfo('翻译中心', '整合版已在运行，请切换到已有窗口。')
    else: Hub().root.mainloop()
