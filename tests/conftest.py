# The ONLY place in tests/ that names the package -- see "About the name"
# in the README.
import openflora as pkg

import pytest


@pytest.fixture(scope="session")
def fp():
    """The package under test."""
    return pkg


@pytest.fixture(scope="session")
def dev(fp):
    """The bundled xc7z020 device model."""
    return fp.device.load_device("xc7z020")
