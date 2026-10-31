"""Reproducible, scoped network experiment using upstream dispatcher/http uploader.

Requires a verified official Go 1.25+ toolchain, strace, and an audited checkout.
Only synthetic fixtures and loopback recording servers are used. This is NOT a
live Windows/game test: updater, packet capture and real WebSockets are excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server

UPSTREAM = 'c6edd9456bec4657755c25f173e8ebc7a31a17f7'
SUPPORT = '''package client
import "net/http"
type uploader interface { sendToIngest([]byte,string,*albionState,string) }
type albionState struct { AODataIngestBaseURL,CharacterId,CharacterName string }
var ConfigGlobal=struct { PublicIngestBaseUrls,PrivateIngestBaseUrls string; EnableWebsockets,DisableUpload bool }{}
type WSHub struct { broadcast chan []byte }
func newHub()*WSHub{return &WSHub{broadcast:make(chan []byte,10)}}
func(h *WSHub)run(){}
func serveWs(h *WSHub,w http.ResponseWriter,r *http.Request){}
func newHTTPUploaderPow(s string)uploader{panic("unexpected PoW destination")}
func newNATSUploader(s string)uploader{panic("unexpected publish destination")}
'''
TEST = '''package client
import("encoding/json";"fmt";"net/http";"net/http/httptest";"os";"sync/atomic";"testing";"time")
type personal struct { CharacterName string }
func(p *personal)Personalize(a,b string){p.CharacterName="synthetic-player"}
func TestPrivateRoutingWire(t *testing.T){
 var local,public atomic.Int32
 l:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){local.Add(1);w.WriteHeader(200)}));defer l.Close()
 p:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){public.Add(1);w.WriteHeader(200)}));defer p.Close()
 ConfigGlobal.PublicIngestBaseUrls=l.URL;ConfigGlobal.PrivateIngestBaseUrls="";ConfigGlobal.EnableWebsockets=false;ConfigGlobal.DisableUpload=false
 sendMsgToPublicUploaders(map[string]any{"Orders":[]any{}},"marketorders.ingest",&albionState{},"test",1)
 if local.Load()!=1||public.Load()!=0{t.Fatal("private destination isolation failed")}
 sendMsgToPrivateUploaders(&personal{},"skills.ingest",&albionState{},"test")
 if local.Load()!=1||public.Load()!=0{t.Fatal("personalized message escaped")}
 ConfigGlobal.DisableUpload=true
 sendMsgToPublicUploaders(map[string]any{},"marketorders.ingest",&albionState{},"test",1)
 if local.Load()!=1{t.Fatal("-d did not block LOCAL upload")}
 ConfigGlobal.DisableUpload=false
 ConfigGlobal.PublicIngestBaseUrls=l.URL+","+p.URL
 sendMsgToPublicUploaders(map[string]any{},"marketorders.ingest",&albionState{},"test",1)
 if local.Load()!=2||public.Load()!=1{t.Fatal("positive dual-destination control failed")}
 fmt.Printf("recording-sinks local=%d public-control=%d (positive control only)\\n",local.Load(),public.Load())
 // Private route into the actual Python/SQLite application, not a mock receiver.
 ConfigGlobal.PublicIngestBaseUrls=os.Getenv("ATD_PRIVATE_DESTINATION")
 expires:=time.Now().UTC().Add(time.Hour).Format(time.RFC3339)
 orders:=map[string]any{"Orders":[]any{map[string]any{"Id":123,"ItemTypeId":"T4_BAG","LocationId":"3005","QualityLevel":1,"EnchantmentLevel":0,"UnitPriceSilver":1500000,"Amount":1,"AuctionType":"offer","Expires":expires}}}
 sendMsgToPublicUploaders(orders,"marketorders.ingest",&albionState{},"test",1)
 sendMsgToPublicUploaders(orders,"marketorders.ingest",&albionState{},"test",1)
 var history any
 if err:=json.Unmarshal([]byte(os.Getenv("ATD_HISTORY_FIXTURE")),&history);err!=nil{t.Fatal(err)}
 sendMsgToPublicUploaders(history,"markethistories.ingest",&albionState{},"test",1)
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--go', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, output = Path(args.checkout), Path(args.output)
    rev = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if rev != UPSTREAM:
        raise RuntimeError('Audit a changed upstream revision before changing this experiment pin')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for p in ('client', 'lib', 'log', 'internal/dashboard'):
            (root / p).mkdir(parents=True)
        hashes = {}
        for name in ('dispatcher.go', 'uploader_http.go'):
            data = (source / 'client' / name).read_bytes()
            expected = subprocess.check_output(['git', '-C', str(source), 'show', rev + ':client/' + name])
            if data != expected:
                raise RuntimeError('Upstream file has local modifications: ' + name)
            hashes[name] = hashlib.sha256(data).hexdigest()
            (root / 'client' / name).write_bytes(data)
        shutil.copyfile(source / 'LICENSE', root / 'LICENSE-upstream')
        (root / 'go.mod').write_text('module github.com/ao-data/albiondata-client\n\ngo 1.25.0\n')
        (root / 'client/support.go').write_text(SUPPORT)
        (root / 'client/privacy_wire_test.go').write_text(TEST)
        (root / 'lib/stub.go').write_text('package lib\ntype PersonalizedUpload interface {Personalize(string,string)}\n')
        (root / 'log/stub.go').write_text('package log\nfunc Infof(s string,a ...any){}\nfunc Errorf(s string,a ...any){}\nfunc Info(a ...any){}\nfunc Panic(a ...any){panic(a)}\n')
        (root / 'internal/dashboard/stub.go').write_text('package dashboard\nfunc IncrementCounterBy(s string,i int64){}\n')
        store = Store(root / 'database')
        import_catalog(store, [{'UniqueName': 'T4_BAG', 'Index': 1, 'LocalizedNames': {'RU-RU': 'Тестовая сумка', 'EN-US': 'Synthetic fixture'}}])
        server = make_server(store, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            server.private_scanner.start('east', True)
            env = dict(os.environ)
            env['GOTOOLCHAIN'] = 'local'
            env['ATD_PRIVATE_DESTINATION'] = server.private_scanner.destination()
            start = int(time.time() // 3600) * 3600 - 3600
            env['ATD_HISTORY_FIXTURE'] = json.dumps({'AlbionId': 1, 'LocationId': '3005', 'QualityLevel': 1, 'Timescale': 0,
                'MarketHistories': [{'Timestamp': start * 10000000 + 621355968000000000, 'ItemAmount': 2, 'SilverAmount': 2000000}]})
            binary = root / 'wire.test'
            subprocess.run([args.go, 'test', '-c', '-o', str(binary), './client'], cwd=root, env=env, check=True)
            trace = output / 'connect.trace'
            result = subprocess.run(['strace', '-f', '-e', 'trace=connect', '-o', str(trace), str(binary), '-test.v'],
                                    cwd=root, env=env, capture_output=True, text=True)
            (output / 'wire-test.log').write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('Official source wire test failed: see wire-test.log')
            connections = [line for line in trace.read_text().splitlines() if 'AF_INET' in line]
            if not connections or any('inet_addr("127.0.0.1")' not in line for line in connections):
                raise RuntimeError('Observed unexpected/non-loopback connect: inspect the scoped trace')
            with store.connect() as db:
                quotes = [dict(r) for r in db.execute("SELECT source,price FROM quotes")]
                native = db.execute("SELECT COUNT(*) FROM native_history WHERE source='private-client'").fetchone()[0]
                hours = db.execute("SELECT quantity,average FROM history WHERE source='private-client'").fetchone()
            status = server.private_scanner.status()
            assert quotes == [{'source': 'private-client', 'price': 150.0}]
            assert native == 1 and hours['quantity'] == 2 and hours['average'] == 100
            assert status['duplicates'] == 1 and status['records'] == 2
            report = {'scope': 'synthetic loopback experiment, NOT full Windows client/game', 'upstream_commit': rev,
                      'upstream_files_sha256': hashes, 'routing_tests_passed': True, 'socket_trace_loopback_only': True,
                      'inet_connect_calls': len(connections), 'sqlite_bridge_passed': True,
                      'windows_firewall_tested': False, 'live_game_tested': False, 'sbi_permission_confirmed': False}
            (output / 'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        finally:
            server.private_scanner.stop()
            server.public_nats.stop()
            server.shutdown()
            thread.join()
            server.server_close()
            server.jobs.executor.shutdown(wait=True)


if __name__ == '__main__':
    main()
