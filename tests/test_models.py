import io
import tarfile

from utter.models import (
    CATALOGUE,
    DEFAULT_MODEL_ID,
    ModelSpec,
    find_spec,
    install_model,
    is_installed,
    remove_model,
)


def test_catalogue_is_consistent():
    ids = [spec.id for spec in CATALOGUE]
    assert len(ids) == len(set(ids))
    assert find_spec(DEFAULT_MODEL_ID) is CATALOGUE[0]
    for spec in CATALOGUE:
        assert spec.kind in ("transducer", "whisper", "streaming")
        needed = {"encoder", "decoder", "tokens"} | (
            set() if spec.kind == "whisper" else {"joiner"}
        )
        assert spec.is_streaming == (spec.kind == "streaming")
        assert set(spec.files) == needed
        assert spec.download_url.endswith(f"{spec.dirname}.tar.bz2")


def _make_archive(path, dirname, names):
    with tarfile.open(path, "w:bz2") as tar:
        for name in names:
            data = b"x" * 10
            info = tarfile.TarInfo(f"{dirname}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_install_and_remove(tmp_path):
    archive = tmp_path / "m.tar.bz2"
    _make_archive(archive, "model-dir", ["enc.onnx", "dec.onnx", "tok.txt"])
    spec = ModelSpec(
        id="t",
        name="T",
        summary="",
        kind="whisper",
        dirname="model-dir",
        files={"encoder": "enc.onnx", "decoder": "dec.onnx", "tokens": "tok.txt"},
        size_mb=1,
        languages="",
        url=archive.as_uri(),
    )
    root = tmp_path / "models"
    phases = []
    assert not is_installed(root, spec)
    install_model(root, spec, lambda phase, fraction: phases.append((phase, fraction)))
    assert is_installed(root, spec)
    assert phases[0][0] == "downloading" and phases[-1] == ("extracting", 1.0)
    assert not (root / "model-dir.tar.bz2.part").exists()
    remove_model(root, spec)
    assert not is_installed(root, spec)
