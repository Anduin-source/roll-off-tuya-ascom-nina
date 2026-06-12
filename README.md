# Controle Roll-Off Tuya

Sistema de controle remoto para coberturas roll-off de observatório usando dispositivos Tuya.

Implementação atual: Observatório Munhoz — MPC X93 — Pier 1.

O projeto controla:

* cobertura motorizada roll-off;
* régua inteligente Tuya;
* driver ASCOM Alpaca para integração com o NINA;
* painel web administrativo para múltiplas coberturas;
* fallback local/cloud conforme disponibilidade da rede.

---

## Visão geral

O sistema foi desenhado com foco em simplicidade operacional e segurança.

No uso normal, o operador abre a interface gráfica, e ela própria inicia o driver Alpaca necessário para o NINA. Ao fechar a interface, o driver iniciado por ela também é encerrado de forma controlada.

Fluxo típico:

```text
Abrir GUI
↓
GUI inicia o driver Alpaca
↓
NINA conecta ao driver
↓
Sessão de astrofoto
↓
Fechar NINA
↓
Fechar GUI
↓
GUI encerra o driver que iniciou
```

---

## Componentes principais

| Arquivo                     | Função                                                                    |
| --------------------------- | ------------------------------------------------------------------------- |
| `telhado_gui.py`            | Interface gráfica Tkinter para controle da cobertura e régua              |
| `dome_driver.py`            | Driver ASCOM Alpaca para integração com NINA                              |
| `painel_local\servidor.py`  | Painel web Flask local para visualização/controle administrativo das coberturas |
| `servidor.py`               | Atalho legado para iniciar o painel local                                 |
| `tuya_cloud.py`             | Funções auxiliares para API Tuya Cloud                                    |
| `ipv4_first.py`             | Preferência IPv4 para evitar atrasos em redes com IPv6 problemático       |
| `config_exemplo.json`       | Modelo de configuração local                                              |
| `requirements.txt`          | Dependências Python do projeto                                            |
| `scripts\run_gui.bat`       | Inicia a interface gráfica usando o ambiente virtual                      |
| `scripts\run_driver.bat`    | Inicia manualmente o driver Alpaca                                        |
| `scripts\run_web_panel.bat` | Inicia o painel web administrativo                                        |
| `scripts\build_web_panel.bat` | Gera executável Windows do painel local com PyInstaller                  |
| `scripts\build_telhado_gui_driver.bat` | Gera executáveis Windows da GUI e do driver Alpaca            |

---

## Arquitetura de controle da cobertura

A cobertura usa uma cascata de controle:

```text
1. DRIVER
   Se o dome_driver.py estiver rodando, a GUI fala com ele via HTTP local.

2. LOCAL
   Se o driver estiver ausente, a GUI pode falar diretamente com o dispositivo via tinytuya local.

3. CLOUD
   Se o caminho local falhar, a GUI usa a API Tuya Cloud.
```

Quando o driver está vivo, a GUI **não cria conexão local direta** com a cobertura. Ela fala com o driver por HTTP. Isso preserva o princípio de dono único do caminho local.

---

## Driver Alpaca

O `dome_driver.py` expõe um driver ASCOM Alpaca na porta:

```text
http://127.0.0.1:11111
```

Principais endpoints próprios:

```text
GET  /health
GET  /status
POST /abrir
POST /fechar
POST /emergency_close
POST /shutdown
```

Endpoints Alpaca usados pelo NINA:

```text
/api/v1/dome/0/connected
/api/v1/dome/0/shutterstatus
/api/v1/dome/0/openshutter
/api/v1/dome/0/closeshutter
/api/v1/dome/0/slewing
/api/v1/dome/0/ismoving
```

No uso normal, o usuário não precisa iniciar o driver manualmente. A GUI inicia o driver automaticamente ao abrir.

---

## Ciclo de vida do driver

A GUI gerencia o ciclo de vida do driver:

1. Ao abrir, testa se já existe driver vivo em `127.0.0.1:11111`.
2. Se já existe, usa esse driver e não o encerra ao fechar.
3. Se não existe, inicia o driver como subprocesso.
4. Ao fechar, encerra somente o driver que ela mesma iniciou.
5. O encerramento é feito por `POST /shutdown`.
6. Se o driver não responder, a GUI usa `terminate()` como fallback.

Isso evita processos Python escondidos em segundo plano e torna o estado operacional claro: abrir a GUI liga o controle local do telhado; fechar a GUI desliga o controle local que ela iniciou.

---

## Comandos da cobertura

Para o dispositivo atualmente usado, o comando real ocorre via:

```text
DPS 1 / switch_1
True  = abrir
False = fechar
```

O comando via `door_control_1` / DPS 6 é aceito pelo firmware, mas não movimenta fisicamente a cobertura neste hardware. Portanto, o projeto usa `switch_1` / DPS 1 para comandos.

O status físico da cobertura é lido por:

```text
DPS 3 / doorcontact_state
False = fechada
True  = aberta
```

Observação: o modelo específico de hardware, firmware e mapeamento DPS deve ser documentado, mas não faz parte do nome do projeto.

---

## Estratégia de conexão local

A conexão local com a cobertura usa o padrão:

```text
abrir conexão
usar
fechar explicitamente
```

Ou seja, cada operação local cria uma conexão nova e fecha explicitamente ao final.

Motivo: testes comparativos mostraram que conexões persistentes ociosas por aproximadamente 30 segundos podiam gerar erros 904 no dispositivo. O modo abre-fecha explícito eliminou esse problema nos testes realizados.

Esse padrão também evita sessões locais abandonadas.

---

## Régua inteligente

A régua inteligente Tuya é um dispositivo separado da cobertura.

Ela continua sendo controlada diretamente pela GUI via tinytuya local, com fallback cloud. Como é outro dispositivo e não é crítico para o fechamento da cobertura, ela não usa o driver Alpaca.

---

## Painel web administrativo

O painel `painel_local\servidor.py` é independente da GUI e do driver.

Ele foi pensado para uso dentro da rede local do observatório. O painel lê as coberturas do `devices.json` gerado pelo tinytuya e consulta/comanda cada dispositivo diretamente pela LAN, sem depender da Tuya Cloud.

Para iniciar:

```bat
scripts\run_web_panel.bat
```

Depois acesse:

```text
http://<IP-do-computador>:5000
```

O servidor escuta em `0.0.0.0`, então outros computadores da mesma rede podem acessar pelo IP do computador que está rodando o painel.

### Cadastro manual de piers

O painel local lê as coberturas do arquivo `devices.json`. Para adicionar um novo pier sem rodar o wizard do tinytuya, copie `painel_local\devices_exemplo.json` para `devices.json` e preencha um item por cobertura:

```json
{
  "name": "Pier 01 - Nome Cobertura",
  "id": "DEVICE_ID_DA_COBERTURA",
  "ip": "192.168.1.101",
  "key": "LOCAL_KEY_DA_COBERTURA",
  "category": "ckmkzq",
  "version": 3.4
}
```

O painel mostra apenas dispositivos com `category` igual a `ckmkzq`, que é a categoria Tuya observada para coberturas/garagens. Isso evita que réguas e tomadas apareçam por engano no painel.

---

## Pré-requisitos de desenvolvimento

Para desenvolvimento, é necessário Python instalado.

Versão recomendada:

```text
Python 3.10 ou superior
```

O projeto deve ser usado dentro de um ambiente virtual `.venv`.

---

## Instalação para desenvolvimento

Clone o repositório:

```powershell
cd C:\Projetos
git clone https://github.com/Anduin-source/roll-off-tuya-ascom-nina.git rolloff-tuya-control
cd C:\Projetos\rolloff-tuya-control
```

Crie o ambiente virtual:

```powershell
python -m venv .venv
```

Ative o ambiente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear a ativação:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Depois ative novamente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## Configuração

Copie o arquivo de exemplo:

```powershell
copy config_exemplo.json config.json
```

Edite o `config.json` com os dados dos seus dispositivos Tuya:

```json
{
  "cobertura": {
    "id":  "ID_DO_DISPOSITIVO",
    "ip":  "IP_LOCAL_DO_DISPOSITIVO",
    "key": "LOCAL_KEY_DO_DISPOSITIVO"
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
    "region":     "us",
    "api_key":    "ACCESS_ID_DA_TUYA",
    "api_secret": "ACCESS_SECRET_DA_TUYA",
    "timezone":   "America/Sao_Paulo",
    "timer_category": "schedule"
  },
  "agendamento": {
    "abrir":  "",
    "fechar": "05:00"
  }
}
```

O arquivo `config.json` contém credenciais e não deve ser enviado ao GitHub.

Também não devem ser versionados:

```text
config.json
devices.json
.venv/
logs/
build/
dist/
```

---

## Como usar

### Interface gráfica

Uso normal:

```bat
scripts\run_gui.bat
```

A GUI sobe automaticamente o driver Alpaca se ele ainda não estiver rodando.

### Driver Alpaca manual

Use somente para teste/debug:

```bat
scripts\run_driver.bat
```

### Painel web

```bat
scripts\run_web_panel.bat
```

Para preparar um executável Windows do painel local no futuro:

```bat
scripts\build_web_panel.bat
```

---

## Sequência recomendada para sessão com NINA

1. Abrir a GUI com `scripts\run_gui.bat`.
2. Confirmar que o status da cobertura mostra `[driver]`.
3. Abrir o NINA.
4. Conectar o Dome no NINA.
5. Rodar a sessão.
6. Ao finalizar, fechar o NINA.
7. Fechar a GUI.

Ao fechar a GUI, o driver que ela iniciou é encerrado automaticamente.

---

## Observações de segurança

* O NINA só consegue controlar a cobertura enquanto o driver Alpaca estiver rodando.
* No uso normal, a GUI inicia o driver antes do NINA.
* Se a GUI for fechada, o driver iniciado por ela também será encerrado.
* A proteção independente final deve ser feita fora do PC, por exemplo:

  * timer Tuya/cloud configurado para fechar de madrugada;
  * futuro sensor de chuva cabeado ou relé independente.
* Abertura é tratada de forma conservadora.
* Fechamento deve ser sempre a ação prioritária em caso de insegurança.

---

## Testes recomendados

Antes de uso operacional desassistido:

1. Testar status local da cobertura.
2. Testar abertura visualmente.
3. Testar fechamento visualmente.
4. Confirmar que o comando de fechamento é idempotente.
5. Rodar GUI + driver + NINA por 8 a 12 horas.
6. Confirmar ausência de processos Python órfãos após fechar a GUI.
7. Confirmar ausência de erros 904/914 recorrentes no log.
8. Confirmar que o timer Tuya/cloud de fechamento está ativo.

---

## Desenvolvimento

Com `.venv` ativado:

```powershell
python telhado_gui.py
```

ou:

```powershell
python dome_driver.py
```

Para atualizar dependências no `requirements.txt`:

```powershell
pip freeze > requirements.txt
```

---

## Futuro empacotamento Windows

O projeto pode ser distribuído como executáveis Windows usando PyInstaller.

Para gerar o pacote da GUI + driver:

```bat
scripts\build_telhado_gui_driver.bat
```

O pacote gerado fica em:

```text
dist\TelhadoControleEntrega
```

Conteúdo esperado:

```text
TelhadoGUI.exe
dome_driver.exe
iniciar_telhado_gui.bat
config_exemplo.json
README_TELHADO_GUI.txt
```

O `config.json` deve continuar externo ao executável.

---

## Autor

Desenvolvido por André Brossel — Observatório Munhoz — MPC X93.

---

## Licença

MIT License — sinta-se livre para usar, modificar e distribuir, mantendo os créditos ao autor original.

---

## Documentacao complementar

Documentos tecnicos do projeto:

- `README_USO.md` - guia rapido de uso operacional.
- `docs/hardware_tuya_ms109.md` - hardware Tuya validado na instalacao atual.
- `docs/estrutura_projeto.md` - estrutura atual do projeto e plano de organizacao futura.
