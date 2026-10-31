import argparse
import json
import logging
import sys
import webbrowser
from .storage import Store
from .transport import HttpClient, sync_catalog, probe


def main():
    parser = argparse.ArgumentParser(description="Albion Trade Desk — локальная экономическая аналитика")
    parser.add_argument("command", choices=("serve", "sync-catalog", "probe", "status"), nargs="?", default="serve")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--server", default="east", choices=("east", "west", "europe"))
    parser.add_argument("--open", action="store_true", help="Открыть браузер")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(args.data_dir)
    try:
        if args.command == "serve":
            from .web import make_server
            server = make_server(store, args.port)
            address = f"http://127.0.0.1:{server.server_port}"
            print("Albion Trade Desk: " + address, flush=True)
            if args.open:
                webbrowser.open(address)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
                server.jobs.executor.shutdown(wait=True, cancel_futures=True)
        elif args.command == "status":
            print(json.dumps(store.status(), indent=2, ensure_ascii=False))
        else:
            client = HttpClient(store)
            result = sync_catalog(client) if args.command == "sync-catalog" else probe(client, args.server)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
