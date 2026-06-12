CONTROLE DO TELHADO - GUI + DRIVER NINA

O QUE E
Pacote Windows para operar a cobertura pelo computador local.
Inclui:
- TelhadoGUI.exe: interface grafica
- dome_driver.exe: driver Alpaca usado pelo NINA

NAO PRECISA DE PYTHON INSTALADO.

COMO INSTALAR
1. Copie a pasta TelhadoControleEntrega para o computador que controla o pier.
2. Mantenha todos os arquivos juntos na mesma pasta:
   - TelhadoGUI.exe
   - dome_driver.exe
   - iniciar_telhado_gui.bat
   - config_exemplo.json
   - README_TELHADO_GUI.txt

COMO CONFIGURAR
1. Copie config_exemplo.json.
2. Renomeie a copia para config.json.
3. Abra config.json no Bloco de Notas.
4. Preencha os dados da cobertura, regua e Tuya Cloud.
5. Salve.

COMO RODAR
1. Clique duas vezes em iniciar_telhado_gui.bat.
2. A GUI abre.
3. A GUI inicia o dome_driver.exe automaticamente se ele ainda nao estiver rodando.
4. Ao fechar a GUI, ela encerra apenas o driver que ela mesma iniciou.

COMO USAR COM NINA
1. Abra a GUI.
2. Aguarde o status da cobertura.
3. Abra o NINA.
4. Conecte o Dome no driver Alpaca:
   Pier 1 Tuya Dome @ 127.0.0.1
5. Ao terminar, feche o NINA.
6. Feche a GUI.

ARQUIVOS IMPORTANTES
- config.json: credenciais e configuracao local. Nao compartilhar publicamente.
- dome_driver.log: log do driver, criado automaticamente se houver uso.

PROBLEMAS COMUNS

Se a GUI nao abre:
- verifique se existe config.json na mesma pasta.

Se o NINA nao encontra o Dome:
- abra a GUI primeiro;
- confirme que o driver iniciou;
- confirme que nao ha outro processo antigo usando a porta 11111.

Se aparecer erro de rede/dispositivo:
- confira IP local e local key no config.json;
- confirme que o computador esta na mesma rede do dispositivo.
