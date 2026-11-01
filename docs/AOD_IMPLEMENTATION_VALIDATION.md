# Проверка интеграции AOD — 1 ноября 2026

Результат: реализация receiver/SQLite/управления процессом/панели готова для Windows-проверки. Полный критерий «штатный AOD + настоящая игра на Windows» в Linux не подтверждён.

- **82 unittest: 80 прошли, 2 явно пропущены** — Windows PowerShell parser для шаблона и сгенерированного bootstrap/supervisor. CI включает обе проверки на Windows.
- Реальные локальные HTTP POST native AOD JSON; несколько ордеров, повторные обновления, отсутствие копий, отклонение невалидного batch с rollback.
- Запоздавшая обработка не затирает новое состояние; регионы/рынки/качества разделены; raw location и зачарование сохраняются. Пустая/неполная страница не удаляет другие ордера.
- 60 конкурентных HTTP POST с 8 workers; повторное открытие; XLSX; аналитика; резервные копии. Все SQLite handles и HTTP threads закрываются, файлы явно удаляются до TemporaryDirectory.cleanup; исключения очистки не подавляются. Эта проверка выполнена на Linux и включена в Windows CI; отсутствие WinError 32 именно на Windows пока не подтверждено.
- Запуск/stop/timeout supervisor проверены **с подставленным Popen**. Это проверка контракта управления, не запуск настоящего AOD. Lock второго экземпляра приложения проверен.
- Chromium: ручное включение, guard неподдержанной ОС, synthetic receiver, обработанные/уникальные ордера, сервер сессии, журнал, Excel, остановка, мобильная ширина. Внешних запросов браузера не было. Синтетические ордера находились только во временной БД.
- Scoped wire test с неизменёнными upstream dispatcher.go и uploader_http.go: sole-local -i, пустой -p, действие -d, положительный контроль нескольких адресов, loopback strace и SQLite bridge. Это не полный exe: updater/WS/NATS/pcap ветви вне эксперимента. [Свидетельства](evidence/private-scanner-final/report.json).
- Python wheel собран, установлен в отдельный target, entry point status запущен. Включены JS/CSS/PS1/контрольная сумма AOD/шаблоны. Пользовательская база не входит в пакет.
- PyInstaller spec и Windows Actions workflow добавлены. **Windows exe не собран здесь; удалённый workflow не запускался.**

Полные [результаты unit](evidence/private-scanner-final/unittest.log), [структурированный результат](evidence/private-scanner-final/validation.json), [границы приватности и первый запуск](PRIVATE_SCANNER.md).

Windows-проверка остаётся обязательной для UAC/NetSecurity/реального Npcap, совпадения exe установленного AOD с pinned hash, доставки с Asia/Europe/Americas, WebView2, всех исходящих UDP/DNS/TCP и поведения Firewall при остановке/обновлении. Текущий код не заявляет подтверждённую приватность и не включает сбор автоматически.


## Доработки и повторная проверка

Последний локальный прогон: **83 теста: 80 passed, 3 Windows-only skipped**. Добавлен нативный Windows preflight: неподходящий exe должен отвергаться до запуска и без изменения Firewall. В Linux он не исполнялся.

Официальный PowerShell 7.4.7 Microsoft установлен только в /tmp после проверки SHA-256. Все исходные PS1 и сгенерированные bootstrap/loader/guardian успешно разобраны настоящим PowerShell parser. Это синтаксическая проверка PS7, не исполнение Windows API.

С тем же PyInstaller spec собран настоящий **Linux** executable. Проверены HTTP, native fixtures, SQLite UPSERT/backup, Excel, остановка и удаление файлов после завершения. Это дополнительная проверка упаковки, не Windows exe. Chromium desktop/mobile повторно прошёл сценарий.

Windows workflow в отдельной ветке codex/private-aod-windows теперь содержит тест упакованного exe и реального NetSecurity/WFP на synthetic probe. Результаты Windows из этой сессии пока не получены: репозиторий закрыт, GitHub API блокируется сетевой политикой. Автопроверка отклонила CI contents: write для возврата результата через Git; запрошено явное одноразовое разрешение, право не включено. Основная ветка не менялась.

Актуальные [логи](evidence/private-scanner-max/unittest.log) и [структурированный отчёт](evidence/private-scanner-max/validation.json).
