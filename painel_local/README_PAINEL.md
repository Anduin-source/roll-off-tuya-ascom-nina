# Painel local de coberturas

Painel web para visualizar e comandar coberturas pela rede local do observatorio, sem depender da Tuya Cloud.

## Rodar em desenvolvimento

Na raiz do projeto:

```bat
scripts\run_web_panel.bat
```

Ou diretamente:

```powershell
.\.venv\Scripts\python.exe painel_local\servidor.py
```

Depois acesse:

```text
http://127.0.0.1:5000
```

## devices.json

O painel procura `devices.json` primeiro na pasta `painel_local/`. Se nao encontrar, usa o `devices.json` da raiz do projeto. Isso permite desenvolvimento no repo e distribuicao futura como pasta/app separado.

Use `painel_local/devices_exemplo.json` como modelo.

## Build futuro

Para gerar um executavel Windows:

```bat
scripts\build_web_panel.bat
```

O pacote para o Cadu deve conter:

```text
PainelCoberturas.exe
iniciar_painel.bat
devices.json
README_CADU.txt
```

O script `scripts\build_web_panel.bat` monta automaticamente a pasta:

```text
dist\PainelCoberturasEntrega
```
