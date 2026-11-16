from app.modules.m2_paths.core import normalize, partition_values, run
def test_trap_1(): # TRAP-05, TRAP-21
    assert normalize("lake/dt=2026/hour=01/000123").endswith("000123")
def test_trap_2(): assert normalize("/lake//a%20b")=="lake/a b"
def test_backslash(): assert normalize("lake\\dt=1\\a")=="lake/dt=1/a"
def test_partition_sort(): assert normalize("lake/hour=01/dt=2026/a")=="lake/dt=2026/hour=01/a"
def test_partition_values(): assert partition_values("lake/dt=2026/hour=01/a")=={"dt":"2026","hour":"01"}
def test_success_marker(): assert normalize("lake/_SUCCESS")=="lake/_SUCCESS"
def test_stable(): assert normalize(normalize("/lake//a%20b"))=="lake/a b"
def test_run_count(): assert run({})["valid_count"]==3
