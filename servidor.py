import ipv4_first  # IPv4 preferencial — ver ipv4_first.py
from flask import Flask, jsonify, render_template_string
import tinytuya
import json
import os

app = Flask(__name__)

# Carrega devices.json gerado pelo wizard
DEVICES_FILE = os.path.join(os.path.dirname(__file__), 'devices.json')

# Filtro: sÃ³ coberturas (produto MS-102 / categoria ckmkzq)
def carregar_coberturas():
    with open(DEVICES_FILE, 'r') as f:
        devices = json.load(f)
    return [d for d in devices if d.get('category') == 'ckmkzq']

def conectar(device):
    d = tinytuya.Device(
        dev_id=device['id'],
        address=device.get('ip', ''),
        local_key=device['key'],
        version=3.4
    )
    d.set_socketTimeout(5)
    return d

def get_status(device):
    try:
        d = conectar(device)
        s = d.status()
        if 'dps' in s:
            return 'aberta' if s['dps'].get('3', False) else 'fechada'
        return 'erro'
    except:
        return 'offline'

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/dispositivos')
def api_dispositivos():
    coberturas = carregar_coberturas()
    resultado = []
    for d in coberturas:
        resultado.append({
            'id': d['id'],
            'nome': d['name'],
            'ip': d.get('ip', 'N/A'),
            'status': get_status(d)
        })
    return jsonify(resultado)

@app.route('/api/acao/<device_id>/<comando>')
def api_acao(device_id, comando):
    coberturas = carregar_coberturas()
    device = next((d for d in coberturas if d['id'] == device_id), None)
    if not device:
        return jsonify({'erro': 'Dispositivo nÃ£o encontrado'}), 404
    if not device.get('ip'):
        return jsonify({'erro': 'IP nÃ£o disponÃ­vel'}), 400
    try:
        d = conectar(device)
        if comando == 'abrir':
            d.set_value(1, True)
        elif comando == 'fechar':
            d.set_value(1, False)
        else:
            return jsonify({'erro': 'Comando invÃ¡lido'}), 400
        return jsonify({'ok': True, 'comando': comando, 'dispositivo': device['name']})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

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
        .card h2 { font-size: 16px; margin-bottom: 8px; color: #a0c4ff; }
        .card .ip { font-size: 12px; color: #888; margin-bottom: 12px; }
        .status { font-size: 18px; font-weight: bold; margin-bottom: 16px; }
        .status.aberta { color: #4ade80; }
        .status.fechada { color: #60a5fa; }
        .status.offline { color: #f87171; }
        .status.erro { color: #fbbf24; }
        .status.carregando { color: #888; }
        .botoes { display: flex; gap: 10px; }
        button { flex: 1; padding: 10px; border: none; border-radius: 8px; 
                 cursor: pointer; font-size: 14px; font-weight: bold; transition: opacity 0.2s; }
        button:hover { opacity: 0.85; }
        button:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn-abrir { background: #4ade80; color: #000; }
        .btn-fechar { background: #60a5fa; color: #000; }
        .btn-status { background: #374151; color: #eee; }
        .atualizando { text-align: center; color: #888; font-size: 13px; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>ðŸ”­ Painel de Coberturas</h1>
    <div class="grid" id="grid"></div>
    <p class="atualizando" id="info">Carregando...</p>

    <script>
        let dispositivos = [];

        function renderizar(dados) {
            dispositivos = dados;
            const grid = document.getElementById('grid');
            grid.innerHTML = '';
            dados.forEach(d => {
                const card = document.createElement('div');
                card.className = 'card';
                card.id = 'card-' + d.id;
                card.innerHTML = `
                    <h2>${d.nome}</h2>
                    <div class="ip">IP: ${d.ip}</div>
                    <div class="status ${d.status}" id="status-${d.id}">
                        ${d.status.toUpperCase()}
                    </div>
                    <div class="botoes">
                        <button class="btn-status" onclick="atualizar('${d.id}')">Status</button>
                        <button class="btn-abrir" onclick="acao('${d.id}', 'abrir')">Abrir</button>
                        <button class="btn-fechar" onclick="acao('${d.id}', 'fechar')">Fechar</button>
                    </div>
                `;
                grid.appendChild(card);
            });
            document.getElementById('info').textContent = 
                'Ãšltima atualizaÃ§Ã£o: ' + new Date().toLocaleTimeString('pt-BR');
        }

        function setStatus(id, texto, classe) {
            const el = document.getElementById('status-' + id);
            if (el) {
                el.textContent = texto;
                el.className = 'status ' + classe;
            }
        }

        function atualizar(id) {
            setStatus(id, 'Verificando...', 'carregando');
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(dados => {
                    const d = dados.find(x => x.id === id);
                    if (d) setStatus(id, d.status.toUpperCase(), d.status);
                });
        }

        function acao(id, comando) {
            setStatus(id, 'Aguarde...', 'carregando');
            fetch(`/api/acao/${id}/${comando}`)
                .then(r => r.json())
                .then(res => {
                    if (res.erro) {
                        setStatus(id, 'ERRO', 'erro');
                    } else {
                        setTimeout(() => atualizar(id), 2000);
                    }
                });
        }

        function carregarTodos() {
            fetch('/api/dispositivos')
                .then(r => r.json())
                .then(renderizar);
        }

        carregarTodos();
        setInterval(carregarTodos, 30000); // atualiza a cada 30 segundos
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)