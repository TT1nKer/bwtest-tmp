#!/usr/bin/env python3
"""
宽带下行测试工具 - Tkinter GUI
跨平台: macOS / Windows
"""

import json
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from engine import (ActivationManager, CheckpointManager, ConfigManager,
                    DownloadEngine, NetworkManager, StatsTracker, TaskRunner)
from engine import VERSION

TITLE = f'宽带下行测试工具 v{VERSION}'


# ============================================================
# Activation Dialog
# ============================================================
class ActivationDialog(tk.Toplevel):
    def __init__(self, parent, activation: ActivationManager):
        super().__init__(parent)
        self.activation = activation
        self.result = None
        self.title('软件激活')
        self.geometry('420x250')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build(self):
        frm = ttk.Frame(self, padding=20)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='请输入激活码', font=('', 14, 'bold')).pack(pady=(0, 5))
        ttk.Label(frm, text='格式: XXXX-XXXX-XXXX-XXXX').pack(pady=(0, 15))

        self.code_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.code_var, font=('', 14),
                          justify='center', width=30)
        entry.pack(pady=(0, 15))
        entry.focus()

        btn_frame = ttk.Frame(frm)
        btn_frame.pack()
        ttk.Button(btn_frame, text='激活', command=self._activate, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text='退出', command=self._on_close, width=10).pack(side=tk.LEFT, padx=5)

        self.msg_var = tk.StringVar(value='')
        lbl = ttk.Label(frm, textvariable=self.msg_var, foreground='red')
        lbl.pack(pady=(15, 0))

        # Allow pasting with cmd/ctrl-v
        entry.bind('<Command-v>', lambda e: entry.event_generate('<<Paste>>'))
        entry.bind('<Control-v>', lambda e: entry.event_generate('<<Paste>>'))

    def _activate(self):
        code = self.code_var.get().strip()
        if not code:
            self.msg_var.set('请输入激活码')
            return
        ok, msg, expiry = self.activation.activate(code)
        if ok:
            self.result = True
            self.destroy()
        else:
            self.msg_var.set(msg)

    def _on_close(self):
        self.result = False
        self.destroy()


# ============================================================
# Task Edit Dialog
# ============================================================
class TaskEditDialog(tk.Toplevel):
    def __init__(self, parent, task: dict = None):
        super().__init__(parent)
        self.result = None
        self.title('编辑任务' if task else '添加任务')
        self.geometry('500x360')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='下载 URL:').pack(anchor=tk.W)
        self.url_var = tk.StringVar(value=task['url'] if task else '')
        ttk.Entry(frm, textvariable=self.url_var, width=60).pack(fill=tk.X, pady=(2, 10))

        ttk.Label(frm, text='备注:').pack(anchor=tk.W)
        self.note_var = tk.StringVar(value=task.get('note', '') if task else '')
        ttk.Entry(frm, textvariable=self.note_var, width=60).pack(fill=tk.X, pady=(2, 10))

        row = ttk.Frame(frm)
        row.pack(fill=tk.X, pady=(5, 5))
        ttk.Label(row, text='执行次数:').pack(side=tk.LEFT)
        self.runs_var = tk.IntVar(value=task.get('run_count', 1) if task else 1)
        ttk.Spinbox(row, from_=1, to=999, textvariable=self.runs_var, width=8).pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(row, text='重试次数:').pack(side=tk.LEFT)
        self.retry_var = tk.IntVar(value=task.get('retry', 3) if task else 3)
        ttk.Spinbox(row, from_=0, to=99, textvariable=self.retry_var, width=8).pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(row, text='线程数:').pack(side=tk.LEFT)
        self.threads_var = tk.IntVar(value=task.get('threads', 1) if task else 1)
        ttk.Spinbox(row, from_=1, to=128, textvariable=self.threads_var, width=8).pack(side=tk.LEFT, padx=5)

        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, pady=(5, 5))
        self.follow_var = tk.BooleanVar(value=task.get('follow_html', False) if task else False)
        ttk.Checkbutton(row2, text='网页跳转（从HTML页面提取真实下载链接，自动加Referer）',
                        variable=self.follow_var).pack(side=tk.LEFT)

        btn_row = ttk.Frame(frm)
        btn_row.pack(pady=(15, 0))
        ttk.Button(btn_row, text='确定', command=self._ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text='取消', command=self._cancel, width=10).pack(side=tk.LEFT, padx=5)

    def _ok(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning('提示', 'URL 不能为空', parent=self)
            return
        self.result = {
            'url': url,
            'note': self.note_var.get().strip(),
            'run_count': self.runs_var.get(),
            'retry': self.retry_var.get(),
            'threads': self.threads_var.get(),
            'follow_html': self.follow_var.get()
        }
        self.destroy()

    def _cancel(self):
        self.destroy()


# ============================================================
# Import Mode Dialog (覆盖/追加)
# ============================================================
class ImportModeDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.mode = None
        self.title('导入模式')
        self.geometry('280x130')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=20)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text='选择任务导入方式:').pack(pady=(0, 15))
        btn_row = ttk.Frame(frm)
        btn_row.pack()
        ttk.Button(btn_row, text='覆盖旧任务', command=lambda: self._choose('overwrite'), width=12).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text='追加到末尾', command=lambda: self._choose('append'), width=12).pack(
            side=tk.LEFT, padx=5)

    def _choose(self, mode):
        self.mode = mode
        self.destroy()


# ============================================================
# Main Application
# ============================================================
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.geometry('1100x800')
        self.root.minsize(900, 600)

        # Engine instances
        self.activation = ActivationManager()
        self.nm = NetworkManager()
        self.de = DownloadEngine()
        self.stats = StatsTracker()
        self.cp = CheckpointManager()
        self.config_mgr = ConfigManager()
        self.runner = TaskRunner(self.nm, self.de, self.stats, self.cp)
        self.runner.on_event(self._on_engine_event)

        self.config = self.config_mgr.get_default_config()
        self._load_saved_config()

        self.running = False
        self.runner_thread = None
        self._error_count = 0
        self._skip_count = 0
        self._done_count = 0

        # Check activation
        if not self._check_activation():
            self.root.destroy()
            return

        self._build_ui()
        self._sync_ui_from_config()  # 把已保存的配置同步到界面控件
        self._refresh_interface_list()
        self._refresh_stats()
        self._check_checkpoint_on_startup()

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ---------- activation ----------
    def _check_activation(self) -> bool:
        ok, expiry, msg = self.activation.check()
        if ok:
            self.root.title(f'{TITLE} - {msg}')
            self._start_activation_timer()
            return True

        dlg = ActivationDialog(self.root, self.activation)
        self.root.wait_window(dlg)
        if dlg.result:
            _, _, msg = self.activation.check()
            self.root.title(f'{TITLE} - {msg}')
            self._start_activation_timer()
            return True
        return False

    def _change_activation(self):
        """帮助菜单：随时更换激活码"""
        dlg = ActivationDialog(self.root, self.activation)
        self.root.wait_window(dlg)
        if dlg.result:
            _, _, msg = self.activation.check()
            self.root.title(f'{TITLE} - {msg}')
            self.act_label.config(text=f'[激活] {msg}', foreground='green')
            messagebox.showinfo('成功', f'激活码已更换\n{msg}')

    def _start_activation_timer(self):
        def _check():
            ok, expiry, msg = self.activation.check()
            if ok:
                self.root.title(f'{TITLE} - {msg}')
                remaining = self.activation.remaining_seconds()
                if 0 < remaining < 86400 * 3:
                    self.act_label.config(text=f'[激活] {msg}', foreground='red')
                else:
                    self.act_label.config(text=f'[激活] {msg}', foreground='green')
            else:
                self.act_label.config(text=f'[激活] {msg}', foreground='red')
                self._disable_controls()
            self.root.after(60000, _check)

        self.root.after(1000, _check)

    def _disable_controls(self):
        for widget in [self.btn_start, self.btn_emergency]:
            try:
                widget.config(state=tk.DISABLED)
            except Exception:
                pass

    # ---------- config persistence ----------
    def _load_saved_config(self):
        cfg_file = Path.home() / '.broadband_test' / 'config.json'
        try:
            if cfg_file.exists():
                with open(cfg_file, 'r') as f:
                    saved = json.load(f)
                    self.config.update(saved)
        except Exception:
            pass

    def _save_config(self):
        cfg_file = Path.home() / '.broadband_test' / 'config.json'
        try:
            with open(cfg_file, 'w') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _sync_ui_from_config(self):
        """把 config 字典同步到界面控件"""
        c = self.config
        if c.get('interface'):
            self.iface_var.set(c['interface'])
        if c.get('subnet_mask'):
            self.subnet_var.set(c['subnet_mask'])
        if c.get('gateway'):
            self.gateway_var.set(c['gateway'])
        if c.get('dns'):
            self.dns_var.set(c['dns'])
        self.wait_var.set(c.get('wait_seconds', 5))
        self.retry_var.set(c.get('default_retry', 3))
        self.threads_var.set(c.get('default_threads', 1))
        self.cutoff_var.set(c.get('cutoff_time', '05:00'))
        self.skip_net_var.set(c.get('skip_network', False))
        self._refresh_ip_tree()
        self._refresh_task_tree()

    def _sync_config_from_ui(self):
        self.config['interface'] = self.iface_var.get()
        self.config['subnet_mask'] = self.subnet_var.get()
        self.config['gateway'] = self.gateway_var.get()
        self.config['dns'] = self.dns_var.get()
        self.config['wait_seconds'] = self.wait_var.get()
        self.config['default_retry'] = self.retry_var.get()
        self.config['default_threads'] = self.threads_var.get()
        self.config['cutoff_time'] = self.cutoff_var.get()
        self.config['skip_network'] = self.skip_net_var.get()
        self._sync_ip_pool()
        self._sync_tasks()
        self._sync_schedule()

    def _sync_ip_pool(self):
        ips = []
        for item in self.ip_tree.get_children():
            vals = self.ip_tree.item(item, 'values')
            if vals:
                ips.append(vals[0])
        self.config['ip_pool'] = ips

    def _sync_tasks(self):
        tasks = []
        for item in self.task_tree.get_children():
            vals = self.task_tree.item(item, 'values')
            if vals and len(vals) >= 7:
                tasks.append({
                    'url': vals[0],
                    'note': vals[1],
                    'run_count': int(vals[2]),
                    'retry': int(vals[3]),
                    'threads': int(vals[4]),
                    'follow_html': vals[6] if len(vals) > 6 else False
                })
        self.config['tasks'] = tasks

    def _sync_schedule(self):
        text = self.schedule_text.get('1.0', 'end-1c').strip()
        windows = []
        if text:
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                parts = line.replace('~', '-').replace('～', '-').replace('—', '-').split('-')
                if len(parts) == 2:
                    windows.append([p.strip() for p in parts])
        self.config['schedule_windows'] = windows

    # ---------- UI build ----------
    def _build_ui(self):
        # Menu
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label='导入IP配置...', command=self._import_ip_config)
        file_menu.add_command(label='导出IP配置...', command=self._export_ip_config)
        file_menu.add_separator()
        file_menu.add_command(label='退出', command=self._on_close)
        menubar.add_cascade(label='文件', menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label='更换激活码', command=self._change_activation)
        help_menu.add_separator()
        help_menu.add_command(label='生成激活码', command=self._show_gen_code)
        help_menu.add_command(label='关于', command=self._show_about)
        menubar.add_cascade(label='帮助', menu=help_menu)
        self.root.config(menu=menubar)

        # Main container
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ---- Row 0: Network config ----
        net_frame = ttk.LabelFrame(main, text='网卡设置', padding=5)
        net_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(net_frame, text='网卡:').pack(side=tk.LEFT)
        self.iface_var = tk.StringVar(value=self.config.get('interface', ''))
        self.iface_combo = ttk.Combobox(net_frame, textvariable=self.iface_var, width=18, state='readonly')
        self.iface_combo.pack(side=tk.LEFT, padx=(2, 10))
        self.iface_combo.bind('<<ComboboxSelected>>', self._on_iface_selected)

        ttk.Label(net_frame, text='掩码:').pack(side=tk.LEFT)
        self.subnet_var = tk.StringVar(value=self.config.get('subnet_mask', '255.255.255.0'))
        ttk.Entry(net_frame, textvariable=self.subnet_var, width=14).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Label(net_frame, text='网关:').pack(side=tk.LEFT)
        self.gateway_var = tk.StringVar(value=self.config.get('gateway', '192.168.70.1'))
        ttk.Entry(net_frame, textvariable=self.gateway_var, width=14).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Label(net_frame, text='DNS:').pack(side=tk.LEFT)
        self.dns_var = tk.StringVar(value=self.config.get('dns', '114.114.114.114'))
        ttk.Entry(net_frame, textvariable=self.dns_var, width=18).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Button(net_frame, text='🔄', width=3, command=self._refresh_interface_list).pack(side=tk.LEFT)

        # ---- Row 1: IP Pool + Tasks (side by side) ----
        mid_frame = ttk.Frame(main)
        mid_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # IP Pool (left)
        ip_frame = ttk.LabelFrame(mid_frame, text='线路 IP 池', padding=3)
        ip_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        ip_cols = ('ip', 'status')
        self.ip_tree = ttk.Treeview(ip_frame, columns=ip_cols, show='headings', height=6)
        self.ip_tree.heading('ip', text='IP 地址')
        self.ip_tree.heading('status', text='状态')
        self.ip_tree.column('ip', width=140)
        self.ip_tree.column('status', width=80)
        ip_scroll = ttk.Scrollbar(ip_frame, orient=tk.VERTICAL, command=self.ip_tree.yview)
        self.ip_tree.configure(yscrollcommand=ip_scroll.set)
        self.ip_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ip_scroll.pack(side=tk.LEFT, fill=tk.Y)

        ip_btn_frame = ttk.Frame(ip_frame)
        ip_btn_frame.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(ip_btn_frame, text='添加', command=self._add_ip).pack(side=tk.LEFT, padx=1)
        ttk.Button(ip_btn_frame, text='删除', command=self._del_ip).pack(side=tk.LEFT, padx=1)
        ttk.Button(ip_btn_frame, text='导入配置', command=self._import_ip_config).pack(side=tk.LEFT, padx=1)
        ttk.Button(ip_btn_frame, text='导出配置', command=self._export_ip_config).pack(side=tk.LEFT, padx=1)

        ttk.Label(ip_btn_frame, text='双击编辑IP').pack(side=tk.RIGHT, padx=5)
        self.ip_tree.bind('<Double-1>', self._edit_ip)

        # Tasks (right)
        task_frame = ttk.LabelFrame(mid_frame, text='下载任务', padding=3)
        task_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(3, 0))

        task_cols = ('url', 'note', 'runs', 'retry', 'threads', 'id', 'follow')
        self.task_tree = ttk.Treeview(task_frame, columns=task_cols, show='headings', height=6)
        self.task_tree.heading('url', text='URL')
        self.task_tree.heading('note', text='备注')
        self.task_tree.heading('runs', text='次数')
        self.task_tree.heading('retry', text='重试')
        self.task_tree.heading('threads', text='线程')
        self.task_tree.heading('id', text='')
        self.task_tree.heading('follow', text='')
        self.task_tree.column('url', width=250)
        self.task_tree.column('note', width=90)
        self.task_tree.column('runs', width=45, anchor=tk.CENTER)
        self.task_tree.column('retry', width=45, anchor=tk.CENTER)
        self.task_tree.column('threads', width=45, anchor=tk.CENTER)
        self.task_tree.column('id', width=0, stretch=False)
        self.task_tree.column('follow', width=0, stretch=False)
        task_scroll = ttk.Scrollbar(task_frame, orient=tk.VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=task_scroll.set)
        self.task_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        task_scroll.pack(side=tk.LEFT, fill=tk.Y)

        task_btn_frame = ttk.Frame(task_frame)
        task_btn_frame.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(task_btn_frame, text='添加', command=self._add_task).pack(side=tk.LEFT, padx=1)
        ttk.Button(task_btn_frame, text='编辑', command=self._edit_task).pack(side=tk.LEFT, padx=1)
        ttk.Button(task_btn_frame, text='删除', command=self._del_task).pack(side=tk.LEFT, padx=1)
        ttk.Button(task_btn_frame, text='导入任务', command=self._import_tasks).pack(side=tk.LEFT, padx=1)
        ttk.Button(task_btn_frame, text='清空', command=self._clear_tasks).pack(side=tk.LEFT, padx=1)

        self.task_tree.bind('<Double-1>', lambda e: self._edit_task())

        # ---- Row 2: Settings ----
        set_frame = ttk.LabelFrame(main, text='执行设置', padding=5)
        set_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(set_frame, text='切换等待(秒):').pack(side=tk.LEFT)
        self.wait_var = tk.IntVar(value=self.config.get('wait_seconds', 5))
        ttk.Spinbox(set_frame, from_=0, to=999, textvariable=self.wait_var, width=5).pack(side=tk.LEFT, padx=(2, 15))

        ttk.Label(set_frame, text='默认重试:').pack(side=tk.LEFT)
        self.retry_var = tk.IntVar(value=self.config.get('default_retry', 3))
        ttk.Spinbox(set_frame, from_=0, to=99, textvariable=self.retry_var, width=5).pack(side=tk.LEFT, padx=(2, 15))

        ttk.Label(set_frame, text='默认线程:').pack(side=tk.LEFT)
        self.threads_var = tk.IntVar(value=self.config.get('default_threads', 8))
        ttk.Spinbox(set_frame, from_=1, to=128, textvariable=self.threads_var, width=5).pack(side=tk.LEFT, padx=(2, 15))

        ttk.Label(set_frame, text='截止时间:').pack(side=tk.LEFT)
        self.cutoff_var = tk.StringVar(value=self.config.get('cutoff_time', '05:00'))
        ttk.Entry(set_frame, textvariable=self.cutoff_var, width=7).pack(side=tk.LEFT, padx=(2, 15))

        ttk.Label(set_frame, text='定时窗口(每行如08:00-12:00):').pack(side=tk.LEFT)
        self.schedule_var = tk.StringVar()
        self.schedule_text = tk.Text(set_frame, height=2, width=30)
        self.schedule_text.pack(side=tk.LEFT, padx=(2, 5), fill=tk.X, expand=True)
        self.schedule_text.insert('1.0', self._windows_to_text(self.config.get('schedule_windows', [])))

        ttk.Separator(set_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        self.skip_net_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(set_frame, text='跳过网络切换（仅测试下载，不断远程）',
                        variable=self.skip_net_var).pack(side=tk.LEFT, padx=5)

        # ---- Row 3: Stats ----
        stats_frame = ttk.LabelFrame(main, text='统计看板（当日下行流量）', padding=3)
        stats_frame.pack(fill=tk.X, pady=(0, 5))

        stats_cols = ('ip', 'traffic', 'speed')
        self.stats_tree = ttk.Treeview(stats_frame, columns=stats_cols, show='headings', height=4)
        self.stats_tree.heading('ip', text='线路 IP')
        self.stats_tree.heading('traffic', text='当日流量')
        self.stats_tree.heading('speed', text='当前速度')
        self.stats_tree.column('ip', width=150)
        self.stats_tree.column('traffic', width=150)
        self.stats_tree.column('speed', width=150)
        self.stats_tree.pack(fill=tk.X)

        # ---- Row 4: Log ----
        log_frame = ttk.LabelFrame(main, text='运行日志', padding=3)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD, state=tk.DISABLED,
                                font=('Consolas', 10))
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.LEFT, fill=tk.Y)

        # ---- Row 5: Controls ----
        ctrl_frame = ttk.Frame(main)
        ctrl_frame.pack(fill=tk.X, pady=(5, 0))

        self.btn_start = ttk.Button(ctrl_frame, text='▶ 开始执行', command=self._start_run, width=14)
        self.btn_start.pack(side=tk.LEFT, padx=2)

        self.btn_stop = ttk.Button(ctrl_frame, text='⏸ 停止', command=self._stop_run, width=10, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=2)

        self.btn_emergency = ttk.Button(ctrl_frame, text='■ 紧急停止', command=self._emergency_stop, width=12)
        self.btn_emergency.pack(side=tk.LEFT, padx=2)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(ctrl_frame, variable=self.progress_var, length=250)
        self.progress_bar.pack(side=tk.LEFT, padx=(15, 5))

        self.status_var = tk.StringVar(value='就绪')
        ttk.Label(ctrl_frame, textvariable=self.status_var, width=25).pack(side=tk.LEFT, padx=5)

        self.act_label = ttk.Label(ctrl_frame, text='', width=25, foreground='gray')
        self.act_label.pack(side=tk.RIGHT, padx=5)

        # Populate data
        self._refresh_ip_tree()
        self._refresh_task_tree()
        self._refresh_stats()

    # ---------- IP pool ----------
    def _refresh_ip_tree(self):
        self.ip_tree.delete(*self.ip_tree.get_children())
        for ip in self.config.get('ip_pool', []):
            self.ip_tree.insert('', tk.END, values=(ip, ''))

    def _add_ip(self):
        dlg = _SimpleInputDialog(self.root, '添加IP', 'IP 地址:',
                                 '192.168.70.' + str(len(self.ip_tree.get_children()) + 2))
        self.root.wait_window(dlg)
        if dlg.result:
            self.ip_tree.insert('', tk.END, values=(dlg.result, ''))
            self._sync_ip_pool()
            self._save_config()

    def _del_ip(self):
        sel = self.ip_tree.selection()
        for s in sel:
            self.ip_tree.delete(s)
        self._sync_ip_pool()
        self._save_config()

    def _edit_ip(self, event=None):
        sel = self.ip_tree.selection()
        if not sel:
            return
        item = sel[0]
        vals = self.ip_tree.item(item, 'values')
        if not vals:
            return
        old_ip = vals[0]
        dlg = _SimpleInputDialog(self.root, '编辑IP', 'IP 地址:', old_ip)
        self.root.wait_window(dlg)
        if dlg.result:
            self.ip_tree.item(item, values=(dlg.result, vals[1]))
            self._sync_ip_pool()
            self._save_config()

    # ---------- tasks ----------
    def _refresh_task_tree(self):
        self.task_tree.delete(*self.task_tree.get_children())
        for i, t in enumerate(self.config.get('tasks', [])):
            self.task_tree.insert('', tk.END,
                                  values=(t['url'], t.get('note', ''), t.get('run_count', 1),
                                          t.get('retry', 3), t.get('threads', 1), i,
                                          t.get('follow_html', False)))

    def _add_task(self):
        dlg = TaskEditDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            idx = len(self.task_tree.get_children())
            self.task_tree.insert('', tk.END,
                                  values=(dlg.result['url'], dlg.result['note'],
                                          dlg.result['run_count'], dlg.result['retry'],
                                          dlg.result['threads'], idx,
                                          dlg.result.get('follow_html', False)))
            self._sync_tasks()
            self._save_config()

    def _edit_task(self):
        sel = self.task_tree.selection()
        if not sel:
            return
        item = sel[0]
        vals = self.task_tree.item(item, 'values')
        if not vals or len(vals) < 6:
            return
        task = {'url': vals[0], 'note': vals[1], 'run_count': int(vals[2]),
                'retry': int(vals[3]), 'threads': int(vals[4]),
                'follow_html': vals[6] if len(vals) > 6 else False}
        dlg = TaskEditDialog(self.root, task)
        self.root.wait_window(dlg)
        if dlg.result:
            self.task_tree.item(item, values=(dlg.result['url'], dlg.result['note'],
                                              dlg.result['run_count'], dlg.result['retry'],
                                              dlg.result['threads'], vals[5],
                                              dlg.result.get('follow_html', False)))
            self._sync_tasks()
            self._save_config()

    def _del_task(self):
        sel = self.task_tree.selection()
        for s in sel:
            self.task_tree.delete(s)
        self._sync_tasks()
        self._save_config()

    def _clear_tasks(self):
        if messagebox.askyesno('确认', '确定清空所有任务？'):
            self.task_tree.delete(*self.task_tree.get_children())
            self._sync_tasks()
            self._save_config()

    def _import_tasks(self):
        fp = filedialog.askopenfilename(
            title='导入任务文件',
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')]
        )
        if not fp:
            return

        try:
            new_tasks = self.config_mgr.parse_task_file(fp)
            if not new_tasks:
                messagebox.showwarning('提示', '文件中未解析到有效任务')
                return

            dlg = ImportModeDialog(self.root)
            self.root.wait_window(dlg)

            if dlg.mode == 'overwrite':
                self.task_tree.delete(*self.task_tree.get_children())
                self.config['tasks'] = new_tasks
            elif dlg.mode == 'append':
                self.config['tasks'].extend(new_tasks)
            else:
                return

            self._refresh_task_tree()
            self._save_config()
            self._log(f'导入 {len(new_tasks)} 个任务 ({dlg.mode})')
        except Exception as e:
            messagebox.showerror('导入失败', str(e))

    # ---------- config import/export ----------
    def _import_ip_config(self):
        fp = filedialog.askopenfilename(
            title='导入IP配置文件',
            filetypes=[('JSON文件', '*.json'), ('所有文件', '*.*')]
        )
        if not fp:
            return
        try:
            imported = self.config_mgr.import_config(fp)
            # Merge relevant fields
            for key in ('ip_pool', 'subnet_mask', 'gateway', 'dns', 'interface',
                        'wait_seconds', 'default_retry', 'default_threads',
                        'cutoff_time', 'schedule_windows'):
                if key in imported:
                    if key == 'ip_pool':
                        self.config['ip_pool'] = imported[key]
                        self._refresh_ip_tree()
                    elif key == 'schedule_windows':
                        self.config['schedule_windows'] = imported[key]
                        self.schedule_text.delete('1.0', tk.END)
                        self.schedule_text.insert('1.0', self._windows_to_text(imported[key]))
                    elif key == 'interface':
                        self.config[key] = imported[key]
                        self.iface_var.set(imported[key])
                    elif key == 'subnet_mask':
                        self.subnet_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'gateway':
                        self.gateway_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'dns':
                        self.dns_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'wait_seconds':
                        self.wait_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'default_retry':
                        self.retry_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'default_threads':
                        self.threads_var.set(imported[key])
                        self.config[key] = imported[key]
                    elif key == 'cutoff_time':
                        self.cutoff_var.set(imported[key])
                        self.config[key] = imported[key]

            # Optionally import tasks
            if 'tasks' in imported and imported['tasks']:
                dlg = ImportModeDialog(self.root)
                self.root.wait_window(dlg)
                if dlg.mode == 'overwrite':
                    self.config['tasks'] = imported['tasks']
                elif dlg.mode == 'append':
                    self.config['tasks'].extend(imported['tasks'])
                else:
                    return
                self._refresh_task_tree()

            self._save_config()
            self._log('配置导入成功')
            messagebox.showinfo('成功', '配置导入成功')
        except Exception as e:
            messagebox.showerror('导入失败', str(e))

    def _export_ip_config(self):
        self._sync_config_from_ui()
        fp = filedialog.asksaveasfilename(
            title='导出IP配置文件',
            defaultextension='.json',
            filetypes=[('JSON文件', '*.json')]
        )
        if not fp:
            return
        if self.config_mgr.export_config(fp, self.config):
            self._log(f'配置已导出至 {fp}')
            messagebox.showinfo('成功', f'配置已导出至:\n{fp}')
        else:
            messagebox.showerror('失败', '导出失败')

    # ---------- interface ----------
    def _refresh_interface_list(self):
        interfaces = self.nm.list_interfaces()
        self.iface_combo['values'] = interfaces
        if not self.iface_var.get() and interfaces:
            self.iface_var.set(interfaces[0])
            self.config['interface'] = interfaces[0]

    def _on_iface_selected(self, event=None):
        iface = self.iface_var.get()
        info = self.nm.get_current_config(iface)
        self._log(f'当前 {iface}: IP={info["ip"]}, GW={info["gateway"]}, DHCP={info["dhcp"]}')

    # ---------- stats ----------
    def _refresh_stats(self):
        self.stats_tree.delete(*self.stats_tree.get_children())
        today_stats = self.stats.get_today_stats()
        # 显示 IP 池中所有线路（包括还没下载的）
        for ip in self.config.get('ip_pool', []):
            b = today_stats.get(ip, 0)
            self.stats_tree.insert('', tk.END, values=(ip, self.stats.format_bytes(b) if b else '0 B', '-'))

    # ---------- log ----------
    def _log(self, msg: str):
        now = datetime.now().strftime('%H:%M:%S')
        line = f'[{now}] {msg}\n'
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ---------- engine events ----------
    def _on_engine_event(self, event_type: str, data: dict):
        """Called from runner thread -> schedule on main thread"""
        self.root.after(0, self._handle_event, event_type, data)

    def _handle_event(self, event_type: str, data: dict):
        if event_type == 'log':
            self._log(data.get('message', ''))
        elif event_type == 'error':
            self._log(f'[错误] {data.get("message", "")}')
            self._error_count += 1
            # 第一个改IP错误弹窗提醒（可能是没管理员权限）
            msg = data.get('message', '')
            if '设置IP失败' in msg and self._error_count == 1:
                messagebox.showwarning('执行失败',
                    f'{msg}\n\n可能原因：\n'
                    '1. 没有以管理员身份运行（请右键exe→以管理员身份运行）\n'
                    '2. 网卡名称不正确\n'
                    '3. IP/网关配置不匹配')
        elif event_type == 'line_status':
            ip = data.get('ip', '')
            status = data.get('status', '')
            status_map = {
                'setting': '设置IP中', 'waiting': '等待中', 'checking': '检测网关',
                'running': '执行中', 'completed': '已完成', 'skipped': '已跳过',
                'error': '失败'
            }
            self._update_ip_status(ip, status_map.get(status, status))
            if status == 'skipped':
                self._skip_count += 1
            elif status == 'completed':
                self._done_count += 1
        elif event_type == 'task_start':
            self._log(f'[{data.get("ip")}] 任务{data.get("run")}/{data.get("total_runs")}: '
                      f'{data.get("url")}')
        elif event_type == 'task_complete':
            if data.get('success'):
                self._log(f'[{data.get("ip")}] 完成 '
                          f'{StatsTracker.format_bytes(data.get("bytes", 0))} '
                          f'{data.get("speed", 0):.1f}Mbps')
            else:
                self._log(f'[{data.get("ip")}] 失败: {data.get("error", "?")}')
            # 只更新对应 IP 的累计流量，不刷掉其他行的实时速度
            self._update_stat_traffic(data.get('ip', ''))
        elif event_type == 'stats_update':
            self._refresh_stats()
        elif event_type == 'complete':
            self._refresh_stats()
            self._log('===== 全部任务执行完毕 =====')
            self._set_running(False)
            total_lines = len(self.config.get('ip_pool', []))
            if self._done_count == 0 and total_lines > 0:
                messagebox.showwarning('执行完毕',
                    f'所有 {total_lines} 条线路均未成功执行。\n\n'
                    f'跳过: {self._skip_count} 条\n'
                    f'失败: {self._error_count} 条\n\n'
                    f'请检查:\n'
                    f'1. 是否以管理员身份运行\n'
                    f'2. IP/网关配置是否正确\n'
                    f'3. 网关是否能Ping通\n'
                    f'4. 下载链接是否有效')
            else:
                messagebox.showinfo('完成', '所有线路任务执行完毕，网卡已恢复DHCP')
            self._error_count = 0
            self._skip_count = 0
            self._done_count = 0
        elif event_type == 'download_progress':
            self._update_stats_speed(data.get('ip', ''), data.get('speed', 0),
                                     data.get('bytes', 0), data.get('total', 0))

    def _update_ip_status(self, ip: str, status: str):
        for item in self.ip_tree.get_children():
            vals = self.ip_tree.item(item, 'values')
            if vals and vals[0] == ip:
                self.ip_tree.item(item, values=(ip, status))
                break

    def _update_stats_speed(self, ip: str, speed: float, bytes_count: int = 0, total: int = 0):
        traffic = StatsTracker.format_bytes(bytes_count) if bytes_count else '-'
        if total > 0 and bytes_count > 0:
            pct = bytes_count * 100 // total
            total_str = StatsTracker.format_bytes(total)
            traffic = f'{traffic} / {total_str} ({pct}%)'
        for item in self.stats_tree.get_children():
            vals = self.stats_tree.item(item, 'values')
            if vals and vals[0] == ip:
                self.stats_tree.item(item,
                    values=(ip, traffic, f'{speed:.1f} Mbps' if speed else '-'))
                break
        else:
            self.stats_tree.insert('', tk.END,
                values=(ip, traffic, f'{speed:.1f} Mbps' if speed else '-'))

    def _update_stat_traffic(self, ip):
        """只更新累计流量，不覆盖实时速度"""
        today = self.stats.get_today_stats()
        b = today.get(ip, 0)
        traffic = self.stats.format_bytes(b) if b else '0 B'
        for item in self.stats_tree.get_children():
            vals = self.stats_tree.item(item, 'values')
            if vals and vals[0] == ip:
                self.stats_tree.item(item, values=(ip, traffic, vals[2]))
                return
        # 新 IP，插入
        self.stats_tree.insert('', tk.END, values=(ip, traffic, '-'))

    # ---------- run control ----------
    def _check_checkpoint_on_startup(self):
        if self.cp.has_checkpoint():
            state = self.cp.load()
            if state:
                ts = state.get('timestamp', '?')
                li = state.get('current_line_index', 0)
                ti = state.get('current_task_index', 0)
                if messagebox.askyesno('断点续传',
                                       f'检测到未完成的任务:\n'
                                       f'  时间: {ts}\n'
                                       f'  进度: 线路 {li + 1}, 任务 {ti + 1}\n\n'
                                       f'是否从断点继续？\n'
                                       f'(选"否"则从头开始)'):
                    self._resume = True
                    return
        self._resume = False

    def _start_run(self):
        if self.running:
            return

        self._sync_config_from_ui()

        if not self.config.get('interface'):
            messagebox.showwarning('提示', '请先选择网卡')
            return
        if not self.config.get('ip_pool'):
            messagebox.showwarning('提示', '请先添加IP地址')
            return
        if not self.config.get('tasks'):
            messagebox.showwarning('提示', '请先添加下载任务')
            return

        resume = getattr(self, '_resume', False)
        self._resume = False

        self._set_running(True)
        self._error_count = 0
        self._skip_count = 0
        self._done_count = 0
        self._log(f'===== 开始执行 {"(断点续传)" if resume else ""} =====')
        self._log(f'IP池: {self.config["ip_pool"]}')
        self._log(f'任务数: {len(self.config["tasks"])}')

        self.runner_thread = threading.Thread(
            target=self._run_thread, args=(self.config, resume), daemon=True)
        self.runner_thread.start()

    def _run_thread(self, config, resume):
        try:
            success = self.runner.run(config, resume)
            if not success and not self.runner.emergency_stop.is_set():
                self.root.after(0, self._log, '执行异常结束，请检查日志')
        except Exception as e:
            self.root.after(0, self._log, f'运行异常: {e}')
        finally:
            self.root.after(0, self._set_running, False)

    def _stop_run(self):
        self.runner.emergency_stop.set()
        self._log('用户请求停止...')
        self.btn_stop.config(state=tk.DISABLED)

    def _emergency_stop(self):
        self._sync_config_from_ui()
        iface = self.config.get('interface', '')
        if messagebox.askyesno('确认', '紧急停止将:\n1. 中断所有下载\n2. 强制恢复网卡为DHCP\n\n确认执行？'):
            self.runner.emergency_stop.set()
            self.de.stop()
            if iface:
                self.nm.set_dhcp(iface)
                self._log(f'紧急停止！{iface} 已恢复DHCP')
            self._set_running(False)

    def _set_running(self, running: bool):
        self.running = running
        if running:
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.status_var.set('运行中...')
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.start()
        else:
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.status_var.set('就绪')
            self.progress_bar.stop()
            self.progress_bar.config(mode='determinate')

    # ---------- helpers ----------
    @staticmethod
    def _windows_to_text(windows: list[list[str]]) -> str:
        return '\n'.join('-'.join(w) for w in windows) if windows else ''

    def _show_gen_code(self):
        dlg = _GenCodeDialog(self.root)
        self.root.wait_window(dlg)

    def _show_about(self):
        messagebox.showinfo('关于', f'{TITLE}\n\n'
                                    f'跨平台宽带下行测试工具\n'
                                    f'support macOS / Windows\n'
                                    f'系统: {__import__("platform").system()}\n'
                                    f'版本: {VERSION}')

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno('确认', '任务正在运行中，确定退出？'):
                return
            self._emergency_stop()
        self._sync_config_from_ui()
        self._save_config()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ============================================================
# Simple Input Dialog
# ============================================================
class _SimpleInputDialog(tk.Toplevel):
    def __init__(self, parent, title: str, label: str, default: str = ''):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry('300x120')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=label).pack(anchor=tk.W, pady=(0, 5))
        self.entry_var = tk.StringVar(value=default)
        entry = ttk.Entry(frm, textvariable=self.entry_var, width=35)
        entry.pack(fill=tk.X, pady=(0, 10))
        entry.focus()
        entry.select_range(0, tk.END)
        entry.bind('<Return>', lambda e: self._ok())

        btn_row = ttk.Frame(frm)
        btn_row.pack()
        ttk.Button(btn_row, text='确定', command=self._ok, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text='取消', command=self.destroy, width=8).pack(side=tk.LEFT, padx=5)

    def _ok(self):
        val = self.entry_var.get().strip()
        if val:
            self.result = val
            self.destroy()


# ============================================================
# Gen Code Dialog
# ============================================================
class _GenCodeDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title('生成激活码')
        self.geometry('380x220')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=20)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text='生成激活码（仅发行方使用）', font=('', 12, 'bold')).pack(pady=(0, 10))

        row = ttk.Frame(frm)
        row.pack(pady=(0, 10))
        ttk.Label(row, text='有效天数:').pack(side=tk.LEFT)
        self.days_var = tk.IntVar(value=30)
        ttk.Spinbox(row, from_=1, to=9999, textvariable=self.days_var, width=8).pack(side=tk.LEFT, padx=5)

        ttk.Button(frm, text='生成', command=self._generate, width=10).pack(pady=(0, 10))

        self.code_var = tk.StringVar()
        code_entry = ttk.Entry(frm, textvariable=self.code_var, font=('Courier', 16),
                               justify='center', state='readonly', width=28)
        code_entry.pack(pady=(0, 10))

        ttk.Button(frm, text='复制到剪贴板', command=self._copy).pack()

    def _generate(self):
        from engine import ActivationManager
        code = ActivationManager.generate_code(self.days_var.get())
        self.code_var.set(code)

    def _copy(self):
        code = self.code_var.get()
        if code:
            self.clipboard_clear()
            self.clipboard_append(code)
            messagebox.showinfo('提示', '已复制到剪贴板', parent=self)


# ============================================================
# Entry
# ============================================================
def run_gui():
    app = App()
    app.run()


if __name__ == '__main__':
    run_gui()
