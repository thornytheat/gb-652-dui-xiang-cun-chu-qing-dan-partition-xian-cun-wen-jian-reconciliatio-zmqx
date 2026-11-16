from app.modules.m4_partitions.core import classify, run
def test_trap_1(): # TRAP-09, TRAP-23
    assert classify([],[])["present"]==[]
def test_trap_2(): assert classify(["hour=01/a","hour=01/b"],["01"])["duplicates"]==["01"]
def test_empty_marker(): assert classify(["hour=03/_EMPTY"],["03"])["empty"]==["03"]
def test_missing_hour(): assert classify(["hour=00/a"],["00","01"])["missing"]==["01"]
def test_unknown_without_hour(): assert classify(["a"],["00"])["present"]==[]
def test_present_sorted(): assert classify(["hour=02/a","hour=01/a"],[])["present"]==["01","02"]
def test_run_gap(): assert run({})["reason"]=="GAP"
def test_run_counts(): assert run({})["input_count"]==3
