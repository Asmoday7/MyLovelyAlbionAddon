"""Owns only the supervisor we started; never terminates an existing AOD process."""
import base64
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid


def encoded_command(text):
    return base64.b64encode(text.encode('utf-16le')).decode('ascii')


class AodProcess:
    def __init__(self, store):
        self.store = store
        self.supported = os.name == "nt"
        self.lock = threading.RLock()
        self.process = None
        self.folder = None
        self.error = None

    def start(self, destination, session):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise ValueError('Сборщик уже запускается или работает')
            if not self.supported:
                raise ValueError('Запуск AOD доступен в Windows 10/11 x64. Локальный приёмник работает и на других ОС.')
            self.error = None
            self.folder = self.store.directory / 'scanner' / uuid.uuid4().hex
            self.folder.mkdir(parents=True)
            with self.store.connect() as db:
                row = db.execute("SELECT value FROM user_settings WHERE key='aod_path'").fetchone()
            pin = json.loads(Path(__file__).with_name('windows').joinpath('aod-release.json').read_text())
            config = {'destination': destination, 'session_id': session,
                      'client_path': json.loads(row[0]) if row else '',
                      'sha256': pin['windows_x64_sha256'], 'folder': str(self.folder.resolve())}
            config_path = self.folder / 'launch.json'
            config_path.write_text(json.dumps(config), encoding='utf-8')
            path64 = base64.b64encode(str(config_path.resolve()).encode('utf-8')).decode('ascii')
            preamble = "$managed = Get-Content -Raw -LiteralPath ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + path64 + "'))) | ConvertFrom-Json\n"
            script = Path(__file__).with_name('windows').joinpath('Start-PrivateScanner.ps1').read_text(encoding='utf-8-sig')
            payload = encoded_command(preamble + script)
            command_file = self.folder / 'guardian.command'
            command_file.write_text(payload, encoding='ascii')
            file64 = base64.b64encode(str(command_file.resolve()).encode('utf-8')).decode('ascii')
            loader = "& ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String([IO.File]::ReadAllText([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + file64 + "')))))))"
            # Own local code; no downloads, no ExecutionPolicy change, no user shell interpolation.
            bootstrap = ("$ErrorActionPreference='Stop'; try { $p=Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -PassThru "
                         "-ArgumentList @('-NoProfile','-STA','-EncodedCommand','" + encoded_command(loader) + "'); $p.WaitForExit(); exit $p.ExitCode } catch { exit 1 }")
            self.process = subprocess.Popen(['powershell.exe', '-NoProfile', '-EncodedCommand', encoded_command(bootstrap)],
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop(self):
        with self.lock:
            process, folder = self.process, self.folder
            if folder:
                (folder / 'stop').touch()
        if process and process.poll() is None:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # Do not kill the elevated guardian before it can stop its child and retain protection.
                self.error = 'Остановка ещё не подтверждена. Защитное правило сохраняется до завершения AOD.'
        return self.status()

    def status(self):
        with self.lock:
            result = {'managed': self.process is not None, 'active': bool(self.process and self.process.poll() is None),
                      'state': 'starting' if self.process and self.process.poll() is None else 'disabled',
                      'error': self.error, 'detected_server': None}
            if self.folder:
                try:
                    data = json.loads((self.folder / 'state.json').read_text(encoding='utf-8-sig'))
                    for key in ('state', 'error', 'pid', 'sha256', 'firewall_active', 'client_path', 'npcap'):
                        if key in data:
                            result[key] = data[key]
                    if data.get('client_path') and data.get('sha256'):
                        with self.store.connect() as db:
                            db.execute("INSERT OR REPLACE INTO user_settings VALUES('aod_path',?)", (json.dumps(data['client_path']),))
                except (OSError, ValueError):
                    pass  # Atomic status may not yet have been written during UAC/picker.
            if self.process and self.process.poll() is not None:
                if self.process.returncode or result['state'] not in ('disabled', 'error'):
                    result.update(state='error', error=result.get('error') or 'Запуск отменён либо AOD завершился. Проверьте журнал и разрешение Windows.')
                result['active'] = False
            if self.error:
                result.update(state='error', error=self.error)
            return result

    def logs(self):
        result = []
        if self.folder:
            for name in ('network-audit.jsonl', 'albiondata-client.log'):
                path = self.folder / name
                if path.exists():
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 32000))
                        text = stream.read().decode('utf-8-sig', errors='replace')
                    # The native client logs its base URL. Never expose the session token in UI/export.
                    import re
                    text = re.sub(r'/private/(east|west|europe)/[A-Za-z0-9_-]+', '/private/\\1/[hidden]', text)
                    result.extend(text.splitlines()[-80:])
        error = self.status().get('error')
        if error:
            result.append(error)
        return result[-100:]
