from app.modules.m1_manifest.core import SAMPLE, parse, run
def test_trap_1(): # TRAP-02, TRAP-18
    assert parse("\ufeffkey,size,etag\na,1,x\n")["rows"][0]["key"]=="a"
def test_trap_2(): assert parse("key,size,etag\na,1\n")["quarantine"][0]["reason"]=="BAD_COLUMNS"
def test_empty_file_state(): assert parse("")["state"]=="empty-file"
def test_only_header_state(): assert parse("key,size,etag\n")["state"]=="only-header"
def test_jsonl_truncated(): assert parse('{"key":"a"}\n{"key":',"jsonl")["quarantine"][0]["reason"]=="TRUNCATED"
def test_jsonl_source_line(): assert parse('{"key":"a"}',"jsonl")["rows"][0]["source_line"]==1
def test_csv_source_line(): assert parse("key,size,etag\na,1,x\n")["rows"][0]["source_line"]==2
def test_sample_accounting():
    out=run(SAMPLE); assert out["input_count"]==out["valid_count"]+out["quarantine_count"]
