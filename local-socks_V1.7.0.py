#!/usr/bin/env python3
"""
Local SOCKS5 v1.7.0 - failover-прокси с пинг-тестом, автообновлением, фолбеком.
--setup: установка, --monitor: healthcheck, --status: статус, --test: проверка,
--update: автообновление, --ignoreupdate: запретить обновление.
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ============= ПУТИ =============
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "output", "local-socks.log")
CONFIG_OUT_PATH = os.path.join(SCRIPT_DIR, "configs", "local-socks.json")
BACKUP_PATH = os.path.join(SCRIPT_DIR, "configs", "local-socks.backup.json")
XRAY_DEFAULT_DIR = os.path.join(SCRIPT_DIR, "xray")
LOG_MAX_SIZE = 1_000_000
PROCESS_MAX_AGE_HOURS = 12  # Перезапуск если Xray старше

VERSION = "1.7.0"
BUILD_DATE = "2026-08-12"
GITHUB_REPO = "https://github.com/kemchurch-cloud/LS"

def get_check_url():
    return f"https://raw.githubusercontent.com/kemchurch-cloud/LS/refs/heads/main/version.txt"

def get_download_url(version=None):
    v = version or VERSION
    return f"https://raw.githubusercontent.com/kemchurch-cloud/LS/refs/heads/main/local-socks_V{v}.exe"

DEFAULT_CONFIG = {
    "version": VERSION,
    "listen_port": 1080,
    "max_proxies": 20,
    "ping": {
        "enabled": True,
        "timeout_sec": 3,
        "max_workers": 50
    },
    "balancer": {
        "strategy": "leastPing",
        "observatory": {
            "probeUrl": "https://t.me",
            "probeInterval": "5m"
        }
    },
    "xray": {
        "executable": os.path.join(XRAY_DEFAULT_DIR, "xray.exe"),
        "download_url": "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip",
        "debug": False
    },
    "sources": [
        "https://raw.githubusercontent.com/kemchurch-cloud/mProxy/refs/heads/main/failover-tg-top10.txt",
        "https://raw.githubusercontent.com/kemchurch-cloud/mProxy/refs/heads/main/YT+TG.txt"
    ],
    "fallback": {
        "enabled": False,
        "proxy_url": "",
        "tag": "fallback-out"
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": ""
    },
    "healthcheck": {
        "enabled": True,
        "targets": ["https://t.me"],
        "timeout_sec": 12,
        "retry_count": 2
    },
    "schedule": {
        "enabled": True,
        "start_time": "08:00",
        "stop_time": "20:00",
        "refresh_interval_min": 60
    },
    "update": {
        "enabled": True,
        "check_url": get_check_url(),
        "download_url": get_download_url()
    }
}


# ============= ЛОГ =============

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_SIZE:
            bak = LOG_PATH.replace(".log", ".old.log")
            if os.path.exists(bak): os.remove(bak)
            os.rename(LOG_PATH, bak)
    except: pass
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except: pass
    print(line)


# ============= КОНФИГ =============

def merge_config(existing: dict, default: dict) -> dict:
    for key, value in default.items():
        if key not in existing:
            existing[key] = value
            log(f"Добавлено поле: {key}")
        elif isinstance(value, dict) and isinstance(existing.get(key), dict):
            if key == "update":
                existing[key]["check_url"] = get_check_url()
                existing[key]["download_url"] = get_download_url()
            existing[key] = merge_config(existing[key], value)
    return existing

def load_config():
    if not os.path.exists(CONFIG_PATH):
        log("Создаю config.json...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        log(f"Отредактируй {CONFIG_PATH} и запусти снова.")
        sys.exit(0)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "update" in cfg:
        cfg["update"]["check_url"] = get_check_url()
        cfg["update"]["download_url"] = get_download_url()
    cfg = merge_config(cfg, DEFAULT_CONFIG)
    if cfg.get("version") != VERSION:
        cfg["version"] = VERSION
        log(f"Конфиг обновлён до {VERSION}")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


# ============= TELEGRAM =============

def tg_send_socks(cfg, msg: str) -> bool:
    t, c, p = cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"], cfg["listen_port"]
    url = f"https://api.telegram.org/bot{t}/sendMessage?chat_id={c}&text={urllib.parse.quote(msg)}&parse_mode=HTML"
    try:
        r = subprocess.run(["curl.exe", "--socks5", f"127.0.0.1:{p}", url, "--max-time", "10"], capture_output=True, timeout=15)
        return r.returncode == 0
    except: return False

def tg_send_direct(cfg, msg: str) -> bool:
    t, c = cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"]
    url = f"https://api.telegram.org/bot{t}/sendMessage?chat_id={c}&text={urllib.parse.quote(msg)}&parse_mode=HTML"
    try:
        urllib.request.urlopen(url, timeout=10)
        return True
    except: return False

def tg_send(cfg, msg: str):
    if not cfg.get("telegram", {}).get("enabled"): return
    if not cfg["telegram"].get("bot_token") or not cfg["telegram"].get("chat_id"): return
    tg_send_socks(cfg, msg) or tg_send_direct(cfg, msg)

def get_host_info():
    hostname = socket.gethostname()
    try: ip = socket.gethostbyname(hostname)
    except: ip = "unknown"
    return hostname, ip


# ============= АВТООБНОВЛЕНИЕ =============

def check_update(cfg) -> bool:
    if "--ignoreupdate" in sys.argv: return False
    if not cfg.get("update", {}).get("enabled"): return False
    try:
        with urllib.request.urlopen(cfg["update"]["check_url"], timeout=10) as r:
            remote = r.read().decode().strip()
        log(f"GitHub: {remote}, текущая: {VERSION}")
        return remote > VERSION
    except Exception as e:
        log(f"Ошибка проверки обновлений: {e}")
    return False

def do_update(cfg):
    hostname, _ = get_host_info()
    tg_send(cfg, f"🔧 <b>Обновление</b>\nХост: {hostname}")
    if not check_update(cfg) and "--update" not in sys.argv:
        return
    url = cfg["update"]["download_url"]
    exe = sys.executable if getattr(sys, 'frozen', False) else __file__
    new = exe + ".new"
    try:
        log(f"Скачиваю: {url}")
        urllib.request.urlretrieve(url, new)
        if os.path.getsize(new) < 100000: raise Exception("Файл слишком мал")
        old = exe + ".old"
        if os.path.exists(old): os.remove(old)
        os.rename(exe, old)
        os.rename(new, exe)
        log("Обновлено. Перезапуск с --setup...")
        tg_send(cfg, "✅ Обновление завершено")
        # Перезапуск с --setup для обновления задач
        os.execl(exe, exe, "--setup")
    except Exception as e:
        log(f"Ошибка: {e}")
        tg_send(cfg, f"❌ Ошибка: {e}")
        if os.path.exists(new): os.remove(new)


# ============= XRAY =============

def ensure_xray(cfg):
    xray_exe = cfg["xray"]["executable"]
    if not os.path.isabs(xray_exe):
        xray_exe = os.path.join(SCRIPT_DIR, xray_exe)
        cfg["xray"]["executable"] = xray_exe
    if os.path.exists(xray_exe): return True
    log("Скачиваю Xray...")
    zip_path = os.path.join(SCRIPT_DIR, "xray-temp.zip")
    extract_dir = os.path.dirname(xray_exe)
    os.makedirs(extract_dir, exist_ok=True)
    try:
        urllib.request.urlretrieve(cfg["xray"]["download_url"], zip_path)
        with zipfile.ZipFile(zip_path, "r") as z: z.extractall(extract_dir)
        os.remove(zip_path)
        log("Xray установлен")
        return True
    except Exception as e:
        log(f"Ошибка: {e}")
        return False

def get_xray_process_age_hours() -> float:
    """Возвращает возраст процесса xray в часах или 0 если не найден."""
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process xray -ErrorAction SilentlyContinue | Select-Object -First 1).StartTime"],
            capture_output=True, text=True
        )
        if r.stdout.strip():
            start = datetime.strptime(r.stdout.strip()[:19], "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - start).total_seconds() / 3600
    except: pass
    return 0


# ============= ПОРТЫ =============

def wait_port_free(port: int, timeout: int = 15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", port)); s.close()
            time.sleep(1)
        except: return True
    return False

def wait_port_ready(port: int, timeout: int = 10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", port)); s.close()
            return True
        except: time.sleep(0.5)
    return False


# ============= ЗАГРУЗКА + ПАРСИНГ =============

def load_proxies(url: str) -> list:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8-sig")
        return list(dict.fromkeys([l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#") and "://" in l]))
    except Exception as e:
        log(f"Ошибка загрузки {url}: {e}")
        return []

def parse_proxy(raw: str) -> dict:
    for p in ["vless://", "vmess://", "trojan://", "ss://", "hysteria2://"]:
        if raw.startswith(p):
            protocol = p.replace("://", "")
            break
    else: return None
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)
    host, port = None, None
    if protocol in ("vless", "trojan"):
        m = re.search(r'@([^:?]+):(\d+)', raw)
        if m: host, port = m.group(1), int(m.group(2))
    elif protocol == "hysteria2":
        m = re.search(r'://(?:[^@]+@)?([^:?]+):(\d+)', raw)
        if m: host, port = m.group(1), int(m.group(2))
    if not host or not port: return None
    return {"raw": raw, "protocol": protocol, "host": host, "port": port, "username": parsed.username or "", "params": params}


# ============= ПИНГ =============

def tcp_ping(proxy: dict, timeout: int = 3) -> dict:
    try:
        start = time.time()
        s = socket.socket(); s.settimeout(timeout)
        s.connect((proxy["host"], proxy["port"]))
        proxy["ping"] = round((time.time() - start) * 1000)
        s.close()
    except:
        proxy["ping"] = None
    return proxy

def ping_all(proxies: list, timeout: int = 3, workers: int = 50) -> list:
    log(f"Пинг {len(proxies)} прокси (таймаут {timeout}с)...")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(tcp_ping, p, timeout): p for p in proxies}
        for i, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if i % 20 == 0 or i == len(proxies):
                log(f"  {i}/{len(proxies)}")
    alive = sorted([r for r in results if r["ping"] is not None], key=lambda r: r["ping"])
    dead = [r for r in results if r["ping"] is None]
    log(f"  Живых: {len(alive)}, мёртвых: {len(dead)}")
    return alive + dead


# ============= СБОРКА КОНФИГА =============

def build_outbound(proxy: dict, tag: str) -> dict:
    p, h, port, params = proxy["protocol"], proxy["host"], proxy["port"], proxy["params"]
    xp = "hysteria" if p == "hysteria2" else p
    ob = {"tag": tag, "protocol": xp, "settings": {}}
    if p == "vless":
        ob["settings"] = {"vnext": [{"address": h, "port": port, "users": [{"id": proxy["username"], "encryption": params.get("encryption", ["none"])[0], "flow": params.get("flow", [""])[0]}]}]}
        sec = params.get("security", ["none"])[0]
        tr = params.get("type", ["tcp"])[0].replace("raw", "tcp")
        ob["streamSettings"] = {"network": tr, "security": sec}
        if sec == "reality":
            ob["streamSettings"]["realitySettings"] = {"serverName": params.get("sni", [h])[0], "publicKey": params.get("pbk", [""])[0], "shortId": params.get("sid", [""])[0], "fingerprint": params.get("fp", ["chrome"])[0]}
            if params.get("spx", [""])[0]: ob["streamSettings"]["realitySettings"]["spiderX"] = params["spx"][0]
        elif sec == "tls":
            ob["streamSettings"]["tlsSettings"] = {"serverName": params.get("sni", [h])[0], "allowInsecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1", "fingerprint": params.get("fp", ["chrome"])[0]}
        if tr == "ws":
            ws = {"path": urllib.parse.unquote(params.get("path", ["/"])[0])}
            if params.get("host", [None])[0]: ws["headers"] = {"Host": params["host"][0]}
            ob["streamSettings"]["wsSettings"] = ws
    elif p == "trojan":
        ob["settings"] = {"servers": [{"address": h, "port": port, "password": proxy["username"]}]}
        sec = params.get("security", ["tls"])[0]
        tr = params.get("type", ["tcp"])[0]
        ob["streamSettings"] = {"network": tr, "security": sec}
        if sec == "tls":
            ob["streamSettings"]["tlsSettings"] = {"serverName": params.get("sni", [h])[0], "allowInsecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1", "fingerprint": params.get("fp", ["chrome"])[0]}
        if tr == "ws": ob["streamSettings"]["wsSettings"] = {"path": urllib.parse.unquote(params.get("path", ["/"])[0])}
    elif p == "hysteria2":
        ob["settings"] = {"version": 2, "address": h, "port": port, "auth": proxy["username"], "serverName": params.get("sni", [h])[0], "insecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1"}
        if params.get("obfs"): ob["settings"]["obfs"] = {"type": params["obfs"][0], "password": params.get("obfs-password", [""])[0]}
    return ob

def build_config(proxies: list, port: int, strategy: str, observatory: dict, fallback: dict, debug: bool) -> dict:
    outbounds, tags = [], []
    for i, raw in enumerate(proxies):
        px = parse_proxy(raw)
        if px:
            ob = build_outbound(px, f"proxy-{i}")
            if ob:
                outbounds.append(ob)
                tags.append(f"proxy-{i}")
    if not outbounds: return None
    
    # Fallback
    if fallback.get("enabled") and fallback.get("proxy_url"):
        fb = parse_proxy(fallback["proxy_url"])
        if fb:
            ftag = fallback.get("tag", "fallback-out")
            fob = build_outbound(fb, ftag)
            if fob:
                outbounds.append(fob)
                tags.append(ftag)
    
    outbounds.append({"tag": "direct", "protocol": "freedom"})
    tags.append("direct")
    
    config = {
        "log": {"loglevel": "debug" if debug else "warning"},
        "inbounds": [{"tag": "socks-in", "port": port, "listen": "0.0.0.0", "protocol": "socks", "settings": {"auth": "noauth", "udp": True}}],
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch", "balancers": [{"tag": "balancer", "selector": tags, "strategy": {"type": strategy}}], "rules": [{"type": "field", "inboundTag": ["socks-in"], "balancerTag": "balancer"}]}
    }
    if strategy == "leastPing":
        config["observatory"] = {"subjectSelector": tags[:-1], "probeUrl": observatory.get("probeUrl", "https://t.me"), "probeInterval": observatory.get("probeInterval", "5m")}
    return config


# ============= ТЕСТ =============

def test_config(xray_exe, config_path, port):
    log_path = config_path.replace(".json", "_test.log")
    wait_port_free(port, 10)
    try:
        with open(log_path, "w") as lf:
            proc = subprocess.Popen([xray_exe, "run", "-c", config_path], stdout=lf, stderr=lf)
        if not wait_port_ready(port, 8):
            proc.terminate()
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f: err = f.read()
            except: err = "Порт не открылся"
            try: os.remove(log_path)
            except: pass
            return False, err[:500]
        proc.terminate()
        try: os.remove(log_path)
        except: pass
        return True, ""
    except Exception as e:
        try: os.remove(log_path)
        except: pass
        return False, str(e)

def healthcheck(cfg) -> dict:
    """Проверяет все target_url. Возвращает {url: True/False}."""
    if not cfg.get("healthcheck", {}).get("enabled"): return {}
    targets = cfg["healthcheck"].get("targets", ["https://t.me"])
    timeout = cfg["healthcheck"]["timeout_sec"]
    port = cfg["listen_port"]
    results = {}
    for url in targets:
        try:
            r = subprocess.run(
                ["curl.exe", "--socks5", f"127.0.0.1:{port}", url, "-s", "-L", "-o", "NUL", "--max-time", str(timeout)],
                capture_output=True, timeout=timeout+5
            )
            results[url] = r.returncode == 0
        except:
            results[url] = False
    return results

def healthcheck_ok(cfg) -> bool:
    """Все ли target_url доступны?"""
    hc = healthcheck(cfg)
    return all(hc.values()) if hc else True

def stop_xray(port=1080):
    subprocess.run(["taskkill", "/f", "/im", "xray.exe"], capture_output=True)
    time.sleep(2)
    if not wait_port_free(port, 10):
        subprocess.run(["taskkill", "/f", "/t", "/im", "xray.exe"], capture_output=True)
        time.sleep(2)

def start_xray(cfg):
    stop_xray(cfg["listen_port"])
    subprocess.Popen([cfg["xray"]["executable"], "run", "-c", CONFIG_OUT_PATH], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait_port_ready(cfg["listen_port"], 10)


# ============= MAIN =============

def main_refresh(cfg):
    hostname, ip = get_host_info()
    port = cfg["listen_port"]
    strategy = cfg.get("balancer", {}).get("strategy", "leastPing")
    observatory = cfg.get("balancer", {}).get("observatory", {})
    ping_cfg = cfg.get("ping", {"enabled": True, "timeout_sec": 3, "max_workers": 50})
    fallback = cfg.get("fallback", {})
    debug = cfg.get("xray", {}).get("debug", False)
    
    xray_alive = False
    try:
        s = socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", port)); s.close()
        xray_alive = True
    except: pass
    
    if xray_alive:
        tg_send(cfg, f"🔧 <b>Обновление</b>\nХост: {hostname}\nIP: {ip}")
    
    log(f"=== Local SOCKS5 v{VERSION} ===")
    
    if not ensure_xray(cfg):
        tg_send(cfg, "❌ Xray не установлен")
        return
    
    all_proxies = []
    for url in cfg.get("sources", []):
        p = load_proxies(url)
        all_proxies.extend(p)
        log(f"Загружено {len(p)} из {url.split('/')[-1]}")
    
    total_raw = len(all_proxies)
    all_proxies = list(dict.fromkeys(all_proxies))
    log(f"Уникальных: {len(all_proxies)} (из {total_raw})")
    
    if not all_proxies:
        tg_send(cfg, "❌ Нет прокси")
        return
    
    parsed = [parse_proxy(raw) for raw in all_proxies]
    parsed = [p for p in parsed if p]
    
    if ping_cfg.get("enabled", True):
        parsed = ping_all(parsed, ping_cfg.get("timeout_sec", 3), ping_cfg.get("max_workers", 50))
    
    max_p = cfg.get("max_proxies", 20)
    best = parsed[:max_p]
    
    pings = [p["ping"] for p in best if p["ping"] is not None]
    ping_info = f"пинг {min(pings)}-{max(pings)}мс" if pings else "без пинга"
    proxy_info = f"{len(best)}/{len(parsed)} ({ping_info})"
    log(f"Отобрано: {proxy_info}")
    
    raw_best = [p["raw"] for p in best]
    config = build_config(raw_best, port, strategy, observatory, fallback, debug)
    if not config:
        tg_send(cfg, "❌ Не удалось собрать конфиг")
        return
    
    os.makedirs(os.path.dirname(CONFIG_OUT_PATH), exist_ok=True)
    temp_path = CONFIG_OUT_PATH.replace(".json", "_new.json")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    log(f"Тестирование конфига Xray (debug={'on' if debug else 'off'})...")
    stop_xray(port)
    ok, err = test_config(cfg["xray"]["executable"], temp_path, port)
    
    if not ok:
        log(f"НЕВАЛИДЕН: {err[:300]}")
        tg_send(cfg, f"❌ <b>Ошибка конфига</b>\nХост: {hostname}\nПрокси: {proxy_info}\n{err[:200]}")
        try: os.remove(temp_path)
        except: pass
        if os.path.exists(CONFIG_OUT_PATH):
            ok2, _ = test_config(cfg["xray"]["executable"], CONFIG_OUT_PATH, port)
            if ok2:
                stop_xray(port); start_xray(cfg)
                tg_send(cfg, "✅ Запущен предыдущий конфиг")
        return
    
    log("Валиден. Применяем...")
    if os.path.exists(CONFIG_OUT_PATH):
        try: shutil.copy(CONFIG_OUT_PATH, BACKUP_PATH)
        except: pass
    try: os.replace(temp_path, CONFIG_OUT_PATH)
    except: shutil.copy(temp_path, CONFIG_OUT_PATH); os.remove(temp_path)
    
    stop_xray(port)
    if start_xray(cfg):
        log(f"Запущен! {proxy_info}")
        time.sleep(5)
        hc = healthcheck(cfg)
        hc_ok = all(hc.values())
        status = "OK" if hc_ok else "FAIL"
        emoji = "✅" if hc_ok else "⚠️"
        detail = ""
        if not hc_ok:
            detail = "\n".join([f"{'✅' if v else '❌'} {k}" for k, v in hc.items()])
        tg_send(cfg, f"{emoji} <b>Обновление завершено</b>\nВерсия: {VERSION}\nХост: {hostname}\nIP: {ip}\nПрокси: {proxy_info}\nСтратегия: {strategy}\nHealthcheck: {status}\n{detail}")
    else:
        tg_send(cfg, "❌ Не удалось запустить Xray")
        if os.path.exists(BACKUP_PATH):
            shutil.copy(BACKUP_PATH, CONFIG_OUT_PATH)
            if start_xray(cfg): tg_send(cfg, "✅ Откат к предыдущему конфигу")


def run_monitor(cfg):
    # Проверка возраста процесса
    age = get_xray_process_age_hours()
    if age > PROCESS_MAX_AGE_HOURS:
        log(f"Xray старше {PROCESS_MAX_AGE_HOURS}ч ({age:.1f}ч). Принудительный перезапуск.")
        tg_send(cfg, f"⏰ Xray старше {PROCESS_MAX_AGE_HOURS}ч, перезапуск...")
        main_refresh(cfg)
        return
    
    hc = healthcheck(cfg)
    if all(hc.values()):
        sys.exit(0)
    
    log(f"Healthcheck FAIL: {hc}")
    hostname, _ = get_host_info()
    tg_send(cfg, f"⚠️ Healthcheck FAIL\nХост: {hostname}\n" + "\n".join([f"{'❌' if not v else '✅'} {k}" for k, v in hc.items()]))
    stop_xray(cfg["listen_port"])
    if start_xray(cfg):
        time.sleep(5)
        if healthcheck_ok(cfg):
            log("Восстановлено")
            tg_send(cfg, "✅ Восстановлено")
        else:
            tg_send(cfg, "❌ Повторный FAIL\nПолный перезапуск...")
            main_refresh(cfg)
    else:
        main_refresh(cfg)


def run_status(cfg):
    hostname, ip = get_host_info()
    port = cfg["listen_port"]
    print(f"=== Local SOCKS5 v{VERSION} ===")
    print(f"Хост: {hostname} ({ip})\nПорт: {port}")
    try:
        s = socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", port)); s.close()
        age = get_xray_process_age_hours()
        print(f"Xray: запущен ({age:.1f}ч)")
        hc = healthcheck(cfg)
        for url, ok in hc.items():
            print(f"  {'OK' if ok else 'FAIL'}: {url}")
    except:
        print("Xray: НЕ ЗАПУЩЕН")
    print(f"Стратегия: {cfg.get('balancer', {}).get('strategy', 'leastPing')}")
    print(f"Прокси: {cfg.get('max_proxies', 20)} (лимит)")
    print(f"Debug: {'on' if cfg.get('xray', {}).get('debug') else 'off'}")
    print(f"Fallback: {'on' if cfg.get('fallback', {}).get('enabled') else 'off'}")


def run_setup(cfg):
    log("=== Setup ===")
    python_path = sys.executable
    script_path = os.path.abspath(sys.argv[0]) if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
    port = cfg["listen_port"]
    
    def ps(script, desc):
        r = subprocess.run(["powershell", "-Command", f"chcp 65001 >$null; {script}"], capture_output=True, text=True, encoding="utf-8")
        out = (r.stdout or "") + (r.stderr or "")
        if "OK" in out: log(f"{desc}: OK"); return True
        log(f"{desc}: {out.strip()[:150]}"); return False
    
    ps(f"try {{ New-NetFirewallRule -DisplayName 'SOCKS5-LocalProxy' -Direction Inbound -Protocol TCP -LocalPort {port} -Action Allow -ErrorAction Stop | Out-Null; 'OK' }} catch {{ if ($_.Exception.Message -match 'already exists') {{ 'OK-EXISTS' }} else {{ 'ERROR: '+$_.Exception.Message }} }}", f"Фаервол {port}")
    
    if cfg.get("schedule", {}).get("enabled"):
        st, sp, ri = cfg["schedule"]["start_time"], cfg["schedule"]["stop_time"], cfg["schedule"]["refresh_interval_min"]
        for name, tt, tv, desc in [("LocalSocks_Boot","AtStartup","","Start on boot"),("LocalSocks_Start","Daily",st,"Start daily"),("LocalSocks_Stop","Daily",sp,"Stop daily")]:
            tr = "$trigger = New-ScheduledTaskTrigger -AtStartup" if tt=="AtStartup" else f"$trigger = New-ScheduledTaskTrigger -Daily -At '{tv}'"
            ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path}'; {tr}; $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $trigger -Settings $s -User SYSTEM -Description '{desc}' -ErrorAction Stop | Out-Null; 'OK'", f"Задача {name}")
        ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path}'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {ri}); $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName 'LocalSocks_Refresh' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName 'LocalSocks_Refresh' -Action $a -Trigger $t -Settings $s -User SYSTEM -Description 'Refresh' -ErrorAction Stop | Out-Null; 'OK'", f"Refresh ({ri}min)")
    
    if cfg.get("healthcheck", {}).get("enabled"):
        ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path} --monitor'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5); $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName 'LocalSocks_Monitor' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName 'LocalSocks_Monitor' -Action $a -Trigger $t -Settings $s -User SYSTEM -Description 'Monitor' -ErrorAction Stop | Out-Null; 'OK'", "Monitor (5min)")
    
    log("Готово. Проверь taskschd.msc")


def main():
    if "--update" in sys.argv or "--ignoreupdate" not in sys.argv:
        cfg = load_config()
        if check_update(cfg): do_update(cfg)
    
    cfg = load_config()
    
    if "--setup" in sys.argv: run_setup(cfg)
    elif "--monitor" in sys.argv: run_monitor(cfg)
    elif "--status" in sys.argv: run_status(cfg)
    elif "--test" in sys.argv:
        hc = healthcheck(cfg)
        for url, ok in hc.items():
            print(f"{'OK' if ok else 'FAIL'}: {url}")
    else: main_refresh(cfg)

if __name__ == "__main__":
    main()