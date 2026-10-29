# Twitch Timecode Saver

Приложение для macOS, которое по горячей клавише сохраняет таймкод текущего момента в Google Таблицу. Работает через перехват клавиатуры на Quartz + Twitch API.

## Установка

1. Клонировать репозиторий
```bash
git clone <your-repo-url>
cd <repo-name>
```

2. Создать виртуальное окружение и установить зависимости
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Настроить конфиги

Скопируй примеры и заполни своими данными:

```bash
cp twitch_config.example.json twitch_config.json
```

Для Google Sheets нужен сервисный аккаунт. Скачай JSON-ключ и назови его `credentials.json`. Положи в корень проекта.

## Настройка Google Sheets

1. Создай Google Таблицу
2. Дай доступ на редактирование email-адресу сервисного аккаунта из `credentials.json` (`client_email`)
3. Скопируй `spreadsheet_id` из URL таблицы и вставь в `twitch_config.json`

## Запуск

```bash
python TwitchTimecode.py
```

## Важно для macOS

Приложению нужен доступ к "Универсальному доступу" (Accessibility) для перехвата горячих клавиш через Quartz.

`Системные настройки > Конфиденциальность и безопасность > Универсальный доступ` — добавить терминал/приложение в список.

## Файлы

- `TwitchTimecode.py` — основное приложение
- `twitch_config.json` — конфиг (не коммитится)
- `credentials.json` — ключ Google (не коммитится)
- `timestamps.txt` — лог таймкодов (не коммитится)
