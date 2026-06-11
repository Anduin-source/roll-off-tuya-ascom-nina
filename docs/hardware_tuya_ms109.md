# Hardware Tuya usado na implementacao atual

Este documento registra o hardware validado na instalacao atual do Controle Roll-Off Tuya.

As informacoes abaixo sao especificas do Observatorio Munhoz, MPC X93, Pier 1. Elas explicam as decisoes tecnicas atuais, mas nao fazem parte do nome generico do projeto.

## Dispositivo da cobertura

Dispositivo validado:

```text
Novadigital MS-109
Mini Pulso Wi-Fi para garagem
OEM Tuya
Modulo CB3S
Alimentacao 100-240 V AC
Protocolo local Tuya 3.4
```

## Mapeamento DPS confirmado

```text
DPS 1  / switch_1          comando real: True=abrir, False=fechar
DPS 3  / doorcontact_state sensor fisico: False=fechada, True=aberta
DPS 4  / door_time_1       tempo de curso configurado no dispositivo
DPS 6  / door_control_1    aceito pelo firmware, mas nao aciona o motor
DPS 12 / door_state_1      alarme/estado auxiliar
```

## Decisao de comando

O projeto usa `switch_1` / DPS 1 para abrir e fechar a cobertura. O comando por `door_control_1` / DPS 6 foi observado como aceito pela API, mas ignorado fisicamente pelo firmware deste MS-109.

## Decisao de conexao local

O driver usa conexao local abre-fecha explicita: abre uma conexao para a operacao, usa e fecha ao final. Isso reduziu erros 904 observados com conexoes persistentes ociosas e evita sockets abandonados no firmware.
