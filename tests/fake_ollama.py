"""Ollama simulado (puerto 18434) con soporte de cascada: /api/tags, /api/ps, /api/generate, /api/chat (+logprobs), /_calls."""
import json, math, os, re
from http.server import BaseHTTPRequestHandler, HTTPServer

CALLS = []
CONF = {'logprobs': os.environ.get('FAKE_LOGPROBS', '1') != '0'}
INSTALLED = os.environ.get('FAKE_TAGS', 'qwen3:1.7b,qwen3:4b').split(',')
KEY = {'Capital de Francia?': 'Paris', 'Capital de Italia?': 'Roma', 'Pregunta dificil': 'Beta', 'Capital de Japon?': 'Tokio',
       'Capital de Peru?': 'Lima', 'Capital de Chile?': 'Santiago'}


def is_fast(model):
    return '1.7b' in model or '0.6b' in model


def lp(letter, conf, others):
    return [{'token': letter, 'logprob': math.log(conf),
             'top_logprobs': [{'token': letter, 'logprob': math.log(conf)}] +
                             [{'token': o, 'logprob': math.log((1 - conf) / max(1, len(others)))} for o in others]}]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == '/_calls': return self._send(CALLS)
        if self.path.startswith('/api/ps'): return self._send({'models': []})
        self._send({'models': [{'name': n} for n in INSTALLED]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/_reset':
            CALLS.clear(); return self._send({})
        if self.path == '/api/generate':
            return self._send({'response': '1, 2', 'eval_count': 24, 'eval_duration': int(1e9)})
        model, msgs = body['model'], body['messages']
        system, user = msgs[0]['content'], msgs[1]['content']
        if body.get('logprobs') and not CONF['logprobs']:
            return self._send({'error': 'logprobs unsupported'}, 400)
        base = {'eval_count': 2, 'eval_duration': int(2e7), 'prompt_eval_count': 120}
        if 'ÚNICAMENTE con la letra' in system or 'RESPUESTA:' in system:
            stem = re.search(r'<pregunta>\n(.*?)\n</pregunta>', user, re.S).group(1)
            opts = dict((m.group(1), m.group(2)) for m in re.finditer(r'^([A-Z])\) (.*)$', user, re.M))
            correct = next(l for l, t in opts.items() if t == KEY.get(stem, 'Paris'))
            wrong = [l for l in opts if l != correct]
            answer, conf = correct, 0.97
            if is_fast(model) and stem == 'Pregunta dificil':
                answer, conf = wrong[0], 0.55
            task = 'closed-fast' if 'ÚNICAMENTE' in system else 'closed-strong'
            CALLS.append({'model': model, 'task': task, 'think': body.get('think'), 'stem': stem})
            if task == 'closed-strong':
                return self._send({'message': {'content': 'Razono...\nRESPUESTA: ' + correct}, **base})
            resp = {'message': {'content': answer}, **base}
            if body.get('logprobs'):
                resp['logprobs'] = lp(answer, conf, [l for l in opts if l != answer])
            return self._send(resp)
        if 'dígito' in system or 'NOTA:' in system:
            task = 'open-fast' if 'SOLO un dígito' in system else 'open-strong'
            CALLS.append({'model': model, 'task': task, 'think': body.get('think'), 'user': user})
            if task == 'open-strong':
                return self._send({'message': {'content': 'Razono...\nNOTA: 2'}, **base})
            digit, conf = ('4', 0.97) if 'ABRIR facil' in user else ('2', 0.80)
            resp = {'message': {'content': digit}, **base}
            if body.get('logprobs'):
                resp['logprobs'] = lp(digit, conf, [d for d in '01234' if d != digit])
            return self._send(resp)
        if 'Eres docente' in system:
            CALLS.append({'model': model, 'task': 'explain', 'user': user})
            return self._send({'message': {'content': 'Explicación simulada.'}, **base})
        CALLS.append({'model': model, 'task': 'unknown'})
        self._send({'message': {'content': ''}})


if __name__ == '__main__':
    HTTPServer(('127.0.0.1', int(os.environ.get('FAKE_PORT', '18434'))), H).serve_forever()
