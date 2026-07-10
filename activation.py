"""激活码核心 - 独立模块，不依赖 engine.py"""
import hashlib
import hmac
import json
import struct
import time
from datetime import datetime
from pathlib import Path

SECRET_KEY = b'bwtest_2026_secret_key_v1'
CONFIG_DIR = Path.home() / '.broadband_test'


class ActivationManager:
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._act_file = self.config_dir / 'activation.dat'

    @staticmethod
    def generate_code(days: int, secret: bytes = None) -> str:
        if secret is None:
            secret = SECRET_KEY
        expiry = int(time.time()) + days * 86400
        expiry_bytes = struct.pack('>I', expiry)
        sig_hex = hmac.new(secret, expiry_bytes, hashlib.sha256).hexdigest()[:8]
        combined = expiry_bytes + bytes.fromhex(sig_hex)
        code_hex = combined.hex().upper()
        return f'{code_hex[:4]}-{code_hex[4:8]}-{code_hex[8:12]}-{code_hex[12:16]}'

    @staticmethod
    def verify_code(code: str, secret: bytes = None) -> int:
        if secret is None:
            secret = SECRET_KEY
        code = code.replace('-', '').replace(' ', '').upper()
        if len(code) != 16:
            return 0
        try:
            combined = bytes.fromhex(code)
            expiry_bytes = combined[:4]
            sig_bytes = combined[4:]
            expected_sig_hex = hmac.new(secret, expiry_bytes, hashlib.sha256).hexdigest()[:8]
            if sig_bytes.hex().upper() != expected_sig_hex.upper():
                return 0
            return struct.unpack('>I', expiry_bytes)[0]
        except (ValueError, struct.error):
            return 0

    def activate(self, code: str) -> tuple[bool, str, int]:
        code = code.strip()
        expiry = self.verify_code(code)
        if not expiry:
            return False, '激活码无效', 0
        if expiry < time.time():
            return False, '激活码已过期', expiry
        data = {'code_hash': hashlib.sha256(code.encode()).hexdigest(),
                'expiry': expiry, 'activated_at': int(time.time())}
        with open(self._act_file, 'w') as f:
            json.dump(data, f)
        return True, f'激活成功，有效期至 {datetime.fromtimestamp(expiry).strftime("%Y-%m-%d %H:%M")}', expiry

    def check(self) -> tuple[bool, int, str]:
        if not self._act_file.exists():
            return False, 0, '未激活'
        try:
            with open(self._act_file, 'r') as f:
                data = json.load(f)
            expiry = data.get('expiry', 0)
            if expiry < time.time():
                return False, expiry, '已过期'
            remaining = expiry - int(time.time())
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            return True, expiry, f'剩余 {days} 天 {hours} 小时'
        except Exception:
            return False, 0, '激活数据损坏'

    def remaining_seconds(self) -> int:
        ok, expiry, _ = self.check()
        if not ok or expiry == 0:
            return -1
        return max(0, expiry - int(time.time()))
