/* Import existing creative work through a frozen preview. No generation side effects. */
async function openDramaImport(){
 const dialog=document.createElement('dialog');dialog.className='form-sheet';dialog.setAttribute('aria-label','导入短剧项目');
 dialog.innerHTML=`<form method="dialog"><header class="sheet-heading"><h2>导入短剧项目</h2><button type="button" class="icon-button" aria-label="关闭导入">×</button></header><section class="sheet-body"><label>短剧项目文件<input id="drama-package" type="file" accept=".json,application/json"></label><p>先检查剧集、角色和镜头，再作为独立作品导入。</p><div id="drama-preview" aria-live="polite"></div><label id="drama-risk-label" hidden><input type="checkbox" id="drama-risk-ack">保留问题标记导入，稍后逐镜确认</label></section><div class="actions"><button value="cancel">取消</button><button type="button" id="drama-confirm" class="primary" disabled>导入为新作品</button></div></form>`;
 let preview=null,loading=false,version=0;const input=dialog.querySelector('#drama-package'),confirm=dialog.querySelector('#drama-confirm'),host=dialog.querySelector('#drama-preview'),ack=dialog.querySelector('#drama-risk-ack');
 const ready=()=>{confirm.disabled=loading||!preview||(preview.warnings.length>0&&!ack.checked)};
 dialog.querySelector('[aria-label="关闭导入"]').onclick=()=>dialog.close();ack.onchange=ready;
 input.onchange=async()=>{const current=++version;preview=null;ack.checked=false;loading=true;ready();host.textContent='正在检查项目…';dialog.querySelector('#drama-risk-label').hidden=true;
  try{const file=input.files[0];if(!file){host.textContent='';return}if(file.size>1800000)throw Error('项目文件过大');const bundle=JSON.parse(await file.text());const result=await api('/api/import/drama/preview',{bundle});if(current!==version||!dialog.isConnected)return;preview=result;
   const s=result.summary;host.innerHTML=`<h3>${esc(s.title)}</h3><p>${s.episodes} 集 · ${s.shots} 镜 · ${s.assets} 项资产 · ${s.seconds} 秒</p><p>角色造型、逐句对白、构图、声音和连续性设定随镜头保留。${s.missing_reference_assets.length} 项资产尚无参考图片。</p><details><summary>检查 ${result.warnings.length} 项待复核问题</summary><ul>${result.warnings.map(w=>`<li>${esc(w.shot_id)} · ${esc(w.message)}</li>`).join('')||'<li>未发现结构问题</li>'}</ul></details><details><summary>字段与来源</summary><ul>${Object.entries(result.mapping).map(([k,v])=>`<li>${esc(k)} → ${esc(v)}</li>`).join('')}</ul></details>`;
   dialog.querySelector('#drama-risk-label').hidden=!result.warnings.length;
  }catch(error){if(current===version){host.textContent=error.message;preview=null}}finally{if(current===version){loading=false;ready()}}
 };
 confirm.onclick=async()=>{if(confirm.disabled||!preview)return;loading=true;ready();input.disabled=true;
  try{const project=await api('/api/import/drama/apply',{id:preview.id,digest:preview.digest});await refresh(false);dialog.close();enterProject(project.id);toast('已导入为独立作品，镜头待确认')}
  catch(error){host.textContent=error.message;input.disabled=false;loading=false;ready()}
 };
 const previous=document.activeElement;dialog.onclose=()=>{version++;dialog.remove();previous?.isConnected&&previous.focus()};document.body.append(dialog);dialog.showModal();
}

function creativeShotDetails(s){
 const spec=s.creative_spec;if(!spec)return '';
 const fields={narrativePurpose:'叙事目的',subjectState:'人物与物件状态',composition:'构图',cameraAngle:'角度',cameraPosition:'机位',lighting:'光照',emotion:'情绪',sound:'声音',continuityIn:'入镜状态',continuityOut:'出镜状态'};
 return `<details data-disclosure="creative-facts"><summary>创作依据 · ${esc(spec.shotId)}</summary><div class="composer-details-body">${Object.entries(fields).filter(([k])=>spec[k]!=null).map(([k,label])=>`<p><strong>${label}</strong><br>${esc(spec[k])}</p>`).join('')}${(s.source_warnings||[]).map(w=>`<p class="muted">待复核：${esc(w.message)}</p>`).join('')}</div></details>`;
}
