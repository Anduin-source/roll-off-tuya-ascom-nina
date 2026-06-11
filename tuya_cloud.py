import ipv4_first  # IPv4 preferencial — ver ipv4_first.py
import tinytuya
import json
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# ConfiguraÃ§Ã£o â€” lida de config.json (nÃ£o versionado)
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

log = logging.getLogger('tuya_cloud')
log.setLevel(logging.INFO)
if not log.handlers:
    _fh = RotatingFileHandler(os.path.join(BASE_DIR, 'tuya_cloud.log'),
                              maxBytes=500_000, backupCount=2, encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s',
                                       datefmt='%Y-%m-%d %H:%M:%S'))
    log.addHandler(_fh)

def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        print("ERRO: config.json nÃ£o encontrado.")
        print("Copie config_exemplo.json para config.json e preencha suas credenciais.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

cfg = carregar_config()

API_REGION = cfg['tuya_cloud']['region']
API_KEY    = cfg['tuya_cloud']['api_key']
API_SECRET = cfg['tuya_cloud']['api_secret']
COB_ID     = cfg['cobertura']['id']
TIMEZONE   = cfg['tuya_cloud'].get('timezone', 'America/Sao_Paulo')
TIMER_CATEGORY = cfg['tuya_cloud'].get('timer_category', 'schedule')

# ---------------------------------------------------------------------------
# FunÃ§Ãµes
# ---------------------------------------------------------------------------

def conectar_cloud():
    return tinytuya.Cloud(
        apiRegion=API_REGION,
        apiKey=API_KEY,
        apiSecret=API_SECRET
    )

def listar_timers():
    c = conectar_cloud()
    return c.cloudrequest(f'/v2.0/cloud/timer/device/{COB_ID}')

def deletar_todos_timers():
    c = conectar_cloud()
    return c.cloudrequest(
        f'/v2.0/cloud/timer/device/{COB_ID}/batch',
        action='DELETE'
    )

def criar_timer(hora_str, acao):
    """
    hora_str : 'HH:MM'
    acao     : 'abrir' ou 'fechar'
    """
    if acao not in ('abrir', 'fechar'):
        raise ValueError(f'Acao invalida: {acao!r}')
    valor = True if acao == 'abrir' else False
    c     = conectar_cloud()
    body  = {
        'category':    TIMER_CATEGORY,
        'time':        hora_str,
        'loops':       '1111111',
        'timezone_id': TIMEZONE,
        'functions':   [{'code': 'switch_1', 'value': valor}],
        'alias_name':  f'pier1_{acao}'
    }
    try:
        resposta = c.cloudrequest(
            f'/v2.0/cloud/timer/device/{COB_ID}',
            action='POST',
            post=body
        )
        log.info('criar_timer acao=%s hora=%s category=%s resposta=%r',
                 acao, hora_str, TIMER_CATEGORY, resposta)
        return resposta
    except Exception:
        log.exception('criar_timer falhou acao=%s hora=%s category=%s',
                      acao, hora_str, TIMER_CATEGORY)
        raise

# ---------------------------------------------------------------------------
# Teste rÃ¡pido
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] in ('abrir', 'fechar'):
        print(criar_timer(sys.argv[2], sys.argv[1]))
    else:
        print("Testando API Cloud Tuya...")
        print("\n--- Timers existentes ---")
        print(listar_timers())
