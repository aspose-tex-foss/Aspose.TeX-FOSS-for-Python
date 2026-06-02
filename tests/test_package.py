"""Smoke tests for package installation."""


def test_version_is_string():
 """Verify that aspose_tex exposes a version string."""
 import aspose_tex

 assert isinstance(aspose_tex.__version__, str)
 assert len(aspose_tex.__version__) > 0


def test_subpackages_importable():
 """Verify all stub sub-packages can be imported."""
