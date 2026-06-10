import ipv4_first  # IPv4 preferencial - ver ipv4_first.py
import threading
import time
import socket
import json
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify
import tinytuya

# ===========================================================================
# Pier 1 Tuya Dome Driver - Alpaca v2.0
#
# Arquitetura: este driver e o DONO UNICO da conexao TCP local com a
# cobertura (Novadigital MS-109). Nenhum outro processo deve abrir
# tinytuya.Device para este dispositivo enquanto o driver roda.
# Ver: ARQUITETURA_pier-controle_CONSOLIDADA_2026-06-10.md
#
# Mapeamento DPS (confirmado via API cloud em 2026-06-10):
#   DPS 1  switch_1          - pulso bruto (NAO USAR - nao idempotente)
#   DPS 3  doorcontact_state - sensor fisico: False=fechada, True=aberta
#   DPS 4  door_time_1       - tempo de curso configurado no dispositivo (s)
#   DPS 6  door_control_1    - comando explicito: 'open' / 'close'
#   DPS 12 door_state_1      - alarme: 'none' = normal
# ===========================================================================

VERSAO_DRIVER = '2.0'

# ---------------------------------------------------------------------------
# Configuracao - lida de config.json (nao versionado)
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')


def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        print('ERRO: config.json nao encontrado.')
        print('Copie config_exemplo.json para config.json e preencha suas credenciais.')
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
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
# Logging - arquivo rotativo + console
# ---------------------------------------------------------------------------

log = logging.getLogger('dome_driver')
log.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s',
                         datefmt='%Y-%m-%d %H:%M:%S')

_fh = RotatingFileHandler(os.path.join(BASE_DIR, 'dome_driver.log'),
                          maxBytes=1_000_000, backupCount=3, encoding='utf-8')
_fh.setFormatter(_fmt)
log.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
log.addHandler(_ch)

# ---------------------------------------------------------------------------
# Estado interno e locks separados
# ---------------------------------------------------------------------------

_state_lock  = threading.Lock()    # protege o estado abaixo
_device_lock = threading.RLock()   # serializa operacoes locais no MS-109
_cloud_lock  = threading.Lock()    # protege criacao do objeto cloud

_connected   = False
_shutter     = 'Unknown'           # Open/Closed/Opening/Closing/Error/Unknown
_modo_cloud  = False               # True = ultimo status veio da cloud
_door_time   = 10                  # tempo de curso (DPS 4), atualizado pelo poll
_status_ts   = 0.0                 # timestamp da ultima leitura bem-sucedida
_door_alarm  = 'none'              # DPS 12

# Contadores para /health (campos simples em memoria - sem subsistema)
_inicio_driver        = time.time()
_local_failures_total = 0
_cloud_fallback_total = 0
_comandos_total       = 0
_ultimo_erro_local    = ''
_ultimo_erro_cloud    = ''

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Conexao local persistente - o coracao da v2.0
#
# UMA instancia de tinytuya.Device, criada uma vez e reutilizada.
# socketPersistent mantem o socket aberto; o poll de 30s funciona como
# heartbeat natural. Em caso de erro a conexao e FECHADA explicitamente
# antes de recriar - nunca abandonada (padrao antigo gerava sessao
# fantasma no firmware, ver diagnostico_2026-06-09).
# ---------------------------------------------------------------------------

_device = None


def _get_device():
    """Retorna a instancia persistente, criando se necessario.
    Chamar somente com _device_lock adquirido."""
    global _device
    if _device is None:
        d = tinytuya.Device(dev_id=COB_ID, address=COB_IP,
                            local_key=COB_KEY, version=VERSION)
        d.set_socketPersistent(True)
        d.set_socketTimeout(3)
        _device = d
        log.info('Conexao local criada (persistente)')
    return _device


def _fechar_device():
    """Fecha explicitamente a conexao local.
    Chamar somente com _device_lock adquirido."""
    global _device
    if _device is not None:
        try:
            _device.close()
            log.info('Conexao local fechada explicitamente')
        except Exception:
            pass
        _device = None

# ---------------------------------------------------------------------------
# Backoff apos falha local
#
# Martelar um dispositivo com problema piora a situacao (e suspeito de
# contribuir para o travamento de firmware). Apos cada falha local
# consecutiva, espera progressivamente mais antes de tentar local de novo:
# 30s, 60s, 120s, 240s, teto de 300s. Enquanto isso, opera via cloud.
# Sucesso local zera o backoff.
# ---------------------------------------------------------------------------

_falhas_consecutivas = 0
_proxima_tentativa_local = 0.0


def _local_liberado():
    return time.time() >= _proxima_tentativa_local


def _registrar_falha_local(erro):
    global _falhas_consecutivas, _proxima_tentativa_local
    global _local_failures_total, _ultimo_erro_local
    _falhas_consecutivas += 1
    _local_failures_total += 1
    _ultimo_erro_local = str(erro)[:200]
    espera = min(30 * (2 ** min(_falhas_consecutivas - 1, 3)), 300)
    _proxima_tentativa_local = time.time() + espera
    log.warning(f'Falha local #{_falhas_consecutivas}: {erro} '
                f'- backoff {espera}s antes da proxima tentativa local')


def _registrar_sucesso_local():
    global _falhas_consecutivas, _proxima_tentativa_local
    if _falhas_consecutivas > 0:
        log.info('Caminho local recuperado - backoff zerado')
    _falhas_consecutivas = 0
    _proxima_tentativa_local = 0.0

# ---------------------------------------------------------------------------
# Cloud singleton
# ---------------------------------------------------------------------------

_cloud = None


def get_cloud():
    global _cloud
    with _cloud_lock:
        if _cloud is None:
            _cloud = tinytuya.Cloud(apiRegion=API_REGION,
                                    apiKey=API_KEY,
                                    apiSecret=API_SECRET)
    return _cloud

# ---------------------------------------------------------------------------
# Leitura de status (local persistente -> fallback cloud)
# ---------------------------------------------------------------------------

def _aplicar_status(dps_aberta, door_time, alarm, via_cloud):
    """Atualiza o estado interno a partir de uma leitura bem-sucedida."""
    global _shutter, _connected, _modo_cloud, _door_time, _status_ts, _door_alarm
    with _state_lock:
        # Nao sobrescreve estados transitorios (Opening/Closing) com leitura
        # antiga - eles expiram pelo refresh agendado apos o comando
        if _shutter not in ('Opening', 'Closing'):
            _shutter = 'Open' if dps_aberta else 'Closed'
        _connected  = True
        _modo_cloud = via_cloud
        _status_ts  = time.time()
        if door_time:
            _door_time = door_time
        if alarm is not None:
            _door_alarm = alarm


def _status_local():
    """Leitura via conexao persistente. Lanca excecao em falha."""
    with _device_lock:
        try:
            d = _get_device()
            s = d.status()
            if not isinstance(s, dict) or 'dps' not in s:
                raise RuntimeError(f'Resposta sem dps: {s}')
            dps = s['dps']
            return (bool(dps.get('3', False)),
                    int(dps.get('4', 0)) or None,
                    dps.get('12'))
        except Exception:
            _fechar_device()   # fecha explicitamente antes de propagar
            raise


def _status_cloud():
    """Leitura via API cloud. Lanca excecao em falha."""
    global _ultimo_erro_cloud
    try:
        r = get_cloud().getstatus(COB_ID)
        if not r.get('success'):
            raise RuntimeError(f'Cloud sem sucesso: {r}')
        dps = {item['code']: item['value'] for item in r.get('result', [])}
        if 'doorcontact_state' not in dps:
            raise RuntimeError('Cloud sem doorcontact_state')
        return (bool(dps['doorcontact_state']),
                int(dps.get('door_time_1', 0)) or None,
                dps.get('door_state_1'))
    except Exception as e:
        _ultimo_erro_cloud = str(e)[:200]
        raise


def ler_status():
    """Atualiza o cache de status. Local primeiro (se liberado pelo
    backoff), cloud como fallback. Marca erro se ambos falharem."""
    global _cloud_fallback_total

    if _local_liberado():
        try:
            aberta, dt, alarm = _status_local()
            _registrar_sucesso_local()
            _aplicar_status(aberta, dt, alarm, via_cloud=False)
            return
        except Exception as e:
            _registrar_falha_local(e)

    try:
        aberta, dt, alarm = _status_cloud()
        _cloud_fallback_total += 1
        _aplicar_status(aberta, dt, alarm, via_cloud=True)
        return
    except Exception as e:
        log.error(f'Status falhou em ambos os caminhos. Cloud: {e}')

    with _state_lock:
        global _shutter, _connected
        _shutter   = 'Error'
        _connected = False

# ---------------------------------------------------------------------------
# Envio de comandos (door_control_1 / DPS 6 - explicito, nunca DPS 1)
# ---------------------------------------------------------------------------

def _comando_local(comando):
    """Envia comando via conexao persistente. Lanca excecao em falha."""
    with _device_lock:
        try:
            d = _get_device()
            result = d.set_value(6, comando)
            if isinstance(result, dict) and 'Err' in result:
                raise RuntimeError(f"Err {result['Err']}")
            return True
        except Exception:
            _fechar_device()
            raise


def _comando_cloud(comando):
    """Envia comando via API cloud. Lanca excecao em falha."""
    global _ultimo_erro_cloud
    try:
        r = get_cloud().sendcommand(
            COB_ID, [{'code': 'door_control_1', 'value': comando}])
        if not r.get('success'):
            raise RuntimeError(f'Cloud sem sucesso: {r}')
        return True
    except Exception as e:
        _ultimo_erro_cloud = str(e)[:200]
        raise


def enviar_comando(comando, origem='nina'):
    """Envia 'open' ou 'close'. Local (se liberado) -> cloud.
    Retorna (ok, via). Loga tudo."""
    global _comandos_total, _cloud_fallback_total
    _comandos_total += 1
    t0 = time.time()

    if _local_liberado():
        try:
            _comando_local(comando)
            _registrar_sucesso_local()
            log.info(f'COMANDO {comando} origem={origem} via=local '
                     f'latencia={time.time()-t0:.1f}s')
            return True, 'local'
        except Exception as e:
            _registrar_falha_local(e)

    try:
        _comando_cloud(comando)
        _cloud_fallback_total += 1
        log.info(f'COMANDO {comando} origem={origem} via=cloud '
                 f'latencia={time.time()-t0:.1f}s')
        return True, 'cloud'
    except Exception as e:
        log.error(f'COMANDO {comando} origem={origem} FALHOU em ambos '
                  f'os caminhos: {e}')
        return False, str(e)


def _tempo_curso():
    """Tempo de espera apos comando: door_time_1 do dispositivo + margem."""
    with _state_lock:
        return _door_time + 3


def _agendar_refresh(segundos):
    """Refresh de status apos o tempo de curso, em background."""
    def _job():
        time.sleep(segundos)
        ler_status()
    threading.Thread(target=_job, daemon=True).start()

# ---------------------------------------------------------------------------
# Fechamento de emergencia - GARANTE, nao tenta
#
# Diferenca para closeshutter: envia, ESPERA o curso, VERIFICA o sensor
# fisico, e repete pelo outro caminho se nao confirmar. Ponto de
# integracao futuro do nobreak do telhado.
# ---------------------------------------------------------------------------

def _verificar_fechada():
    """Le o sensor fisico pelos dois caminhos. Retorna True se confirmada
    fechada, False se aberta, None se ilegivel."""
    try:
        aberta, _, _ = _status_local()
        _registrar_sucesso_local()
        return not aberta
    except Exception:
        pass
    try:
        aberta, _, _ = _status_cloud()
        return not aberta
    except Exception:
        return None


def executar_emergency_close():
    """Sequencia: local -> verifica -> cloud -> verifica.
    Emergencia ignora o backoff (tenta local mesmo em janela de espera).
    Retorna dict com o resultado detalhado."""
    log.warning('EMERGENCY CLOSE iniciado')
    tentativas = []
    curso = _tempo_curso()

    for caminho, enviar in (('local', _comando_local), ('cloud', _comando_cloud)):
        try:
            enviar('close')
            log.info(f'emergency_close: comando enviado via {caminho}, '
                     f'aguardando {curso}s de curso')
            time.sleep(curso)
            fechada = _verificar_fechada()
            tentativas.append({'caminho': caminho, 'enviado': True,
                               'confirmada_fechada': fechada})
            if fechada is True:
                log.warning(f'EMERGENCY CLOSE confirmado via {caminho}')
                with _state_lock:
                    global _shutter
                    _shutter = 'Closed'
                return {'ok': True, 'confirmada': True, 'tentativas': tentativas}
        except Exception as e:
            tentativas.append({'caminho': caminho, 'enviado': False,
                               'erro': str(e)[:200]})
            log.error(f'emergency_close: caminho {caminho} falhou: {e}')

    log.critical('EMERGENCY CLOSE NAO CONFIRMADO - intervencao necessaria! '
                 f'Detalhes: {tentativas}')
    return {'ok': False, 'confirmada': False, 'tentativas': tentativas}

# ---------------------------------------------------------------------------
# Poll de status - tambem funciona como heartbeat da conexao persistente
# ---------------------------------------------------------------------------

def poll_status():
    while True:
        ler_status()
        with _state_lock:
            modo = 'cloud' if _modo_cloud else 'local'
            s = _shutter
        log.info(f'[poll] status={s} modo={modo}')
        time.sleep(30)

# ---------------------------------------------------------------------------
# Alpaca discovery (UDP)
# ---------------------------------------------------------------------------

def alpaca_discovery():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 32227))
    log.info('Alpaca Discovery rodando na porta 32227')
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if b'alpacadiscovery' in data.lower():
                response = json.dumps({'AlpacaPort': 11111}).encode()
                sock.sendto(response, addr)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Endpoints novos (driver v2.0) - consumidos pela GUI e por scripts
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    with _state_lock:
        idade = round(time.time() - _status_ts, 1) if _status_ts else None
        return jsonify({
            'driver_version': VERSAO_DRIVER,
            'uptime_s': round(time.time() - _inicio_driver),
            'connected': _connected,
            'shutter': _shutter,
            'modo': 'cloud' if _modo_cloud else 'local',
            'door_time_s': _door_time,
            'door_alarm': _door_alarm,
            'status_idade_s': idade,
            'local_failures_total': _local_failures_total,
            'cloud_fallbacks_total': _cloud_fallback_total,
            'comandos_total': _comandos_total,
            'falhas_locais_consecutivas': _falhas_consecutivas,
            'backoff_ate': (_proxima_tentativa_local
                            if _proxima_tentativa_local > time.time() else 0),
            'ultimo_erro_local': _ultimo_erro_local,
            'ultimo_erro_cloud': _ultimo_erro_cloud,
        })


@app.route('/status', methods=['GET'])
def status_simples():
    """Status simplificado para a GUI - sem interpretar codigos Alpaca."""
    with _state_lock:
        mapa = {'Open': 'aberta', 'Closed': 'fechada', 'Opening': 'abrindo',
                'Closing': 'fechando', 'Error': 'erro', 'Unknown': 'desconhecido'}
        idade = round(time.time() - _status_ts, 1) if _status_ts else None
        return jsonify({
            'estado': mapa.get(_shutter, 'desconhecido'),
            'modo': 'cloud' if _modo_cloud else 'local',
            'idade_s': idade,
        })


@app.route('/abrir', methods=['POST'])
def abrir_simples():
    """Abertura para a GUI."""
    ok, via = enviar_comando('open', origem='gui')
    if ok:
        with _state_lock:
            global _shutter
            _shutter = 'Opening'
        _agendar_refresh(_tempo_curso())
        return jsonify({'ok': True, 'via': via})
    return jsonify({'ok': False, 'erro': via}), 500


@app.route('/fechar', methods=['POST'])
def fechar_simples():
    """Fechamento para a GUI."""
    ok, via = enviar_comando('close', origem='gui')
    if ok:
        with _state_lock:
            global _shutter
            _shutter = 'Closing'
        _agendar_refresh(_tempo_curso())
        return jsonify({'ok': True, 'via': via})
    return jsonify({'ok': False, 'erro': via}), 500


@app.route('/emergency_close', methods=['POST'])
def emergency_close():
    """Fechamento garantido com verificacao. Bloqueia ate confirmar
    (ou esgotar os caminhos). Integracao futura: nobreak."""
    resultado = executar_emergency_close()
    codigo = 200 if resultado['ok'] else 500
    return jsonify(resultado), codigo

# ---------------------------------------------------------------------------
# Management endpoints (Alpaca - contrato com o NINA, inalterado)
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
            'ManufacturerVersion': VERSAO_DRIVER,
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
# Dome endpoints (Alpaca - contrato com o NINA, inalterado)
# ---------------------------------------------------------------------------

@app.route('/api/v1/dome/0/connected', methods=['GET'])
def get_connected():
    with _state_lock:
        val = _connected
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/connected', methods=['PUT'])
def put_connected():
    # Retorna estado em cache imediatamente - nao bloqueia o NINA.
    # Refresh disparado em background.
    threading.Thread(target=ler_status, daemon=True).start()
    with _state_lock:
        val = _connected
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/shutterstatus', methods=['GET'])
def get_shutter_status():
    status_map = {'Open': 0, 'Closed': 1, 'Opening': 2, 'Closing': 3,
                  'Error': 4, 'Unknown': 4}
    with _state_lock:
        s = _shutter
    return jsonify({'Value': status_map.get(s, 4),
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/openshutter', methods=['PUT'])
def open_shutter():
    ok, via = enviar_comando('open', origem='nina')
    if ok:
        with _state_lock:
            global _shutter
            _shutter = 'Opening'
        _agendar_refresh(_tempo_curso())
        return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})
    return jsonify({'ErrorNumber': 1, 'ErrorMessage': via})


@app.route('/api/v1/dome/0/closeshutter', methods=['PUT'])
def close_shutter():
    ok, via = enviar_comando('close', origem='nina')
    if ok:
        with _state_lock:
            global _shutter
            _shutter = 'Closing'
        _agendar_refresh(_tempo_curso())
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
    with _state_lock:
        moving = _shutter in ('Opening', 'Closing')
    return jsonify({'Value': moving, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/name', methods=['GET'])
def get_name():
    return jsonify({'Value': 'Pier 1 Tuya Dome',
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/description', methods=['GET'])
def get_description():
    return jsonify({'Value': 'Driver Alpaca para cobertura Novadigital MS-109 '
                             'via tinytuya (conexao persistente + cloud fallback)',
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/driverinfo', methods=['GET'])
def get_driver_info():
    return jsonify({'Value': f'Pier 1 Tuya Dome Driver v{VERSAO_DRIVER}',
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/driverversion', methods=['GET'])
def get_driver_version():
    return jsonify({'Value': VERSAO_DRIVER,
                    'ErrorNumber': 0, 'ErrorMessage': ''})


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
    log.info(f'Pier 1 Tuya Dome Driver - Alpaca v{VERSAO_DRIVER}')
    log.info('Rodando em http://localhost:11111')
    log.info('Conectando ao dispositivo...')
    ler_status()
    with _state_lock:
        modo = 'cloud' if _modo_cloud else 'local'
        s = _shutter
    log.info(f'Status inicial: {s} ({modo})')
    threading.Thread(target=poll_status, daemon=True).start()
    threading.Thread(target=alpaca_discovery, daemon=True).start()
    app.run(host='0.0.0.0', port=11111, debug=False, threaded=True)
