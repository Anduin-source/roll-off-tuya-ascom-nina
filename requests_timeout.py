"""Timeout padrao para chamadas HTTP feitas pelo TinyTuya Cloud.

TinyTuya 1.18.1 chama ``requests.get/post`` sem informar timeout. Uma conexao
interrompida pode, portanto, bloquear para sempre a thread de polling do
driver. Este modulo instala um wrapper idempotente no ``requests`` somente no
processo atual.
"""

import requests

CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 12


def instalar():
    request_atual = requests.sessions.Session.request
    if getattr(request_atual, '_tuya_timeout_instalado', False):
        return

    request_original = request_atual

    def request_com_timeout(self, method, url, **kwargs):
        kwargs.setdefault('timeout', (CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
        return request_original(self, method, url, **kwargs)

    request_com_timeout._tuya_timeout_instalado = True
    requests.sessions.Session.request = request_com_timeout


instalar()
