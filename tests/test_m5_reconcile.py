from app.modules.m5_reconcile.core import reconcile, run
def test_trap_1(): # TRAP-14
    assert reconcile([{"key":"a","size":1,"etag":"x"}],[{"key":"a","size":2,"etag":"x"}])["conflicts"]==["a"]
def test_trap_2(): assert reconcile([{"key":"a","size":1,"etag":"x"}],[])["missing"]==["a"]
def test_orphan(): assert reconcile([],[{"key":"z","size":1,"etag":"x"}])["orphan"]==["z"]
def test_match(): assert reconcile([{"key":"a","size":1,"etag":"x"}],[{"key":"a","size":1,"etag":"x"}])["matched"]==["a"]
def test_balance(): assert reconcile([{"key":"a","size":1,"etag":"x"}],[])["balanced"] is True
def test_quarantine_kept(): assert reconcile([],[],2)["quarantine_count"]==2
def test_sample_diff(): assert run({})["reason"]=="DIFF"
def test_clean_ok(): assert run({"manifest":[],"objects":[],"quarantine":0})["reason"]=="OK"
