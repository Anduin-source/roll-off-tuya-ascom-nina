import ipv4_first  # IPv4 preferencial - ver ipv4_first.py
from flask import Flask, jsonify, render_template_string
import tinytuya
import json
import os

app = Flask(__name__)

import sys

# Quando compilado pelo PyInstaller (sys.frozen=True), os arquivos de dados
# (config.json, devices.json) ficam ao lado do .exe (sys.executable).
# Em modo Python puro, ficam ao lado do .py (__file__).
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_BASE_DIR, 'config.json')
DEVICES_FILE = os.path.join(_BASE_DIR, 'devices.json')

# ---------------------------------------------------------------------------
# Carregamento de configuracao e dispositivos
# ---------------------------------------------------------------------------

def carregar_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def carregar_coberturas():
    """Retorna apenas dispositivos da categoria ckmkzq (coberturas/garagens)."""
    with open(DEVICES_FILE, 'r', encoding='utf-8') as f:
        devices = json.load(f)
    return [d for d in devices if d.get('category') == 'ckmkzq']


def get_cloud():
    """Cria objeto Cloud a partir do config.json. Token gerenciado pelo tinytuya."""
    cfg = carregar_config()
    return tinytuya.Cloud(
        apiRegion=cfg['tuya_cloud']['region'],
        apiKey=cfg['tuya_cloud']['api_key'],
        apiSecret=cfg['tuya_cloud']['api_secret']
    )

# ---------------------------------------------------------------------------
# Status em lote — 1 chamada para todos os dispositivos (ate 20 por chamada)
# Substitui o padrao antigo de N conexoes locais sequenciais.
# Sem tinytuya.Device, sem socket local, sem risco de sessao fantasma.
# ---------------------------------------------------------------------------

def get_status_batch(device_ids):
    """
    Consulta o estado de todos os dispositivos em uma unica chamada cloud.
    Retorna dict: {device_id: 'aberta' | 'fechada' | 'offline'}

    Usa doorcontact_state (DPS 3) — sensor fisico real, nao o ultimo comando.
    False = fechada, True = aberta.
    """
    if not device_ids:
        return {}
    try:
        c = get_cloud()
        ids_str = ','.join(device_ids)
        result = c.cloudrequest(
            f'/v1.0/iot-03/devices/status?device_ids={ids_str}'
        )
        status_map = {}
        if result.get('success') and result.get('result'):
            for item in result['result']:
                dev_id = item.get('id')
                if not dev_id:
                    continue
                dps = {s['code']: s['value'] for s in item.get('status', [])}
                if 'doorcontact_state' in dps:
                    status_map[dev_id] = 'aberta' if dps['doorcontact_state'] else 'fechada'
                else:
                    status_map[dev_id] = 'offline'
        return status_map
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Endpoints da API
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/dispositivos')
def api_dispositivos():
    """Retorna status de todas as coberturas em uma unica chamada cloud."""
    coberturas = carregar_coberturas()
    device_ids = [d['id'] for d in coberturas]
    status_map = get_status_batch(device_ids)
    resultado = []
    for d in coberturas:
        resultado.append({
            'id': d['id'],
            'nome': d['name'],
            'status': status_map.get(d['id'], 'offline')
        })
    return jsonify(resultado)


@app.route('/api/acao/<device_id>/<comando>')
def api_acao(device_id, comando):
    """
    Envia comando via cloud usando switch_1 (DPS 1, booleano absoluto).
    door_control_1 (DPS 6) e aceito mas ignorado pelo firmware MS-109.
    Fechar: direto. Abrir: confirmacao exigida no frontend.

    Nao usa tinytuya.Device nem conexao local - invariante arquitetural:
    somente dome_driver.py abre socket local com o MS-109.
    """
    coberturas = carregar_coberturas()
    device = next((d for d in coberturas if d['id'] == device_id), None)
    if not device:
        return jsonify({'erro': 'Dispositivo nao encontrado'}), 404
    if comando not in ('abrir', 'fechar'):
        return jsonify({'erro': 'Comando invalido'}), 400
    try:
        c = get_cloud()
        valor = True if comando == 'abrir' else False
        result = c.sendcommand(
            device_id,
            [{'code': 'switch_1', 'value': valor}]
        )
        if result.get('success'):
            return jsonify({
                'ok': True,
                'comando': comando,
                'dispositivo': device['name']
            })
        else:
            return jsonify({'erro': str(result)}), 500
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
        h1 { text-align: center; margin-bottom: 30px; color: #a0c4ff; font-size: 24px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
        .card { background: #16213e; border-radius: 12px; padding: 20px; border: 1px solid #0f3460; }
        .card h2 { font-size: 16px; margin-bottom: 12px; color: #a0c4ff; }
        .status { font-size: 18px; font-weight: bold; margin-bottom: 16px; }
        .status.aberta  { color: #4ade80; }
        .status.fechada { color: #60a5fa; }
        .status.offline { color: #f87171; }
        .status.erro    { color: #fbbf24; }
        .status.aguarde { color: #888; }
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
            text-align: center; color: #555; font-size: 12px;
            margin-top: 24px;
        }
    </style>
</head>
<body>
    <h1>Observatorio Munhoz &mdash; Coberturas</h1>
    <div class="grid" id="grid"></div>
    <p class="rodape" id="rodape">Carregando...</p>

    <script>
        // Abrir exige confirmacao — abertura espontanea e pior modo de falha
        function confirmarAbrir(nome) {
            return confirm('Confirma ABRIR a cobertura "' + nome + '"?');
        }

        function setStatus(id, texto, classe) {
            const el = document.getElementById('status-' + id);
            if (el) { el.textContent = texto; el.className = 'status ' + classe; }
        }

        function atualizar(id) {
            setStatus(id, 'Verificando...', 'aguarde');
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(dados => {
                    const d = dados.find(x => x.id === id);
                    if (d) setStatus(id, d.status.toUpperCase(), d.status);
                })
                .catch(() => setStatus(id, 'ERRO', 'erro'));
        }

        function acao(id, nome, comando) {
            if (comando === 'abrir' && !confirmarAbrir(nome)) return;
            setStatus(id, 'Aguarde...', 'aguarde');
            fetch('/api/acao/' + id + '/' + comando)
                .then(r => r.json())
                .then(res => {
                    if (res.erro) {
                        setStatus(id, 'ERRO', 'erro');
                        alert('Erro: ' + res.erro);
                    } else {
                        // Aguarda o tempo de curso do MS-109 (door_time_1 = 10s)
                        // antes de reler o sensor fisico
                        setTimeout(() => atualizar(id), 12000);
                    }
                })
                .catch(() => setStatus(id, 'ERRO', 'erro'));
        }

        function renderizar(dados) {
            const grid = document.getElementById('grid');

            dados.forEach(d => {
                const existente = document.getElementById('card-' + d.id);
                if (existente) {
                    // Card ja existe — so atualiza o status
                    setStatus(d.id, d.status.toUpperCase(), d.status);
                    return;
                }

                // Card novo — construido via DOM, sem strings inline
                // (evita problemas de escape e nomes com caracteres especiais)
                const card = document.createElement('div');
                card.className = 'card';
                card.id = 'card-' + d.id;

                const titulo = document.createElement('h2');
                titulo.textContent = d.nome;

                const status = document.createElement('div');
                status.className = 'status ' + d.status;
                status.id = 'status-' + d.id;
                status.textContent = d.status.toUpperCase();

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
                card.append(titulo, status, botoes);
                grid.appendChild(card);
            });

            document.getElementById('rodape').textContent =
                'Ultima atualizacao: ' + new Date().toLocaleTimeString('pt-BR') +
                ' (auto-refresh 60s) — apenas cloud, sem conexao local';
        }

        function carregarTodos() {
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(renderizar)
                .catch(() => {
                    document.getElementById('rodape').textContent = 'Erro ao carregar — tentando novamente...';
                });
        }

        carregarTodos();
        setInterval(carregarTodos, 60000); // 60s — batch cloud, 1 chamada por ciclo
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
