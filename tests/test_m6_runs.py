from app.modules.m6_runs.core import SAMPLE, csv_text, run
class Store:
    def __init__(self): self.item=None
    def record(self,d,r,v): self.item=self.item or (d,r,v); return {"run_id":self.item[1],"result":self.item[2]}
def test_csv_header(): assert csv_text(SAMPLE["rows"]).startswith("key,status,evidence")
def test_csv_has_missing(): assert "MISSING" in csv_text(SAMPLE["rows"])
def test_stable_id(): assert run({})["run_id"]==run({})["run_id"]
def test_stable_digest(): assert run({})["digest"]==run({})["digest"]
def test_trap_1(): # TRAP-16
    s=Store(); assert run({"store":s})["run_id"]==run({"store":s})["run_id"]
def test_trap_2(): assert run({})["input_count"]==2
def test_valid_count(): assert run({})["valid_count"]==1
def test_bad_count(): assert run({})["quarantine_count"]==1
