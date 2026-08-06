# Local SOCKS5 Proxy

Локальный SOCKS5-прокси с автоматическим failover для Telegram и других приложений. 
Объединяет списки проверенных прокси, балансирует нагрузку, автоматически обновляется.

## Возможности

- SOCKS5-прокси на `0.0.0.0:1080` для всей локальной сети
- Автоматическая загрузка списков прокси из GitHub
- Поддержка протоколов: VLESS, Trojan, VMess, Shadowsocks, Hysteria2
- Балансировка между прокси (random)
- Автоустановка Xray при первом запуске
- Healthcheck — проверка работоспособности каждые 5 минут с автоперезапуском
- Telegram-уведомления о статусе, ошибках, обновлениях
- Автозапуск при включении ПК, по расписанию (8:00-20:00)
- Интерактивная установка (фаервол + задачи) одной командой `--setup`

## Установка

1. Скачай `local-socks.exe`
2. Запусти от администратора:
**local-socks.exe --setup**
3. При первом запуске создастся `config.json` с настройками по умолчанию
4. Для Telegram-уведомлений — впиши bot_token и chat_id в `config.json`

## config.json

```json
{
 "listen_port": 1080,          // Порт SOCKS5
 "max_proxies": 20,            // Максимум прокси (чтобы не перегружать Xray)
 "xray": {
     "executable": "xray/xray.exe",  // Путь к Xray (скачается автоматически)
     "download_url": "..."           // Откуда скачать Xray
 },
 "sources": [                       // Ссылки на списки прокси
     "https://.../failover-tg-top10.txt",
     "https://.../YT+TG.txt"
 ],
 "telegram": {
     "enabled": false,          // Включить уведомления
     "bot_token": "",           // Токен бота
     "chat_id": ""              // ID чата
 },
 "healthcheck": {
     "enabled": true,           // Проверять curl'ом
     "target_url": "https://t.me",
     "timeout_sec": 8
 },
 "schedule": {
     "enabled": true,           // Создавать задачи в планировщике
     "start_time": "08:00",     // Запуск SOCKS5
     "stop_time": "20:00",      // Остановка SOCKS5
     "refresh_interval_min": 60 // Обновление списка прокси
 }
}


**Использование**
Команда	Описание
local-socks.exe	Запустить/обновить прокси
local-socks.exe --setup	Интерактивная установка (от админа)
local-socks.exe --monitor	Healthcheck (автоматически по расписанию)
Задачи в планировщике (после --setup)
Задача	Когда	Что делает
LocalSocks_Boot	При включении ПК	Запуск SOCKS5
LocalSocks_Start	8:00 ежедневно	Запуск SOCKS5
LocalSocks_Stop	20:00 ежедневно	Остановка Xray
LocalSocks_Refresh	Каждый час	Обновление списка прокси
LocalSocks_Monitor	Каждые 5 минут	Healthcheck + автоперезапуск
Подключение клиентов
Тип: SOCKS5

Адрес: IP_компьютера (например 192.168.1.30)
Порт: 1080
Аутентификация: нет

Telegram-уведомления
Создай бота через @BotFather
Получи bot_token
Напиши боту, потом получи chat_id через https://api.telegram.org/bot<TOKEN>/getUpdates
Впиши в config.json → telegram.enabled: true

Уведомления:

🟢 Запуск прокси
🔄 Обновление конфига
⚠️ Healthcheck fail
❌ Ошибки

Как работает healthcheck
Каждые 5 минут:
curl --socks5 127.0.0.1:1080 https://t.me -I
Если FAIL → перезапуск Xray
Если снова FAIL → полный перезапуск с обновлением списка прокси
Telegram-уведомление при каждом сбое

Файлы
text
local-socks.exe          # Основной exe
config.json              # Настройки (создаётся при первом запуске)
output/local-socks.log   # Лог
configs/local-socks.json # Сгенерированный конфиг Xray
xray/xray.exe            # Xray (скачивается автоматически)
