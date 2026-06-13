# CLAUDE.local.md — contexto específico desta instalação

> Este arquivo NÃO deve ser versionado. Adicione `CLAUDE.local.md` ao `.gitignore`.
> Copie este arquivo para `CLAUDE.local.md` e preencha com os dados da sua instalação.
> Leia em conjunto com `CLAUDE.md`.

---

## Instalação

**Observatório / local:**
**Piers em produção:**
**Status geral:**

---

## Atores

| Pessoa | Papel |
|---|---|
| | Desenvolvedor / operador principal |
| | Responsável on-site (hardware, power-cycles) |

---

## Máquinas

| Máquina | IP LAN | Função |
|---|---|---|
| | | PC principal |

- **Gateway:**
- **Subnet:**

---

## Dispositivos (preencher por pier)

| Dispositivo | IP | Hardware | Versão | MAC |
|---|---|---|---|---|
| Cobertura Pier X | | | | |
| Régua Pier X | | | | |

---

## Tuya API

- **Region:** (ex: `us`)
- **Endpoint:** (ex: `openapi.tuyaus.com`)
- **Credenciais:** em `config.json` (não versionado)

---

## Configuração de rede aplicada

(Documentar aqui qualquer ajuste de rede específico desta instalação,
ex: IPv6 desabilitado, métricas de interface, VPN.)

---

## Estado das etapas

| Etapa | O quê | Status |
|---|---|---|
| 0 | Power-cycle + diagnóstico DPS | |
| 1 | `ipv4_first.py` + imports | |
| 2 | `painel_local/servidor.py` | |
| 3 | `dome_driver.py` robusto | |
| 4 | Cascata na GUI | |
| 5 | Teste prolongado 8–12h | |
| 6 | Expansão aos demais piers | |

---

## Pendências

- [ ]
- [ ]

---

## Particularidades do hardware local

(Documentar aqui qualquer comportamento específico do hardware desta instalação
que difira do documentado em `docs/hardware_tuya_ms109.md`.)
