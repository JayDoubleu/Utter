import io
import tarfile

from utter.models import (
    CATALOGUE,
    DEFAULT_MODEL_ID,
    LANGUAGES,
    ModelSpec,
    effective_language,
    find_spec,
    install_model,
    is_installed,
    language_choices,
    recognizer_language,
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


def test_language_codes_are_unique():
    codes = [code for code, _name in LANGUAGES]
    assert len(codes) == len(set(codes))
    assert codes[0] == "auto"


def test_language_choices_follow_the_model():
    nemotron = find_spec("nemotron-3.5-streaming")
    whisper = find_spec("whisper-small")
    nemotron_codes = [code for code, _name in language_choices(nemotron)]
    whisper_codes = [code for code, _name in language_choices(whisper)]
    assert {"auto", "en", "en-GB", "pt-BR"} <= set(nemotron_codes)
    assert "el" not in nemotron_codes
    assert "en-GB" not in whisper_codes and "el" in whisper_codes
    assert language_choices(find_spec("parakeet-tdt-0.6b-v3")) == ()
    assert language_choices(find_spec("whisper-base.en")) == ()


def test_recognizer_language():
    nemotron = find_spec("nemotron-3.5-streaming")
    whisper = find_spec("whisper-small")
    assert recognizer_language(nemotron, "en-GB") == "en-GB"
    assert recognizer_language(nemotron, "auto") == "auto"
    assert recognizer_language(nemotron, "el") == "auto"
    assert recognizer_language(whisper, "auto") == ""
    assert recognizer_language(whisper, "en-GB") == "en"
    assert recognizer_language(whisper, "nb") == "no"
    assert recognizer_language(whisper, "xx") == ""
    assert recognizer_language(find_spec("whisper-base.en"), "de") == "en"
    assert effective_language(whisper, "pt-BR") == "pt"
