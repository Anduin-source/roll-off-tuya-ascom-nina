import ipv4_first  # IPv4 preferencial - ver ipv4_first.py
import requests_timeout  # timeout obrigatorio nas chamadas TinyTuya Cloud
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
# Tuya Dome Driver - Alpaca v2.0
#
# Arquitetura: este driver e o DONO UNICO da conexao TCP local com a
# cobertura (Novadigital MS-109). Nenhum outro processo deve abrir
# tinytuya.Device para este dispositivo enquanto o driver roda.
# Ver: ARQUITETURA_pier-controle_CONSOLIDADA_2026-06-10.md
#
# Mapeamento DPS (confirmado via API cloud em 2026-06-10):
#   DPS 1  switch_1          - ACIONAMENTO REAL: True=abrir, False=fechar (absoluto)
#   DPS 3  doorcontact_state - sensor fisico: False=fechada, True=aberta
#   DPS 4  door_time_1       - tempo de curso configurado no dispositivo (s)
#   DPS 6  door_control_1    - aceito mas IGNORADO por este firmware (nao usar p/ comando)
#   DPS 12 door_state_1      - alarme: 'none' = normal
# ===========================================================================

VERSAO_DRIVER = '2.2-cloud-robusto'

# ---------------------------------------------------------------------------
# Configuracao - lida de config.json (nao versionado)
# ---------------------------------------------------------------------------

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')


def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        print('ERRO: config.json nao encontrado.')
        print('Copie config_exemplo.json para config.json e preencha suas credenciais.')
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


cfg = carregar_config()

COB_ID     = cfg['cobertura']['id']
COB_IP     = cfg['cobertura']['ip']
COB_KEY    = cfg['cobertura']['key']
VERSION    = cfg['cobertura'].get('version', 3.4)  # por device; default 3.4 preserva instalacoes existentes
MODO_CONEXAO = str(cfg['cobertura'].get('modo_conexao', 'auto')).lower()
if MODO_CONEXAO not in ('auto', 'local', 'cloud'):
    raise ValueError('cobertura.modo_conexao deve ser auto, local ou cloud')
LOCAL_HABILITADO = MODO_CONEXAO in ('auto', 'local')
CLOUD_HABILITADA = MODO_CONEXAO in ('auto', 'cloud')

# ---------------------------------------------------------------------------
# Identidade Alpaca do device (fonte unica de verdade)
# DEVICE_NAME: nome generico fixo, igual em todas as instalacoes. A
#   diferenciacao entre piers se da pelo IP na descoberta do NINA, nao pelo nome.
# UNIQUE_ID: derivado do id Tuya da cobertura (COB_ID). O id Tuya e globalmente
#   unico por rele, estavel (independe de IP) e amarrado ao telhado fisico, entao
#   cada instalacao nasce com identidade unica automaticamente, sem passo manual.
# ---------------------------------------------------------------------------
DEVICE_NAME = 'Tuya Dome'
UNIQUE_ID   = f'tuya-dome-{COB_ID}'

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
_cloud_op_lock = threading.RLock() # uma unica chamada cloud por vez
_status_refresh_lock = threading.Lock()
_command_lock = threading.Lock()
_transition_lock = threading.Lock()
_backoff_lock = threading.Lock()

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
_falhas_status_consecutivas = 0
_transicao_ativa = False
_transicao_deadline = 0.0

STATUS_OBSOLETO_S = 120

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Conexao local: ABRE-FECHA EXPLICITO (uma conexao por operacao)
#
# Decisao baseada em teste empirico (teste_conexao.py, 2026-06-10):
# socket PERSISTENTE e ABRE-FECHA deram ambos 100% de sucesso em leituras
# densas, MAS no driver real o socket persistente ficava ocioso ~30s entre
# polls e o firmware do MS-109 derrubava a conexao por inatividade,
# gerando 904 a cada ~3min. Abre-fecha elimina a janela de ociosidade.
#
# A diferenca crucial para o padrao da v1.1 (que gerava sessao fantasma)
# nao e "abrir a cada vez" - e o FECHAMENTO EXPLICITO (d.close()) ao fim
# de cada uso. Socket fechado limpo nao vira fantasma; socket abandonado,
# sim. Custo: ~0.2s de handshake por operacao (irrelevante: NINA le do cache).
# Ver: ARQUITETURA_pier-controle_CONSOLIDADA e diagnostico_2026-06-09.
#
# Uso obrigatorio do padrao:
#     with _device_lock:
#         d = _abrir_device()
#         try:
#             ... usar d ...
#         finally:
#             _fechar_device(d)
# ---------------------------------------------------------------------------

def _abrir_device():
    """Cria uma conexao local nova. Chamar com _device_lock adquirido."""
    d = tinytuya.Device(dev_id=COB_ID, address=COB_IP,
                        local_key=COB_KEY, version=VERSION)
    d.set_socketPersistent(False)
    d.set_socketTimeout(3)
    return d


def _fechar_device(d):
    """Fecha explicitamente a conexao. Nunca lanca excecao."""
    if d is not None:
        try:
            d.close()
        except Exception:
            pass


def _device_atual():
    """No modo abre-fecha nao ha conexao mantida entre operacoes - cada
    operacao abre e fecha a sua. Retorna None; o shutdown so adquire o
    _device_lock para garantir que nenhuma operacao esta em curso."""
    return None

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
    if not LOCAL_HABILITADO:
        return False
    with _backoff_lock:
        return time.time() >= _proxima_tentativa_local


def _registrar_falha_local(erro):
    global _falhas_consecutivas, _proxima_tentativa_local
    global _local_failures_total, _ultimo_erro_local
    with _backoff_lock:
        _falhas_consecutivas += 1
        _local_failures_total += 1
        _ultimo_erro_local = str(erro)[:200]
        espera = min(30 * (2 ** min(_falhas_consecutivas - 1, 4)), 300)
        _proxima_tentativa_local = time.time() + espera
        numero = _falhas_consecutivas
    log.warning(f'Falha local #{numero}: {erro} '
                f'- backoff {espera}s antes da proxima tentativa local')


def _registrar_sucesso_local():
    global _falhas_consecutivas, _proxima_tentativa_local
    with _backoff_lock:
        anteriores = _falhas_consecutivas
        _falhas_consecutivas = 0
        _proxima_tentativa_local = 0.0
    if anteriores > 0:
        log.info('Caminho local recuperado - backoff zerado')

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
# Leitura de status (local abre-fecha -> fallback cloud)
# ---------------------------------------------------------------------------

def _aplicar_status(dps_aberta, door_time, alarm, via_cloud):
    """Atualiza o estado interno a partir de uma leitura bem-sucedida."""
    global _shutter, _connected, _modo_cloud, _door_time, _status_ts, _door_alarm
    global _falhas_status_consecutivas
    with _state_lock:
        estado_fisico = 'Open' if dps_aberta else 'Closed'
        # Transicao: so confirma a saida de Opening/Closing quando o sensor
        # fisico bate com o alvo da transicao. Isso evita que uma leitura no
        # meio do curso (telhado ainda movendo) zere o estado, mas PERMITE que
        # a confirmacao real do sensor encerre a transicao - resolve o
        # "preso em Closing" quando o curso e maior que o tempo estimado.
        if _shutter == 'Closing':
            if estado_fisico == 'Closed':
                _shutter = 'Closed'      # confirmou: fechou
            # senao mantem Closing (ainda em curso)
        elif _shutter == 'Opening':
            if estado_fisico == 'Open':
                _shutter = 'Open'        # confirmou: abriu
            # senao mantem Opening
        else:
            _shutter = estado_fisico     # estado estavel: segue o sensor
        _connected  = True
        _falhas_status_consecutivas = 0
        _modo_cloud = via_cloud
        _status_ts  = time.time()
        if door_time:
            _door_time = door_time
        if alarm is not None:
            _door_alarm = alarm


def _status_local():
    """Leitura local: abre, le, fecha explicitamente. Lanca excecao em falha."""
    with _device_lock:
        d = _abrir_device()
        try:
            s = d.status()
            if not isinstance(s, dict) or 'dps' not in s:
                raise RuntimeError(f'Resposta sem dps: {s}')
            dps = s['dps']
            return (bool(dps.get('3', False)),
                    int(dps.get('4', 0)) or None,
                    dps.get('12'))
        finally:
            _fechar_device(d)   # fecha SEMPRE, sucesso ou falha


def _status_cloud():
    """Leitura cloud com uma repeticao para falhas HTTP transitorias."""
    global _ultimo_erro_cloud
    if not CLOUD_HABILITADA:
        raise RuntimeError('Cloud desabilitada por configuracao')

    ultimo_erro = None
    for tentativa in (1, 2):
        try:
            with _cloud_op_lock:
                r = get_cloud().getstatus(COB_ID)
            if not isinstance(r, dict) or not r.get('success'):
                raise RuntimeError(f'Cloud sem sucesso: {r}')
            dps = {item['code']: item['value'] for item in r.get('result', [])}
            if 'doorcontact_state' not in dps:
                raise RuntimeError('Cloud sem doorcontact_state')
            return (bool(dps['doorcontact_state']),
                    int(dps.get('door_time_1', 0)) or None,
                    dps.get('door_state_1'))
        except Exception as e:
            ultimo_erro = e
            _ultimo_erro_cloud = str(e)[:200]
            if tentativa == 1:
                log.warning(f'Leitura cloud falhou; repetindo em 1s: {e}')
                time.sleep(1)
    raise ultimo_erro


def ler_status():
    """Atualiza o cache de status. Local primeiro (se liberado pelo
    backoff), cloud como fallback. Preserva o ultimo estado em falhas
    transitorias e retorna True somente quando houve leitura valida."""
    global _cloud_fallback_total, _falhas_status_consecutivas
    global _connected

    with _status_refresh_lock:
        if _local_liberado():
            try:
                aberta, dt, alarm = _status_local()
                _registrar_sucesso_local()
                _aplicar_status(aberta, dt, alarm, via_cloud=False)
                return True
            except Exception as e:
                _registrar_falha_local(e)

        if CLOUD_HABILITADA:
            try:
                aberta, dt, alarm = _status_cloud()
                _cloud_fallback_total += 1
                _aplicar_status(aberta, dt, alarm, via_cloud=True)
                return True
            except Exception as e:
                log.error(f'Status falhou. Cloud: {e}')

        with _state_lock:
            _falhas_status_consecutivas += 1
            _connected = False
        return False

# ---------------------------------------------------------------------------
# Envio de comandos
#
# IMPORTANTE: este firmware (Novadigital MS-109) NAO aciona o motor pelo
# door_control_1 (DPS 6) - o dispositivo aceita o comando e o ignora.
# O acionamento real e pelo switch_1 (DPS 1), confirmado empiricamente
# (2026-06-10, via camera): set_value(1, True)=abrir, False=fechar.
# E COMANDO ABSOLUTO, nao toggle: 'close' num telhado ja fechado nao o abre.
# door_control_1 segue disponivel para LEITURA de estado, mas nunca para comando.
# ---------------------------------------------------------------------------

# Mapeia comando textual -> valor booleano do switch_1 (DPS 1).
# Lanca ValueError para qualquer string diferente de 'open'/'close' —
# evita que erro de digitacao vire fechamento silencioso.
def _comando_para_dps1(comando):
    if comando == 'open':
        return True
    if comando == 'close':
        return False
    raise ValueError(f'Comando invalido para DPS1: {repr(comando)}')

def _comando_local(comando):
    """Comando local via switch_1 (DPS 1). comando: 'open'/'close'.
    Abre, envia, fecha explicitamente. Lanca excecao em falha."""
    valor = _comando_para_dps1(comando)
    with _device_lock:
        d = _abrir_device()
        try:
            result = d.set_value(1, valor)
            if isinstance(result, dict) and 'Err' in result:
                raise RuntimeError(f"Err {result['Err']}")
            return True
        finally:
            _fechar_device(d)   # fecha SEMPRE, sucesso ou falha


def _comando_cloud(comando):
    """Envia comando via API cloud usando switch_1 (DPS 1).
    Lanca excecao em falha."""
    global _ultimo_erro_cloud
    valor = _comando_para_dps1(comando)
    try:
        if not CLOUD_HABILITADA:
            raise RuntimeError('Cloud desabilitada por configuracao')
        # TinyTuya repassa o corpo recebido diretamente para a API Tuya.
        # A API exige o envelope {"commands": [...]}; uma lista isolada faz
        # as leituras cloud funcionarem, mas o comando ser rejeitado.
        with _cloud_op_lock:
            r = get_cloud().sendcommand(COB_ID, {
                'commands': [{'code': 'switch_1', 'value': valor}]
            })
        if not r.get('success'):
            raise RuntimeError(f'Cloud sem sucesso: {r}')
        return True
    except Exception as e:
        _ultimo_erro_cloud = str(e)[:200]
        raise


def _comando_redundante(comando):
    """Retorna True se o estado em cache ja e o desejado.
    Usado para evitar envio de comando desnecessario e reduzir risco
    operacional — principalmente para 'close' em automacoes de seguranca."""
    with _state_lock:
        return (
            (comando == 'close' and _shutter in ('Closed', 'Closing')) or
            (comando == 'open'  and _shutter in ('Open', 'Opening'))
        )


def enviar_comando(comando, origem='nina'):
    """Envia 'open' ou 'close'. Local (se liberado) -> cloud.
    Retorna (ok, via). Loga tudo."""
    global _comandos_total, _cloud_fallback_total, _shutter
    with _command_lock:
        _comandos_total += 1
        t0 = time.time()

        if _comando_redundante(comando):
            with _state_lock:
                atual = _shutter
            log.info(f'COMANDO {comando} origem={origem} ignorado: '
                     f'estado atual={atual}')
            return True, 'cache'

        via = None
        erro_final = None

        if _local_liberado():
            try:
                _comando_local(comando)
                _registrar_sucesso_local()
                via = 'local'
            except Exception as e:
                erro_final = e
                _registrar_falha_local(e)

        if via is None and CLOUD_HABILITADA:
            try:
                _comando_cloud(comando)
                _cloud_fallback_total += 1
                via = 'cloud'
            except Exception as e:
                erro_final = e

        if via is None:
            log.error(f'COMANDO {comando} origem={origem} FALHOU: {erro_final}')
            return False, str(erro_final)

        with _state_lock:
            _shutter = 'Opening' if comando == 'open' else 'Closing'
        log.info(f'COMANDO {comando} origem={origem} via={via} '
                 f'latencia={time.time()-t0:.1f}s')
        return True, via


def _tempo_curso():
    """Tempo de espera apos comando: door_time_1 do dispositivo + margem."""
    with _state_lock:
        # Margem sobre o door_time configurado. Curso real medido ~15s;
        # piso de 20s da folga para variacao (frio, atrito) sem encurtar.
        # O polling de confirmacao (_confirmar_transicao) tolera variacao.
        return max(_door_time, 20) + 3


def _agendar_refresh():
    _confirmar_transicao()


def _confirmar_transicao():
    """Mantem somente um monitor de movimento, com consultas cloud moderadas."""
    global _transicao_ativa, _transicao_deadline
    timeout_s = max(60, _tempo_curso() + 30)
    with _transition_lock:
        _transicao_deadline = time.time() + timeout_s
        if _transicao_ativa:
            return
        _transicao_ativa = True

    def _job():
        global _transicao_ativa, _shutter, _connected
        try:
            while True:
                with _transition_lock:
                    limite = _transicao_deadline
                if time.time() >= limite:
                    break
                ler_status()
                with _state_lock:
                    transitorio = _shutter in ('Opening', 'Closing')
                if not transitorio:
                    return
                time.sleep(5)

            with _state_lock:
                s = _shutter
                if s in ('Opening', 'Closing'):
                    _shutter = 'Error'
                    _connected = False
            log.warning(f'Transicao nao confirmada em {timeout_s}s '
                        f'(estado={s}). Verificar status cloud e sensor.')
        finally:
            with _transition_lock:
                _transicao_ativa = False

    threading.Thread(target=_job, daemon=True).start()

# ---------------------------------------------------------------------------
# Fechamento de emergencia - envia, aguarda e verifica
#
# Diferenca para closeshutter: envia, ESPERA o curso, le o sensor fisico,
# e repete pelo outro caminho se nao confirmar. Nao garante fechamento em
# caso de falha mecanica, eletrica ou de rede - e a melhor tentativa
# possivel por software. Ponto de integracao futuro do nobreak.
# ---------------------------------------------------------------------------

def _verificar_fechada():
    """Le o sensor fisico pelos dois caminhos. Retorna True se confirmada
    fechada, False se aberta, None se ilegivel."""
    if LOCAL_HABILITADO:
        try:
            aberta, _, _ = _status_local()
            _registrar_sucesso_local()
            return not aberta
        except Exception:
            pass
    if CLOUD_HABILITADA:
        try:
            aberta, _, _ = _status_cloud()
            return not aberta
        except Exception:
            pass
    return None


def executar_emergency_close():
    """Sequencia: local -> verifica -> cloud -> verifica.
    Emergencia ignora o backoff (tenta local mesmo em janela de espera).
    Retorna dict com o resultado detalhado."""
    log.warning('EMERGENCY CLOSE iniciado')
    tentativas = []
    curso = _tempo_curso()

    caminhos = []
    if LOCAL_HABILITADO:
        caminhos.append(('local', _comando_local))
    if CLOUD_HABILITADA:
        caminhos.append(('cloud', _comando_cloud))

    for caminho, enviar in caminhos:
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
# Poll de status - 30s entre leituras (intervalo que motivou o abre-fecha)
# ---------------------------------------------------------------------------

def poll_status():
    while True:
        try:
            ok = ler_status()
            with _state_lock:
                modo = 'cloud' if _modo_cloud else 'local'
                s = _shutter
            log.info(f'[poll] status={s} modo={modo} leitura={"ok" if ok else "falhou"}')
        except Exception:
            log.exception('Erro inesperado no poll; a thread continuara ativa')
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

def _estado_publico():
    """Retorna estado confiavel; status antigo nunca e anunciado como atual."""
    with _state_lock:
        idade = time.time() - _status_ts if _status_ts else None
        obsoleto = idade is None or idade > STATUS_OBSOLETO_S
        shutter = 'Error' if obsoleto else _shutter
        connected = bool(_connected and not obsoleto)
        return shutter, connected, idade, obsoleto


@app.route('/health', methods=['GET'])
def health():
    shutter_publico, connected_publico, idade_bruta, obsoleto = _estado_publico()
    with _state_lock, _backoff_lock:
        idade = round(idade_bruta, 1) if idade_bruta is not None else None
        return jsonify({
            'driver_version': VERSAO_DRIVER,
            'uptime_s': round(time.time() - _inicio_driver),
            'connected': connected_publico,
            'shutter': shutter_publico,
            'shutter_interno': _shutter,
            'modo': 'cloud' if _modo_cloud else 'local',
            'modo_conexao_configurado': MODO_CONEXAO,
            'door_time_s': _door_time,
            'door_alarm': _door_alarm,
            'status_idade_s': idade,
            'status_obsoleto': obsoleto,
            'falhas_status_consecutivas': _falhas_status_consecutivas,
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
    shutter_publico, _, idade_bruta, obsoleto = _estado_publico()
    with _state_lock:
        mapa = {'Open': 'aberta', 'Closed': 'fechada', 'Opening': 'abrindo',
                'Closing': 'fechando', 'Error': 'erro', 'Unknown': 'desconhecido'}
        idade = round(idade_bruta, 1) if idade_bruta is not None else None
        return jsonify({
            'estado': mapa.get(shutter_publico, 'desconhecido'),
            'modo': 'cloud' if _modo_cloud else 'local',
            'idade_s': idade,
            'obsoleto': obsoleto,
        })


@app.route('/abrir', methods=['POST'])
def abrir_simples():
    """Abertura para a GUI."""
    ok, via = enviar_comando('open', origem='gui')
    if ok:
        if via != 'cache':
            _agendar_refresh()
        return jsonify({'ok': True, 'via': via})
    return jsonify({'ok': False, 'erro': via}), 500


@app.route('/fechar', methods=['POST'])
def fechar_simples():
    """Fechamento para a GUI."""
    ok, via = enviar_comando('close', origem='gui')
    if ok:
        if via != 'cache':
            _agendar_refresh()
        return jsonify({'ok': True, 'via': via})
    return jsonify({'ok': False, 'erro': via}), 500


@app.route('/emergency_close', methods=['POST'])
def emergency_close():
    """Fechamento de emergencia com verificacao."""
    resultado = executar_emergency_close()
    codigo = 200 if resultado['ok'] else 500
    return jsonify(resultado), codigo


@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Encerramento gracioso: fecha a conexao local com o MS-109 antes de
    sair, evitando socket pendurado no firmware. Chamado pela GUI ao fechar.
    NAO move o telhado - apenas encerra o processo do driver."""
    log.info('Shutdown solicitado - encerrando driver graciosamente')
    with _device_lock:
        _fechar_device(_device_atual())

    def _encerrar():
        time.sleep(0.3)  # da tempo da resposta HTTP voltar ao cliente (GUI)
        # os._exit(0) e INTENCIONAL: encerra o processo imediatamente sem
        # rodar finalizadores nem esperar as threads do Flask/poll/discovery
        # (todas daemon). sys.exit() nao serve aqui porque so encerra a thread
        # atual, deixando o servidor Flask e o poll vivos. O socket local ja
        # foi fechado acima (_fechar_device), entao nao ha recurso pendente.
        os._exit(0)

    threading.Thread(target=_encerrar, daemon=True).start()
    return jsonify({'ok': True, 'message': 'driver encerrando'})

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
            'ServerName': DEVICE_NAME,
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
        'DeviceName': DEVICE_NAME,
        'DeviceType': 'Dome',
        'DeviceNumber': 0,
        'UniqueID': UNIQUE_ID
    }]})

# ---------------------------------------------------------------------------
# Dome endpoints (Alpaca - contrato com o NINA, inalterado)
# ---------------------------------------------------------------------------

@app.route('/api/v1/dome/0/connected', methods=['GET'])
def get_connected():
    _, val, _, _ = _estado_publico()
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/connected', methods=['PUT'])
def put_connected():
    # Retorna estado em cache imediatamente - nao bloqueia o NINA.
    # Refresh disparado em background.
    threading.Thread(target=ler_status, daemon=True).start()
    _, val, _, _ = _estado_publico()
    return jsonify({'Value': val, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/shutterstatus', methods=['GET'])
def get_shutter_status():
    status_map = {'Open': 0, 'Closed': 1, 'Opening': 2, 'Closing': 3,
                  'Error': 4, 'Unknown': 4}
    s, _, _, _ = _estado_publico()
    return jsonify({'Value': status_map.get(s, 4),
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/openshutter', methods=['PUT'])
def open_shutter():
    ok, via = enviar_comando('open', origem='nina')
    if ok:
        if via != 'cache':
            _agendar_refresh()
        return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})
    return jsonify({'ErrorNumber': 1, 'ErrorMessage': via})


@app.route('/api/v1/dome/0/closeshutter', methods=['PUT'])
def close_shutter():
    ok, via = enviar_comando('close', origem='nina')
    if ok:
        if via != 'cache':
            _agendar_refresh()
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


@app.route('/api/v1/dome/0/cansetshutter', methods=['GET'])
def can_set_shutter():
    # True - o driver controla abrir/fechar a cobertura.
    # Sem isto, o NINA desabilita os botoes de Shutter no Manual Control
    # e nao consegue fechar automaticamente por seguranca.
    return jsonify({'Value': True, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/slaved', methods=['GET'])
def get_slaved():
    # Roll-off nao segue o telescopio (nao gira) - sempre False.
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/slaved', methods=['PUT'])
def put_slaved():
    # Aceita o comando sem erro, mas nao faz nada (nao ha azimute a seguir).
    return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/canslave', methods=['GET'])
def can_slave():
    # Roll-off nao acompanha o telescopio em azimute.
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/slewing', methods=['GET'])
def slewing():
    # 'Slewing' no contexto ASCOM Dome inclui o shutter em movimento.
    with _state_lock:
        movendo = _shutter in ('Opening', 'Closing')
    return jsonify({'Value': movendo, 'ErrorNumber': 0, 'ErrorMessage': ''})


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


# --- Endpoints de movimento/park (roll-off nao gira nem estaciona) ---
# Implementados para evitar 404 nos fluxos de coordenacao do NINA.
# Operacoes nao suportadas retornam ErrorNumber 1024 (NotImplemented ASCOM),
# nao um 404 HTTP, para o NINA tratar como capacidade ausente, nao como falha.

ASCOM_NOT_IMPLEMENTED = 1024


@app.route('/api/v1/dome/0/abortslew', methods=['PUT'])
def abort_slew():
    return jsonify({'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/park', methods=['PUT'])
def park():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao estaciona em azimute'})


@app.route('/api/v1/dome/0/setpark', methods=['PUT'])
def set_park():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao tem posicao de park'})


@app.route('/api/v1/dome/0/findhome', methods=['PUT'])
def find_home_cmd():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao tem home'})


@app.route('/api/v1/dome/0/slewtoazimuth', methods=['PUT'])
def slew_to_azimuth():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao gira'})


@app.route('/api/v1/dome/0/slewtoaltitude', methods=['PUT'])
def slew_to_altitude():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao controla altitude'})


@app.route('/api/v1/dome/0/synctoazimuth', methods=['PUT'])
def sync_to_azimuth():
    return jsonify({'ErrorNumber': ASCOM_NOT_IMPLEMENTED,
                    'ErrorMessage': 'Roll-off nao gira'})


@app.route('/api/v1/dome/0/atpark', methods=['GET'])
def at_park():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/athome', methods=['GET'])
def at_home():
    return jsonify({'Value': False, 'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/name', methods=['GET'])
def get_name():
    return jsonify({'Value': DEVICE_NAME,
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/description', methods=['GET'])
def get_description():
    return jsonify({'Value': 'Driver Alpaca para cobertura Novadigital MS-109 '
                             'via tinytuya (local abre-fecha + cloud fallback)',
                    'ErrorNumber': 0, 'ErrorMessage': ''})


@app.route('/api/v1/dome/0/driverinfo', methods=['GET'])
def get_driver_info():
    return jsonify({'Value': f'{DEVICE_NAME} Driver v{VERSAO_DRIVER}',
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
    log.info(f'{DEVICE_NAME} Driver - Alpaca v{VERSAO_DRIVER}')
    log.info('Rodando em http://localhost:11111')
    log.info(f'Modo de conexao configurado: {MODO_CONEXAO}')
    # O primeiro status roda em background para que /health fique disponivel
    # imediatamente, mesmo se a cloud estiver lenta ou indisponivel.
    threading.Thread(target=poll_status, daemon=True).start()
    threading.Thread(target=alpaca_discovery, daemon=True).start()
    app.run(host='0.0.0.0', port=11111, debug=False, threaded=True)
