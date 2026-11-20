from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from app.config import settings


def fingerprint(snapshot: dict[str, Any]) -> str:
    """Identifica un examen sin depender de las notas (que cambian al publicar)."""
    url = str(snapshot.get('url', '')).split('#')[0]
    texts = '|'.join(
        f"{q.get('question_id') or ''}:{(q.get('question_text') or q.get('raw_text') or '')[:80]}"
        for q in snapshot.get('questions', [])
    )
    return hashlib.sha256(f'{url}\n{texts}'.encode('utf-8')).hexdigest()[:16]


class Store:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / 'state.json'
        self.log_path = self.dir / 'publish_log.jsonl'
        self.lock = threading.RLock()
        self.data: dict[str, Any] = self._default()
        self.load()

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            'snapshot': None,
            'fingerprint': None,
            'instructions': '',
            'results': {},
            'overrides': {},
            'published': {},
            'settings': {
                'write_explanations': settings.write_explanations,
                'overwrite_explanations': settings.overwrite_explanations,
                'force_all': False,
                'time_budget_s': settings.time_budget_s,
            },
        }

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding='utf-8'))
                self.data.update({k: v for k, v in loaded.items() if k in self.data})
                self.data['settings'] = {**self._default()['settings'], **self.data.get('settings', {})}
            except Exception:
                pass

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding='utf-8')
            tmp.replace(self.path)

    def append_log(self, entry: dict[str, Any]) -> None:
        with self.lock, self.log_path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
