# CLAUDE.md — pier-controle / Observatório Munhoz (MPC X93)

> Este arquivo é o briefing permanente para o Claude Code.
> Leia-o inteiro antes de qualquer modificação de código.

---

## 1. O que é este projeto

Sistema de automação de coberturas (telhados roll-off) e réguas de tomadas inteligentes
do Observatório Munhoz (MPC X93), localizado em Munhoz, MG, Brasil. O observatório tem
18 piers; o sistema controla os dispositivos via protocolo Tuya IoT (local LAN + cloud
fallback) e expõe um driver ASCOM Alpaca para o software de astrofotografia NINA.

**Hardware de cobertura crítico:** dispositivos Tuya categoria `ckmkzq` — MS-102,
EKAC-T3099WB (EKAZA). Comunicação local na porta TCP 6668.

**Repositório:** `Anduin-source/pier-controle` (GitHub, público)
**Credenciais:** nunca no repositório — ficam em `config.json` (não versionado, ver `.gitignore`)

---

## 2. INVARIANTES — nunca violar

### 2.1 — Uma única conexão TCP local por dispositivo de cobertura

Quando o `dome_driver.py` está rodando, **somente ele** abre conexão TCP local com o
MCP1001/MS-102/EKAZA na porta 6668. Nenhum outro módulo, script ou thread pode criar
um `tinytuya.Device` para esses dispositivos enquanto o driver estiver ativo.

**Por quê:** o firmware aceita exatamente uma sessão TCP local. Conexões concorrentes ou
mal encerradas criam uma "sessão fantasma" no firmware RAM. Sintoma: erro 914 em todas as
tentativas subsequentes, mesmo com `local_key` correto. Resolução: power-cycle físico do
hardware (não tem solução por software). Já aconteceu em produção. Custo: deslocamento
físico ao observatório (Munhoz, MG).

### 2.2 — Nunca abrir conexão local sem fechamento explícito

Qualquer código que abra `tinytuya.Device` para cobertura **fora** do driver deve
chamar `d.__del__()` ou fechar o socket explicitamente. O padrão antigo de criar conexão
nova a cada 30s sem fechar foi a causa raiz provável do travamento atual do Pier 1.

### 2.3 — Fechar é mais crítico que abrir

O fechamento do telhado protege equipamento de ~R$50k contra chuva. Em caso de dúvida
sobre lógica de controle, erre do lado do fechamento. Nunca adicione confirmação de
usuário ao fechamento; sempre adicione ao abertura.

### 2.4 — IPv6 desabilitado nos adaptadores Windows do observatório

A Starlink anuncia IPv6 mas o tráfego é blackhole. Python (requests/urllib3) não
implementa happy eyeballs — tenta AAAA sequencialmente, ~21s de timeout por endereço,
totalizando ~128s por chamada cloud. IPv6 foi desabilitado nos adaptadores Ethernet e
Wi-Fi do Pier1-Desktop via `Disable-NetAdapterBinding`. Qualquer novo código que use
rede deve importar `ipv4_first.py` (a ser criado, ver Etapa 1 abaixo).

---

## 3. Arquitetura acordada (não reabrir sem motivo explícito)

```
NINA ──Alpaca/HTTP──────┐
                         ├──► dome_driver.py ──► 1 conexão local persistente ──► MCP1001/EKAZA
GUI ──HTTP (se driver ───┘          │                                              ▲
      estiver vivo)                 └── fallback ──► Tuya Cloud ───────────────────┤
                                                                                   │
GUI ──(somente se driver AUSENTE)──► local direto ─────────────────────────────────┤
GUI ──(se local falhou)────────────► Tuya Cloud ───────────────────────────────────┤
                                                                                   │
servidor.py (painel Cadu) ─────────► Tuya Cloud SOMENTE (nunca local) ─────────────┘
```

### Decisões tomadas e seus motivos

| Decisão | Motivo |
|---|---|
| `servidor.py` usa cloud-puro | Maior multiplicador de conexões locais. Cloud tem latência irrelevante para supervisão (2s). |
| Régua permanece na GUI (não migrar ao driver) | Dispositivo diferente, socket próprio, cliente único, não crítico. Complexidade sem ganho. |
| GUI cascata 3 níveis | Preserva uso standalone (colegas sem NINA). |
| `servidor.py` usa chamada em lote | 18 polls/30s = ~51k calls/dia → 1 lote/60s = ~1.4k calls/dia. |
| Caminho local primário no driver | Tempestade = quando mais precisa fechar = quando Starlink está pior (atenuação por chuva). Correlação perversa. |

### `dome_driver.py` — especificação

- `set_socketPersistent(True)` — uma conexão persistente, com heartbeat
- Locks separados: `_state_lock` (estado), `_device_lock` (operações locais), `_cloud_lock` (cloud)
- Cache de status com timestamp — NINA e GUI consultam sem tocar no dispositivo
- Backoff exponencial após erro 914 ou timeout — não martelar o firmware
- Fallback cloud automático quando local falha
- Agendador de Tarefas Windows, auto-reinício em falha, independente do NINA
- Endpoints: `GET /health`, `GET /status`, `POST /emergency_close`
- `POST /emergency_close`: envia local (timeout 2-3s) → aguarda 8s de curso → verifica `doorcontact_state` → se falhou, repete por cloud → se ainda falhou, log barulhento

### `telhado_gui.py` — cascata

1. `GET http://127.0.0.1:11111/health` (~1ms, recusa instantânea se driver morto)
2. Driver ausente → local direto (abre e **fecha** explicitamente)
3. Local falhou → Tuya Cloud
4. Interface mostra modo em uso: `DRIVER/LOCAL`, `DRIVER/CLOUD`, `STANDALONE/LOCAL`, `STANDALONE/CLOUD`

---

## 4. Armadilhas conhecidas (com causa raiz)

### Erro 914 — triage na ordem certa

1. `local_key` correto? (comparar `devices.json` × `Cloud.getdevices()`)
2. IP correto? (`tinytuya scan`)
3. Versão de protocolo correta? (testar 3.3/3.4/3.5)
4. Processo concorrente? (verificar `pythonw`, `servidor.py`, `dome_driver.py`)
5. TCP abre mas handshake falha? → **sessão fantasma** → power-cycle físico

Se `Test-NetConnection <IP> -Port 6668` retorna `TcpTestSucceeded: True` mas tinytuya
retorna 914 com todas as versões: é sessão fantasma. Única solução: power-cycle físico
(~15s desligado). **Não usar "reset" via app** — despareia o dispositivo, gera nova
`local_key`, exige re-execução do wizard.

### `devices.json` — arquivo crítico

Sobrescrever com backup antigo corrompe todas as `local_key`s. Sempre:
1. Fazer backup com nome datado antes de qualquer operação de escrita
2. Verificar source/destination antes de `Copy-Item`

### PowerShell — encoding UTF-8 BOM

`Out-File` produz UTF-8 BOM por padrão. Python falha ao importar arquivos com BOM.
Sempre usar:
```powershell
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
```

### DPS — comando toggle vs explícito (NÃO RESOLVIDO — Etapa 0 pendente)

Dispositivos categoria `ckmkzq` podem ter DPS 1 como gatilho de impulso (toggle),
não como estado explícito. Dois envios de "fechar" podem fechar e reabrir o telhado.
`door_control_1` com valores `open`/`close` é explícito e idempotente — usar este
depois que a Etapa 0 confirmar o mapeamento empiricamente.

---

## 5. Estado atual e próximas etapas

**Status geral:** código base funcional no Pier 1. Arquitetura refatorada acordada,
implementação em andamento.

### Etapa 0 — PRÉ-REQUISITO (bloqueante para tudo mais)

- [ ] Power-cycle físico do MCP1001/MS-102 do Pier 1 (~15s desligado; está na rede elétrica direta, NÃO na régua)
- [ ] Após power-cycle: confirmar `d.status()` local funciona
- [ ] Mapear DPS: imprimir `d.status()` local bruto + `cloud.getstatus()` bruto lado a lado
- [ ] Testar idempotência do comando de fechar: enviar 2× e verificar que não reabre
- [ ] Preencher tabela de mapeamento DPS antes de qualquer código novo de controle

**Cadu executa on-site.**

### Etapa 1

- [ ] Criar `ipv4_first.py` (reordena `socket.getaddrinfo` para IPv4 primeiro)
- [ ] Importar no topo de `telhado_gui.py`, `servidor.py`, `dome_driver.py`, `tuya_cloud.py`

### Etapa 2

- [ ] Refatorar `servidor.py`: remover TODO `tinytuya.Device` para coberturas, usar apenas `tinytuya.Cloud`
- [ ] Implementar chamada em lote: `GET /v1.0/iot-03/devices/status?device_ids=...` (até 20 dispositivos, via `cloudrequest`)
- [ ] Polling 60s + cache + botão "Atualizar agora"
- [ ] Fechar: sem confirmação. Abrir: com confirmação.

### Etapa 3

- [ ] Refatorar `dome_driver.py` com spec da seção 3 acima
- [ ] Registrar no Agendador de Tarefas (boot, auto-reinício)

### Etapa 4

- [ ] Cascata na `telhado_gui.py`
- [ ] Régua: 1 chamada cloud em vez de 4 sequenciais

### Etapa 5

- [ ] Teste prolongado 8-12h com driver + GUI + NINA + painel simultâneos
- [ ] Critérios: zero erros 914; zero fallbacks cloud não explicados; NINA conectado sem reconexões; cache < 60s; comandos simultâneos não se atropelam

### Etapa 6

- [ ] Expansão aos demais piers (somente após Pier 1 validado)

---

## 6. Topologia de rede

| Máquina | IP LAN | IP ZeroTier | Rede Wi-Fi |
|---|---|---|---|
| Pier1-Desktop | `10.1.3.10` | `10.218.81.1` | AndreB (Starlink, primário) |
| Pier2-MiniPC | `10.1.3.20` | `10.218.81.2` | obs5g |

- **Gateway:** `10.1.1.1` — **Subnet:** `10.1.0.0/16`
- **obs5g / obs2g:** redes do Cadu (rádio/local, sem acesso externo)
- **AndreB:** rede do Andre (Starlink)
- **ZeroTier:** acesso externo apenas Andre
- **Cadu:** opera somente localmente, sem ZeroTier
- Allsky camera IM3: `10.1.3.15` (RTSP, LAN-only)
- Pier1-Desktop: métricas de interface — Ethernet=10, Wi-Fi=50 (definido manualmente)

**Tuya API:** Region `us` (Western America), endpoint `openapi.tuyaus.com`
Credenciais em `config.json` (não versionado).

---

## 7. Inventário de dispositivos

### Coberturas (categoria `ckmkzq`)

| Nome | IP | Hardware | Versão | Status (06/06/26) |
|---|---|---|---|---|
| Pier 01 - Andre Cobertura | `10.1.3.19` | MS-102 | 3.4 | ABERTA |
| Pier 02 - Andre Cobertura | `10.1.2.23` | EKAC-T3099WB (EKAZA) | 3.5 | ABERTA |
| Pier 14 - Ednilson Cobertura | `10.1.3.149` | MS-102 | 3.4 | FECHADA |
| Pier 15 - Alexandre | `10.1.3.159` | MS-102 | 3.4 | FECHADA |
| Pier 17 - Moleiro | sem IP | MS-102 | — | OFFLINE |

DPS conhecidos:
- DPS 3 (`doorcontact_state`): `True` = ABERTA, `False` = FECHADA
- DPS 12 (`door_state_1`): `unclosed_time` = aberta além do tempo; `none` = normal
- DPS 1 / `door_control_1`: mapeamento pendente (Etapa 0 — ver seção 5)

MACs: Pier 01 = `d8:c8:0c:42:ba:c5` | Pier 02 = `c0:f8:53:c1:18:a3`

### Réguas (categoria `pc`)

| Nome | IP | Hardware | Versão |
|---|---|---|---|
| Pier 1 - Andre Regua | `10.1.3.12` | WKC-F321 | 3.4 |
| Pier 2 - Andre Regua | `10.1.3.23` | WKC-F321 | 3.4 |
| Allsky / MSwitch2 | `10.1.3.9` | WKC-F321 | 3.4 |
| Pier 5 - Claudius | `10.1.3.52` | SM-SO301 | 3.4 |
| Pier 8 - Irineu | `10.1.3.85` | SM-SO301 | 3.4 |
| Pier 14 - Ednilson | `10.1.3.144` | SM-SO301 | 3.4 |
| Pier 3 - Barretos | `10.1.3.39` | SM-SO301 | 3.3 |

### Tomada individual

| Nome | Hardware | Nota |
|---|---|---|
| Pier 02 - CAM ASI533 | NX-SM112 | Tem medição de potência/corrente/tensão (DPS 18/19/20) |

---

## 8. Atores e responsabilidades

| Ator | Papel |
|---|---|
| Andre (owner) | Desenvolvimento, Pier 1, acesso remoto via ZeroTier |
| Cadu | Gerente do observatório — infraestrutura, roteador, hardware on-site, power-cycles |

Cadu não tem acesso ao repositório nem ao ZeroTier. Opera somente via painel web
(`servidor.py` em `http://10.1.3.10:5000`) e presença física.

---

## 9. Pendências administrativas

- [ ] Verificar validade da assinatura Tuya IoT Core no portal de desenvolvedor
- [ ] Reservas DHCP no roteador (MAC → IP fixo) para dispositivos críticos — conversa com Cadu
- [ ] Ritual mensal: testar timer Tuya 05:00 (backup não testado não é backup)
- [ ] Comprar tomada inteligente para alimentação do MCP1001 (hoje: direto na rede elétrica → power-cycle exige presença física)

---

## 10. Referências internas

| Arquivo | Conteúdo |
|---|---|
| `ARQUITETURA_pier-controle_CONSOLIDADA_2026-06-10.md` | Spec completa da arquitetura acordada |
| `diagnostico_2026-06-09_ipv6_e_erro914.md` | Diagnóstico detalhado dos dois problemas resolvidos/pendentes |
| `inventario_dispositivos.md` | Inventário completo com IPs, Device IDs, versões |
| `config_exemplo.json` | Template de configuração (credenciais reais em `config.json`, não versionado) |
