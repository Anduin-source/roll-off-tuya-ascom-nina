"""
ipv4_first.py — Preferencia de IPv4 sobre IPv6 para conexoes de rede.

Contexto: Python (requests/urllib3) nao implementa 'happy eyeballs' — em redes
com IPv6 anunciado mas quebrado (ex: Starlink, radio, CGNAT), cada tentativa
IPv6 custa ~21s de timeout TCP antes de cair no IPv4. Com 3 enderecos IPv6 e
2 requisicoes HTTPS por chamada (padrao Tuya Cloud), o resultado sao ~128s por
operacao — diagnosticado no Observatorio Munhoz em 2026-06-09.

Solucao: reordenar o socket.getaddrinfo para retornar IPv4 primeiro, mantendo
IPv6 disponivel como fallback caso nao haja IPv4. Afeta somente o processo
Python em que for importado — zero impacto no sistema operacional ou em outros
programas.

Uso: importar como PRIMEIRO import em qualquer programa que faca chamadas de
rede (antes de tinytuya, requests, flask, etc):

    import ipv4_first  # deve ser o primeiro import — preferencia IPv4/IPv6

Compativel com Windows, Linux e macOS. Nao requer privilegios de administrador.
Reversivel: basta nao importar o modulo.

Historico: diagnostico completo em diagnostico_2026-06-09_ipv6_e_erro914.md
"""

import socket as _socket

_getaddrinfo_original = _socket.getaddrinfo


def _ipv4_primeiro(host, port, family=0, type=0, proto=0, flags=0):
    resultados = _getaddrinfo_original(host, port, family, type, proto, flags)
    return sorted(resultados, key=lambda r: 0 if r[0] == _socket.AF_INET else 1)


_socket.getaddrinfo = _ipv4_primeiro