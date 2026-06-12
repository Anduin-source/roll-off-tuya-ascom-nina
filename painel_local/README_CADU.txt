PAINEL COBERTURAS - OBSERVATORIO MUNHOZ

O QUE E
Painel local para visualizar e comandar as coberturas dos piers.
Nao precisa de Python instalado.
Nao depende da Tuya Cloud para funcionar.

COMO INSTALAR
1. Copie a pasta PainelCoberturasEntrega para o computador do observatorio.
2. Deixe todos os arquivos juntos na mesma pasta:
   - PainelCoberturas.exe
   - iniciar_painel.bat
   - devices.json
   - README_CADU.txt

COMO CONFIGURAR OS PIERS
1. Abra o arquivo devices.json no Bloco de Notas.
2. Para cada cobertura, preencha:
   - name: nome que aparece no painel
   - id: Device ID Tuya
   - ip: IP local do controlador na rede do observatorio
   - key: Local Key Tuya
   - category: ckmkzq
   - version: 3.4
3. Salve o arquivo.

Exemplo:

{
  "name": "Pier 01 - Cobertura",
  "id": "DEVICE_ID_AQUI",
  "ip": "192.168.1.101",
  "key": "LOCAL_KEY_AQUI",
  "category": "ckmkzq",
  "version": 3.4
}

COMO RODAR
1. Clique duas vezes em iniciar_painel.bat.
2. O navegador deve abrir em:
   http://127.0.0.1:5000
3. Para acessar de outro computador na mesma rede, use:
   http://IP-DO-COMPUTADOR-DO-PAINEL:5000

SE O WINDOWS PERGUNTAR SOBRE FIREWALL
Clique em Permitir acesso para rede privada/local.

COMO PARAR
Feche a janela do PainelCoberturas.exe.

PROBLEMAS COMUNS

Se um pier aparece OFFLINE:
- verifique se o IP no devices.json esta correto;
- verifique se a Local Key esta correta;
- verifique se o controlador esta ligado e na mesma rede.

Se o painel nao abre em outro computador:
- confira o IP do computador que esta rodando o painel;
- confira se o firewall liberou a porta 5000;
- confirme que os computadores estao na mesma rede.
