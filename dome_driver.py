import ipv4_first  # IPv4 preferencial — ver ipv4_first.py
import threading
import time
import socket
import json
import os
import sys
from flask import Flask, jsonify, request
import tinytuya

# ---------------------------------------------------------------------------
# Configuracao â€” lida de config.json (nao versionado)
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        print("ERRO: config.json nao encontrado.")
        print("Copie config.exemplo.json para config.json e preencha suas credenciais.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

cfg = carregar_config()

COB_ID     = cfg['cobertura']['id']
COB_IP     = cfg['cobertura']['ip']
COB_KEY    = cfg['cobertura']['key']
VERSION    = 3.4

API_REGION = cfg['tuya_cloud']['region']
API_KEY    = cfg['tuya_cloud']['api_key']
API_SECRET = cfg['tuya_cloud']['api_secret']

# ---------------------------------------------------------------------------
# Estado interno
# ---------------------------------------------------------------------------

_connected  = False
_shutter    = 'Unknown'
_modo_cloud = False          # True quando operando via cloud fallback
_lock       = threading.Lock()

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Cloud singleton
# ---------------------------------------------------------------------------

_cloud      = None
_cloud_lock = threading.Lock()

def get_cloud():
    global _cloud
    with _cloud_lock:
        if _cloud is None:
            _cloud = tinytuya.Cloud(
                apiRegion=API_REGION,
                apiKey=API_KEY,
                apiSecret=API_SECRET
            )
    return _cloud

# ---------------------------------------------------------------------------
# Comunicacao com o dispositivo
# ---------------------------------------------------------------------------

def conectar():
    d = tinytuya.Device(dev_id=COB_ID, address=COB_IP,
                        local_key=COB_KEY, version=VERSION)
    d.set_socketTimeout(3)
    return d

def ler_status():
    global _shutter, _connected, _modo_cloud

    # --- Tentativa local ---
    try:
        d = conectar()
        s = d.status()
        if 'dps' in s:
            aberta = s['dps'].get('3', False)
            with _lock:
                _shutter    = 'Open' if aberta else 'Closed'
                _connected  = True
                _modo_cloud = False
            return
        # Se retornou erro (914 etc), cai para cloud
    except Exception:
        pass

    # --- Fallback cloud ---
    try:
        cloud = get_cloud()
        r = cloud.getstatus(COB_ID)
        if 'result' in r:
            for dp in r['result']:
                if dp.get('code') == 'doorcontact_state':
                    aberta = dp.get('value', False)
                    with _lock:
                        _shutter    = 'Open' if aberta else 'Closed'
                        _connected  = True
                        _modo_cloud = True
                    return
    except Exception:
        pass

    # --- Ambos falharam ---
    with _lock:
        _shutter    = 'Error'
        _connected  = False
        _modo_cloud = False

def enviar_comando(comando):
    """Envia 'open' ou 'close'. Tenta local, depois cloud. Retorna (ok, modo)."""
    # --- Tentativa local ---
    try:
        d = conectar()
        result = d.set_value(6, comando)
        if isinstance(result, dict) and 'Err' in result:
            raise Exception(f"Err {result['Err']}")
        return True, 'local'
    except Exception:
        pass

    # --- Fallback cloud ---
    try:
        cloud = get_cloud()
        cloud.sendcommand(COB_ID, [{'code': 'door_control_1', 'value': comando}])
        return True, 'cloud'
    except Exception as e:
        return False, str(e)

def poll_status():
    while True:
        ler_status()
        with _lock:
            modo = 'cloud' if _modo_cloud else 'local'
            s    = _shutter
        print(f"[poll] status={s} modo={modo}")
        time.sleep(30)

# ---------------------------------------------------------------------------
# Alpaca discovery (UDP)
# ---------------------------------------------------------------------------

def alpaca_discovery():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 32227))
    print("Alpaca Discovery rodando na porta 32227")
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if b'alpacadiscovery' in data.lower():
                response = json.dumps({'AlpacaPort': 11111}).encode()
                sock.sendto(response, addr)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Management endpoints
# ---------------------------------------------------------------------------

@app.route('/management/apiversions', methods=['GET'])
def api_versions2():
    return jsonify({'Value': [1]})

@app.route('/management/v1/apiversions', methods=['GET'])
def api_versions():
    return jsonify({'Value': [1]})

@app.route('/management/v1/description', methods=['GET'])
def management_description():
    return jsonify({
        'Value': {
            'ServerName': 'Pier 1 Tuya Dome',
            'Manufacturer': 'Observatorio Munhoz',
            'ManufacturerVersion': '1.1',
            'Location': 'Munhoz MG'
        },
        'ErrorNumber': 0,
        'ErrorMessage': ''
    })

@app.route('/management/v1/configureddevices', methods=['GET'])
def configured_devices():
    return jsonify({'Value': [{
        'DeviceName': 'Pier 1 Tuya Dome',
        'DeviceType': 'Dome',
        'DeviceNumber': 0,
        'UniqueID': 'pier1-tuya-dome-001'
    }]})

# ---------------------------------------------------------------------------
# Dome endpoints
# ---------------------------------------------------------------------------

@app.route('/api/v1/dome/0/connected', methods=['GET'])
def get_connected():
    with _lock:
        val = _connected
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/connected', methods=['PUT'])
def put_connected():
    # Retorna estado em cache imediatamente â€” nao bloqueia o NINA
    # Refresh disparado em background para manter o poll atualizado
    threading.Thread(target=ler_status, daemon=True).start()
    with _lock:
        val = _connected
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/shutterstatus', methods=['GET'])
def get_shutter_status():
    status_map = {'Open': 0, 'Closed': 1, 'Opening': 2, 'Closing': 3, 'Error': 4, 'Unknown': 4}
    with _lock:
        s = _shutter
    return jsonify({'Value': status_map.get(s, 4), 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/openshutter', methods=['PUT'])
def open_shutter():
    global _shutter
    ok, via = enviar_comando('open')
    if ok:
        print(f"[open] comando enviado via {via}")
        with _lock:
            _shutter = 'Opening'
        threading.Thread(target=lambda: (time.sleep(15), ler_status()), daemon=True).start()
        return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})
    return jsonify({'ErrorNumber': 1, 'ErrorMessage': via})

@app.route('/api/v1/dome/0/closeshutter', methods=['PUT'])
def close_shutter():
    global _shutter
    ok, via = enviar_comando('close')
    if ok:
        print(f"[close] comando enviado via {via}")
        with _lock:
            _shutter = 'Closing'
        threading.Thread(target=lambda: (time.sleep(15), ler_status()), daemon=True).start()
        return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})
    return jsonify({'ErrorNumber': 1, 'ErrorMessage': via})

@app.route('/api/v1/dome/0/cansyncazimuth', methods=['GET'])
def can_sync_azimuth():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/cansetazimuth', methods=['GET'])
def can_set_azimuth():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/cansetaltitude', methods=['GET'])
def can_set_altitude():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/canpark', methods=['GET'])
def can_park():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/cansetpark', methods=['GET'])
def can_set_park():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/canfindhome', methods=['GET'])
def can_find_home():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/altitude', methods=['GET'])
def get_altitude():
    return jsonify({'Value': 0.0, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/azimuth', methods=['GET'])
def get_azimuth():
    return jsonify({'Value': 0.0, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/ismoving', methods=['GET'])
def is_moving():
    with _lock:
        moving = _shutter in ('Opening', 'Closing')
    return jsonify({'Value': moving, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/name', methods=['GET'])
def get_name():
    return jsonify({'Value': 'Pier 1 Tuya Dome', 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/description', methods=['GET'])
def get_description():
    return jsonify({'Value': 'Driver Alpaca para cobertura MS-102 via tinytuya (cloud fallback)',
                    'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/driverinfo', methods=['GET'])
def get_driver_info():
    return jsonify({'Value': 'Pier 1 Tuya Dome Driver v1.1', 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/driverversion', methods=['GET'])
def get_driver_version():
    return jsonify({'Value': '1.1', 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/interfaceversion', methods=['GET'])
def get_interface_version():
    return jsonify({'Value': 2, 'ErrorNumber': 0, 'ErrorMessage': ''})

@app.route('/api/v1/dome/0/supportedactions', methods=['GET'])
def supported_actions():
    return jsonify({'Value': [], 'ErrorNumber': 0, 'ErrorMessage': ''})

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("Pier 1 Tuya Dome Driver â€” Alpaca v1.1")
    print("Rodando em http://localhost:11111")
    print("Conectando ao dispositivo...")
    ler_status()
    with _lock:
        modo = 'cloud' if _modo_cloud else 'local'
        s    = _shutter
    print(f"Status inicial: {s} ({modo})")
    threading.Thread(target=poll_status, daemon=True).start()
    threading.Thread(target=alpaca_discovery, daemon=True).start()
    app.run(host='0.0.0.0', port=11111, debug=False)