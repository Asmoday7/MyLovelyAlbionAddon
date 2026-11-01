import argparse
import json
import logging
import sys
import webbrowser
import sqlite3
from pathlib import Path
from contextlib import closing
from .storage import Store, default_directory
from .instance import InstanceLock
from .transport import HttpClient, sync_catalog, probe


def main():
    parser = argparse.ArgumentParser(description="Albion Trade Desk — локальная экономическая аналитика")
    parser.add_argument("command", choices=("serve", "sync-catalog", "probe", "status"), nargs="?", default="serve")
    parser.add_argument("--data-dir", default=str(default_directory()))
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--server", default="east", choices=("east", "west", "europe"))
    parser.add_argument("--open", action="store_true", help="Открыть браузер")
    parser.add_argument("--verbose", action="store_true", help="Показать технические HTTP-журналы для диагностики")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s" if args.verbose else "%(message)s")
    directory = Path(args.data_dir)
    lock = InstanceLock(directory)
    try:
        if args.command == "serve":
            lock.acquire()
        # Carry an old source-install database forward once, including its live WAL.
        legacy = Path.cwd() / 'data' / 'trade-desk.sqlite3'
        if directory == default_directory() and not (directory / 'trade-desk.sqlite3').exists() and legacy.exists():
            directory.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(legacy)) as source, closing(sqlite3.connect(directory / 'trade-desk.sqlite3')) as target:
                source.backup(target)
        store = Store(directory)
        if args.command == "serve":
            from .web import make_server
            from .server_socket import available_server
            server = available_server(lambda port: make_server(store, port), args.port)
            if args.port and server.server_port != args.port:
                print(f"Порт {args.port} недоступен. Выбран свободный порт {server.server_port}.", flush=True)
            address = f"http://127.0.0.1:{server.server_port}"
            print("\nAlbion Trade Desk запущен.", flush=True)
            print("Адрес приложения: " + address, flush=True)
            print("Окно можно свернуть. Все действия выполняйте в браузере.", flush=True)
            print("Первый запуск: откройте «Мои наблюдения» и нажмите «Запустить сборщик».", flush=True)
            print("Для остановки нажмите Ctrl+C.\n", flush=True)
            if args.open:
                webbrowser.open(address)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.command == "status":
            print(json.dumps(store.status(), indent=2, ensure_ascii=False))
        else:
            client = HttpClient(store)
            result = sync_catalog(client) if args.command == "sync-catalog" else probe(client, args.server)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
