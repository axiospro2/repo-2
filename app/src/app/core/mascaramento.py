"""Mascaramento de dados pessoais (LGPD) antes de logar.

`documento` (CPF/CNPJ/CGI) é dado pessoal — nunca deve ir para o Datadog em
texto puro. Mantemos só os últimos 4 dígitos, o suficiente para correlacionar
uma ocorrência de log com um ticket/chamado sem expor o documento inteiro.
"""

from __future__ import annotations

from typing import Optional

_DIGITOS_VISIVEIS = 4


def mascarar_documento(documento: Optional[str]) -> str:
    """Mascara um CPF/CNPJ/CGI para uso em logs, mantendo só os últimos 4 dígitos.

    Documentos com 4 caracteres ou menos são mascarados por inteiro: não há
    dígitos "extras" a esconder além dos últimos 4, e a alternativa (Documento
    curto ⇒ aparece sem máscara) exporia dado pessoal em texto puro no Datadog.
    """
    if not documento:
        return ""
    if len(documento) <= _DIGITOS_VISIVEIS:
        return "*" * len(documento)
    visiveis = documento[-_DIGITOS_VISIVEIS:]
    ocultos = "*" * (len(documento) - _DIGITOS_VISIVEIS)
    return f"{ocultos}{visiveis}"
