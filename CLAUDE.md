# CLAUDE.md — roll-off-tuya-ascom-nina

> Briefing permanente para o Claude Code.
> Leia inteiro antes de qualquer modificação de código.
> Para contexto específico da instalação local, leia também `CLAUDE.local.md`
> (não versionado — crie a partir de `CLAUDE.local.exemplo.md`).

---

## 1. O que é este projeto

Sistema de automação de coberturas roll-off e réguas de tomadas inteligentes para
observatórios astronômicos. Controla dispositivos Tuya via protocolo local LAN
(porta TCP 6668) com fallback cloud, e expõe driver ASCOM Alpaca para integração
com o software de astrofotografia NINA.

Hardware de cobertura validado: **Novadigital MS-109** (Mini Pulso Wi-Fi, OEM Tuya,
módulo CB3S, protocolo local 3.4, categoria Tuya `ckmkzq`). Outros dispositivos
da mesma categoria (`ckmkzq`) devem ser compatíveis, mas exigem validação do
mapeamento DPS antes de uso em produção.

**Credenciais:** nunca no repositório — ficam em `config.json` (não versionado).

---

## 2. INVARIANTES — nunca violar

### 2.1 — Uma única conexão TCP local por dispositivo de cobertura

Quando o `dome_driver.py` está rodando, **somente ele** abre conexão TCP local com
o dispositivo de cobertura na porta 6668. A `telhado_gui.py` **nunca** cria
`tinytuya.Device` para a cobertura enquanto o driver estiver ativo.

**Por quê:** firmware Tuya aceita exatamente uma sessão TCP local. Socket abandonado
(não fechado explicitamente) fica como "sessão fantasma" no firmware RAM. Sintoma:
erro 914 em todas as tentativas subsequentes, mesmo com `local_key` correto.
Resolução: power-cycle físico do hardware (~15s desligado). Não tem solução por
software.

### 2.2 — Sempre fechar conexão local explicitamente

Todo código que abre `tinytuya.Device` **deve** chamar `d.close()` no `finally`:

```python
d = tinytuya.Device(...)
try:
    # usar d
finally:
    try:
        d.close()
    except Exception:
        pass
```

Socket fechado limpo não vira fantasma. Socket abandonado, sim. O padrão da v1.x
(criar conexão a cada 30s sem fechar) foi a causa raiz do primeiro travamento
de firmware registrado neste projeto.

### 2.3 — Fechar é mais crítico que abrir

Fechamento do telhado protege equipamento contra chuva — tratado como função
crítica de segurança. Nunca adicionar confirmação ao fechamento. Sempre adicionar
confirmação à abertura (painel web e GUI).

### 2.4 — Comando via DPS 1 / switch_1, nunca DPS 6

No MS-109, o `door_control_1` (DPS 6) é aceito pelo firmware mas **não aciona o
motor fisicamente** — confirmado empiricamente por câmera. Mapeamento correto:

```
COMANDO  → DPS 1 / switch_1: True=abrir, False=fechar (absoluto, não toggle)
ESTADO   → DPS 3 / doorcontact_state: False=fechada, True=aberta
ALARME   → DPS 12 / door_state_1: 'none'=normal
NUNCA    → DPS 6 / door_control_1 para comando (ignorado pelo firmware do MS-109)
```

**Atenção para outros hardwares:** este mapeamento é específico do MS-109. Outros
dispositivos `ckmkzq` podem ter comportamento diferente. Sempre validar o
mapeamento DPS empiricamente antes de usar em produção (ver seção 6).

### 2.5 — Importar `ipv4_first` em todo módulo que usa rede

Python (requests/urllib3) não implementa happy eyeballs. Em redes com IPv6
anunciado mas quebrado (ex: Starlink), cada tentativa IPv6 custa ~21s de timeout.
Com 3 registros AAAA e 2 requisições HTTPS por chamada Tuya: ~128s por operação.
Solução: `import ipv4_first` no topo de todo módulo que faz chamadas de rede.

### 2.6 — Identidade Alpaca única por instalação, derivada do config

O `dome_driver.py` anuncia ao NINA um `DeviceName`, um `ServerName` e um
`UniqueID`. Regra:

- **`DEVICE_NAME`** é genérico e fixo (`'Tuya Dome'`), igual em todas as
  instalações. A diferenciação entre piers se dá **pelo IP** na descoberta do
  NINA, nunca pelo nome.
- **`UNIQUE_ID`** é **derivado do `id` Tuya da cobertura**
  (`f'tuya-dome-{COB_ID}'`), definido logo após o carregamento do `config.json`.
  **Nunca hardcoded.**

**Por quê:** o `UniqueID` é a impressão digital que o ASCOM/NINA usa para lembrar
o device entre reconexões (perfis, configurações). O `id` Tuya é globalmente
único por relé, estável (independe de IP) e amarrado ao telhado físico, então
cada instalação nasce única automaticamente. Valor hardcoded é herdado ao clonar
a config de um pier para outro — foi a causa do incidente da seção 7 (o NINA
controlando o telhado do pier errado). **IP nunca serve como identidade: ele
muda** (ex.: IP ZeroTier de miniPC temporário).

### 2.7 — Cloud sempre com timeout, serialização e envelope

TinyTuya 1.18.1 não define timeout nas chamadas `requests` e repassa o corpo de
`sendcommand()` diretamente à API. Regras:

- importar `requests_timeout` antes de criar `tinytuya.Cloud`;
- executar somente uma operação cloud por vez em cada processo;
- enviar comandos como `{"commands": [...]}`, nunca como lista isolada;
- uma leitura cloud pode ser repetida uma vez; comandos não são repetidos
  automaticamente porque um timeout não prova que a Tuya deixou de aceitá-los.

Instalações sem acesso LAN devem usar `"modo_conexao": "cloud"` para não
acumular tentativas locais e erro 905.

---

## 3. Arquitetura

```
NINA ──Alpaca/HTTP──────┐
                         ├──► dome_driver.py ──► conexão local abre-fecha ──► dispositivo
GUI ──HTTP (driver vivo)─┘          │                                          ▲
                                    └── fallback ──► Tuya Cloud ───────────────┤
                                                                               │
GUI ──(driver AUSENTE)──────────────► local direto (abre-fecha) ───────────────┤
GUI ──(local falhou)────────────────► Tuya Cloud ───────────────────────────────┤
                                                                               │
painel_local/servidor.py ───────────► local direto (abre-fecha, paralelo) ─────┘
```

**Por que local-primário no driver:** tempestade = quando mais precisa fechar =
quando internet está pior (atenuação por chuva). Correlação perversa. Caminho
local: PC → roteador → dispositivo (3 elos internos). Cloud: PC → internet →
servidores Tuya → internet → dispositivo (6 elos, 3 fora de controle).

**Por que abre-fecha e não socket persistente:** firmware do MS-109 derruba
conexões locais ociosas com erro 904 após ~30s. Abre-fecha elimina a janela de
ociosidade. Custo: ~0.2s de handshake por operação — irrelevante pois NINA e GUI
leem do cache, não do dispositivo diretamente.

---

## 4. Componentes

### `dome_driver.py` — driver ASCOM Alpaca

Dono único da conexão local quando ativo. Roda como processo independente
(subido pela GUI ou manualmente).

- Padrão abre-fecha explícito por operação
- Locks separados: `_state_lock`, `_device_lock`, `_cloud_lock`
- Cache de status com timestamp
- Backoff progressivo após falha local: 30s → 60s → 120s → 240s → teto 300s
- Fallback cloud automático durante backoff
- Supressão de comando redundante (estado já confirmado → ignora)
- Transição Opening/Closing confirmada por sensor físico (DPS 3), não por timer
- Poll de status a cada 30s em thread daemon
- Logging rotativo (`dome_driver.log`, 1MB × 3 backups)
- Identidade Alpaca (`DEVICE_NAME` genérico + `UNIQUE_ID` derivado do `id` Tuya)
  definida logo após o carregamento do config — ver invariante 2.6

Endpoints próprios:
- `GET /health` — estado completo com contadores e modo atual
- `GET /status` — estado simplificado para a GUI
- `POST /abrir`, `POST /fechar`
- `POST /emergency_close` — envia → aguarda curso → verifica DPS 3 → repete via cloud
- `POST /shutdown` — fecha socket, responde HTTP, `os._exit(0)` em thread separada

Endpoints Alpaca (contrato com NINA — não alterar):
- `/api/v1/dome/0/connected`, `/shutterstatus`, `/openshutter`, `/closeshutter`,
  `/slewing`, `/ismoving`, `/cansetshutter` e demais

### `telhado_gui.py` — interface Tkinter

Cascata de conexão em 3 níveis + gestão do ciclo de vida do driver.

**Cascata:**
1. `GET /health` no driver (timeout 0.5s)
2. Driver vivo → HTTP; nunca cria `tinytuya.Device` para a cobertura
3. Driver ausente → local direto (abre-fecha)
4. Local falhou → Tuya Cloud

**Ciclo de vida do driver:**
- Ao abrir: sobe driver como subprocesso se não existir
- `_driver_era_nosso = True` somente se a GUI iniciou o processo
- Ao fechar: encerra via `POST /shutdown` somente se foi ela quem iniciou
- Se driver já existia ao abrir: usa mas não encerra ao fechar

**Interface:** label de modo visível (`[driver]`, `[local]`, `[cloud]`).
Régua: tinytuya direto (dispositivo separado, não envolve o driver).

### `painel_local/servidor.py` — painel web Flask

Painel administrativo para uso na rede local. Sem dependência de Tuya Cloud.

- Lê `devices.json`, filtra por `category == 'ckmkzq'`
- Status paralelo via `ThreadPoolExecutor(max_workers=8)`
- Comandos via `switch_1` / DPS 1
- Auto-refresh 60s; fechar direto, abrir com `confirm()`
- Procura `devices.json` em `painel_local/` primeiro, depois na raiz
- `servidor.py` na raiz: entry point legado (5 linhas) que importa `painel_local.servidor`

### `ipv4_first.py` — preferência IPv4

Reordena `socket.getaddrinfo` para IPv4 primeiro. Importar no topo de todo
módulo que faz chamadas de rede.

### `tuya_cloud.py` — auxiliares cloud

Funções para API Tuya Cloud (timers, comandos cloud).

---

## 5. Estrutura do repositório

```
roll-off-tuya-ascom-nina/
├── dome_driver.py
├── telhado_gui.py
├── tuya_cloud.py
├── ipv4_first.py
├── servidor.py             # entry point legado → painel_local/servidor.py
├── config_exemplo.json     # template — credenciais reais em config.json (não versionado)
├── requirements.txt
├── README.md
├── README_USO.md
├── CLAUDE.md               # este arquivo (genérico, versionado)
├── CLAUDE.local.exemplo.md # template para CLAUDE.local.md (versionado)
├── painel_local/
│   ├── servidor.py
│   ├── devices_exemplo.json
│   ├── README_PAINEL.md
│   └── README_CADU.txt
├── docs/
│   ├── hardware_tuya_ms109.md
│   ├── estrutura_projeto.md
│   └── README_TELHADO_GUI.txt
└── scripts/
    ├── run_gui.bat
    ├── run_driver.bat
    ├── run_web_panel.bat
    └── build_web_panel.bat
```

**Não versionados:** `config.json`, `devices.json`, `.venv/`, `logs/`, `CLAUDE.local.md`

---

## 6. Validação de novo hardware (obrigatória antes de produção)

Para qualquer dispositivo `ckmkzq` diferente do MS-109:

1. **Power-cycle** do dispositivo antes de iniciar (~15s desligado)
2. **Comparar DPS local vs cloud:** imprimir `d.status()` bruto e
   `cloud.getstatus(ID)` bruto lado a lado
3. **Teste de idempotência** — presencial, de dia, olhando o telhado:
   com telhado **fechado**, enviar comando fechar → nada deve mover.
   Repetir → nada deve mover. Se mover: DPS 1 é toggle, não absoluto —
   a lógica de retry do driver precisa ser adaptada.
4. **Nunca testar idempotência remotamente** nem com telhado aberto.
5. Documentar o mapeamento em `docs/hardware_<modelo>.md`

---

## 7. Armadilhas conhecidas

### Erro 914

Triage em ordem:
1. `local_key` correto? (`devices.json` × `Cloud.getdevices()`)
2. IP correto? (`tinytuya scan`)
3. Versão de protocolo? (testar 3.3/3.4/3.5)
4. Processo concorrente com socket aberto?
5. TCP conecta mas handshake falha (`Test-NetConnection -Port 6668` = True)?
   → sessão fantasma → **power-cycle físico**
   **Nunca usar reset via app** — despareia o dispositivo, gera nova `local_key`

### Erro 904

Firmware derruba conexão ociosa após ~30s. Solução: padrão abre-fecha.
Já implementado em todos os componentes. Se aparecer: verificar se algum
código novo usa socket persistente.

### `devices.json` — arquivo crítico

Sobrescrever com backup antigo corrompe todas as `local_key`s. Sempre:
- Backup datado antes de qualquer escrita
- Verificar source/destination antes de qualquer cópia

### PowerShell — encoding UTF-8 BOM

`Out-File` produz UTF-8 BOM por padrão. Python falha ao importar arquivos com BOM.
Usar sempre:
```powershell
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
```

### `door_control_1` não move o telhado (MS-109)

DPS 6 é aceito pela API mas ignorado fisicamente pelo firmware do MS-109.
Sempre usar DPS 1 / `switch_1` para comandos neste hardware.

### NINA controla o telhado do pier errado

Sintoma: comando pelo NINA aciona a cobertura de **outro** pier. O Alpaca é só
HTTP para um IP e não tem noção de "dono" nem autenticação — obedece a qualquer
endpoint conectado. Causas, em ordem:

1. **Driver do pier alvo desligado** → a descoberta do NINA (broadcast UDP porta
   32227) só acha servidores Alpaca vivos. Se o do pier certo está fora do ar, o
   NINA conecta no único disponível (outro pier). Subir o driver do pier alvo
   resolve.
2. **`UniqueID` idêntico entre piers** (config clonada com identidade hardcoded)
   → a descoberta pode deduplicar e os perfis se misturam. Corrigir com o
   `UNIQUE_ID` derivado do `id` Tuya (invariante 2.6).
3. **Servidor amarrado a todas as interfaces** → o mesmo driver aparece várias
   vezes na descoberta (loopback, LAN local, ZeroTier), com nomes iguais. Sempre
   identifique pelo **IP ZeroTier**; opcionalmente restrinja a interface de escuta.

Diagnóstico: `http://<ip>:11111/management/v1/configureddevices` mostra a
identidade real (nome + `UniqueID`) de cada endpoint. Isolamento real entre
usuários/piers é responsabilidade da **rede** (redes ZeroTier separadas ou flow
rules), não do driver.

---

## 8. Configuração para nova instalação

1. Clonar o repositório
2. Criar ambiente virtual: `python -m venv .venv`
3. Instalar dependências: `pip install -r requirements.txt`
4. Copiar `config_exemplo.json` → `config.json` e preencher credenciais
5. Executar `tinytuya wizard` para obter `devices.json` com `local_key`s
6. Validar mapeamento DPS do hardware (seção 6)
7. Copiar `CLAUDE.local.exemplo.md` → `CLAUDE.local.md` e preencher

---

## 9. Referências internas

| Arquivo | Conteúdo |
|---|---|
| `docs/hardware_tuya_ms109.md` | Mapeamento DPS confirmado para o MS-109 |
| `docs/estrutura_projeto.md` | Estrutura atual e roadmap de reorganização |
| `painel_local/README_PAINEL.md` | Como rodar e distribuir o painel |
| `CLAUDE.local.md` | Contexto específico desta instalação (não versionado) |
