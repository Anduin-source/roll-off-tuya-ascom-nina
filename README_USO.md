# Controle Roll-Off Tuya - Uso rapido

## Uso normal

Abra a interface grafica:

```bat
scripts\run_gui.bat
```

A GUI inicia o driver Alpaca automaticamente se ele ainda nao estiver rodando.
Ao fechar a GUI, ela encerra somente o driver que ela propria iniciou.

## Sessao com NINA

1. Abra `scripts\run_gui.bat`.
2. Aguarde o status da cobertura aparecer na GUI.
3. Abra o NINA.
4. Conecte o Dome ao driver `Tuya Dome`.
5. Ao terminar a sessao, feche o NINA.
6. Feche a GUI.

## Uso manual do driver

Para teste ou debug, rode:

```bat
scripts\run_driver.bat
```

Se o driver foi aberto manualmente, a GUI pode usa-lo, mas nao o encerra ao fechar.

## Painel web

Para abrir o painel administrativo:

```bat
scripts\run_web_panel.bat
```

Depois acesse:

```text
http://<IP-do-computador>:5000
```

O painel usa `devices.json` e comunica com as coberturas pela rede local do observatorio, sem Tuya Cloud.

Para adicionar um novo pier manualmente, edite `devices.json` e inclua um item com `name`, `id`, `ip`, `key`, `category: "ckmkzq"` e `version`. Use `painel_local\devices_exemplo.json` como modelo. A versao Tuya deve ser conferida por dispositivo; use `3.4` para dispositivos que responderem em `3.4` e `3.5` para dispositivos que responderem em `3.5`.

## Arquivos locais

O arquivo `config.json` deve existir na raiz do projeto, mas nao deve ser enviado ao GitHub.
Use `config_exemplo.json` como modelo.
