"""Smoke test: the package is installed and importable."""

import t2sql


def test_package_has_version():
    assert t2sql.__version__ == "0.1.0"


def test_subpackages_import():
    # These folders are empty placeholders today; importing them proves the layout is wired up.
    import t2sql.core
    import t2sql.dialects
    import t2sql.generation
    import t2sql.graph
    import t2sql.retrieval
    import t2sql.validation

    assert all(
        m is not None
        for m in (
            t2sql.core,
            t2sql.dialects,
            t2sql.generation,
            t2sql.graph,
            t2sql.retrieval,
            t2sql.validation,
        )
    )
