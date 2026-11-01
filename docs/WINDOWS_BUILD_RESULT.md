# Windows-сборка и выполненные проверки

Сборка получена из GitHub Actions на Windows NT 10.0.26100.0 (Windows hosted runner).

- Application source: **636c3a4de97000fc694200aa1541476219e3e16a**.
- CI recipe commit: **e91c562aa93c9a09bf87b32005e1d483f6fc8843**. Единственное отличие от application source — временный job в windows-build.yml для возврата результата.
- [CI run 41271027327](https://github.com/Asmoday7/MyLovelyAlbionAddon/actions/runs/41271027327).
- Файл: **AlbionTradeDesk.exe**, Windows PE AMD64, **10 821 343 байта**.
- SHA-256: **9c8afd8957850a444da4e6e4c509796943658e3593a4ff739a25568a826590d7**. Хэш полученного файла совпал с отчётом сборки; PE signature и AMD64 machine проверены отдельно после скачивания.

## Что прошло на настоящем Windows runner

1. **83 unittest — все прошли, без пропусков.** Включены Windows PowerShell parser, проверка сгенерированного supervisor и реальное отклонение неподтверждённого exe до запуска. [Полный лог](evidence/windows-ci/unittest.log).
2. PyInstaller сборка Windows exe. [Лог](evidence/windows-ci/build.log).
3. Запуск именно упакованного exe: настоящий loopback HTTP, native AOD fixtures, повторный UPSERT, SQLite backup, Excel, остановка приложения, удаление SQLite-файлов после выхода. WinError 32 в этом сценарии не возник. [Отчёт](evidence/windows-ci/frozen.json).
4. Реальные NetSecurity/Firewall/WFP на отдельном self-built synthetic процессе: loopback TCP/UDP разрешён; внешние IPv4 TCP/UDP заблокированы; Security events **5157 и 5152** зарегистрированы для обоих протоколов. Изменение адресного фильтра обнаружено тем же checker, который использует настоящий supervisor. Профили и политика аудита runner восстановлены в finally. [Отчёт](evidence/windows-ci/firewall.json).

Флаги tests/build/frozen/firewall в [отчёте CI](evidence/windows-ci/build-report.json) — success. [Итоговая проверка происхождения](evidence/windows-ci/verified-result.json).

## Граница результата

Это Windows CI, а не домашний Windows 10/11 пользователя. В живую игру не входили, Npcap не устанавливали, AOD capture не запускали. Полное отсутствие egress настоящего AOD, WebView2/дочерних процессов и поведение конкретной сети/VPN ещё требуют проверки на пользовательском компьютере. WFP-тест применяет общую policy к synthetic probe; он не является сертификацией всей программы AOD.

Регион по-прежнему задаётся в сессии: native HTTP AOD не содержит server ID. Автовключения сканера нет. Разрешение SBI на конкретный private use case не получено.

Одноразовый возврат сборки через Git выполнялся по явному разрешению пользователя. Ветка запуска с job contents: write удалена после получения результата. Итоговая ветка реализации сохраняет contents: read; main не изменялась. Ветка builds/aod-e91c562aa93c-41271027327-1 хранит только exe и отчёты, без workflow.
