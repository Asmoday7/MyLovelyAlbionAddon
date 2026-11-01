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
