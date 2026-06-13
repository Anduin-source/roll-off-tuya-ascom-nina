from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template_string
import tinytuya
import json
import os
import sys

# Permite rodar este arquivo dentro de painel_local/ mantendo imports comuns
# na raiz do projeto em modo desenvolvimento.
if not getattr(sys, 'frozen', False):
    _PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_DIR not in sys.path:
        sys.path.insert(0, _PROJECT_DIR)

import ipv4_first  # IPv4 preferencial - ver ipv4_first.py

app = Flask(__name__)

# Quando compilado pelo PyInstaller (sys.frozen=True), os arquivos de dados
# (devices.json) ficam ao lado do .exe (sys.executable).
# Em modo Python puro, ficam ao lado do .py (__file__).
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_LOCAL_DEVICES_FILE = os.path.join(_BASE_DIR, 'devices.json')
_PROJECT_DEVICES_FILE = os.path.join(os.path.dirname(_BASE_DIR), 'devices.json')
DEVICES_FILE = (
    _LOCAL_DEVICES_FILE
    if os.path.exists(_LOCAL_DEVICES_FILE)
    else _PROJECT_DEVICES_FILE
)
VERSION_PADRAO = 3.4
MAX_WORKERS = 8

# ---------------------------------------------------------------------------
# Dispositivos
# ---------------------------------------------------------------------------

def carregar_devices_json():
    if not os.path.exists(DEVICES_FILE):
        raise FileNotFoundError('devices.json nao encontrado na pasta do projeto')
    with open(DEVICES_FILE, 'r', encoding='utf-8-sig') as f:
        dados = json.load(f)
    if isinstance(dados, dict):
        return dados.get('devices', [])
    return dados


def normalizar_device(d):
    return {
        'id': d.get('id') or d.get('dev_id'),
        'name': d.get('name') or d.get('nome') or d.get('id') or 'sem nome',
        'ip': d.get('ip') or d.get('address'),
        'key': d.get('key') or d.get('local_key'),
        'version': float(d.get('version') or VERSION_PADRAO),
        'category': d.get('category') or d.get('product_category') or '',
    }


def carregar_coberturas():
    """Retorna coberturas/garagens do devices.json do tinytuya."""
    devices = [normalizar_device(d) for d in carregar_devices_json()]
    coberturas = []
    for d in devices:
        if d['category'] != 'ckmkzq':
            continue
        if not d['id']:
            continue
        coberturas.append(d)
    return coberturas


def procurar_cobertura(device_id):
    return next((d for d in carregar_coberturas() if d['id'] == device_id), None)

# ---------------------------------------------------------------------------
# Tuya local
# ---------------------------------------------------------------------------

def abrir_device(device):
    if not device.get('ip') or not device.get('key'):
        raise RuntimeError('Dispositivo sem ip/local_key no devices.json')
    d = tinytuya.Device(
        dev_id=device['id'],
        address=device['ip'],
        local_key=device['key'],
        version=device.get('version') or VERSION_PADRAO
    )
    d.set_socketPersistent(False)
    d.set_socketTimeout(3)
    return d


def fechar_device(d):
    if d is not None:
        try:
            d.close()
        except Exception:
            pass


def status_local(device):
    d = abrir_device(device)
    try:
        resposta = d.status()
        if not isinstance(resposta, dict) or 'dps' not in resposta:
            raise RuntimeError(f'Resposta sem dps: {resposta}')
        dps = resposta['dps']
        if '3' not in dps:
            raise RuntimeError('DPS 3/doorcontact_state ausente')
        return 'aberta' if bool(dps.get('3')) else 'fechada'
    finally:
        fechar_device(d)


def comando_local(device, comando):
    if comando not in ('abrir', 'fechar'):
        raise ValueError(f'Comando invalido: {comando!r}')
    valor = True if comando == 'abrir' else False
    d = abrir_device(device)
    try:
        resposta = d.set_value(1, valor)
        if isinstance(resposta, dict) and 'Err' in resposta:
            raise RuntimeError(f"Err {resposta['Err']}")
        return resposta
    finally:
        fechar_device(d)


def status_cobertura(device):
    item = {
        'id': device['id'],
        'nome': device['name'],
        'ip': device.get('ip') or '',
        'status': 'offline',
        'erro': '',
    }
    try:
        item['status'] = status_local(device)
    except Exception as e:
        item['erro'] = str(e)[:160]
    return item

# ---------------------------------------------------------------------------
# Endpoints da API
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/dispositivos')
def api_dispositivos():
    """Retorna status das coberturas usando apenas a rede local."""
    try:
        coberturas = carregar_coberturas()
    except Exception as e:
        return jsonify({'erro': str(e), 'dispositivos': []}), 500

    resultado = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        tarefas = {executor.submit(status_cobertura, d): d for d in coberturas}
        for futuro in as_completed(tarefas):
            resultado.append(futuro.result())
    resultado.sort(key=lambda d: d['nome'].lower())
    return jsonify(resultado)


@app.route('/api/acao/<device_id>/<comando>', methods=['POST'])
def api_acao(device_id, comando):
    """
    Envia comando local usando switch_1 (DPS 1, booleano absoluto).
    door_control_1 (DPS 6) e aceito mas ignorado pelo firmware MS-109.
    Fechar: direto. Abrir: confirmacao exigida no frontend.
    """
    device = procurar_cobertura(device_id)
    if not device:
        return jsonify({'erro': 'Dispositivo nao encontrado'}), 404
    if comando not in ('abrir', 'fechar'):
        return jsonify({'erro': 'Comando invalido'}), 400
    try:
        resposta = comando_local(device, comando)
        return jsonify({
            'ok': True,
            'comando': comando,
            'dispositivo': device['name'],
            'resposta': resposta,
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

# ---------------------------------------------------------------------------
# Interface HTML
# ---------------------------------------------------------------------------

HTML = '''
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Painel Coberturas</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
        h1 { text-align: center; margin-bottom: 8px; color: #a0c4ff; font-size: 24px; }
        .sub { text-align: center; color: #8ea4c8; margin-bottom: 28px; font-size: 13px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
        .card { background: #16213e; border-radius: 8px; padding: 20px; border: 1px solid #0f3460; }
        .card h2 { font-size: 16px; margin-bottom: 6px; color: #a0c4ff; }
        .ip { color: #7787a6; font-size: 12px; margin-bottom: 12px; }
        .status { font-size: 18px; font-weight: bold; margin-bottom: 16px; }
        .status.aberta  { color: #4ade80; }
        .status.fechada { color: #60a5fa; }
        .status.offline { color: #f87171; }
        .status.erro    { color: #fbbf24; }
        .status.aguarde { color: #888; }
        .erro-msg { color: #fbbf24; min-height: 16px; font-size: 11px; margin: -8px 0 12px; }
        .botoes { display: flex; gap: 10px; }
        button {
            flex: 1; padding: 10px; border: none; border-radius: 8px;
            cursor: pointer; font-size: 14px; font-weight: bold; transition: opacity 0.2s;
        }
        button:hover    { opacity: 0.85; }
        button:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn-abrir  { background: #4ade80; color: #000; }
        .btn-fechar { background: #60a5fa; color: #000; }
        .btn-status { background: #374151; color: #eee; }
        .rodape {
            text-align: center; color: #7b8499; font-size: 12px;
            margin-top: 24px;
        }
    </style>
</head>
<body>
    <h1>Observatorio Munhoz &mdash; Coberturas</h1>
    <p class="sub">Painel local LAN &mdash; sem Tuya Cloud</p>
    <div class="grid" id="grid"></div>
    <p class="rodape" id="rodape">Carregando...</p>

    <script>
        function confirmarAbrir(nome) {
            return confirm('Confirma ABRIR a cobertura "' + nome + '"?');
        }

        function setStatus(id, texto, classe, erro) {
            const el = document.getElementById('status-' + id);
            if (el) { el.textContent = texto; el.className = 'status ' + classe; }
            const err = document.getElementById('erro-' + id);
            if (err) { err.textContent = erro || ''; }
        }

        function atualizar(id) {
            setStatus(id, 'Verificando...', 'aguarde', '');
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(dados => {
                    const lista = Array.isArray(dados) ? dados : (dados.dispositivos || []);
                    const d = lista.find(x => x.id === id);
                    if (d) setStatus(id, d.status.toUpperCase(), d.status, d.erro);
                })
                .catch(() => setStatus(id, 'ERRO', 'erro', 'falha ao consultar servidor'));
        }

        function acao(id, nome, comando) {
            if (comando === 'abrir' && !confirmarAbrir(nome)) return;
            setStatus(id, 'Aguarde...', 'aguarde', '');
            fetch('/api/acao/' + id + '/' + comando, {method: 'POST'})
                .then(r => r.json())
                .then(res => {
                    if (res.erro) {
                        setStatus(id, 'ERRO', 'erro', res.erro);
                        alert('Erro: ' + res.erro);
                    } else {
                        setTimeout(() => atualizar(id), 12000);
                    }
                })
                .catch(() => setStatus(id, 'ERRO', 'erro', 'falha ao enviar comando'));
        }

        function renderizar(dados) {
            const grid = document.getElementById('grid');
            const lista = Array.isArray(dados) ? dados : (dados.dispositivos || []);

            if (!Array.isArray(dados) && dados.erro) {
                document.getElementById('rodape').textContent = 'Erro: ' + dados.erro;
                return;
            }

            lista.forEach(d => {
                const existente = document.getElementById('card-' + d.id);
                if (existente) {
                    setStatus(d.id, d.status.toUpperCase(), d.status, d.erro);
                    return;
                }

                const card = document.createElement('div');
                card.className = 'card';
                card.id = 'card-' + d.id;

                const titulo = document.createElement('h2');
                titulo.textContent = d.nome;

                const ip = document.createElement('div');
                ip.className = 'ip';
                ip.textContent = d.ip || 'sem IP local';

                const status = document.createElement('div');
                status.className = 'status ' + d.status;
                status.id = 'status-' + d.id;
                status.textContent = d.status.toUpperCase();

                const erro = document.createElement('div');
                erro.className = 'erro-msg';
                erro.id = 'erro-' + d.id;
                erro.textContent = d.erro || '';

                const botoes = document.createElement('div');
                botoes.className = 'botoes';

                const btnStatus = document.createElement('button');
                btnStatus.className = 'btn-status';
                btnStatus.textContent = 'Status';
                btnStatus.addEventListener('click', () => atualizar(d.id));

                const btnAbrir = document.createElement('button');
                btnAbrir.className = 'btn-abrir';
                btnAbrir.textContent = 'Abrir';
                btnAbrir.addEventListener('click', () => acao(d.id, d.nome, 'abrir'));

                const btnFechar = document.createElement('button');
                btnFechar.className = 'btn-fechar';
                btnFechar.textContent = 'Fechar';
                btnFechar.addEventListener('click', () => acao(d.id, d.nome, 'fechar'));

                botoes.append(btnStatus, btnAbrir, btnFechar);
                card.append(titulo, ip, status, erro, botoes);
                grid.appendChild(card);
            });

            document.getElementById('rodape').textContent =
                'Ultima atualizacao: ' + new Date().toLocaleTimeString('pt-BR') +
                ' (auto-refresh 60s) - rede local';
        }

        function carregarTodos() {
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(renderizar)
                .catch(() => {
                    document.getElementById('rodape').textContent = 'Erro ao carregar - tentando novamente...';
                });
        }

        carregarTodos();
        setInterval(carregarTodos, 60000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
