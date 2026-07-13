# verificar_timers_pier2.py — SÓ LEITURA. Roda no Pier2-MiniPC.
# Lê os device IDs do config.json local (fonte de verdade).

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import json
from tuya_cloud import conectar_cloud

with open(os.path.join(PROJECT_DIR, 'config.json'), encoding='utf-8-sig') as f:
    cfg = json.load(f)

alvos = [
    ('COBERTURA', cfg['cobertura']['id']),
    ('REGUA',     cfg['regua']['id']),
]

c = conectar_cloud()

for nome, dev_id in alvos:
    print("=" * 55)
    print(f"{nome}  (device {dev_id})")
    print("=" * 55)
    r = c.cloudrequest(f'/v2.0/cloud/timer/device/{dev_id}', action='GET')
    if not isinstance(r, dict):
        print("Resposta inesperada:", r); continue
    if not r.get('success'):
        print("SEM ACESSO / erro:", r.get('msg') or r)
        print("→ device provavelmente NÃO está no projeto Cloud dessas credenciais.")
        continue
    timers = r.get('result', [])
    ativos = [t for t in timers if t.get('enable')]
    print(f"Total: {len(timers)}  |  Ativos (enable=True): {len(ativos)}")
    for t in timers:
        acao = 'ABRIR' if t['functions'][0]['value'] else 'fechar'
        en = 'ATIVO' if t.get('enable') else 'inativo'
        print(f"  {t['time']}  {acao:6s}  {en:7s}  id={t['timer_id']}  alias={t.get('alias_name','')}")
    print()