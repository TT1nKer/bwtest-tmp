#!/usr/bin/env python3
"""激活码生成器 - GUI版"""

import tkinter as tk
from tkinter import ttk, messagebox
from activation import ActivationManager
from engine import VERSION


class GenCodeApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f'激活码生成器 v{VERSION}')
        self.root.geometry('440x340')
        self.root.resizable(False, False)

        frm = ttk.Frame(self.root, padding=20)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text=f'激活码生成器 v{VERSION}', font=('', 16, 'bold')).pack(pady=(0, 15))

        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text='有效天数:', width=10).pack(side=tk.LEFT)
        self.days_var = tk.IntVar(value=365)
        ttk.Spinbox(row1, from_=1, to=9999, textvariable=self.days_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(row1, text='天').pack(side=tk.LEFT)

        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text='生成数量:', width=10).pack(side=tk.LEFT)
        self.count_var = tk.IntVar(value=1)
        ttk.Spinbox(row2, from_=1, to=999, textvariable=self.count_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(row2, text='个').pack(side=tk.LEFT)

        self.info_var = tk.StringVar(value='输入天数和数量，点击生成激活码')
        ttk.Label(frm, textvariable=self.info_var, foreground='gray').pack(pady=5)

        ttk.Button(frm, text='生成激活码', command=self._generate, width=16).pack(pady=5)

        ttk.Label(frm, text='生成的激活码:').pack(anchor=tk.W, pady=(10, 0))
        self.output = tk.Text(frm, height=6, font=('Consolas', 11), state=tk.DISABLED)
        self.output.pack(fill=tk.BOTH, expand=True, pady=5)

        ttk.Button(frm, text='复制到剪贴板', command=self._copy_all, width=16).pack(pady=(5, 0))

        self.root.mainloop()

    def _generate(self):
        days = self.days_var.get()
        count = self.count_var.get()
        codes = []
        for i in range(count):
            codes.append(ActivationManager.generate_code(days))
            if count > 1 and i < count - 1:
                import time; time.sleep(1.1)

        self.output.config(state=tk.NORMAL)
        self.output.delete('1.0', tk.END)
        for c in codes:
            self.output.insert(tk.END, f'{c}\n')
        self.output.config(state=tk.DISABLED)

        if days >= 365: unit = f'{days / 365:.1f} 年'
        elif days >= 30: unit = f'{days / 30:.1f} 个月'
        else: unit = f'{days} 天'
        self.info_var.set(f'已生成 {count} 个激活码，每个有效期 {unit}')

    def _copy_all(self):
        text = self.output.get('1.0', 'end-1c')
        if text.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo('提示', '已复制到剪贴板')


if __name__ == '__main__':
    GenCodeApp()
