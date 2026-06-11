"""
teste_conexao.py — Compara dois modos de conexao local com o MS-109,
contando erros (904, 914, timeouts) de cada um.

INTERVALO DE 30s: replica a condicao real do driver (poll a cada 30s), que e
onde o erro 904 efetivamente aparece. Um teste anterior com 10s deu 100% em
ambos os modos, mas NAO reproduziu a falha — logo nao foi conclusivo. Este
teste usa o mesmo intervalo do driver para reproduzir a condicao de falha.

Objetivo: decidir empiricamente, para ESTE dispositivo, se o driver deve usar:
  A) Conexao PERSISTENTE (socketPersistent True) — mantida aberta entre leituras
  B) ABRE-FECHA EXPLICITO   (socketPersistent False) — aberta e fechada a cada leitura

Matriz de decisao:
  persistente da 904, abre-fecha nao  -> mudar driver para abre-fecha
  ambos 0 erro                        -> 904 vem de concorrencia interna no
                                         driver (poll + ler_status paralelos),
                                         nao do modo de conexao
  ambos dao 904                       -> suspeitar Wi-Fi / firmware MS-109
  persistente 0 erro                  -> manter persistente

NAO envia nenhum comando ao telhado — somente leituras de status (read-only).

IMPORTANTE: rodar com o dome_driver.py PARADO (Ctrl+C), senao havera dois
clientes competindo pelo socket e o teste fica contaminado.

Uso:
    python scripts/teste_conexao.py        # 20 leituras por modo (~20 min total)
    python scripts/teste_conexao.py 30     # 30 leituras por modo (~30 min total)
"""

import json
import os
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import ipv4_first  # IPv4 preferencial
import tinytuya

BASE_DIR = PROJECT_DIR
cfg = json.load(open(os.path.join(BASE_DIR, 'config.json'), encoding='utf-8'))

COB_ID  = cfg['cobertura']['id']
COB_IP  = cfg['cobertura']['ip']
COB_KEY = cfg['cobertura']['key']
VERSION = 3.4

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
INTERVALO = 30  # segundos entre leituras — REPLICA o poll real do driver,
                # onde o erro 904 efetivamente aparece (nao 10s do teste anterior)


def classificar(resultado):
    """Retorna ('ok', None) ou ('erro', codigo)."""
    if isinstance(resultado, dict):
        if 'dps' in resultado:
            return 'ok', None
        if 'Err' in resultado:
            return 'erro', resultado['Err']
        return 'erro', f'sem_dps:{resultado}'
    return 'erro', f'tipo:{type(resultado).__name__}'


def teste_persistente(n):
    print(f'\n=== MODO A: PERSISTENTE ({n} leituras, intervalo {INTERVALO}s) ===')
    d = tinytuya.Device(dev_id=COB_ID, address=COB_IP, local_key=COB_KEY, version=VERSION)
    d.set_socketPersistent(True)
    d.set_socketTimeout(3)
    erros = {}
    ok = 0
    latencias = []
    for i in range(n):
        t = time.time()
        try:
            r = d.status()
        except Exception as e:
            r = {'Err': f'exc:{type(e).__name__}'}
        lat = time.time() - t
        latencias.append(lat)
        estado, cod = classificar(r)
        if estado == 'ok':
            ok += 1
            marca = 'OK '
        else:
            erros[str(cod)] = erros.get(str(cod), 0) + 1
            marca = f'ERR {cod}'
        print(f'  {i+1:2d}/{n}  {marca:12s} {lat:.2f}s')
        time.sleep(INTERVALO)
    try:
        d.close()
    except Exception:
        pass
    return ok, erros, latencias


def teste_abre_fecha(n):
    print(f'\n=== MODO B: ABRE-FECHA EXPLICITO ({n} leituras, intervalo {INTERVALO}s) ===')
    erros = {}
    ok = 0
    latencias = []
    for i in range(n):
        t = time.time()
        d = tinytuya.Device(dev_id=COB_ID, address=COB_IP, local_key=COB_KEY, version=VERSION)
        d.set_socketPersistent(False)
        d.set_socketTimeout(3)
        try:
            r = d.status()
        except Exception as e:
            r = {'Err': f'exc:{type(e).__name__}'}
        finally:
            try:
                d.close()   # fechamento EXPLICITO — a diferenca crucial
            except Exception:
                pass
        lat = time.time() - t
        latencias.append(lat)
        estado, cod = classificar(r)
        if estado == 'ok':
            ok += 1
            marca = 'OK '
        else:
            erros[str(cod)] = erros.get(str(cod), 0) + 1
            marca = f'ERR {cod}'
        print(f'  {i+1:2d}/{n}  {marca:12s} {lat:.2f}s')
        time.sleep(INTERVALO)
    return ok, erros, latencias


def resumo(nome, ok, erros, latencias, n):
    print(f'\n--- {nome} ---')
    print(f'  Sucessos: {ok}/{n} ({100*ok/n:.0f}%)')
    total_erros = sum(erros.values())
    print(f'  Erros:    {total_erros}/{n} ({100*total_erros/n:.0f}%)')
    if erros:
        for cod, qtd in sorted(erros.items(), key=lambda x: -x[1]):
            print(f'      {cod}: {qtd}')
    if latencias:
        media = sum(latencias) / len(latencias)
        print(f'  Latencia media: {media:.2f}s (min {min(latencias):.2f}, max {max(latencias):.2f})')


if __name__ == '__main__':
    print('Teste comparativo de modos de conexao local — MS-109')
    print('CERTIFIQUE-SE de que o dome_driver.py esta PARADO.')
    print(f'Dispositivo: {COB_ID} @ {COB_IP}')

    okA, errosA, latA = teste_persistente(N)
    print('\n  ...pausa de 15s entre os modos...')
    time.sleep(15)
    okB, errosB, latB = teste_abre_fecha(N)

    print('\n' + '=' * 50)
    print('RESULTADO COMPARATIVO')
    print('=' * 50)
    resumo('MODO A: PERSISTENTE', okA, errosA, latA, N)
    resumo('MODO B: ABRE-FECHA EXPLICITO', okB, errosB, latB, N)

    print('\n--- VEREDITO ---')
    taxa_A = 100 * okA / N
    taxa_B = 100 * okB / N
    if taxa_B > taxa_A + 5:
        print(f'  MODO B (abre-fecha) e melhor: {taxa_B:.0f}% vs {taxa_A:.0f}%')
    elif taxa_A > taxa_B + 5:
        print(f'  MODO A (persistente) e melhor: {taxa_A:.0f}% vs {taxa_B:.0f}%')
    else:
        print(f'  Empate tecnico: A={taxa_A:.0f}% B={taxa_B:.0f}% '
              f'(decidir por latencia/simplicidade)')
