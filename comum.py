"""Utilitários partilhados pelas fontes de leilões."""

import os
import re
import socket
import ssl
import tempfile
import unicodedata

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 45

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9",
}

CONCELHO = "Paredes de Coura"


class ScrapeError(RuntimeError):
    """A estrutura da fonte mudou — é preciso rever o código."""


def sessao():
    """
    Sessão com repetições. Os runners do GitHub Actions saem por IPs de
    datacenter e alguns destes sites são lentos ou recusam a primeira ligação.
    """
    s = requests.Session()
    politica = Retry(
        total=4,
        backoff_factor=3,  # 0s, 3s, 6s, 12s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adaptador = HTTPAdapter(max_retries=politica)
    s.mount("https://", adaptador)
    s.mount("http://", adaptador)
    s.headers.update(HEADERS)
    return s


SESSAO = sessao()


# OID 1.3.6.1.5.5.7.48.2 ("CA Issuers"), tal como aparece dentro do certificado.
_CA_ISSUERS = bytes.fromhex("06082B06010505073002")


def _ca_issuers(der):
    """
    Devolve o URL de onde se descarrega o certificado que assinou este, lido do
    campo AIA. Em DER, a seguir ao OID vem logo a etiqueta 0x86 (um URL), o
    comprimento num byte e o texto em ASCII — por isso dá para ler sem
    bibliotecas de criptografia.
    """
    pos = der.find(_CA_ISSUERS)
    if pos < 0:
        return None
    pos += len(_CA_ISSUERS)
    if der[pos] != 0x86 or der[pos + 1] >= 0x80:
        return None
    tamanho = der[pos + 1]
    return der[pos + 2 : pos + 2 + tamanho].decode("ascii", "replace")


def _certificado_do_servidor(anfitriao):
    """O certificado que o servidor apresenta, em DER, sem o validar."""
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE
    with socket.create_connection((anfitriao, 443), timeout=TIMEOUT) as ligacao:
        with contexto.wrap_socket(ligacao, server_hostname=anfitriao) as tls:
            return tls.getpeercert(binary_form=True)


def completar_cadeia(sessao_http, anfitriao):
    """
    Remendo para servidores que enviam só o certificado final, sem os
    intermédios — é o caso do citius.mj.pt.

    O macOS vai buscar o intermédio em falta sozinho (pelo campo AIA do
    certificado), por isso no Mac isto nunca é preciso. O Linux dos runners do
    GitHub Actions não vai, e a ligação morre com "unable to get local issuer
    certificate". Aqui seguimos a mesma pista à mão: descarregamos os
    intermédios, juntamo-los à lista de certificados de confiança do certifi e
    dizemos à sessão para usar essa lista.

    Não se perde segurança: os certificados acrescentados continuam a ter de
    encadear até uma raiz já de confiança.
    """
    caminho = os.path.join(tempfile.gettempdir(), "cadeia-%s.pem" % anfitriao)
    intermedios = []
    der = _certificado_do_servidor(anfitriao)
    for _ in range(4):
        url = _ca_issuers(der)
        if not url:
            break
        der = requests.get(url, timeout=TIMEOUT).content
        if not der.startswith(b"\x30"):  # não veio em DER — desistimos
            break
        intermedios.append(ssl.DER_cert_to_PEM_cert(der))
    if not intermedios:
        raise ScrapeError(
            "%s tem a cadeia de certificados incompleta e não foi possível "
            "completá-la pelo AIA." % anfitriao
        )
    with open(caminho, "w") as ficheiro:
        with open(certifi.where()) as base:
            ficheiro.write(base.read())
        ficheiro.writelines(intermedios)
    sessao_http.verify = caminho
    return caminho


def normalizar(texto):
    """minúsculas, sem acentos, espaços colapsados — para comparar nomes."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def chave(texto):
    """
    Normaliza uma etiqueta para comparação, sem pontuação.
    'N.º Leilão Finanças:' -> 'no leilao financas'
    (atenção: o 'º' decompõe-se em 'o' no NFKD, daí o 'no'.)
    """
    return re.sub(r"[^a-z0-9 ]", "", normalizar(texto)).strip()


def euros(valor):
    """10000.0 -> '10 000,00 €'"""
    if valor in (None, ""):
        return "?"
    try:
        formatado = "{:,.2f}".format(float(valor))
    except (TypeError, ValueError):
        return str(valor)
    # de 1,234.56 (formato inglês) para 1 234,56
    return formatado.replace(",", " ").replace(".", ",") + " €"


def area(valor):
    """25.9 -> '25,9 m²'   |   120.0 -> '120 m²'"""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if not numero:
        return None  # área 0 significa "não aplicável" (quotas, direitos, veículos)
    texto = ("%g" % numero).replace(".", ",")
    return "%s m²" % texto


def data_iso(texto):
    """'2026-08-05T11:00:00' -> '2026-08-05 11:00'"""
    if not texto:
        return "?"
    return str(texto).replace("T", " ")[:16]
