const state={busy:false};
document.querySelectorAll("[data-endpoint]").forEach(btn=>btn.addEventListener("click",async()=>{
  if(state.busy)return; state.busy=true; const out=btn.parentElement.querySelector(".result"); out.textContent="运行中";
  const isGet=btn.dataset.endpoint.includes("export")||btn.dataset.endpoint.includes("/api/runs");
  const body={};
  if(btn.dataset.batch)body.batch_id=btn.dataset.batch;
  if(btn.dataset.snapshot)body.snapshot_id=btn.dataset.snapshot;
  if(btn.dataset.collection)body.collection_id=btn.dataset.collection;
  if(btn.dataset.text)body.text=btn.dataset.text;
  if(btn.dataset.endpoint.includes("/api/objects/verify")&&btn.dataset.stream)body.objects=JSON.parse(btn.dataset.stream);
  try{const res=await fetch(btn.dataset.endpoint,{method:isGet?"GET":"POST",headers:{"content-type":"application/json"},body:isGet?null:JSON.stringify(body)});out.textContent=await res.text()}catch(e){out.textContent="请求失败，请重试"}finally{state.busy=false}
}));
document.querySelector("#refresh")?.addEventListener("click",()=>location.reload());
