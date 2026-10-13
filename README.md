# HID Monitor

Программа для анализа HID-пакетов: перечисляет HID-устройства, прослушивает выбранное и разбирает пакеты (HEX-дамп, побайтовая расшифровка, интерпретации int16/int32/float).

A tool that lists HID devices, listens to a selected one and decodes its packets (hex dump, per-byte decode, int16/int32/float interpretations).

## Быстрый старт / Quick start

**Установка:** скачайте установщик
[`HIDMonitor-Setup-1.0.0.exe`](https://github.com/Pepchik/HID-monitor/releases/download/v1.0.0/HIDMonitor-Setup-1.0.0.exe)
со [страницы релизов](https://github.com/Pepchik/HID-monitor/releases/latest) и запустите —
мастер установит приложение и создаст ярлыки. Удаление — стандартно через «Программы и компоненты».

**Запуск из исходников:**

```bash
pip install hidapi        # модуль называется "hid"
python hid_monitor.py
```

## Возможности / Features

- 4 рабочие области: устройства, пакеты, HEX-дамп, расшифровка по байтам.
- Настраиваемая раскладка: разделители между областями перетаскиваются мышью, области меняются местами перетаскиванием за заголовок, двойной клик по заголовку — сброс раскладки.
- Подсветка байтов, изменившихся относительно предыдущего пакета.
- Интерпретации данных со смещения 1 (после report ID): uint16/32 LE/BE, int16/32 LE, float32 LE/BE, ASCII.
- Два языка интерфейса: русский и английский (переключатель в правом верхнем углу).
- Лимит 5000 пакетов в памяти, автоскролл списка.

## Сборка exe / Building the exe

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onedir --windowed --name HIDMonitor hid_monitor.py
```

Результат — папка `dist/HIDMonitor` (exe + `_internal` с зависимостями).

## Требования / Requirements

- Windows (через hidapi/ctypes)
- Python 3.11+ (для запуска из исходников)
- `hidapi` (`pip install hidapi`)

## Лицензия / License

[MIT](LICENSE)
