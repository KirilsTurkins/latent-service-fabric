"""One-shot test formatting correction; removed after application."""
from pathlib import Path

path = Path('crates/latent-admission/src/tests/stress.rs')
source = path.read_text()
assert source.count('.maximum_concurrent_activations = 3\n') == 2
assert source.count('.maximum_queued_activations = 3\n') == 1
source = source.replace('.maximum_concurrent_activations = 3\n', '.maximum_concurrent_activations = 3;\n')
source = source.replace('.maximum_queued_activations = 3\n', '.maximum_queued_activations = 3;\n')
path.write_text(source)
Path(__file__).unlink()
