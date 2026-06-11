# Estrutura do projeto

Este documento descreve a organizacao atual do projeto Controle Roll-Off Tuya.

O objetivo e deixar claro o papel de cada arquivo antes de futuras etapas de reorganizacao, renomeacao ou empacotamento em executavel Windows.

## Estrutura atual

rolloff-tuya-control/

Arquivos principais:

- telhado_gui.py
- dome_driver.py
- servidor.py
- tuya_cloud.py
- ipv4_first.py

Configuracao:

- config_exemplo.json
- config.json nao versionado
- devices.json nao versionado, se existir

Documentacao:

- README.md
- README_USO.md
- docs/hardware_tuya_ms109.md
- docs/estrutura_projeto.md

Scripts:

- scripts/run_gui.bat
- scripts/run_driver.bat
- scripts/run_web_panel.bat

## Papel dos arquivos principais

### telhado_gui.py

Interface grafica Tkinter.

Responsabilidades:

- exibir status da cobertura;
- abrir e fechar a cobertura;
- controlar a regua inteligente;
- iniciar automaticamente o driver Alpaca quando necessario;
- encerrar o driver ao fechar, se a propria GUI tiver iniciado o driver;
- usar fallback local/cloud quando o driver nao estiver disponivel.

### dome_driver.py

Driver ASCOM Alpaca.

Responsabilidades:

- expor endpoints Alpaca para o NINA;
- expor endpoints HTTP auxiliares para a GUI;
- controlar a cobertura via Tuya local com fallback cloud;
- manter o principio de dono unico da conexao local com a cobertura;
- executar comandos de abertura e fechamento;
- fornecer endpoint de encerramento controlado via /shutdown.

### servidor.py

Painel web administrativo.

Responsabilidades:

- consultar coberturas via Tuya Cloud;
- enviar comandos via Tuya Cloud;
- evitar conexao local direta com a cobertura;
- fornecer painel para uso administrativo.

### tuya_cloud.py

Funcoes auxiliares para integracao com a API Tuya Cloud.

### ipv4_first.py

Ajuste auxiliar para priorizar IPv4.

Ajuda a evitar atrasos em redes onde a resolucao IPv6 causa lentidao ou falhas.

## Ambiente virtual

O projeto usa ambiente virtual local:

.venv/

A pasta .venv nao deve ser versionada.

As dependencias ficam registradas em:

requirements.txt

## Organizacao futura sugerida

Uma reorganizacao futura pode mover os arquivos Python para uma estrutura mais padronizada:

src/rolloff_tuya_control/

Possiveis nomes futuros:

- rolloff_gui.py
- alpaca_driver.py
- web_panel.py
- tuya_cloud.py
- cli_control.py
- ipv4_first.py

Essa reorganizacao deve ser feita em uma etapa separada, apos teste funcional da versao atual.

## Estrategia de baixo risco

A ordem recomendada e:

1. manter a versao atual funcionando;
2. documentar a arquitetura;
3. revisar .gitignore e configuracoes;
4. preparar scripts de execucao;
5. somente depois renomear arquivos ou reorganizar pastas;
6. por ultimo preparar empacotamento em executavel Windows.

Nao misturar renomeacao de arquivos, reorganizacao de imports e empacotamento em uma unica etapa.
