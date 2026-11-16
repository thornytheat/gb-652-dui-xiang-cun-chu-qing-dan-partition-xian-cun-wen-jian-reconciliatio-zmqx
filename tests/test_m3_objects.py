from app.modules.m3_objects.core import verify, verify_all, run
def test_trap_1(): # TRAP-08, TRAP-22
    assert verify({"size":"10","etag":"x"},{"size":10,"etag":"x"})=="MATCH"
def test_trap_2(): assert verify({"size":10,"etag":"x-2"},{"size":10,"etag":"x-2"})=="MATCH"
def test_size_mismatch(): assert verify({"size":10,"etag":"x"},{"size":9,"etag":"x"})=="SIZE_MISMATCH"
def test_etag_mismatch(): assert verify({"size":10,"etag":"x"},{"size":10,"etag":"y"})=="ETAG_MISMATCH"
def test_missing(): assert verify_all([{"key":"a","size":1,"etag":"x"}],[])[0]["status"]=="MISSING"
def test_order_from_manifest(): assert [x["key"] for x in verify_all([{"key":"b","size":1,"etag":"x"},{"key":"a","size":1,"etag":"x"}],[])]==["b","a"]
def test_run_has_diff(): assert run({})["reason"]=="DIFF"
def test_counts(): assert run({})["valid_count"]+run({})["quarantine_count"]==2
