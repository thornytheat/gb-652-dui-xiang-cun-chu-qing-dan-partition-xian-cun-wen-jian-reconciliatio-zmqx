from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
PAGES = [('/manifest', 'm1_manifest.html', '清单采信'), ('/paths', 'm2_paths.html', '路径契约'), ('/objects', 'm3_objects.html', '对象核验'), ('/partitions', 'm4_partitions.html', '分区判定'), ('/reconcile', 'm5_reconcile.html', '差异对账'), ('/runs', 'm6_runs.html', '批次导出')]
