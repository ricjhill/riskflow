"""Verify all packages are importable."""


def test_domain_model_importable() -> None:
    import src.domain.model


def test_domain_service_importable() -> None:
    import src.domain.service


def test_ports_input_importable() -> None:
    import src.ports.input


def test_ports_output_importable() -> None:
    import src.ports.output


def test_adapters_http_importable() -> None:
    import src.adapters.http


def test_adapters_slm_importable() -> None:
    import src.adapters.slm


def test_adapters_storage_importable() -> None:
    import src.adapters.storage


def test_adapters_parsers_importable() -> None:
    import src.adapters.parsers


def test_entrypoint_importable() -> None:
    from src.entrypoint.main import app

    assert app.title == "RiskFlow API"
