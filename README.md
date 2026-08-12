# Local SOCKS5 Proxy

Локальный SOCKS5-прокси с failover, автообновлением и собственным пинг-тестом.

## Быстрый старт

1. Скачай `local-socks_V1.7.0.exe`
2. Запусти от **администратора**:
local-socks_V1.7.0.exe --setup

text
3. Отредактируй `config.json` (Telegram, источники, стратегия)
4. Подключайся из локалки: **SOCKS5** `IP_компа:1080`

## Команды

| Команда | Что делает |
|---------|-----------|
| (без флагов) | Запуск/обновление прокси |
| `--setup` | Установка: фаервол + задачи в планировщике |
| `--monitor` | Healthcheck (автоматически каждые 5 минут) |
| `--status` | Показать статус |
| `--test` | Проверить healthcheck |
| `--update` | Принудительное обновление |
| `--ignoreupdate` | Запретить автообновление |

## config.json (ключевые поля)

| Поле | Описание | По умолчанию |
|------|----------|-------------|
| `listen_port` | Порт SOCKS5 | 1080 |
| `max_proxies` | Максимум прокси | 20 |
| `ping.enabled` | Свой пинг-тест перед запуском | true |
| `ping.timeout_sec` | Таймаут TCP-пинга | 3 |
| `balancer.strategy` | `leastPing` или `random` | leastPing |
| `fallback.enabled` | Резервный прокси | false |
| `fallback.proxy_url` | Ссылка на резервный прокси | "" |
| `healthcheck.targets` | Список URL для проверки | ["https://t.me"] |
| `xray.debug` | Debug-логи Xray | false |
| `telegram.enabled` | Уведомления в Telegram | false |

## Автообновление

1. Скрипт проверяет `version.txt` на GitHub
2. Если версия новее — скачивает exe
3. Заменяет себя, перезапускается с `--setup`

## Fallback-прокси

Если все прокси из балансера мертвы — Xray переключается на `fallback.proxy_url`. Пример:
```json
"fallback": {
 "enabled": true,
 "proxy_url": "vless://uuid@host:port?security=reality&sni=..."
}

## Мульти-target healthcheck
Можно проверять несколько сервисов:

```json
"healthcheck": {
    "targets": ["https://t.me", "https://www.youtube.com", "https://www.tiktok.com"]
}

**Задачи в планировщике**
Задача	Когда
LocalSocks_Boot	При включении ПК
LocalSocks_Start	8:00
LocalSocks_Stop	20:00
LocalSocks_Refresh	Каждый час
LocalSocks_Monitor	Каждые 5 минут
Подключение клиентов
Тип: SOCKS5

Адрес: IP компьютера

Порт: 1080

Аутентификация: нет
