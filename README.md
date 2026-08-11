# Local SOCKS5 Proxy v1.5.0

Локальный SOCKS5-прокси с failover для Telegram. Автоматически загружает списки проверенных прокси, балансирует нагрузку, обновляется и отправляет уведомления в Telegram.

## Что нового в v1.5.0

- **Автообновление** — скрипт проверяет GitHub и сам заменяет exe при выходе новой версии
- **Миграция config.json** — недостающие поля добавляются автоматически, старые настройки не теряются
- **Балансировка** — выбор стратегии: `leastPing` (быстрейший) или `random` (случайный)
- **Ротация логов** — `local-socks.log` не растёт бесконечно (лимит 1 МБ)
- **`--status`** — показать текущий статус (порт, healthcheck, стратегия)
- **`--test`** — быстрая проверка healthcheck
- **`--ignoreupdate`** — запретить автообновление
- **Исправлен healthcheck** — curl с `-s -L -o NUL`, без ложных FAIL
- **Исправлена валидация конфига Xray** — логи ошибок сохраняются для отладки

## Быстрый старт

1. Скачай `local-socks_V1.5.0.exe`
2. Запусти от **администратора**:
local-socks_V1.5.0.exe --setup

text
3. При первом запуске создастся `config.json` с настройками по умолчанию
4. Для Telegram-уведомлений — впиши `bot_token` и `chat_id` в `config.json`

## Команды

| Команда | Описание |
|---------|----------|
| `local-socks.exe` | Запустить/обновить прокси |
| `local-socks.exe --setup` | Интерактивная установка (фаервол + задачи) |
| `local-socks.exe --monitor` | Healthcheck (запускается автоматически) |
| `local-socks.exe --status` | Показать статус |
| `local-socks.exe --test` | Проверить healthcheck и выйти |
| `local-socks.exe --update` | Принудительное обновление |
| `local-socks.exe --ignoreupdate` | Запретить автообновление при этом запуске |

## config.json

```json
{
 "version": "1.5.0",
 "listen_port": 1080,
 "max_proxies": 20,
 "balancer": {
     "strategy": "leastPing",
     "observatory": {
         "probeUrl": "https://t.me",
         "probeInterval": "5m"
     }
 },
 "xray": {
     "executable": "xray/xray.exe",
     "download_url": "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
 },
 "sources": [
     "https://raw.githubusercontent.com/.../failover-tg-top10.txt",
     "https://raw.githubusercontent.com/.../YT+TG.txt"
 ],
 "telegram": {
     "enabled": false,
     "bot_token": "",
     "chat_id": ""
 },
 "healthcheck": {
     "enabled": true,
     "target_url": "https://t.me",
     "timeout_sec": 12,
     "retry_count": 2
 },
 "schedule": {
     "enabled": true,
     "start_time": "08:00",
     "stop_time": "20:00",
     "refresh_interval_min": 60
 },
 "update": {
     "enabled": true,
     "check_url": "https://raw.githubusercontent.com/.../version.txt",
     "download_url": "https://raw.githubusercontent.com/.../local-socks_V1.5.0.exe"
 }
}
Стратегии балансировки
Значение	Описание
leastPing	Самый быстрый прокси (требует Observatory)
random	Случайный выбор (надёжнее, но не оптимальный по скорости)
Если leastPing вызывает проблемы (healthcheck FAIL, таймауты) — смените на random.

Автообновление
При запуске скрипт проверяет update.check_url (файл version.txt в репо)

Сравнивает с текущей версией

Если есть новая — скачивает exe из update.download_url, заменяет, перезапускается

Старый exe сохраняется как *.old

Задачи в планировщике
Задача	Когда	Что делает
LocalSocks_Boot	При включении ПК	Запуск
LocalSocks_Start	8:00	Запуск
LocalSocks_Stop	20:00	Остановка
LocalSocks_Refresh	Каждый час	Обновление списка прокси
LocalSocks_Monitor	Каждые 5 минут	Healthcheck + перезапуск
Подключение клиентов
Тип: SOCKS5

Адрес: IP компьютера (например 192.168.1.30)

Порт: 1080

Аутентификация: нет

Telegram-уведомления
Создайте бота через @BotFather

Получите bot_token

Напишите боту, затем получите chat_id: https://api.telegram.org/bot<TOKEN>/getUpdates

В config.json: telegram.enabled = true, впишите токен и chat_id

Уведомления отправляются через SOCKS5 (если прокси жив) или напрямую.

Файлы
text
local-socks_V1.5.0.exe     # Основной файл
config.json                 # Настройки (создаётся автоматически)
output/local-socks.log      # Лог (ротация при 1 МБ)
configs/local-socks.json    # Конфиг Xray
xray/xray.exe               # Xray (скачивается автоматически)
Обновление с предыдущих версий
Скачайте новый exe

Замените старый (задачи в планировщике обновятся автоматически при --setup)

Старый config.json совместим — недостающие поля добавятся при первом запуске