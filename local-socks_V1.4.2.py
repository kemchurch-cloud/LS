#!/usr/bin/env python3
"""
Local SOCKS5 v1.4.2 - failover-прокси с автоустановкой, healthcheck, Telegram-уведомлениями.
"""

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
from datetime import datetime

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "output", "local-socks.log")
CONFIG_OUT_PATH = os.path.join(SCRIPT_DIR, "configs", "local-socks.json")
BACKUP_PATH = os.path.join(SCRIPT_DIR, "configs", "local-socks.backup.json")
XRAY_DEFAULT_DIR = os.path.join(SCRIPT_DIR, "xray")

VERSION = "1.4.2"
BUILD_DATE = "2026-08-06"

DEFAULT_CONFIG = {
    "version": VERSION,
    "listen_port": 1080,
    "max_proxies": 20,
    "xray": {
        "executable": os.path.join(XRAY_DEFAULT_DIR, "xray.exe"),
        "download_url": "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
    },
    "sources": [
        "https://raw.githubusercontent.com/kemchurch-cloud/mProxy/refs/heads/main/failover-tg-top10.txt",
        "https://raw.githubusercontent.com/kemchurch-cloud/mProxy/refs/heads/main/YT+TG.txt"
    ],
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": ""
    },
    "healthcheck": {
        "enabled": True,
        "target_url": "https://t.me",
        "timeout_sec": 8,
        "retry_count": 2
    },
    "schedule": {
        "enabled": True,
        "start_time": "08:00",
        "stop_time": "20:00",
        "refresh_interval_min": 60
    }
}


# ============= ЛОГ =============

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass
    print(line)


# ============= КОНФИГ =============

def load_config():
    if not os.path.exists(CONFIG_PATH):
        log("Создаю config.json...")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        log(f"Отредактируй {CONFIG_PATH} и запусти снова.")
        sys.exit(0)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============= TELEGRAM =============

def tg_send_socks(cfg, msg: str) -> bool:
    token = cfg["telegram"]["bot_token"]
    chat_id = cfg["telegram"]["chat_id"]
    port = cfg["listen_port"]
    url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={urllib.parse.quote(msg)}&parse_mode=HTML"
    try:
        r = subprocess.run(["curl.exe", "--socks5", f"127.0.0.1:{port}", url, "--max-time", "10"], capture_output=True, timeout=15)
        return r.returncode == 0
    except:
        return False

def tg_send_direct(cfg, msg: str) -> bool:
    token = cfg["telegram"]["bot_token"]
    chat_id = cfg["telegram"]["chat_id"]
    url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={urllib.parse.quote(msg)}&parse_mode=HTML"
    try:
        urllib.request.urlopen(url, timeout=10)
        return True
    except:
        return False

def tg_send(cfg, msg: str):
    if not cfg.get("telegram", {}).get("enabled"):
        return
    if not cfg["telegram"].get("bot_token") or not cfg["telegram"].get("chat_id"):
        return
    if tg_send_socks(cfg, msg):
        return
    tg_send_direct(cfg, msg)


def get_host_info():
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except:
        ip = "unknown"
    return hostname, ip


# ============= XRAY =============

def ensure_xray(cfg):
    xray_exe = cfg["xray"]["executable"]
    if not os.path.isabs(xray_exe):
        xray_exe = os.path.join(SCRIPT_DIR, xray_exe)
        cfg["xray"]["executable"] = xray_exe
    if os.path.exists(xray_exe):
        return True
    log("Скачиваю Xray...")
    url = cfg["xray"]["download_url"]
    zip_path = os.path.join(SCRIPT_DIR, "xray-temp.zip")
    extract_dir = os.path.dirname(xray_exe)
    os.makedirs(extract_dir, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
        os.remove(zip_path)
        log(f"Xray установлен: {xray_exe}")
        return True
    except Exception as e:
        log(f"Ошибка: {e}")
        return False


# ============= ЗАГРУЗКА ПРОКСИ =============

def load_proxies(url: str) -> list:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8-sig")
        return list(dict.fromkeys([l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#") and "://" in l]))
    except Exception as e:
        log(f"Ошибка загрузки {url}: {e}")
        return []


# ============= ПАРСИНГ + СБОРКА =============

def parse_proxy(raw: str) -> dict:
    for p in ["vless://", "vmess://", "trojan://", "ss://", "hysteria2://"]:
        if raw.startswith(p):
            protocol = p.replace("://", "")
            break
    else:
        return None
    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)
    host, port = None, None
    if protocol in ("vless", "trojan"):
        m = re.search(r'@([^:?]+):(\d+)', raw)
        if m: host, port = m.group(1), int(m.group(2))
    elif protocol == "hysteria2":
        m = re.search(r'://(?:[^@]+@)?([^:?]+):(\d+)', raw)
        if m: host, port = m.group(1), int(m.group(2))
    if not host or not port:
        return None
    return {"raw": raw, "protocol": protocol, "host": host, "port": port, "username": parsed.username or "", "params": params}

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
            if params.get("spx", [""])[0]:
                ob["streamSettings"]["realitySettings"]["spiderX"] = params["spx"][0]
        elif sec == "tls":
            ob["streamSettings"]["tlsSettings"] = {"serverName": params.get("sni", [h])[0], "allowInsecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1", "fingerprint": params.get("fp", ["chrome"])[0]}
        if tr == "ws":
            ws = {"path": urllib.parse.unquote(params.get("path", ["/"])[0])}
            if params.get("host", [None])[0]:
                ws["headers"] = {"Host": params["host"][0]}
            ob["streamSettings"]["wsSettings"] = ws
    elif p == "trojan":
        ob["settings"] = {"servers": [{"address": h, "port": port, "password": proxy["username"]}]}
        sec = params.get("security", ["tls"])[0]
        tr = params.get("type", ["tcp"])[0]
        ob["streamSettings"] = {"network": tr, "security": sec}
        if sec == "tls":
            ob["streamSettings"]["tlsSettings"] = {"serverName": params.get("sni", [h])[0], "allowInsecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1", "fingerprint": params.get("fp", ["chrome"])[0]}
        if tr == "ws":
            ob["streamSettings"]["wsSettings"] = {"path": urllib.parse.unquote(params.get("path", ["/"])[0])}
    elif p == "hysteria2":
        ob["settings"] = {"version": 2, "address": h, "port": port, "auth": proxy["username"], "serverName": params.get("sni", [h])[0], "insecure": params.get("insecure", ["0"])[0] == "1" or params.get("allowInsecure", ["0"])[0] == "1"}
        if params.get("obfs"):
            ob["settings"]["obfs"] = {"type": params["obfs"][0], "password": params.get("obfs-password", [""])[0]}
    return ob

def build_config(proxies: list, port: int) -> dict:
    outbounds, tags = [], []
    for i, raw in enumerate(proxies):
        px = parse_proxy(raw)
        if px:
            tag = f"proxy-{i}"
            ob = build_outbound(px, tag)
            if ob:
                outbounds.append(ob)
                tags.append(tag)
    if not outbounds:
        return None
    outbounds.append({"tag": "direct", "protocol": "freedom"})
    tags.append("direct")
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "socks-in", "port": port, "listen": "0.0.0.0", "protocol": "socks", "settings": {"auth": "noauth", "udp": True}}],
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch", "balancers": [{"tag": "balancer", "selector": tags, "strategy": {"type": "random"}}], "rules": [{"type": "field", "inboundTag": ["socks-in"], "balancerTag": "balancer"}]}
    }


# ============= ТЕСТ + HEALTHCHECK =============

def test_config(xray_exe: str, config_path: str, port: int) -> tuple:
    log_path = config_path.replace(".json", "_test.log")
    try:
        with open(log_path, "w") as lf:
            proc = subprocess.Popen([xray_exe, "run", "-c", config_path], stdout=lf, stderr=lf)
        time.sleep(5)
        if proc.poll() is not None:
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    err = f.read()
            except:
                err = "Не удалось прочитать лог"
            try: os.remove(log_path)
            except: pass
            return False, err[:500]
        try:
            s = socket.socket(); s.settimeout(2); s.connect(("127.0.0.1", port)); s.close()
            proc.terminate()
            try: os.remove(log_path)
            except: pass
            return True, ""
        except:
            proc.terminate()
            try: os.remove(log_path)
            except: pass
            return False, "Порт не открылся"
    except Exception as e:
        return False, str(e)

def healthcheck(cfg) -> bool:
    if not cfg.get("healthcheck", {}).get("enabled"):
        return True
    try:
        r = subprocess.run(["curl.exe", "--socks5", f"127.0.0.1:{cfg['listen_port']}", cfg["healthcheck"]["target_url"], "-I", "--max-time", str(cfg["healthcheck"]["timeout_sec"])], capture_output=True, timeout=cfg["healthcheck"]["timeout_sec"]+5)
        return r.returncode == 0
    except:
        return False

def stop_xray():
    subprocess.run(["taskkill", "/f", "/im", "xray.exe"], capture_output=True)
    time.sleep(1)

def start_xray(cfg) -> bool:
    stop_xray()
    subprocess.Popen([cfg["xray"]["executable"], "run", "-c", CONFIG_OUT_PATH], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    try:
        s = socket.socket(); s.settimeout(2); s.connect(("127.0.0.1", cfg["listen_port"])); s.close()
        return True
    except:
        return False


# ============= MAIN =============

def main_refresh(cfg):
    hostname, ip = get_host_info()
    port = cfg["listen_port"]
    
    # Уведомление о начале (если Xray уже жив)
    xray_was_alive = False
    try:
        s = socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", port)); s.close()
        xray_was_alive = True
    except:
        pass
    
    if xray_was_alive:
        tg_send(cfg, f"🔧 <b>Начало обновления</b>\nВерсия: {VERSION}\nХост: {hostname}\nIP: {ip}")
    
    log(f"=== Local SOCKS5 v{VERSION} ===")
    
    if not ensure_xray(cfg):
        tg_send(cfg, f"❌ Xray не установлен\nХост: {hostname}")
        return
    
    xray_exe = cfg["xray"]["executable"]
    if not os.path.isabs(xray_exe):
        xray_exe = os.path.join(SCRIPT_DIR, xray_exe)
    
    # Загрузка
    all_proxies = []
    for url in cfg.get("sources", []):
        p = load_proxies(url)
        all_proxies.extend(p)
        log(f"Загружено {len(p)} из {url.split('/')[-1]}")
    
    total_before = len(all_proxies)
    all_proxies = list(dict.fromkeys(all_proxies))
    max_p = cfg.get("max_proxies", 20)
    limited = len(all_proxies) > max_p
    if limited:
        all_proxies = all_proxies[:max_p]
    
    proxy_info = f"{len(all_proxies)}/{total_before}" if limited else str(len(all_proxies))
    log(f"Прокси: {proxy_info}")
    
    if not all_proxies:
        tg_send(cfg, f"❌ Нет прокси\nХост: {hostname}")
        return
    
    config = build_config(all_proxies, port)
    if not config:
        tg_send(cfg, f"❌ Не удалось собрать конфиг\nХост: {hostname}")
        return
    
    os.makedirs(os.path.dirname(CONFIG_OUT_PATH), exist_ok=True)
    temp_path = CONFIG_OUT_PATH.replace(".json", "_new.json")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    # Тест
    log("Тестирование...")
    stop_xray()
    ok, err = test_config(xray_exe, temp_path, port)
    
    if not ok:
        log(f"НЕВАЛИДЕН: {err[:300]}")
        log_path = temp_path.replace(".json", "_test.log")
        tg_send(cfg, f"❌ <b>Обновление не удалось</b>\nХост: {hostname}\nПрокси: {proxy_info}\nОшибка: {err[:200]}\nЛог: {log_path}")
        try: os.remove(temp_path)
        except: pass
        
        # Откат
        if os.path.exists(CONFIG_OUT_PATH):
            ok2, _ = test_config(xray_exe, CONFIG_OUT_PATH, port)
            if ok2:
                stop_xray()
                start_xray(cfg)
                tg_send(cfg, f"✅ Запущен предыдущий конфиг")
        return
    
    log("Валиден. Применяем...")
    if os.path.exists(CONFIG_OUT_PATH):
        try: shutil.copy(CONFIG_OUT_PATH, BACKUP_PATH)
        except: pass
    try: os.replace(temp_path, CONFIG_OUT_PATH)
    except: shutil.copy(temp_path, CONFIG_OUT_PATH); os.remove(temp_path)
    
    stop_xray()
    if start_xray(cfg):
        log(f"Запущен! Прокси: {proxy_info}")
        time.sleep(5)
        hc = healthcheck(cfg)
        if hc:
            log("Healthcheck OK")
            tg_send(cfg, f"✅ <b>Обновление завершено</b>\nВерсия: {VERSION}\nХост: {hostname}\nIP: {ip}\nПрокси: {proxy_info}\nHealthcheck: OK")
        else:
            log("Healthcheck FAIL")
            tg_send(cfg, f"⚠️ <b>Обновление завершено с ошибкой</b>\nХост: {hostname}\nПрокси: {proxy_info}\nHealthcheck: FAIL")
    else:
        tg_send(cfg, f"❌ Не удалось запустить Xray\nХост: {hostname}")
        if os.path.exists(BACKUP_PATH):
            shutil.copy(BACKUP_PATH, CONFIG_OUT_PATH)
            if start_xray(cfg):
                tg_send(cfg, "✅ Откат к предыдущему конфигу")


def run_monitor(cfg):
    if healthcheck(cfg):
        sys.exit(0)
    log("Healthcheck FAIL")
    hostname, _ = get_host_info()
    tg_send(cfg, f"⚠️ Healthcheck FAIL\nХост: {hostname}\nПробую перезапуск...")
    stop_xray()
    if start_xray(cfg):
        time.sleep(5)
        if healthcheck(cfg):
            log("Восстановлено")
            tg_send(cfg, f"✅ Восстановлено\nХост: {hostname}")
        else:
            tg_send(cfg, f"❌ Повторный FAIL\nХост: {hostname}\nПолный перезапуск...")
            main_refresh(cfg)
    else:
        main_refresh(cfg)


def run_setup(cfg):
    log("=== Setup v{VERSION} ===")
    python_path = sys.executable
    script_path = os.path.abspath(sys.argv[0]) if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
    port = cfg["listen_port"]
    
    def ps(script, desc):
        r = subprocess.run(["powershell", "-Command", f"chcp 65001 >$null; {script}"], capture_output=True, text=True, encoding="utf-8")
        out = (r.stdout or "") + (r.stderr or "")
        if "OK" in out: log(f"{desc}: OK"); return True
        else: log(f"{desc}: {out.strip()[:150]}"); return False
    
    ps(f"try {{ New-NetFirewallRule -DisplayName 'SOCKS5-LocalProxy' -Direction Inbound -Protocol TCP -LocalPort {port} -Action Allow -ErrorAction Stop | Out-Null; 'OK' }} catch {{ if ($_.Exception.Message -match 'already exists') {{ 'OK-EXISTS' }} else {{ 'ERROR: '+$_.Exception.Message }} }}", f"Фаервол {port}")
    
    if cfg.get("schedule", {}).get("enabled"):
        st, sp, ri = cfg["schedule"]["start_time"], cfg["schedule"]["stop_time"], cfg["schedule"]["refresh_interval_min"]
        for name, tt, tv, desc in [("LocalSocks_Boot","AtStartup","","Start on boot"),("LocalSocks_Start","Daily",st,"Start daily"),("LocalSocks_Stop","Daily",sp,"Stop daily")]:
            tr = "$trigger = New-ScheduledTaskTrigger -AtStartup" if tt=="AtStartup" else f"$trigger = New-ScheduledTaskTrigger -Daily -At '{tv}'"
            ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path}'; {tr}; $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $trigger -Settings $s -User SYSTEM -Description '{desc}' -ErrorAction Stop | Out-Null; 'OK'", f"Задача {name}")
        ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path}'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {ri}) -RepetitionDuration (New-TimeSpan -Days 365); $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName 'LocalSocks_Refresh' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName 'LocalSocks_Refresh' -Action $a -Trigger $t -Settings $s -User SYSTEM -Description 'Refresh' -ErrorAction Stop | Out-Null; 'OK'", f"Refresh ({ri}min)")
    
    if cfg.get("healthcheck", {}).get("enabled"):
        ps(f"$a=New-ScheduledTaskAction -Execute '{python_path}' -Argument '{script_path} --monitor'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 365); $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Unregister-ScheduledTask -TaskName 'LocalSocks_Monitor' -Confirm:$false -ErrorAction SilentlyContinue; Register-ScheduledTask -TaskName 'LocalSocks_Monitor' -Action $a -Trigger $t -Settings $s -User SYSTEM -Description 'Monitor' -ErrorAction Stop | Out-Null; 'OK'", "Monitor (5min)")
    
    log("Готово. Проверь taskschd.msc")


def main():
    if "--setup" in sys.argv:
        run_setup(load_config())
    elif "--monitor" in sys.argv:
        run_monitor(load_config())
    else:
        main_refresh(load_config())

if __name__ == "__main__":
    main()