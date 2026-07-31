from app.core.mascaramento import mascarar_documento


def test_mascara_documento_none_retorna_vazio():
    assert mascarar_documento(None) == ""


def test_mascara_documento_vazio_retorna_vazio():
    assert mascarar_documento("") == ""


def test_mascara_documento_cnpj_mantem_4_ultimos_digitos():
    assert mascarar_documento("12345678000199") == "**********0199"


def test_mascara_documento_curto_mascara_tudo():
    assert mascarar_documento("123") == "***"


def test_mascara_documento_exatamente_4_digitos_mascara_tudo():
    assert mascarar_documento("1234") == "****"


def test_mascara_documento_5_digitos_mantem_so_os_4_ultimos():
    assert mascarar_documento("12345") == "*2345"
