# Fluidd Desktop

Десктоп-обёртка для веб-интерфейса Fluidd на Klipper-принтерах (Elegoo Neptune 4 и др.).

- **Автопоиск принтера.** IP меняется при каждом включении, поэтому приложение само
  ищет в локальной сети хост с Moonraker (`/server/info`, порты 7125 и 80):
  сначала последний известный IP, потом ARP-таблица, потом перебор всех `/24`-подсетей ПК.
- **Fluidd во встроенном окне** (Qt WebEngine), настройки Fluidd сохраняются между запусками.
- **Уведомления Windows:** печать началась / пауза / продолжена / 25-50-75% / завершена /
  отменена / ошибка, ошибки Klipper, принтер подключился / отключился.
- **Работа в трее.** Закрытие окна сворачивает в трей, мониторинг продолжается.
  Если принтер пропал (выключен или сменил IP), поиск повторяется каждые 15 с.

## Запуск

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Сборка в .exe

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconsole --name FluiddDesktop main.py
```

Готовое приложение — `dist\FluiddDesktop\FluiddDesktop.exe`.

## Настройки

`%USERPROFILE%\.fluidd_desktop\config.json`:

| ключ | по умолчанию | описание |
|---|---|---|
| `last_ip` | — | последний найденный IP (проверяется первым) |
| `extra_subnets` | `[]` | доп. подсети для поиска, например `["192.168.1.0/24"]` |
| `poll_interval_sec` | `3` | период опроса статуса |
| `rescan_interval_sec` | `15` | период повторного поиска |
| `progress_notifications` | `true` | уведомления на 25/50/75% |
