import ipv4_first  # IPv4 preferencial — ver ipv4_first.py
import tinytuya
import json
import os
import sys

# ---------------------------------------------------------------------------
# ConfiguraÃ§Ã£o â€” lida de config.json (nÃ£o versionado)
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

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
    valor = True if acao == 'abrir' else False
    c     = conectar_cloud()
    body  = {
        'time':        hora_str,
        'loops':       '1111111',
        'timezone_id': TIMEZONE,
        'functions':   [{'code': 'switch_1', 'value': valor}],
        'alias_name':  f'pier1_{acao}'
    }
    return c.cloudrequest(
        f'/v2.0/cloud/timer/device/{COB_ID}',
        action='POST',
        post=body
    )

# ---------------------------------------------------------------------------
# Teste rÃ¡pido
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("Testando API Cloud Tuya...")
    print("\n--- Timers existentes ---")
    print(listar_timers())
