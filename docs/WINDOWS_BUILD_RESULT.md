# Windows-сборка и выполненные проверки

## Готовая Windows-сборка 0.3.1

- [Скачать Windows x64 ZIP](https://github.com/Asmoday7/MyLovelyAlbionAddon/actions/runs/41871657888/artifacts/13344857008)
  (нужен вход в GitHub); [успешный CI](https://github.com/Asmoday7/MyLovelyAlbionAddon/actions/runs/41871657888).
- Application source: `1f230c1c60a349f2ea6cb9905dc66ac0efe6edf0`.
- SHA-256 архива: `4c6aa7e7eda7ec065e51cef1dcedeaba5baac67073d80d31d5ec2e320ae677a5` — совпал с digest GitHub Actions.
- `AlbionTradeDesk.exe`: PE AMD64, **10,874,923 байта**;
  SHA-256 `5375a48da1f0a751c7aab7b5f32cde01a8e476bc3dbd859488fd7277d45fef27` — совпал с отчётом сборки.
- На Windows прошли **126 тестов без пропусков**, упаковка, запуск готовой EXE,
  проверки SQLite/Excel/остановки и Firewall/WFP на синтетическом процессе.
- Внутри EXE отдельно проверены полный анализ и возврат всех 305 рецептов,
  точная диагностика отказа смешанного пакета и сохранность уже принятых данных.
- В браузере на Linux проверены полный каталог: **12 517 из 12 517 рецептов**,
  отображение всех **9 118 предметов** после объединения вариантов рецептов,
  без страниц и без ошибок JavaScript. Использовалась временная копия каталога
  без котировок. API — около 7,3 с, окончательный расчёт/отображение — около 8,3 с
  в этой среде; это не гарантия времени на другом компьютере.
- [Проверенное происхождение](evidence/windows-0.3.1/verified.json),
  [проверки упакованной программы](evidence/windows-0.3.1/frozen.json).

Причина HTTP 400 конкретного пользовательского пакета пока не установлена:
её нужно прочитать в «Мои наблюдения» → «Последний отклонённый пакет» после
установки этой версии. Качество 0 проверялось на синтетических данных, а не
подтверждено для пользовательского пакета. С живой игрой/Npcap новая EXE здесь
не запускалась. Настройки и публикация облачной среды не менялись.

## Предыдущий готовый артефакт 0.3.0

- [Скачать Windows x64 ZIP](https://github.com/Asmoday7/MyLovelyAlbionAddon/actions/runs/41291412315/artifacts/13076748896)
  (нужен вход в GitHub); [страница запуска CI](https://github.com/Asmoday7/MyLovelyAlbionAddon/actions/runs/41291412315).
- Application source: `47af477efb3d1a9cc0f0bea4a9042abf95412036`.
- Архив скачан через GitHub API и проверен по опубликованному digest:
  `2cce2d0e6210c5fa269480e28fe73887b680e83edf5078e49f14c132b74474ed` (SHA-256).
- `AlbionTradeDesk.exe`: Windows PE AMD64, **10 872 559 байт**; SHA-256
  `d939e365b7fb03bbb8a9502b35e016f94598e79c964ffdbc9fa2110fdd8a0379`
  совпал с `build-report.json` из этого архива.
- Отчёт этой сборки: tests/build/frozen/firewall — success. `unittest.log`:
  **120 тестов, OK, без пропусков**. Проверка с живой игрой и Npcap не заявляется.

В этой сборке уже есть исправление рыночных кодов из 0.1.1. На временных базах
дополнительно воспроизведены HTTP-запросы одного ордера с `1002`, `1000-HellDen`
и `1000`: код старой сборки ниже возвращает 200/400/400, текущий приёмник —
200/200/200, сохраняя один нормализованный ордер в Lymhurst. В пользовательском
логе нет тела ответа HTTP 400, поэтому совпадение конкретной ошибки требует
проверки после замены старого exe.

Сохранённая позже правка снятия лимита 300 рецептов не входит в этот артефакт:
для неё потребуется отдельная Windows-сборка. При проверке 0.3.0 использовался существующий
артефакт; последующая сборка 0.3.1 описана выше.

## Архивная сборка 0.1.0

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
