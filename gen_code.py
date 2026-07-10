#!/usr/bin/env python3
"""
激活码生成工具 - 仅供发行方使用
用法:
    python gen_code.py 30              # 生成30天激活码
    python gen_code.py 365 10          # 生成10个365天激活码
    python gen_code.py 365 --export    # 生成并导出 activation.dat 文件
"""

import sys
import time
from pathlib import Path
from activation import ActivationManager, CONFIG_DIR


def export_activation_file(days: int) -> str:
    """生成 activation.dat 文件"""
    code = ActivationManager.generate_code(days)
    am = ActivationManager()
    ok, msg, expiry = am.activate(code)
    if not ok:
        return f'生成失败: {msg}'

    # 写入到当前目录
    dest = Path('activation.dat')
    src = CONFIG_DIR / 'activation.dat'
    if src.exists():
        with open(src, 'rb') as f:
            dest.write_bytes(f.read())

    return str(dest.resolve())


def main():
    if len(sys.argv) < 2:
        print('用法: python gen_code.py <天数> [数量] [--export]')
        print('示例: python gen_code.py 30')
        print('      python gen_code.py 365 10')
        print('      python gen_code.py 365 --export')
        sys.exit(1)

    days = int(sys.argv[1])

    if '--export' in sys.argv:
        path = export_activation_file(days)
        am = ActivationManager()
        _, _, msg = am.check()
        print(f'导出成功: {path}')
        print(f'有效期:   {msg}')
        print(f'客户将该文件放到 C:\\Users\\用户名\\.broadband_test\\ 即完成激活')
        return

    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    print(f'生成 {count} 个激活码，每个有效期 {days} 天:')
    print('-' * 40)

    for i in range(count):
        code = ActivationManager.generate_code(days)
        print(f'  {i + 1:3d}.  {code}')
        if count > 1 and i < count - 1:
            import time as _time
            _time.sleep(1.2)

    print('-' * 40)
    if days >= 365:
        print(f'有效期约 {days / 365:.1f} 年')
    elif days >= 30:
        print(f'有效期约 {days / 30:.1f} 个月')
    else:
        print(f'有效期 {days} 天')


if __name__ == '__main__':
    main()
