# Controle Roll-Off Tuya

Sistema de controle remoto para coberturas roll-off de observatório usando dispositivos Tuya. Controla a cobertura motorizada e a régua inteligente, expõe um driver ASCOM Alpaca para o NINA, e inclui um painel web para gerenciar múltiplos piers.

Implementação atual: Observatório Munhoz — MPC X93.

---

## Instalação rápida (sem Git)

Ideal para instalar em outro pier ou PC dedicado, sem precisar clonar o repositório.

1. **Baixe o projeto**: na página do repositório no GitHub, clique em `Code` → `Download ZIP`, e extraia em uma pasta (ex.: `C:\Projetos\roll-off-tuya-ascom-nina`).
2. **Instale o Python** (3.10 ou superior), se ainda não tiver: https://www.python.org/downloads/ — marque a opção "Add python.exe to PATH" durante a instalação.
3. **Instale as dependências**, abrindo um terminal na pasta extraída:
   ```powershell
   pip install -r requirements.txt
   ```
4. **Configure suas credenciais**: copie `config_exemplo.json` para `config.json` e preencha com os dados do seu dispositivo Tuya (veja [Configuração](#configuração) abaixo).
5. **Rode a interface**:
   ```powershell
   scripts\run_gui.bat
   ```

Pronto — a GUI abre e já inicia o driver Alpaca automaticamente.

> Prefere trabalhar com o código-fonte via Git? `git clone https://github.com/Anduin-source/roll-off-tuya-ascom-nina.git` funciona normalmente; os passos seguintes (dependências, configuração, execução) são os mesmos.

---

## O que o projeto controla

- Cobertura motorizada roll-off (dispositivo Tuya)
- Régua inteligente Tuya
- Driver ASCOM Alpaca, para o NINA controlar a cobertura como "Dome"
- Painel web administrativo, para gerenciar coberturas de vários piers

---

## Como usar

| Ação | Comando |
| --- | --- |
| Abrir a interface gráfica (uso normal) | `scripts\run_gui.bat` |
| Rodar o driver manualmente (só debug) | `scripts\run_driver.bat` |
| Abrir o painel web administrativo | `scripts\run_web_panel.bat` (depois acesse `http://<IP-do-PC>:5000`) |

A GUI inicia o driver Alpaca sozinha, se ele ainda não estiver rodando, e o encerra ao fechar. No uso normal, não é preciso iniciar o driver manualmente.

### Sequência recomendada para sessão com NINA

1. Abrir a GUI (`scripts\run_gui.bat`)
2. Confirmar que o status da cobertura mostra `[driver]`
3. Abrir o NINA e conectar o Dome
4. Rodar a sessão
5. Fechar o NINA, depois fechar a GUI

---

## Configuração

Copie o modelo e edite com os dados do seu dispositivo:

```powershell
copy config_exemplo.json config.json
```

```json
{
  "cobertura": {
    "id":  "ID_DO_DISPOSITIVO",
    "ip":  "IP_LOCAL_DO_DISPOSITIVO",
    "key": "LOCAL_KEY_DO_DISPOSITIVO",
    "version": 3.4,
    "modo_conexao": "auto"
  },
  "regua": {
    "id":  "ID_DA_REGUA",
    "ip":  "IP_LOCAL_DA_REGUA",
    "key": "LOCAL_KEY_DA_REGUA",
    "switches": {
      "1": "Switch 1",
      "2": "PC",
      "3": "Montagem",
      "4": "Switch 4"
    }
  },
  "tuya_cloud": {
    "region":         "us",
    "api_key":        "ACCESS_ID_DA_TUYA",
    "api_secret":     "ACCESS_SECRET_DA_TUYA",
    "timezone":       "America/Sao_Paulo",
    "timer_category": "schedule"
  }
}
```

Não sabe o `id`, `ip` ou `key` do seu dispositivo? Rode o assistente do [tinytuya](https://github.com/jasonacox/tinytuya) (`python -m tinytuya wizard`) — ele descobre esses dados a partir da sua conta Tuya Cloud.

`config.json` contém credenciais e nunca deve ser enviado ao GitHub (já protegido pelo `.gitignore`).

`modo_conexao` aceita `auto`, `local` ou `cloud`. Use `auto` no caso normal
(rede local com fallback cloud). Em uma instalação acessível somente pela
Tuya Cloud, use `cloud`; assim o driver não perde tempo tentando a LAN.

---

## Observações de segurança

- O NINA só controla a cobertura enquanto o driver Alpaca estiver rodando; a GUI cuida disso automaticamente.
- Em caso de dúvida ou falha, fechar deve ser sempre a ação prioritária.
- Recomenda-se uma proteção independente do PC (ex.: timer de fechamento na nuvem Tuya, ou sensor de chuva cabeado).

Antes de uso desassistido, teste manualmente status, abertura e fechamento, e rode a GUI + driver + NINA por algumas horas confirmando que nenhum processo trava ou fica órfão.

---

## Autor

Desenvolvido por André Brossel — Observatório Munhoz — MPC X93.

## Licença

MIT License — sinta-se livre para usar, modificar e distribuir, mantendo os créditos ao autor original.

---

## Documentação complementar

- `README_USO.md` — guia rápido de uso operacional
- `docs/hardware_tuya_ms109.md` — hardware Tuya validado na instalação atual
- `docs/estrutura_projeto.md` — estrutura do projeto
