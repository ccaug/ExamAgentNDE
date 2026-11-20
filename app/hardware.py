"""Detección de hardware y elección automática de modelos por nivel (rápido / fuerte)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any


def _ram_gb() -> float | None:
    try:
        import psutil  # type: ignore
        return round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    try:
        return round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30, 1)
    except Exception:
        pass
    try:  # Windows sin psutil
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('l', ctypes.c_ulong), ('m', ctypes.c_ulong), ('total', ctypes.c_ulonglong)] + \
                       [(f'x{i}', ctypes.c_ulonglong) for i in range(5)]
        ms = MS(); ms.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))  # type: ignore[attr-defined]
        return round(ms.total / 2**30, 1)
    except Exception:
        return None


def detect() -> dict[str, Any]:
    gpu = None
    if shutil.which('nvidia-smi'):
        try:
            out = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                                 capture_output=True, text=True, timeout=4).stdout.strip().splitlines()
            best = None
            for line in out:
                name, mem = [x.strip() for x in line.rsplit(',', 1)]
                vram = float(mem) / 1024
                if best is None or vram > best['vram_gb']:
                    best = {'vendor': 'nvidia', 'name': name, 'vram_gb': round(vram, 1)}
            gpu = best
        except Exception:
            gpu = None
    ram = _ram_gb()
    if gpu is None and platform.system() == 'Darwin' and platform.machine() == 'arm64' and ram:
        gpu = {'vendor': 'apple', 'name': 'Apple Silicon (memoria unificada)', 'vram_gb': round(ram * 0.65, 1)}
    return {'gpu': gpu, 'ram_gb': ram, 'cpu_threads': os.cpu_count(), 'os': platform.system(), 'machine': platform.machine()}


# (preferencias del modelo RÁPIDO, preferencias del modelo FUERTE), de mejor a peor.
CLASSES: dict[str, tuple[list[str], list[str]]] = {
    'gpu_xl': (['qwen3:4b', 'qwen3:1.7b'], ['qwen3:30b-a3b', 'qwen3:14b', 'qwen3:8b', 'qwen3:4b']),
    'gpu_l': (['qwen3:4b', 'qwen3:1.7b'], ['qwen3:14b', 'qwen3:8b', 'qwen3:4b']),
    'gpu_m': (['qwen3:4b', 'qwen3:1.7b'], ['qwen3:8b', 'qwen3:4b']),
    'gpu_s': (['qwen3:1.7b', 'qwen3:0.6b'], ['qwen3:4b', 'qwen3:1.7b']),
    'cpu_l': (['qwen3:1.7b', 'qwen3:0.6b'], ['qwen3:4b', 'qwen3:1.7b']),
    'cpu_s': (['qwen3:0.6b'], ['qwen3:1.7b', 'qwen3:0.6b']),
    'cpu_xs': (['qwen3:0.6b'], ['qwen3:0.6b']),
}


def classify(hw: dict[str, Any]) -> str:
    gpu = hw.get('gpu')
    if gpu:
        v = gpu['vram_gb']
        return 'gpu_xl' if v >= 20 else 'gpu_l' if v >= 12 else 'gpu_m' if v >= 7 else 'gpu_s' if v >= 3.5 else 'cpu_l'
    ram = hw.get('ram_gb') or 8
    return 'cpu_l' if ram >= 12 else 'cpu_s' if ram >= 6 else 'cpu_xs'


def _has(installed: list[str], name: str) -> bool:
    return any(i == name or i == name + ':latest' or i.split(':')[0] + ':' + i.split(':')[-1] == name for i in installed)


def resolve(hw: dict[str, Any], installed: list[str] | None, fast_override: str = '', strong_override: str = '',
            workers_setting: int = 0) -> dict[str, Any]:
    """Elige los modelos de cada nivel entre los instalados; lista lo que conviene descargar."""
    cls = classify(hw)
    fast_pref, strong_pref = CLASSES[cls]
    inst = installed or []

    def pick(prefs: list[str], override: str) -> tuple[str, str | None]:
        if override:
            return override, (None if (not installed or _has(inst, override)) else override)
        for p in prefs:
            if _has(inst, p):
                recommended_missing = prefs[0] if p != prefs[0] and installed is not None else None
                return p, recommended_missing
        if inst:  # nada preferido instalado: usa lo que haya
            return inst[0], prefs[0]
        return prefs[0], prefs[0] if installed is not None else None

    fast, fast_missing = pick(fast_pref, fast_override)
    strong, strong_missing = pick(strong_pref, strong_override)
    missing = [m for m in dict.fromkeys([fast_missing, strong_missing]) if m]
    workers = workers_setting if workers_setting > 0 else (2 if hw.get('gpu') else 1)
    return {'class': cls, 'fast': fast, 'strong': strong, 'workers': workers, 'missing': missing,
            'same_model': fast == strong, 'gpu': bool(hw.get('gpu'))}
