#!/usr/bin/env python3
"""
宽带下行测试 - CLI 核心引擎
Platform: macOS / Windows (auto-detect)
"""

import hashlib
import json
import os
import platform
import re
import ssl
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import gettempdir
from urllib.request import Request, urlopen, ProxyHandler, build_opener, HTTPSHandler

# ============================================================
# Constants
# ============================================================
VERSION = '1.7.4'
CHUNK_SIZE = 1024 * 1024  # 1MB download chunks
CONFIG_DIR = Path.home() / '.broadband_test'
TEMP_DOWNLOAD_DIR = Path(gettempdir()) / 'broadband_test_dl'

# ============================================================
# Activation Manager (imported from activation.py for consistency)
# ============================================================
from activation import ActivationManager, SECRET_KEY


# ============================================================
# Network Manager
# ============================================================
class NetworkManager:
    """跨平台网络管理 (IP切换/Ping/DHCP恢复)"""

    def __init__(self):
        self._os = platform.system()

    def list_interfaces(self) -> list[str]:
        """列出可用网卡"""
        try:
            if self._os == 'Windows':
                result = subprocess.run(['netsh', 'interface', 'show', 'interface'],
                                        capture_output=True, text=True, timeout=10)
                interfaces = []
                for line in result.stdout.split('\n'):
                    if any(k in line for k in ('已连接', 'Connected', 'Dedicated', 'Enabled')):
                        parts = line.split()
                        if len(parts) >= 4:
                            name = ' '.join(parts[3:]).strip()
                            if name:
                                interfaces.append(name)
                return interfaces if interfaces else ['Ethernet']
            else:
                result = subprocess.run(['networksetup', '-listallnetworkservices'],
                                        capture_output=True, text=True, timeout=10)
                lines = result.stdout.strip().split('\n')
                return [l.strip() for l in lines[1:] if l.strip() and not l.startswith('An asterisk')]
        except Exception:
            return ['Ethernet']

    def get_current_config(self, interface: str) -> dict:
        """获取当前网卡配置"""
        info = {'ip': '', 'subnet': '', 'gateway': '', 'dns': '', 'dhcp': True}
        try:
            if self._os == 'Windows':
                result = subprocess.run(['netsh', 'interface', 'ip', 'show', 'config', interface],
                                        capture_output=True, text=True, timeout=10)
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if 'IP Address' in line and ':' in line:
                        info['ip'] = line.split(':')[-1].strip()
                    elif 'Subnet Prefix' in line or 'Subnet Mask' in line:
                        val = line.split(':')[-1].strip()
                        if '/' in val:
                            prefix = int(val.split('/')[-1].strip())
                            info['subnet'] = self._prefix_to_mask(prefix)
                        else:
                            info['subnet'] = val
                    elif 'Default Gateway' in line and ':' in line:
                        info['gateway'] = line.split(':')[-1].strip()
                    elif 'DHCP enabled' in line.lower():
                        info['dhcp'] = 'yes' in line.lower()
            else:
                result = subprocess.run(['networksetup', '-getinfo', interface],
                                        capture_output=True, text=True, timeout=10)
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('IP address:') or line.startswith('IP 地址:'):
                        info['ip'] = line.split(':')[-1].strip()
                    elif line.startswith('Subnet mask:') or line.startswith('子网掩码:'):
                        info['subnet'] = line.split(':')[-1].strip()
                    elif line.startswith('Router:') or line.startswith('路由器:'):
                        info['gateway'] = line.split(':')[-1].strip()
                # Check DHCP status
                dns_result = subprocess.run(['networksetup', '-getdnsservers', interface],
                                            capture_output=True, text=True, timeout=10)
                dns_out = dns_result.stdout.strip()
                if 'There aren\'t any' not in dns_out:
                    info['dns'] = dns_out.replace('\n', ',')
        except Exception:
            pass
        return info

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        """CIDR前缀转子网掩码"""
        mask = (0xffffffff >> (32 - prefix)) << (32 - prefix)
        return f'{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}'

    def set_static_ip(self, interface: str, ip: str, subnet: str,
                      gateway: str, dns: str) -> tuple[bool, str]:
        """设置静态IP"""
        try:
            if self._os == 'Windows':
                cmd = ['netsh', 'interface', 'ip', 'set', 'address',
                       f'name="{interface}"', 'static', ip, subnet, gateway]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    return False, result.stderr.strip() or result.stdout.strip() or '设置失败（请以管理员身份运行）'
                if dns:
                    servers = [s.strip() for s in dns.split(',') if s.strip()]
                    cmd = ['netsh', 'interface', 'ip', 'set', 'dns',
                           f'name="{interface}"', 'static', servers[0]]
                    subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    for i, s in enumerate(servers[1:], 2):
                        cmd = ['netsh', 'interface', 'ip', 'add', 'dns',
                               f'name="{interface}"', s, f'index={i}']
                        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                return True, f'{interface} -> {ip}'
            else:
                cmd = ['networksetup', '-setmanual', interface, ip, subnet, gateway]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    return False, result.stderr.strip() or '需要管理员权限'
                if dns:
                    servers = [s.strip() for s in dns.split(',') if s.strip()]
                    subprocess.run(['networksetup', '-setdnsservers', interface] + servers,
                                   capture_output=True, text=True, timeout=10)
                return True, f'{interface} -> {ip}'
        except subprocess.TimeoutExpired:
            return False, '命令超时'
        except Exception as e:
            return False, str(e)

    def set_dhcp(self, interface: str) -> tuple[bool, str]:
        """恢复DHCP"""
        try:
            if self._os == 'Windows':
                cmd = ['netsh', 'interface', 'ip', 'set', 'address',
                       f'name="{interface}"', 'dhcp']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                cmd = ['netsh', 'interface', 'ip', 'set', 'dns',
                       f'name="{interface}"', 'dhcp']
                subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    return False, result.stderr.strip() or '恢复DHCP失败'
                return True, f'{interface} 已恢复DHCP'
            else:
                result = subprocess.run(['networksetup', '-setdhcp', interface],
                                        capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    return False, result.stderr.strip() or '需要管理员权限'
                return True, f'{interface} 已恢复DHCP'
        except Exception as e:
            return False, str(e)

    def ping(self, host: str, timeout: float = 2.0) -> bool:
        """Ping网关检测"""
        try:
            if self._os == 'Windows':
                cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), host]
            else:
                cmd = ['ping', '-c', '1', '-W', str(int(timeout)), host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
            return result.returncode == 0
        except Exception:
            return False


# ============================================================
# Download Engine
# ============================================================
class DownloadResult:
    def __init__(self, success: bool, bytes_downloaded: int = 0,
                 speed_mbps: float = 0.0, error: str = ''):
        self.success = success
        self.bytes_downloaded = bytes_downloaded
        self.speed_mbps = speed_mbps
        self.error = error


class DownloadEngine:
    """下载引擎 - 多线程并行、重试、速度测量、临时文件清理"""

    def __init__(self, temp_dir: Path = None):
        self.temp_dir = temp_dir or TEMP_DOWNLOAD_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.stop_flag = threading.Event()
        self._ctx = ssl._create_unverified_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._opener = self._build_opener()

    def _build_opener(self):
        """自动检测代理环境变量，创建URL opener（含不验证SSL的HTTPSHandler）"""
        proxies = {}
        for env_name in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY'):
            val = os.environ.get(env_name, '')
            if val:
                if val.startswith('http://') or val.startswith('https://'):
                    proxies['https'] = val
                    proxies['http'] = val
                    break
        if proxies:
            proxy_handler = ProxyHandler(proxies)
            https_handler = HTTPSHandler(context=self._ctx)
            return build_opener(proxy_handler, https_handler)
        return None

    def download(self, url: str, retry_count: int = 3, threads: int = 1,
                 progress_callback=None, follow_html: bool = False) -> DownloadResult:
        """多线程下载，progress_callback(bytes_total, 0, speed_mbps, status)"""
        if follow_html:
            return self._download_follow_html(url, retry_count, threads, progress_callback)
        if threads <= 1:
            return self._download_single(url, retry_count, progress_callback, False)
        return self._download_multi(url, retry_count, threads, progress_callback, False)

    def _download_follow_html(self, url, retry_count, threads, progress_callback):
        """HTML跟随：先单线程获取真实链接，再多线程下载"""
        if progress_callback:
            progress_callback(0, 0, 0, '解析页面...')
        real_url = self._extract_real_url(url, progress_callback)
        if not real_url:
            if progress_callback:
                progress_callback(0, 0, 0, '未找到下载链接，直接下载页面')
            return self._download_single(url, retry_count, progress_callback, False)
        if progress_callback:
            progress_callback(0, 0, 0, '跳转: %s...' % real_url[:50])
        if threads <= 1:
            return self._download_single(real_url, retry_count, progress_callback, False)
        return self._download_multi(real_url, retry_count, threads, progress_callback, False, referer=url)

    def _download_single(self, url: str, retry_count: int,
                         progress_callback=None, follow_html: bool = False) -> DownloadResult:
        """单线程下载（带重试）"""
        last_error = ''
        for attempt in range(retry_count + 1):
            if self.stop_flag.is_set():
                return DownloadResult(False, 0, 0, '用户停止')
            try:
                result = self._download_one(url, attempt + 1, retry_count + 1,
                                            thread_id=0, progress_callback=progress_callback,
                                            follow_html=follow_html)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
            if attempt < retry_count:
                if progress_callback:
                    progress_callback(0, 0, 0, f'重试 {attempt + 2}/{retry_count + 1}...')
                time.sleep(1)
        return DownloadResult(False, 0, 0, last_error)

    def _extract_real_url(self, html_url: str, progress_callback=None) -> str | None:
        """从HTML页面提取真实下载链接，连接失败会抛异常"""
        if progress_callback:
            progress_callback(0, 0, 0, '解析页面...')
        resp = self._open(html_url, timeout=12)
        content_type = resp.headers.get('Content-Type', '')
        cl = int(resp.headers.get('Content-Length', 0))
        body = resp.read(cl if cl > 0 else 102400)
        resp.close()
        if 'text/html' not in content_type:
            return None
        html = body.decode('utf-8', errors='ignore')
        for p in [r'href="([^"]+\.(?:iso|exe|zip|rar|7z|bin|img|dmg|gz|tar|bz2|xz))"',
                  r"href='([^']+\.(?:iso|exe|zip|rar|7z|bin|img|dmg|gz|tar|bz2|xz))'"]:
            m = re.search(p, html)
            if m:
                real = m.group(1)
                if real.startswith('//'):
                    real = 'https:' + real
                return real
        return None

    def _download_multi(self, url: str, retry_count: int, threads: int,
                         progress_callback=None, follow_html: bool = False,
                         referer: str = None) -> DownloadResult:
        """多线程分片下载——HTTP Range请求，N线程拉同一个文件的不同段落"""
        # 先获取文件大小和类型
        file_size = 0
        content_type = ''
        extra_headers = {}
        if referer:
            extra_headers['Referer'] = referer
        try:
            head_resp = self._open(url, headers=extra_headers, timeout=10, method='HEAD')
            file_size = int(head_resp.headers.get('Content-Length', 0))
            content_type = head_resp.headers.get('Content-Type', '')
            head_resp.close()
        except Exception:
            pass
        # 无法获取大小 → 完整下载
        if file_size == 0:
            return self._download_multi_full(url, retry_count, threads, progress_callback, False)

        # 每个线程下载一个Range分片
        chunk_size = file_size // threads
        lock = threading.Lock()
        thread_bytes = {}
        start_time = time.time()

        def worker(tid):
            start = tid * chunk_size
            end = (file_size - 1) if tid == threads - 1 else ((tid + 1) * chunk_size - 1)
            range_hdr = f'bytes={start}-{end}'
            tf = self.temp_dir / f'dl_r_{hashlib.md5(url.encode()).hexdigest()[:6]}_{tid}.tmp'
            try:
                for attempt in range(retry_count + 1):
                    if self.stop_flag.is_set():
                        return DownloadResult(False, 0, 0, '用户停止')
                    try:
                        hdrs = {'Range': range_hdr}
                        if referer:
                            hdrs['Referer'] = referer
                        r = self._open(url, headers=hdrs, timeout=30)
                        dl = 0
                        with open(tf, 'wb') as f:
                            while True:
                                if self.stop_flag.is_set():
                                    return DownloadResult(False, dl, 0, '用户停止')
                                c = r.read(CHUNK_SIZE)
                                if not c: break
                                f.write(c)
                                dl += len(c)
                                with lock: thread_bytes[tid] = dl
                        with lock: thread_bytes[tid] = dl
                        return DownloadResult(True, dl, 0)
                    except Exception as e:
                        if attempt >= retry_count:
                            return DownloadResult(False, 0, 0, str(e))
                        time.sleep(1)
            finally:
                if tf.exists():
                    try: tf.unlink()
                    except OSError: pass

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {executor.submit(worker, i): i for i in range(threads)}
            while not all(f.done() for f in futures):
                if self.stop_flag.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return DownloadResult(False, sum(thread_bytes.values()), 0, '用户停止')
                total = sum(thread_bytes.values())
                elapsed = time.time() - start_time
                speed = (total * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
                if progress_callback:
                    progress_callback(total, file_size, speed, f'下载中 {speed:.1f} Mbps')
                time.sleep(0.3)
            results = [f.result() for f in futures]

        total = sum(r.bytes_downloaded for r in results)
        elapsed = time.time() - start_time
        speed = (total * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        all_ok = all(r.success for r in results)
        return DownloadResult(all_ok, total, speed,
                             next((r.error for r in results if not r.success), ''))

    def _download_multi_full(self, url, retry_count, threads, progress_callback, follow_html):
        """退路：Range不支持时每个线程下完整文件"""
        lock = threading.Lock()
        thread_bytes = {}
        start_time = time.time()

        def worker(tid):
            for attempt in range(retry_count + 1):
                if self.stop_flag.is_set():
                    return DownloadResult(False, 0, 0, '用户停止')
                try:
                    result = self._download_one(url, attempt + 1, retry_count + 1,
                                                thread_id=tid, progress_callback=None,
                                                follow_html=follow_html)
                    if result.success:
                        with lock: thread_bytes[tid] = result.bytes_downloaded
                        return result
                except Exception as e:
                    pass
                if attempt < retry_count:
                    time.sleep(1)
            return DownloadResult(False, 0, 0, 'all retries failed')

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {executor.submit(worker, i): i for i in range(threads)}
            while not all(f.done() for f in futures):
                if self.stop_flag.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return DownloadResult(False, sum(thread_bytes.values()), 0, '用户停止')
                total = sum(thread_bytes.values())
                el = time.time() - start_time
                sp = (total * 8) / (el * 1_000_000) if el > 0 else 0
                time.sleep(0.3)
            results = [f.result() for f in futures]

        total = sum(r.bytes_downloaded for r in results)
        elapsed = time.time() - start_time
        speed = (total * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        return DownloadResult(all(r.success for r in results), total, speed,
                             next((r.error for r in results if not r.success), ''))

    def _download_one(self, url: str, attempt: int, total_attempts: int,
                      thread_id: int = 0, progress_callback=None,
                      follow_html: bool = False) -> DownloadResult:
        """单连接下载，写入临时文件后立即清理"""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        temp_file = self.temp_dir / f'dl_{url_hash}_{thread_id}_{attempt}.tmp'
        return self._download_urllib(url, attempt, total_attempts,
                                      thread_id, progress_callback, temp_file,
                                      follow_html)

    def _download_win_powershell(self, url, attempt, total_attempts,
                                  thread_id, progress_callback, temp_file):
        """Windows原生PowerShell下载——后台下载+实时进度"""
        ps_file = self.temp_dir / f'dl_ps_{thread_id}_{attempt}.ps1'
        try:
            ps_code = (
                '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12\n'
                '$wc = New-Object System.Net.WebClient\n'
                '$wc.Headers.Add("User-Agent","BandwidthTester/1.0")\n'
                '$wc.DownloadFile($env:DL_URL, $env:DL_PATH)\n'
                'if (Test-Path $env:DL_PATH) {\n'
                '  Write-Output "OK"\n'
                '} else {\n'
                '  Write-Output "FAIL"\n'
                '}'
            )
            with open(ps_file, 'w', encoding='utf-8') as f:
                f.write(ps_code)

            env = dict(os.environ)
            env['DL_URL'] = url
            env['DL_PATH'] = str(temp_file)

            start_time = time.time()
            proc = subprocess.Popen(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', str(ps_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env
            )

            # Poll file size while downloading
            last_bytes = 0
            last_time = start_time
            while proc.poll() is None:
                if self.stop_flag.is_set():
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except: proc.kill()
                    return DownloadResult(False, last_bytes, 0, '用户停止')
                try:
                    if temp_file.exists():
                        current = temp_file.stat().st_size
                        now = time.time()
                        if current != last_bytes:
                            delta_bytes = current - last_bytes
                            delta_time = now - last_time
                            # 最近一段的瞬时速度
                            inst_speed = (delta_bytes * 8) / (delta_time * 1_000_000) if delta_time > 0 else 0
                            # 整体平均速度
                            total_elapsed = now - start_time
                            avg_speed = (current * 8) / (total_elapsed * 1_000_000) if total_elapsed > 0 else 0
                            if progress_callback:
                                elapsed_str = f'{total_elapsed:.0f}s'
                                if total_elapsed > 60:
                                    elapsed_str = f'{total_elapsed/60:.1f}min'
                                progress_callback(current, 0, inst_speed,
                                                  f'下载中 {StatsTracker.format_bytes(current)} '
                                                  f'{inst_speed:.1f}Mbps {elapsed_str} '
                                                  f'({attempt}/{total_attempts})')
                            last_bytes = current
                            last_time = now
                except OSError:
                    pass
                time.sleep(0.8)

            # Download complete — get final stats
            stdout, stderr = proc.communicate(timeout=10)
            elapsed = time.time() - start_time

            if temp_file.exists():
                bytes_downloaded = temp_file.stat().st_size
            else:
                bytes_downloaded = 0

            if bytes_downloaded > 0:
                speed = (bytes_downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
                if progress_callback:
                    progress_callback(bytes_downloaded, bytes_downloaded, speed,
                                      f'下载完成 {StatsTracker.format_bytes(bytes_downloaded)} '
                                      f'耗时 {elapsed:.0f}s ({attempt}/{total_attempts})')
                return DownloadResult(True, bytes_downloaded, speed)

            err = stderr.strip() or '下载返回空数据'
            return DownloadResult(False, bytes_downloaded, 0, err[:200])

        except Exception as e:
            return DownloadResult(False, 0, 0, str(e)[:200])
        finally:
            if temp_file.exists():
                try: temp_file.unlink()
                except OSError: pass
            if ps_file.exists():
                try: ps_file.unlink()
                except OSError: pass

    def _open(self, url, headers=None, timeout=15, method=None):
        """统一URL打开，自动走代理（如已配置环境变量）"""
        hdrs = {'User-Agent': 'BandwidthTester/1.0', 'Accept': '*/*',
                'Connection': 'close'}
        if headers:
            hdrs.update(headers)
        req = Request(url, headers=hdrs)
        if method:
            req.method = method
        if self._opener:
            return self._opener.open(req, timeout=timeout)
        return urlopen(req, context=self._ctx, timeout=timeout)

    def _download_urllib(self, url, attempt, total_attempts,
                          thread_id, progress_callback, temp_file,
                          follow_html=False):
        """urllib下载，可选自动跳转HTML页面"""
        try:
            if progress_callback:
                short_url = url[:60] + ('...' if len(url) > 60 else '')
                progress_callback(0, 0, 0, '正在连接 %s...' % short_url)
            response = self._open(url, timeout=12)
            total_bytes = int(response.headers.get('Content-Length', 0))
            content_type = response.headers.get('Content-Type', '')

            # 可选：从HTML页面提取真实下载链接
            if follow_html and 'text/html' in content_type and (total_bytes == 0 or total_bytes < 102400):
                body = response.read(total_bytes if total_bytes > 0 else 102400)
                html = body.decode('utf-8', errors='ignore')
                real_url = None
                for p in [r'href="([^"]+\.(?:iso|exe|zip|rar|7z|bin|img|dmg|gz|tar|bz2|xz))"',
                          r"href='([^']+\.(?:iso|exe|zip|rar|7z|bin|img|dmg|gz|tar|bz2|xz))'"]:
                    m = __import__('re').search(p, html)
                    if m:
                        real_url = m.group(1)
                        break
                if real_url:
                    if real_url.startswith('//'):
                        real_url = 'https:' + real_url
                    if progress_callback:
                        progress_callback(0, 0, 0, '页面跳转: %s...' % real_url[:50])
                    try: response.close()
                    except: pass
                    resp2 = self._open(real_url, headers={'Referer': url}, timeout=12)
                    total_bytes = int(resp2.headers.get('Content-Length', 0))
                    response = resp2

            start_time = time.time()
            bytes_downloaded = 0
            last_report = start_time

            with open(temp_file, 'wb') as f:
                while True:
                    if self.stop_flag.is_set():
                        return DownloadResult(False, bytes_downloaded, 0, '用户停止')
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    now = time.time()
                    if progress_callback and (now - last_report) >= 0.3:
                        elapsed = now - start_time
                        speed = (bytes_downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
                        progress_callback(bytes_downloaded, total_bytes, speed,
                                          f'下载中 ({attempt}/{total_attempts})')
                        last_report = now

            elapsed = time.time() - start_time
            avg_speed = (bytes_downloaded * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
            return DownloadResult(True, bytes_downloaded, avg_speed)

        except Exception as e:
            return DownloadResult(False, 0, 0, str(e))
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def stop(self):
        self.stop_flag.set()

    def reset(self):
        self.stop_flag.clear()


# ============================================================
# Stats Tracker
# ============================================================
class StatsTracker:
    """流量统计 - 按日期/线路"""

    def __init__(self, stats_file: Path = None):
        self.stats_file = stats_file or (CONFIG_DIR / 'stats.json')
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def add_bytes(self, line_ip: str, bytes_count: int):
        """记录流量"""
        with self._lock:
            stats = self._load()
            today = datetime.now().strftime('%Y-%m-%d')
            if today not in stats:
                stats[today] = {}
            stats[today][line_ip] = stats[today].get(line_ip, 0) + bytes_count
            self._save(stats)

    def get_today_stats(self) -> dict:
        """当日统计 {ip: bytes}"""
        stats = self._load()
        today = datetime.now().strftime('%Y-%m-%d')
        return stats.get(today, {})

    @staticmethod
    def format_bytes(bytes_count: int) -> str:
        if bytes_count >= 1024 ** 3:
            return f'{bytes_count / (1024**3):.2f} GB'
        if bytes_count >= 1024 ** 2:
            return f'{bytes_count / (1024**2):.2f} MB'
        if bytes_count >= 1024:
            return f'{bytes_count / 1024:.2f} KB'
        return f'{bytes_count} B'

    def _load(self) -> dict:
        try:
            if self.stats_file.exists():
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self, data: dict):
        with open(self.stats_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# Config Manager
# ============================================================
class ConfigManager:
    """配置管理 - 导入/导出"""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def export_config(filepath: str, config: dict) -> bool:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    @staticmethod
    def import_config(filepath: str) -> dict:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def parse_task_file(filepath: str) -> list[dict]:
        """
        解析任务文本文件
        格式: URL 备注：xxx 执行：N 重试：N
        或纯URL每行一个
        """
        tasks = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                url = line
                note = ''
                run_count = 1
                retry = 3
                threads = 8
                parts = re.split(r'\s{2,}|\t', line, maxsplit=4)
                if parts:
                    url = parts[0].strip()
                    for p in parts[1:]:
                        p = p.strip()
                        for prefix in ('备注：', '备注:', 'note:', 'note：'):
                            if p.lower().startswith(prefix.lower()):
                                note = p.split('：', 1)[-1].split(':', 1)[-1].strip()
                                break
                        else:
                            for prefix in ('执行：', '执行:', 'runs:', 'runs：'):
                                if p.lower().startswith(prefix.lower()):
                                    try:
                                        run_count = int(p.split('：', 1)[-1].split(':', 1)[-1].strip())
                                    except ValueError:
                                        pass
                                    break
                            else:
                                for prefix in ('重试：', '重试:', 'retry:', 'retry：'):
                                    if p.lower().startswith(prefix.lower()):
                                        try:
                                            retry = int(p.split('：', 1)[-1].split(':', 1)[-1].strip())
                                        except ValueError:
                                            pass
                                        break
                                else:
                                    for prefix in ('线程：', '线程:', 'threads:', 'threads：'):
                                        if p.lower().startswith(prefix.lower()):
                                            try:
                                                threads = int(p.split('：', 1)[-1].split(':', 1)[-1].strip())
                                            except ValueError:
                                                pass
                                            break
                if url:
                    tasks.append({'url': url, 'note': note, 'run_count': run_count, 'retry': retry, 'threads': threads})
        return tasks

    @staticmethod
    def get_default_config() -> dict:
        return {
            'interface': '',
            'subnet_mask': '255.255.255.0',
            'gateway': '192.168.70.1',
            'dns': '114.114.114.114',
            'ip_pool': [],
            'tasks': [],
            'wait_seconds': 5,
            'default_retry': 3,
            'default_threads': 8,
            'cutoff_time': '05:00',
            'schedule_windows': []
        }


# ============================================================
# Checkpoint Manager
# ============================================================
class CheckpointManager:
    """断点续传"""

    def __init__(self, state_file: Path = None):
        self.state_file = state_file or (CONFIG_DIR / 'state.json')
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def has_checkpoint(self) -> bool:
        return self.state_file.exists()

    def save(self, state: dict):
        with self._lock:
            state['timestamp'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

    def load(self) -> dict | None:
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def clear(self):
        try:
            self.state_file.unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# Scheduler
# ============================================================
class Scheduler:
    """定时调度器"""

    def __init__(self, windows: list[list[str]], cutoff_time: str):
        self.windows = windows or []
        self.cutoff_time = cutoff_time

    def is_in_window(self, now: datetime = None) -> bool:
        if not self.windows:
            return True
        if now is None:
            now = datetime.now()
        current = now.hour * 60 + now.minute
        for s, e in self.windows:
            sh, sm = map(int, s.split(':'))
            eh, em = map(int, e.split(':'))
            if sh * 60 + sm <= current < eh * 60 + em:
                return True
        return False

    def next_window_start(self, now: datetime = None) -> datetime | None:
        if not self.windows:
            return None
        if now is None:
            now = datetime.now()
        current = now.hour * 60 + now.minute
        today = now.date()
        candidates = []
        for s, _ in self.windows:
            sh, sm = map(int, s.split(':'))
            start_mins = sh * 60 + sm
            if start_mins > current:
                candidates.append(datetime.combine(today,
                    datetime.min.time().replace(hour=sh, minute=sm)))
            else:
                candidates.append(datetime.combine(today + timedelta(days=1),
                    datetime.min.time().replace(hour=sh, minute=sm)))
        return min(candidates) if candidates else None

    def is_past_cutoff(self, now: datetime = None) -> bool:
        if not self.cutoff_time:
            return False
        if now is None:
            now = datetime.now()
        ch, cm = map(int, self.cutoff_time.split(':'))
        cutoff_mins = ch * 60 + cm
        current_mins = now.hour * 60 + now.minute
        return current_mins >= cutoff_mins


# ============================================================
# Task Runner
# ============================================================
class TaskRunner:
    """任务执行器 - 核心调度引擎"""

    def __init__(self, network: NetworkManager, download: DownloadEngine,
                 stats: StatsTracker, checkpoint: CheckpointManager):
        self.nm = network
        self.de = download
        self.stats = stats
        self.cp = checkpoint
        self.scheduler = None
        self.emergency_stop = threading.Event()
        self._callbacks = []

    def on_event(self, callback):
        self._callbacks.append(callback)

    def _emit(self, event_type: str, data: dict = None):
        for cb in self._callbacks:
            try:
                cb(event_type, data or {})
            except Exception:
                pass

    def run(self, config: dict, resume: bool = False) -> bool:
        ip_pool = config.get('ip_pool', [])
        tasks = config.get('tasks', [])
        wait_sec = config.get('wait_seconds', 5)
        retry_count = config.get('default_retry', 3)
        interface = config.get('interface', '')
        subnet = config.get('subnet_mask', '255.255.255.0')
        gateway = config.get('gateway', '')
        dns = config.get('dns', '')
        windows = config.get('schedule_windows', [])
        cutoff = config.get('cutoff_time', '05:00')
        skip_net = config.get('skip_network', False)

        if not interface:
            self._emit('error', {'message': '未选择网卡'})
            return False
        if not ip_pool:
            self._emit('error', {'message': 'IP池为空'})
            return False
        if not tasks:
            self._emit('error', {'message': '任务列表为空'})
            return False

        self.scheduler = Scheduler(windows, cutoff)
        self.de.reset()
        self.emergency_stop.clear()

        start_line_idx = 0
        start_task_idx = 0
        completed_lines = []

        if resume and self.cp.has_checkpoint():
            state = self.cp.load()
            if state and state.get('config_hash') == self._config_hash(config):
                start_line_idx = state.get('current_line_index', 0)
                start_task_idx = state.get('current_task_index', 0)
                completed_lines = state.get('completed_lines', [])
                self._emit('log', {'message': f'从断点恢复: 线路 {start_line_idx + 1}, 任务 {start_task_idx + 1}'})
            else:
                self._emit('log', {'message': '配置已变更，从头开始'})
                self.cp.clear()

        try:
            for line_idx, line_ip in enumerate(ip_pool):
                if line_idx < start_line_idx:
                    continue
                if line_ip in completed_lines:
                    continue

                if self.emergency_stop.is_set():
                    self._emergency_revert(interface)
                    return False

                if not self._wait_for_schedule():
                    return False

                self._emit('log', {'message': f'切换IP: {line_ip}...'})
                self._emit('line_status', {'ip': line_ip, 'status': 'setting'})

                if not skip_net:
                    ok, msg = self.nm.set_static_ip(interface, line_ip, subnet, gateway, dns)
                    if not ok:
                        self._emit('error', {'message': f'设置IP失败 [{line_ip}]: {msg}'})
                        self._emit('line_status', {'ip': line_ip, 'status': 'error'})
                        continue
                else:
                    self._emit('log', {'message': f'[跳过] 网络切换已禁用，使用当前IP'})

                self._emit('log', {'message': f'等待 {wait_sec} 秒...'})
                self._emit('line_status', {'ip': line_ip, 'status': 'waiting'})

                for i in range(wait_sec):
                    if self.emergency_stop.is_set():
                        self._emergency_revert(interface)
                        return False
                    time.sleep(1)

                self._emit('line_status', {'ip': line_ip, 'status': 'checking'})
                if not skip_net:
                    if not self.nm.ping(gateway):
                        self._emit('log', {'message': f'SKIP [{line_ip}] 网关 {gateway} 不通'})
                        self._emit('line_status', {'ip': line_ip, 'status': 'skipped'})
                        continue
                else:
                    self._emit('log', {'message': f'[跳过] 网关检测'})

                self._emit('log', {'message': f'OK [{line_ip}] 网关可达'})
                self._emit('line_status', {'ip': line_ip, 'status': 'running'})

                for task_idx, task in enumerate(tasks):
                    if line_idx == start_line_idx and task_idx < start_task_idx:
                        continue
                    if self.emergency_stop.is_set():
                        self._emergency_revert(interface)
                        return False
                    if self._check_cutoff():
                        self._emit('log', {'message': '已到截止时间'})
                        self.cp.save({
                            'config_hash': self._config_hash(config),
                            'current_line_index': line_idx,
                            'current_task_index': task_idx,
                            'completed_lines': completed_lines,
                            'ip_pool_snapshot': ip_pool,
                            'tasks_snapshot': tasks
                        })
                        self._revert_dhcp(interface)
                        return True

                    run_count = task.get('run_count', 1)
                    task_retry = task.get('retry', retry_count)
                    task_threads = task.get('threads', config.get('default_threads', 8))
                    task_follow = task.get('follow_html', False)
                    url = task['url']
                    note = task.get('note', '')

                    for run_num in range(run_count):
                        if self.emergency_stop.is_set():
                            self._emergency_revert(interface)
                            return False

                        self._emit('task_start', {
                            'ip': line_ip, 'url': url, 'note': note,
                            'run': run_num + 1, 'total_runs': run_count
                        })
                        self._emit('log', {
                            'message': f'[{line_ip}] 下载: {url}'
                        })

                        _last_log = [0.0]
                        def _progress_cb(b, t, s, st, _line_ip=line_ip, _url=url):
                            self._emit('download_progress', {
                                'ip': _line_ip, 'url': _url,
                                'bytes': b, 'total': t, 'speed': s, 'status': st
                            })
                            # 每3秒写一条日志，让客户看到大文件正在下载
                            now = time.time()
                            if b > 0 and now - _last_log[0] >= 3:
                                _last_log[0] = now
                                if b >= 1024**3:
                                    size_str = f'{b/1024**3:.2f} GB'
                                elif b >= 1024**2:
                                    size_str = f'{b/1024**2:.1f} MB'
                                else:
                                    size_str = f'{b/1024:.1f} KB'
                                # 百分比
                                if t > 0 and b > 0:
                                    pct = b * 100 // t
                                    size_str += f' / {pct}%'
                                self._emit('log', {
                                    'message': f'[{_line_ip}] {size_str} {s:.1f}Mbps {st}'
                                })

                        result = self.de.download(url, task_retry, task_threads, _progress_cb, follow_html=task_follow)

                        if result.success:
                            self.stats.add_bytes(line_ip, result.bytes_downloaded)
                            self._emit('task_complete', {
                                'ip': line_ip, 'url': url, 'bytes': result.bytes_downloaded,
                                'speed': result.speed_mbps, 'success': True
                            })
                            self._emit('log', {
                                'message': f'OK [{line_ip}] {self.stats.format_bytes(result.bytes_downloaded)} '
                                           f'{result.speed_mbps:.1f}Mbps {url}'
                            })
                            if result.bytes_downloaded < 1024:
                                self._emit('log', {
                                    'message': f'  WARNING [{line_ip}] 下载量不足1KB，可能URL不是可下载文件'
                                })
                        else:
                            self._emit('task_complete', {
                                'ip': line_ip, 'url': url, 'success': False, 'error': result.error
                            })
                            self._emit('log', {'message': f'FAIL [{line_ip}] {url}: {result.error}'})
                            if '403' in str(result.error) or 'Forbidden' in str(result.error):
                                self._emit('log', {'message': f'  HINT [{line_ip}] 试试用网页URL+勾选"网页跳转"，自动加Referer头'})
                            break

                    self.cp.save({
                        'config_hash': self._config_hash(config),
                        'current_line_index': line_idx,
                        'current_task_index': task_idx + 1,
                        'completed_lines': completed_lines,
                        'ip_pool_snapshot': ip_pool,
                        'tasks_snapshot': tasks
                    })

                completed_lines.append(line_ip)
                self._emit('line_status', {'ip': line_ip, 'status': 'completed'})
                self._emit('stats_update', {'stats': self.stats.get_today_stats()})
                self.cp.save({
                    'config_hash': self._config_hash(config),
                    'current_line_index': line_idx + 1,
                    'current_task_index': 0,
                    'completed_lines': completed_lines,
                    'ip_pool_snapshot': ip_pool,
                    'tasks_snapshot': tasks
                })

            if not skip_net:
                self._revert_dhcp(interface)
            self.cp.clear()
            self._emit('complete', {'stats': self.stats.get_today_stats()})
            return True

        except Exception as e:
            self._emit('error', {'message': f'运行异常: {e}'})
            if not skip_net:
                self._revert_dhcp(interface)
            return False

    def _emergency_revert(self, interface: str):
        self.de.stop()
        self._emit('log', {'message': 'EMERGENCY STOP! 恢复DHCP...'})
        self.nm.set_dhcp(interface)

    def _revert_dhcp(self, interface: str):
        self._emit('log', {'message': '完成，恢复DHCP...'})
        self.nm.set_dhcp(interface)

    def _wait_for_schedule(self) -> bool:
        if not self.scheduler or not self.scheduler.windows:
            return True
        if self.scheduler.is_in_window():
            return True
        nxt = self.scheduler.next_window_start()
        if nxt:
            self._emit('log', {'message': f'不在执行窗口，等待到 {nxt.strftime("%H:%M:%S")}...'})
            while datetime.now() < nxt:
                if self.emergency_stop.is_set():
                    return False
                time.sleep(1)
        return True

    def _check_cutoff(self) -> bool:
        if not self.scheduler:
            return False
        # 只有设置了定时窗口才检查截止时间
        if not self.scheduler.windows:
            return False
        return self.scheduler.is_past_cutoff()

    @staticmethod
    def _config_hash(config: dict) -> str:
        key_fields = ['ip_pool', 'tasks']
        data = {k: config.get(k, []) for k in key_fields}
        return hashlib.md5(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ============================================================
# Self-test (CLI mode)
# ============================================================
if __name__ == '__main__':
    print(f'宽带下行测试引擎 v1.0')
    print(f'  系统: {platform.system()} {platform.release()}')
    print(f'  配置目录: {CONFIG_DIR}')
    print(f'  临时目录: {TEMP_DOWNLOAD_DIR}')

    nm = NetworkManager()
    interfaces = nm.list_interfaces()
    print(f'  可用网卡: {interfaces}')

    am = ActivationManager()
    ok, expiry, msg = am.check()
    print(f'  激活状态: {msg}')

    cp = CheckpointManager()
    if cp.has_checkpoint():
        state = cp.load()
        print(f'  断点: {state.get("timestamp", "?")}, 线路 {state.get("current_line_index", 0) + 1}')
    else:
        print(f'  断点: 无')

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--gen-code', type=int, metavar='DAYS', help='生成激活码')
    ap.add_argument('--list-if', action='store_true', help='列出网卡')
    ap.add_argument('--verify', type=str, metavar='CODE', help='验证激活码')
    args = ap.parse_args()

    if args.gen_code:
        code = ActivationManager.generate_code(args.gen_code)
        print(f'激活码 ({args.gen_code}天): {code}')
    elif args.list_if:
        for iface in nm.list_interfaces():
            info = nm.get_current_config(iface)
            print(f'  {iface}: {info["ip"]}/{info["subnet"]} gw={info["gateway"]} dhcp={info["dhcp"]}')
    elif args.verify:
        ok, expiry, msg = am.activate(args.verify)
        print(f'验证: {msg}')
