#!/usr/bin/env python3
"""
宽带下行测试工具 - 入口
用法:
    python main.py              # 启动 GUI
    python main.py --cli        # CLI 模式
    python main.py --gen-code 30  # 生成30天激活码
"""

import sys

if __name__ == '__main__':
    if '--cli' in sys.argv:
        from engine import (ActivationManager, CheckpointManager, ConfigManager,
                            DownloadEngine, NetworkManager, StatsTracker, TaskRunner)
        import json
        from pathlib import Path
        import platform

        print(f'宽带下行测试引擎 CLI v1.0')
        print(f'系统: {platform.system()}')
        print()

        nm = NetworkManager()
        print('可用网卡:')
        for iface in nm.list_interfaces():
            info = nm.get_current_config(iface)
            print(f'  {iface}: IP={info["ip"]}, GW={info["gateway"]}, DHCP={info["dhcp"]}')

        am = ActivationManager()
        ok, expiry, msg = am.check()
        if not ok:
            print(f'[!] 激活状态: {msg}')
            code = input('请输入激活码: ').strip()
            ok2, msg2, _ = am.activate(code)
            if ok2:
                print(f'[OK] {msg2}')
            else:
                print(f'[FAIL] {msg2}')
                sys.exit(1)
        else:
            print(f'[OK] {msg}')

        print()
        cfg_file = Path.home() / '.broadband_test' / 'config.json'
        if cfg_file.exists():
            with open(cfg_file) as f:
                config = json.load(f)
            print(f'配置已加载: {cfg_file}')
            print(f'  IP池: {config.get("ip_pool", [])}')
            print(f'  任务数: {len(config.get("tasks", []))}')
            print(f'  网卡: {config.get("interface", "未设置")}')

            confirm = input('\n按 Enter 开始执行 (Ctrl+C 取消): ')
            if confirm == '':
                de = DownloadEngine()
                st = StatsTracker()
                cp = CheckpointManager()
                runner = TaskRunner(nm, de, st, cp)

                def _log_cb(et, d):
                    msg = d.get('message', '') if et == 'log' else f'[{et}] {d}'
                    print(f'  {msg}')

                runner.on_event(_log_cb)

                resume = cp.has_checkpoint()
                if resume:
                    r = input('检测到断点，是否续传? (y/n): ')
                    resume = r.lower() == 'y'
                    if not resume:
                        cp.clear()

                runner.run(config, resume)
                print('\n执行完成')
        else:
            print(f'配置文件不存在: {cfg_file}')
            print('请先通过 GUI 或手动创建配置')
    else:
        from gui import run_gui
        run_gui()
