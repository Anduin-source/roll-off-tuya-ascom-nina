IMPORTANTE: antes de qualquer ação, verifique se existe um arquivo chamado `claude_local.md` na raiz do repositório. Se existir, consulte-o e use os valores definidos ali (ele contém credenciais e configurações locais). `claude_local.md` NÃO deve ser versionado.

**Resumo do Projeto**

Projeto de controle remoto de coberturas roll-off usando dispositivos Tuya, com driver ASCOM Alpaca (`dome_driver.py`), interface gráfica (`telhado_gui.py`) e painel web administrativo (`painel_local/servidor.py`). Destinado ao Observatório Munhoz (pier(s) locais).

**Arquivos/locais importantes (inspecionar)**
- `telhado_gui.py` — GUI Tkinter e lógica de ciclo de driver
- `dome_driver.py` — driver ASCOM Alpaca (porta local e endpoints)
- `painel_local/servidor.py` — painel web Flask (porta 5000)
- `tuya_cloud.py` — integração / helpers Tuya Cloud
- `config_exemplo.json` — modelo de configuração
- `config.json` — configuração local (contém credenciais; NÃO versionar)
- `devices.json` — inventário local de dispositivos (NÃO versionar)
- `requirements.txt` — dependências Python
- `scripts/` — scripts úteis: `run_gui.bat`, `run_driver.bat`, `run_web_panel.bat`, `build_*` etc.
- `build/` — artefatos PyInstaller (ignorar para execução)

**Ambiente recomendado**
- Plataforma: Windows (PowerShell) — scripts `.bat` incluídos
- Python 3.10+ (usar ambiente virtual `.venv`)
- Instalação: `python -m venv .venv` → `.\.venv\Scripts\Activate.ps1` → `pip install -r requirements.txt`

Comandos rápidos:

`scripts\run_gui.bat`  — inicia a GUI e, se necessário, o `dome_driver` como subprocesso
`scripts\run_driver.bat` — inicia apenas o driver (uso para debug)
`scripts\run_web_panel.bat` — inicia o painel web (acessível em http://<IP>:5000)

**Endpoints e portas relevantes**
- Driver Alpaca (quando rodando): `http://127.0.0.1:11111`
  - `/health`, `/status`, `/abrir`, `/fechar`, `/emergency_close`, `/shutdown`
- Endpoints Alpaca compatíveis usados pelo NINA: `/api/v1/dome/0/*`
- Painel web (Flask): porta 5000 (escuta `0.0.0.0`)

**O que verificar / tarefas para o handoff**
- Confirmar versão do Python e dependências (`requirements.txt`).
- Verificar se `config.json` e `devices.json` existem localmente e não foram committados.
- Testar ciclo de vida do driver: iniciar GUI → verificar driver em `127.0.0.1:11111` → fechar GUI → driver encerrado.
- Testar endpoints principais (`/health`, `/status`, `/abrir`, `/fechar`).
- Testar comunicação local com dispositivos Tuya (ping IP, conexão tinytuya usando `id`+`key`).
- Testar fallback cloud: verificar `tuya_cloud` em `config.json` e chamar APIs de teste sem expor chaves.
- Verificar `painel_local` leitura de `devices.json` e endpoints do painel.
- Testar scripts `.bat` em ambiente Windows com `.venv` ativado.

**Segurança / segredos**
- Nunca versionar credenciais: `config.json`, `devices.json` e `claude_local.md` não devem ser commitados.
- Use `claude_local.md` (local, não versionado) para armazenar chaves e credenciais que Claude deve consultar. Se o arquivo não existir, consulte `claude_local_example.md` e solicite as credenciais ao mantenedor.

**Formato esperado de `claude_local.md` (recomendações)**
- Preferir um bloco YAML ou JSON claro com chaves:
  - `tuya_cloud`: `api_key`, `api_secret`, `region`, `timezone`
  - `devices`: lista de objetos `{ name, id, ip, key, category, version }`
  - `piers`: mapeamento por `pier_id` com `device` e `role` (ex: cobertura, régua)
  - `python_env`: caminho para `.venv` (opcional)
  - `contact`: lista de responsáveis / telefones / e-mails
  - `notes`: instruções operacionais específicas do Observatório Munhoz

Veja `claude_local_example.md` na raiz para um template com placeholders.

**Checklist final para entregar (Handoff)**
1. Confirmar que `README.md` é fiel ao estado atual do código.
2. Verificar que `requirements.txt` instala corretamente no `.venv`.
3. Garantir que `scripts\run_gui.bat` e `scripts\run_web_panel.bat` iniciam serviços como esperado.
4. Testar controle real em pelo menos um pier em rede local (ou em mock se não houver hardware disponível).
5. Validar que `claude_local.md` (local) contém todas as chaves necessárias e que está no `.gitignore`.

**Observações para Claude (instrução direta para uso do Claude code)**
1. Antes de modificar código, verifique a existência de `claude_local.md` e carregue suas variáveis; se existir, combine essas configurações com `config_exemplo.json` para obter valores reais de operação.
2. Nunca escreva credenciais em arquivos versionados; se alguma operação requerer chaves inexistentes, solicite instruções ao mantenedor em vez de colocar chaves em `claude.md`.
3. Ao documentar ou modificar handlers que lidam com dispositivos, registre claramente quais `DPS` são usados (ex.: `switch_1` / DPS 1 é usado para abrir/fechar a cobertura).

---

Arquivo de referência: `README.md` para contexto operacional básico e `docs/` para documentação técnica adicional.
