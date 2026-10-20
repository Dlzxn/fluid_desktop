# Fluidd Desktop

Десктоп-обёртка для веб-интерфейса Fluidd на Klipper-принтерах (Elegoo Neptune 4 и др.).

**Автор:** Alexey ([@Dlzxn](https://github.com/Dlzxn)) — aleshamarichev09@gmail.com

## Установка

Скачайте `FluiddDesktop-Setup-<версия>.exe` со страницы
[Releases](https://github.com/Dlzxn/fluid_desktop/releases/latest) и запустите.
Права администратора не нужны: программа ставится в профиль пользователя
(`%LOCALAPPDATA%\Programs\FluiddDesktop`). При установке можно включить ярлык на рабочем
столе и автозапуск вместе с Windows. Удаление — через «Параметры → Приложения».

## Возможности

- **Автопоиск принтера.** IP меняется при каждом включении, поэтому приложение само
  ищет в локальной сети хост с Moonraker (`/server/info`, порты 7125 и 80):
  сначала последний известный IP, потом ARP-таблица, потом перебор всех `/24`-подсетей ПК.
- **Fluidd во встроенном окне** (Qt WebEngine), настройки Fluidd сохраняются между запусками.
- **Уведомления Windows:** печать началась / пауза / продолжена / 25-50-75% / завершена /
  отменена / ошибка, ошибки Klipper, принтер подключился / отключился.
- **Работа в трее.** Закрытие окна сворачивает в трей, мониторинг продолжается.
  Если принтер пропал (выключен или сменил IP), поиск повторяется каждые 15 с.
- **Автообновление.** При запуске и раз в 6 часов приложение проверяет последний релиз на GitHub;
  если вышла новая версия — предложит скачать её и само установит с перезапуском.
  Проверить вручную: кнопка «⬆ Обновления» или меню трея.

## Запуск из исходников

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Сборка установщика

Нужен [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Результат — `dist\FluiddDesktop-Setup-<версия>.exe`.

## Выпуск новой версии

1. Поднять `__version__` в `fluid_desktop/__init__.py`.
2. Закоммитить в `main` и запушить тег: `git tag v1.0.1 && git push origin v1.0.1`.
3. GitHub Actions (`.github/workflows/release.yml`) соберёт установщик и опубликует релиз —
   установленные копии приложения предложат обновиться.

## Настройки

`%USERPROFILE%\.fluidd_desktop\config.json`:

| ключ | по умолчанию | описание |
|---|---|---|
| `last_ip` | — | последний найденный IP (проверяется первым) |
| `extra_subnets` | `[]` | доп. подсети для поиска, например `["192.168.1.0/24"]` |
| `poll_interval_sec` | `3` | период опроса статуса |
| `rescan_interval_sec` | `15` | период повторного поиска |
| `progress_notifications` | `true` | уведомления на 25/50/75% |
| `auto_update` | `true` | проверять обновления на GitHub |

## Лицензия

Apache 2.0, © 2026 Alexey (Dlzxn). См. [LICENSE](LICENSE).
