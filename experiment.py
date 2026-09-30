#!/usr/bin/env python3
"""Fixed-input VeriEnv experiment. Generated code runs only in a disposable sandbox."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
UPSTREAM = 'f3a43895e0e496ac0c7435f69a92c7c94c05fa0d'

def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

def command(argv, cwd, log, timeout=900):
    with log.open('w') as f:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        except OSError as exc:
            f.write(str(exc) + '\n')
            return {'status': 'blocked', 'error': str(exc), 'argv': argv}
        try:
            code = proc.wait(timeout=timeout)
            return {'status': 'passed' if code == 0 else 'failed', 'returncode': code,
                    'argv': argv}
        except subprocess.TimeoutExpired:
            stop(proc)
            return {'status': 'failed', 'error': 'timeout', 'argv': argv}

def request(base, path, method='GET'):
    # This harness accesses loopback synthetic environments only.
    req = urllib.request.Request(base + path, data=b'{}' if method == 'POST' else None,
                                 headers={'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)

def verify(spec, state):
    if spec['kind'] == 'issue':
        return state.get('repo') == spec['seed']['repo'] and state.get('issues') == [spec['expected']]
    return state.get('products') == spec['seed']['products'] and state.get('cart') == [spec['expected']]

def stability(values):
    return {'values': values, 'stable': len(values) >= 2 and len(set(values)) == 1,
            'all_passed': bool(values) and all(values)}

def sdk_state(work, base):
    output = subprocess.check_output([sys.executable, '-c',
        'import json,sys; from sdk import Client; print(json.dumps(Client(sys.argv[1]).state()))',
        base], cwd=work, timeout=10, stderr=subprocess.STDOUT)
    return json.loads(output)

def prompt(spec):
    return '''Implement a minimal local synthetic %s environment, adapting VeriEnv's
website + backend + SDK + reset pattern. Work only inside this directory.
This fixed functional specification replaces absent screenshots; do not claim visual fidelity.
Do not contact GitHub, Amazon, Linear, or any external data API. Use only seeded data.
Use Python standard library HTTP server + SQLite + HTML/JS, no package installation needed.
Bind only 127.0.0.1:%s. Start using python3 app.py and initialize persistent SQLite state.
Provide GET /health returning {"ok":true}; POST /reset restores exactly the seed;
GET /state returns current persisted state as JSON, with no writes or caching.
Provide sdk.py exposing Client(base_url).state() and .reset() using urllib.
UI at / must contain a search input data-testid="search", button "search-submit",
matching result link/button "result", and details container "details" containing
repo name for GitHub or product name for Amazon. Search must filter actual seeded data.
GitHub: details includes inputs "issue-title", "issue-body" and button "create-issue";
click inserts one issue with exactly title/body keys into persistent issues list.
Amazon: details includes button "add-cart"; click adds one product with product_id/quantity
keys to persistent cart list. No checkout or payment flows.
Provide these exact test IDs with unique elements, actual browser handlers, no placeholders.
Preserve seed data, implement repeatable reset, and write website_description.md,
start_servers.sh, reset_servers.sh and task_instructions.json documenting the one fixed task.
The server must stay in foreground. Do not start servers or leave background processes.
Do not change input files. Fixed specification follows:\n%s
''' % (spec['site'], spec['port'], json.dumps(spec, indent=2))

def evaluate(spec, work, out):
    result = {'status': 'failed', 'interaction_runs': [], 'verifier': None}
    base = 'http://127.0.0.1:' + str(spec['port'])
    # Do not reset/operate a pre-existing service on our reserved port.
    import socket
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', spec['port'])) == 0:
            return {'status': 'blocked', 'error': 'reserved port already occupied'}
    with (out / 'server.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, 'app.py'], cwd=work, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError('server exited before readiness')
                try:
                    if request(base, '/health').get('ok') is True:
                        break
                except Exception:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('health timeout')
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for i in range(spec['reset_repeats']):
                        trial = {'trial': i, 'interaction': 'failed'}
                        result['interaction_runs'].append(trial)
                        request(base, '/reset', 'POST')
                        before = request(base, '/state')
                        dump(out / f'{i}-before.json', before)
                        if before != spec['seed'] or verify(spec, before):
                            raise AssertionError('reset state incorrect or baseline falsely passes')
                        context = browser.new_context(viewport={'width':1280,'height':800})
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        page = context.new_page()
                        page.on('console', lambda msg: (out / 'browser.log').open('a').write(msg.text+'\n'))
                        page.on('pageerror', lambda err: (out / 'browser.log').open('a').write(str(err)+'\n'))
                        # Block all non-loopback browser requests, including external resources.
                        from urllib.parse import urlparse
                        context.route('**/*', lambda route: route.continue_() if
                            urlparse(route.request.url).hostname == '127.0.0.1' and
                            urlparse(route.request.url).port == spec['port'] else route.abort())
                        try:
                            page.goto(base, wait_until='networkidle', timeout=15000)
                            term = spec['seed']['repo'] if spec['kind']=='issue' else spec['seed']['products'][0]['name']
                            page.get_by_test_id('search').fill(term)
                            page.get_by_test_id('search-submit').click()
                            page.get_by_test_id('result').click()
                            from playwright.sync_api import expect
                            expect(page.get_by_test_id('details')).to_contain_text(term)
                            if spec['kind'] == 'issue':
                                page.get_by_test_id('issue-title').fill(spec['expected']['title'])
                                page.get_by_test_id('issue-body').fill(spec['expected']['body'])
                                page.get_by_test_id('create-issue').click()
                            else:
                                page.get_by_test_id('add-cart').click()
                            # Allow asynchronous UI persistence to finish before frozen-state checks.
                            for _ in range(50):
                                if verify(spec, request(base, '/state')):
                                    break
                                time.sleep(.1)
                            states = [sdk_state(work, base) for _ in range(spec['verifier_repeats'])]
                            dump(out / f'{i}-states.json', states)
                            if any(s != request(base, '/state') for s in states):
                                raise AssertionError('SDK and persisted HTTP state disagree')
                            checks = [verify(spec, state) for state in states]
                            trial.update(interaction='passed' if all(checks) else 'failed',
                                         verifier=stability(checks), state_stable=all(s==states[0] for s in states))
                            page.screenshot(path=str(out / f'{i}-final.png'), full_page=True)
                        finally:
                            context.tracing.stop(path=str(out / f'{i}-trace.zip'))
                            context.close()
                finally:
                    browser.close()
            values = [v for t in result['interaction_runs'] for v in t['verifier']['values']]
            result['verifier'] = stability(values)
            result['status'] = 'passed' if result['verifier']['all_passed'] and all(
                t['state_stable'] for t in result['interaction_runs']) else 'failed'
        except Exception:
            result['error'] = traceback.format_exc()
            (out / 'failure.log').write_text(result['error'])
        finally:
            stop(proc)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['generate','evaluate'])
    parser.add_argument('--site', choices=['github','amazon','all'], default='all')
    parser.add_argument('--run-dir', type=Path, help='Required for evaluate; output directory for generate')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if args.mode == 'evaluate' and not args.run_dir:
        parser.error('evaluate requires --run-dir from a prior generation')
    out = (args.run_dir or ROOT/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for site in (['github','amazon'] if args.site=='all' else [args.site]):
        dest=out/site
        work=dest/'environment'
        if args.mode=='generate':
            if dest.exists():
                parser.error('refusing to overwrite previous generation')
            work.mkdir(parents=True)
            raw=(ROOT/'inputs'/f'{site}.json').read_bytes()
            spec=json.loads(raw)
            (dest/'input.json').write_bytes(raw)
            text=prompt(spec)
            (dest/'prompt.txt').write_text(text)
            dump(dest/'manifest.json', {'upstream_commit':UPSTREAM,'input_sha256':digest(raw),
                'prompt_sha256':digest(text.encode()),'model':spec['model'],
                'python':platform.python_version(),'platform':platform.platform(),
                'note':'Fixed inputs do not guarantee deterministic LLM generation.'})
            argv=['cursor-agent','-p','--force','--output-format','stream-json',
                  '--stream-partial-output','--model',spec['model'],text]
            generation=command(argv, work, dest/'generation.log', args.timeout)
            # Avoid embedding the prompt twice in result files.
            generation['argv'] = argv[:-1]+['<prompt.txt>']
            required=['app.py','sdk.py','website_description.md','start_servers.sh',
                      'reset_servers.sh','task_instructions.json']
            missing=[p for p in required if not (work/p).is_file()]
            if generation['status']=='passed' and missing:
                generation.update(status='failed',error='missing required artifacts',missing=missing)
            dump(dest/'generation.json',generation)
            results[site]={'generation':generation,'interaction':'not_tested','verifier':'not_tested'}
        else:
            try:
                raw=(dest/'input.json').read_bytes()
                manifest=json.loads((dest/'manifest.json').read_text())
                if digest(raw)!=manifest['input_sha256']:
                    raise ValueError('frozen input hash mismatch')
                spec=json.loads(raw)
                generation=json.loads((dest/'generation.json').read_text())
                if generation['status']!='passed':
                    results[site]={'status':'blocked','error':'generation did not pass',
                                   'interaction':'not_tested','verifier':'not_tested'}
                else:
                    evaluation=dest/('evaluation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
                    evaluation.mkdir()
                    results[site]=evaluate(spec,work,evaluation)
                    dump(evaluation/'result.json',results[site])
            except Exception:
                results[site]={'status':'failed','error':traceback.format_exc()}
    filename='generation-summary.json' if args.mode=='generate' else 'evaluation-summary.json'
    dump(out/filename,results)
    print(json.dumps({'run_dir':str(out),'results':results},indent=2))
    return 0 if all((r.get('generation') or r)['status']=='passed' for r in results.values()) else 1

if __name__=='__main__':
    sys.exit(main())
