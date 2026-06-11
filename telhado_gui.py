import ipv4_first  # IPv4 preferencial - ver ipv4_first.py
import tkinter as tk
import tinytuya
import threading
import schedule
import time
import json
import os
import sys
import urllib.request

# ===========================================================================
# Pier 1 - Interface de controle (GUI)
#
# Cobertura: cascata de conexao em 3 niveis (Etapa 4 da arquitetura)
#   1. DRIVER  - se dome_driver.py estiver rodando (HTTP localhost:11111)
#   2. LOCAL   - conexao direta tinytuya, SOMENTE se o driver estiver ausente
#                (abre e FECHA explicitamente - nunca abandona socket)
#   3. CLOUD   - fallback final
#
# Invariante: quando o driver esta vivo, a GUI NUNCA cria tinytuya.Device
# para a cobertura - fala HTTP com o driver. Isso garante um unico dono do
# socket local. Comando sempre via door_control_1 (DPS 6), nunca switch_1.
#
# Regua: permanece tinytuya direto (dispositivo separado, socket proprio,
# nao critico). Sem cascata de driver.
# ===========================================================================

DRIVER_URL = 'http://127.0.0.1:11111'
DRIVER_TIMEOUT = 0.5   # conexao recusada e instantanea; 0.5s cobre driver lento

# ---------------------------------------------------------------------------
# Configuracao - lida de config.json (nao versionado)
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        print("ERRO: config.json nao encontrado.")
        print("Copie config_exemplo.json para config.json e preencha suas credenciais.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def salvar_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


config = carregar_config()

COB_ID  = config['cobertura']['id']
COB_IP  = config['cobertura']['ip']
COB_KEY = config['cobertura']['key']

REG_ID  = config['regua']['id']
REG_IP  = config['regua']['ip']
REG_KEY = config['regua']['key']

API_REGION = config['tuya_cloud']['region']
API_KEY    = config['tuya_cloud']['api_key']
API_SECRET = config['tuya_cloud']['api_secret']

_switches_raw = config['regua'].get('switches', {})
SWITCHES      = {int(k): v for k, v in _switches_raw.items()}
SWITCH_CODES  = {1: 'switch_1', 2: 'switch_2', 3: 'switch_3', 4: 'switch_4'}

# ---------------------------------------------------------------------------
# Cores / tema
# ---------------------------------------------------------------------------

BG        = '#1a1a2e'
BG_CARD   = '#16213e'
BG_BTN    = '#0f3460'
BG_ENTRY  = '#0a1628'
AZUL      = '#4a9eff'
VERDE     = '#4ade80'
VERMELHO  = '#f87171'
AMARELO   = '#fbbf24'
CINZA     = '#6b7280'
TEXTO     = '#e2e8f0'
TEXTO_MUT = '#94a3b8'
SEPARADOR = '#1e3a5f'

# ---------------------------------------------------------------------------
# Conexao cloud (singleton com lock)
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
# Camada de comunicacao da COBERTURA - cascata driver -> local -> cloud
# ---------------------------------------------------------------------------

def _driver_vivo():
    """Testa se o dome_driver responde. Conexao recusada e instantanea
    quando o driver nao esta rodando - nao ha timeout a esperar."""
    try:
        req = urllib.request.urlopen(DRIVER_URL + '/health', timeout=DRIVER_TIMEOUT)
        return req.status == 200
    except Exception:
        return False


def _driver_status():
    """Le o status pelo driver. Retorna (aberta_bool_or_None, 'driver')."""
    try:
        req = urllib.request.urlopen(DRIVER_URL + '/status', timeout=2)
        data = json.loads(req.read().decode())
        estado = data.get('estado')
        if estado == 'aberta':
            return True, 'driver'
        if estado == 'fechada':
            return False, 'driver'
        return None, 'driver'
    except Exception:
        return None, 'driver'


def _driver_comando(comando):
    """Envia abrir/fechar pelo driver. comando: 'abrir' ou 'fechar'.
    Retorna True se aceito."""
    try:
        rota = '/abrir' if comando == 'abrir' else '/fechar'
        req = urllib.request.Request(DRIVER_URL + rota, method='POST')
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        return data.get('ok', False)
    except Exception:
        return False


def _local_status():
    """Le status via conexao local direta. Abre e FECHA explicitamente.
    Retorna (aberta_bool_or_None). Lanca excecao em falha de conexao."""
    d = tinytuya.Device(dev_id=COB_ID, address=COB_IP, local_key=COB_KEY, version=3.4)
    d.set_socketPersistent(False)
    d.set_socketTimeout(1.5)
    try:
        s = d.status()
        if isinstance(s, dict) and 'dps' in s:
            return bool(s['dps'].get('3', False))
        raise RuntimeError(f'sem dps: {s}')
    finally:
        try:
            d.close()
        except Exception:
            pass


def _local_comando(comando):
    """Envia comando via local direto usando door_control_1 (DPS 6).
    Abre e FECHA explicitamente. Lanca excecao em falha."""
    valor = 'open' if comando == 'abrir' else 'close'
    d = tinytuya.Device(dev_id=COB_ID, address=COB_IP, local_key=COB_KEY, version=3.4)
    d.set_socketPersistent(False)
    d.set_socketTimeout(1.5)
    try:
        r = d.set_value(6, valor)
        if isinstance(r, dict) and 'Err' in r:
            raise RuntimeError(f"Err {r['Err']}")
        return True
    finally:
        try:
            d.close()
        except Exception:
            pass


def _cloud_status():
    """Le status via cloud. Retorna aberta_bool_or_None."""
    s = get_cloud().getstatus(COB_ID)
    if s and 'result' in s:
        for item in s['result']:
            if item.get('code') == 'doorcontact_state':
                return bool(item.get('value', False))
    return None


def _cloud_comando(comando):
    """Envia comando via cloud usando door_control_1. Lanca excecao em falha."""
    valor = 'open' if comando == 'abrir' else 'close'
    r = get_cloud().sendcommand(COB_ID, [{'code': 'door_control_1', 'value': valor}])
    if not r.get('success'):
        raise RuntimeError(f'cloud sem sucesso: {r}')
    return True


def status_cobertura():
    """Le o status da cobertura pela cascata. Retorna (aberta, modo)."""
    if _driver_vivo():
        return _driver_status()
    try:
        return _local_status(), 'local'
    except Exception:
        pass
    try:
        return _cloud_status(), 'cloud'
    except Exception:
        return None, 'cloud'


def comando_cobertura(comando):
    """Envia abrir/fechar pela cascata. Retorna (ok, modo)."""
    if _driver_vivo():
        return _driver_comando(comando), 'driver'
    try:
        _local_comando(comando)
        return True, 'local'
    except Exception:
        pass
    try:
        _cloud_comando(comando)
        return True, 'cloud'
    except Exception:
        return False, 'cloud'

# ---------------------------------------------------------------------------
# Atualizacao do label da cobertura - fonte unica de verdade
# ---------------------------------------------------------------------------

def _sufixo_modo(modo):
    if modo == 'driver':
        return ''           # driver e o caminho normal, sem icone
    if modo == 'local':
        return ' \U0001F50C'  # tomada (local direto, sem driver)
    if modo == 'cloud':
        return ' \U0001F4E1'  # antena (cloud)
    return ''


def atualizar_label_cobertura(aberta, modo):
    sufixo = _sufixo_modo(modo)
    if aberta is None:
        label_cob.config(text='ERRO', fg=VERMELHO)
    else:
        label_cob.config(
            text=('ABERTA' if aberta else 'FECHADA') + sufixo,
            fg=VERDE if aberta else AZUL)

# ---------------------------------------------------------------------------
# Acoes da cobertura
# ---------------------------------------------------------------------------

def acao_cobertura(comando):
    btn_abrir.config(state='disabled')
    btn_fechar.config(state='disabled')
    btn_atualizar.config(state='disabled')
    label_cob.config(text='buscando...', fg=CINZA)

    def executar():
        try:
            if comando == 'status':
                aberta, modo = status_cobertura()
                janela.after(0, lambda: atualizar_label_cobertura(aberta, modo))

            elif comando in ('abrir', 'fechar'):
                aberta_atual, modo = status_cobertura()
                alvo_aberta = (comando == 'abrir')

                # So envia o comando se o estado for diferente do alvo
                if aberta_atual is None or aberta_atual != alvo_aberta:
                    ok, modo = comando_cobertura(comando)
                else:
                    ok = True  # ja esta no estado desejado

                sufixo = _sufixo_modo(modo)
                transicao = 'abrindo...' if comando == 'abrir' else 'fechando...'
                janela.after(0, lambda: label_cob.config(
                    text=transicao + sufixo, fg=AMARELO))

                def verificar():
                    time.sleep(13)  # door_time_1 (10s) + margem
                    aberta2, modo2 = status_cobertura()
                    # No fechar, da uma segunda chance se ainda aberta
                    if comando == 'fechar' and aberta2 is True:
                        time.sleep(8)
                        aberta2, modo2 = status_cobertura()
                    janela.after(0, lambda: atualizar_label_cobertura(aberta2, modo2))

                threading.Thread(target=verificar, daemon=True).start()

        except Exception:
            janela.after(0, lambda: label_cob.config(text='ERRO', fg=VERMELHO))

        janela.after(0, lambda: btn_abrir.config(state='normal'))
        janela.after(0, lambda: btn_fechar.config(state='normal'))
        janela.after(0, lambda: btn_atualizar.config(state='normal'))

    threading.Thread(target=executar, daemon=True).start()


def abrir_agendado():
    try:
        aberta, _ = status_cobertura()
        if not aberta:
            ok, modo = comando_cobertura('abrir')
            if ok:
                janela.after(0, lambda: label_cob.config(
                    text='ABERTA' + _sufixo_modo(modo), fg=VERDE))
    except Exception:
        pass


def fechar_agendado():
    try:
        aberta, _ = status_cobertura()
        if aberta:
            ok, modo = comando_cobertura('fechar')
            if ok:
                janela.after(0, lambda: label_cob.config(
                    text='FECHADA' + _sufixo_modo(modo), fg=AZUL))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Conexao da REGUA (tinytuya direto - dispositivo separado, nao critico)
# ---------------------------------------------------------------------------

def conectar_regua():
    """Local primeiro (abre/fecha explicito), cloud como fallback.
    Retorna (dispositivo, modo, dps). Em modo local, o CHAMADOR e
    responsavel por fechar o dispositivo apos o uso."""
    d = tinytuya.Device(dev_id=REG_ID, address=REG_IP, local_key=REG_KEY, version=3.4)
    d.set_socketPersistent(False)
    d.set_socketTimeout(1.5)
    try:
        s = d.status()
        if isinstance(s, dict) and 'dps' in s:
            return d, 'local', s['dps']   # chamador fecha 'd' no finally dele
    except Exception:
        pass

    # Local falhou - fecha o device antes de cair para cloud
    try:
        d.close()
    except Exception:
        pass

    c = get_cloud()
    s = c.getstatus(REG_ID)
    dps = {}
    if s and 'result' in s:
        for item in s['result']:
            dps[item['code']] = item['value']
    return c, 'cloud', dps

# ---------------------------------------------------------------------------
# Acoes da regua
# ---------------------------------------------------------------------------

def acao_regua(switch_num, comando):
    if comando in botoes_regua[switch_num]:
        botoes_regua[switch_num][comando].config(state='disabled')
    labels_regua[switch_num].config(text='...', fg=CINZA)

    def executar():
        dispositivo = None
        try:
            dispositivo, modo, dps = conectar_regua()
            sufixo = ' \U0001F4E1' if modo == 'cloud' else ''
            code   = SWITCH_CODES[switch_num]

            if comando == 'status':
                ligado = dps.get(str(switch_num), False) if modo == 'local' else dps.get(code, False)
                labels_regua[switch_num].config(
                    text=('ON' if ligado else 'OFF') + sufixo,
                    fg=VERDE if ligado else CINZA)

            elif comando == 'ligar':
                if modo == 'local':
                    dispositivo.set_value(switch_num, True)
                else:
                    dispositivo.sendcommand(REG_ID, [{'code': code, 'value': True}])
                labels_regua[switch_num].config(text='ON' + sufixo, fg=VERDE)

            elif comando == 'desligar':
                if modo == 'local':
                    dispositivo.set_value(switch_num, False)
                else:
                    dispositivo.sendcommand(REG_ID, [{'code': code, 'value': False}])
                labels_regua[switch_num].config(text='OFF' + sufixo, fg=CINZA)

        except Exception:
            labels_regua[switch_num].config(text='ERRO', fg=VERMELHO)
        finally:
            # fecha conexao local da regua se foi local
            if dispositivo is not None and hasattr(dispositivo, 'close'):
                try:
                    dispositivo.close()
                except Exception:
                    pass

        if comando in botoes_regua[switch_num]:
            botoes_regua[switch_num][comando].config(state='normal')

    threading.Thread(target=executar, daemon=True).start()


def status_todos_regua():
    """Status das 4 tomadas. Em modo cloud, 1 chamada cobre todas."""
    # Tenta uma leitura unica primeiro (1 conexao para os 4 switches)
    def executar():
        dispositivo = None
        try:
            dispositivo, modo, dps = conectar_regua()
            sufixo = ' \U0001F4E1' if modo == 'cloud' else ''
            for sw in SWITCHES:
                code = SWITCH_CODES[sw]
                ligado = dps.get(str(sw), False) if modo == 'local' else dps.get(code, False)
                lbl = labels_regua[sw]
                lbl.config(text=('ON' if ligado else 'OFF') + sufixo,
                           fg=VERDE if ligado else CINZA)
        except Exception:
            for sw in SWITCHES:
                labels_regua[sw].config(text='ERRO', fg=VERMELHO)
        finally:
            if dispositivo is not None and hasattr(dispositivo, 'close'):
                try:
                    dispositivo.close()
                except Exception:
                    pass

    threading.Thread(target=executar, daemon=True).start()

# ---------------------------------------------------------------------------
# Agendamento
# ---------------------------------------------------------------------------

def validar_hora(hora_str):
    if hora_str.strip() == '':
        return True
    try:
        h, m = hora_str.strip().split(':')
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except Exception:
        return False


def flash_feedback(label, msg, cor, duracao=2000):
    label.config(text=msg, fg=cor)
    janela.after(duracao, lambda: label.config(text=''))


def iniciar_agendamento_salvo():
    schedule.clear()
    h_abrir  = config.get('agendamento', {}).get('abrir', '')
    h_fechar = config.get('agendamento', {}).get('fechar', '')
    if h_abrir:
        schedule.every().day.at(h_abrir).do(
            lambda: threading.Thread(target=abrir_agendado, daemon=True).start())
    if h_fechar:
        schedule.every().day.at(h_fechar).do(
            lambda: threading.Thread(target=fechar_agendado, daemon=True).start())


def loop_schedule():
    while True:
        schedule.run_pending()
        time.sleep(10)


def formatar_hora(entry, label_feedback, config_key):
    val = entry.get().replace(':', '').strip()

    if val == '':
        config.setdefault('agendamento', {})[config_key] = ''
        salvar_config(config)
        iniciar_agendamento_salvo()
        flash_feedback(label_feedback, "removido", AMARELO)
        return

    if len(val) == 3:
        val = '0' + val
    if len(val) != 4 or not val.isdigit():
        flash_feedback(label_feedback, "use 4 digitos: HHMM", VERMELHO)
        return

    hora = val[:2] + ':' + val[2:]
    if not validar_hora(hora):
        flash_feedback(label_feedback, "hora invalida", VERMELHO)
        return

    entry.delete(0, tk.END)
    entry.insert(0, hora)
    config.setdefault('agendamento', {})[config_key] = hora
    salvar_config(config)
    iniciar_agendamento_salvo()

    def criar_na_nuvem():
        try:
            from tuya_cloud import criar_timer
            acao = 'abrir' if config_key == 'abrir' else 'fechar'
            r = criar_timer(hora, acao)
            if r.get('success'):
                flash_feedback(label_feedback, "salvo na nuvem", VERDE)
            else:
                flash_feedback(label_feedback, "salvo local (nuvem falhou)", AMARELO)
        except Exception:
            flash_feedback(label_feedback, "salvo local", AMARELO)

    threading.Thread(target=criar_na_nuvem, daemon=True).start()

# ---------------------------------------------------------------------------
# Helpers de UI
# ---------------------------------------------------------------------------

def btn_estilo(parent, texto, cor_bg, cor_fg, cmd):
    return tk.Button(parent, text=texto, command=cmd,
                     bg=cor_bg, fg=cor_fg, activebackground=cor_bg,
                     font=('Segoe UI', 10, 'bold'), relief='flat',
                     padx=16, pady=7, cursor='hand2', bd=0)


def separador(parent):
    tk.Frame(parent, bg=SEPARADOR, height=1).pack(fill='x', padx=16, pady=8)


class HorarioEditavel:
    def __init__(self, parent, config_key, label_feedback):
        self.config_key     = config_key
        self.label_feedback = label_feedback
        self.editando       = False
        self.frame          = tk.Frame(parent, bg=BG_CARD)

        valor_atual = config.get('agendamento', {}).get(config_key, '')
        self.var    = tk.StringVar(value=valor_atual)
        cor_inicial = TEXTO if valor_atual else CINZA
        txt_inicial = valor_atual if valor_atual else 'N/A'

        self.label = tk.Label(self.frame, text=txt_inicial,
                              font=('Segoe UI', 16, 'bold'),
                              bg=BG_CARD, fg=cor_inicial, cursor='hand2')
        self.label.pack(anchor='w')
        self.label.bind('<Button-1>', self._entrar_edicao)

        self.entry = tk.Entry(self.frame, textvariable=self.var,
                              font=('Segoe UI', 16, 'bold'), width=6,
                              bg=BG_ENTRY, fg=TEXTO, insertbackground=TEXTO,
                              relief='flat', justify='center',
                              highlightthickness=1,
                              highlightcolor=AZUL,
                              highlightbackground=SEPARADOR)
        self.entry.bind('<Return>',    self._salvar)
        self.entry.bind('<Escape>',    self._cancelar)
        self.entry.bind('<FocusOut>',  self._cancelar)

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def _entrar_edicao(self, event=None):
        if self.editando:
            return
        self.editando = True
        self.var.set(config.get('agendamento', {}).get(self.config_key, ''))
        self.label.pack_forget()
        self.entry.pack(anchor='w')
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)

    def _salvar(self, event=None):
        formatar_hora(self.entry, self.label_feedback, self.config_key)
        valor = config.get('agendamento', {}).get(self.config_key, '')
        self._sair_edicao(valor if valor else 'N/A', TEXTO if valor else CINZA)

    def _cancelar(self, event=None):
        if not self.editando:
            return
        valor = config.get('agendamento', {}).get(self.config_key, '')
        self._sair_edicao(valor if valor else 'N/A', TEXTO if valor else CINZA)

    def _sair_edicao(self, texto, cor):
        self.editando = False
        self.entry.pack_forget()
        self.label.config(text=texto, fg=cor)
        self.label.pack(anchor='w')

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

janela = tk.Tk()
janela.title("Pier 1 - Controle")
janela.configure(bg=BG)
janela.geometry("420x660")
janela.resizable(False, False)

tk.Label(janela, text="\U0001F52D Pier 1", font=('Segoe UI', 15, 'bold'),
         bg=BG, fg=TEXTO).pack(pady=(18, 2))
tk.Label(janela, text="Observatorio Munhoz", font=('Segoe UI', 10),
         bg=BG, fg=TEXTO_MUT).pack(pady=(0, 14))

# Card cobertura
card_cob = tk.Frame(janela, bg=BG_CARD, bd=0,
                    highlightthickness=1, highlightbackground=BG_BTN)
card_cob.pack(fill='x', padx=20, pady=(0, 12))

tk.Label(card_cob, text="COBERTURA", font=('Segoe UI', 9, 'bold'),
         bg=BG_CARD, fg=TEXTO_MUT).pack(anchor='w', padx=16, pady=(12, 0))

label_cob = tk.Label(card_cob, text="---", font=('Segoe UI', 24, 'bold'),
                     bg=BG_CARD, fg=CINZA)
label_cob.pack(pady=(4, 8))

frame_btn_cob = tk.Frame(card_cob, bg=BG_CARD)
frame_btn_cob.pack(pady=(0, 6))

btn_abrir    = btn_estilo(frame_btn_cob, "Abrir",  '#166534', VERDE, lambda: acao_cobertura('abrir'))
btn_fechar   = btn_estilo(frame_btn_cob, "Fechar", '#1e3a5f', AZUL,  lambda: acao_cobertura('fechar'))
btn_atualizar = btn_estilo(frame_btn_cob, "\u21BA",    '#2a2a2a', TEXTO_MUT, lambda: acao_cobertura('status'))

btn_abrir.grid(row=0, column=0, padx=6)
btn_fechar.grid(row=0, column=1, padx=6)
btn_atualizar.grid(row=0, column=2, padx=6)

tk.Label(card_cob, text="\u21BA sincroniza o status com o dispositivo",
         font=('Segoe UI', 7), bg=BG_CARD, fg=CINZA).pack(pady=(2, 6))

separador(card_cob)

tk.Label(card_cob, text="AGENDAMENTO", font=('Segoe UI', 9, 'bold'),
         bg=BG_CARD, fg=TEXTO_MUT).pack(anchor='w', padx=16, pady=(0, 10))

frame_ag = tk.Frame(card_cob, bg=BG_CARD)
frame_ag.pack(padx=16, fill='x')

col_abrir = tk.Frame(frame_ag, bg=BG_CARD)
col_abrir.pack(side='left', padx=(0, 50))
tk.Label(col_abrir, text="Abrir", font=('Segoe UI', 9),
         bg=BG_CARD, fg=TEXTO_MUT).pack(anchor='w')
label_feedback_abrir = tk.Label(col_abrir, text="", font=('Segoe UI', 8), bg=BG_CARD, fg=VERDE)
campo_abrir = HorarioEditavel(col_abrir, 'abrir', label_feedback_abrir)
campo_abrir.pack(anchor='w', pady=(2, 2))
label_feedback_abrir.pack(anchor='w')

col_fechar = tk.Frame(frame_ag, bg=BG_CARD)
col_fechar.pack(side='left')
tk.Label(col_fechar, text="Fechar", font=('Segoe UI', 9),
         bg=BG_CARD, fg=TEXTO_MUT).pack(anchor='w')
label_feedback_fechar = tk.Label(col_fechar, text="", font=('Segoe UI', 8), bg=BG_CARD, fg=VERDE)
campo_fechar = HorarioEditavel(col_fechar, 'fechar', label_feedback_fechar)
campo_fechar.pack(anchor='w', pady=(2, 2))
label_feedback_fechar.pack(anchor='w')

tk.Label(card_cob, text="Clique no horario para editar - Enter para salvar",
         font=('Segoe UI', 8), bg=BG_CARD, fg=CINZA).pack(
         anchor='w', padx=16, pady=(8, 14))

# Card regua
card_reg = tk.Frame(janela, bg=BG_CARD, bd=0,
                    highlightthickness=1, highlightbackground=BG_BTN)
card_reg.pack(fill='x', padx=20, pady=(0, 12))

tk.Label(card_reg, text="REGUA", font=('Segoe UI', 9, 'bold'),
         bg=BG_CARD, fg=TEXTO_MUT).pack(anchor='w', padx=16, pady=(12, 8))

labels_regua  = {}
botoes_regua  = {}

for sw, nome in SWITCHES.items():
    row = tk.Frame(card_reg, bg=BG_CARD)
    row.pack(fill='x', padx=16, pady=3)

    tk.Label(row, text=nome, font=('Segoe UI', 10),
             bg=BG_CARD, fg=TEXTO, width=10, anchor='w').pack(side='left')

    lbl = tk.Label(row, text="---", font=('Segoe UI', 10, 'bold'),
                   bg=BG_CARD, fg=CINZA, width=5)
    lbl.pack(side='left', padx=8)
    labels_regua[sw] = lbl

    btn_off = btn_estilo(row, "OFF", '#3b1a1a', VERMELHO, lambda s=sw: acao_regua(s, 'desligar'))
    btn_off.pack(side='right', padx=(4, 0))

    btn_on = btn_estilo(row, "ON", '#14532d', VERDE, lambda s=sw: acao_regua(s, 'ligar'))
    btn_on.pack(side='right', padx=(4, 0))

    botoes_regua[sw] = {'ligar': btn_on, 'desligar': btn_off}

tk.Frame(card_reg, bg=BG_CARD, height=10).pack()

# ---------------------------------------------------------------------------
# Inicializacao
# ---------------------------------------------------------------------------

threading.Thread(target=get_cloud, daemon=True).start()
iniciar_agendamento_salvo()
threading.Thread(target=loop_schedule, daemon=True).start()

janela.after(500, lambda: acao_cobertura('status'))
janela.after(800, status_todos_regua)

janela.mainloop()
