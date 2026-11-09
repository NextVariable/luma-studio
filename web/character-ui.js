const viewLabels={front:'正面',side:'侧面',back:'背面',three_quarter:'斜侧面'};
const voiceChoices=['alloy','ash','ballad','coral','echo','fable','onyx','nova','sage','shimmer','verse','marin','cedar'];
function characterControls(a,v){
 if(a.kind!=='character')return '';
 return `<details class="character-look"><summary>服装与配音 · ${esc(v.outfit||'基础服装')}</summary><label>服装 / 阶段<input id="look-outfit-${esc(a.id)}" data-look-field value="${esc(v.outfit||'')}" maxlength="200" placeholder="例如：蓝色雨衣 · 青年"></label><label>角色配音音色<select id="look-voice-${esc(a.id)}" data-look-field>${voiceChoices.map(x=>`<option value="${x}" ${(v.voice_id||'alloy')===x?'selected':''}>${x}</option>`).join('')}</select></label><p class="muted">选择配音音色。保存造型后，可在镜头中采用。</p><div class="character-views">${Object.entries(viewLabels).map(([k,n])=>`<label class="character-view-upload"><span>${n}</span><span class="view-upload-preview">${v.views?.[k]?`<img loading="lazy" alt="${esc(a.name)} ${n}" src="/media/${esc(v.views[k])}">`:`<span>${uiIcon('plus')}<small>添加图片</small></span>`}</span><input type="file" aria-label="上传${esc(a.name)}${n}参考图" accept="image/png,image/jpeg,image/webp" data-character-view="${esc(a.id)}" data-angle="${k}"></label>`).join('')}</div><button data-save-look="${esc(a.id)}">保存造型</button></details>`;
}
function bindCharacterAssets(){
 async function storeLook(a,extra={}){
  const fields={outfit:$('#look-outfit-'+a.id).value,voice_id:$('#look-voice-'+a.id).value,...extra};
  await productionEdit({action:'character_look',asset_id:a.id,...fields});
  const clean=['look-outfit-'+a.id,'look-voice-'+a.id];
  p().assets.forEach(asset=>{if(document.querySelector(`[data-asset-name="${asset.id}"]`)?.value===asset.name)clean.push('asset-name:'+asset.id);if(document.querySelector(`[data-asset="${asset.id}"]`)?.value===(asset.description||''))clean.push('asset:'+asset.id)});
  clearDraft(clean);render();toast('角色造型已保存，旧镜头保持原版本');
 }
 document.querySelectorAll('[data-save-look]').forEach(b=>b.onclick=()=>storeLook(p().assets.find(a=>a.id===b.dataset.saveLook)).catch(e=>toast(e.message)));
 document.querySelectorAll('[data-character-view]').forEach(el=>el.onchange=async()=>{try{
  const file=el.files[0];if(!file)return;
  const a=p().assets.find(a=>a.id===el.dataset.characterView),v=a.versions.find(v=>v.id===a.selected_version),upload=await uploadMedia(file);
  if(!upload.streams.includes('video'))throw Error('请选择角色图片');
  const sameOutfit=$('#look-outfit-'+a.id).value===(v.outfit||'');
  await storeLook(a,{views:{...(sameOutfit?v.views:{}),[el.dataset.angle]:upload.file}});
 }catch(e){toast(e.message)}});
}

function lineAudioControls(s,l){
 const takes=s.takes.filter(t=>t.kind==='audio'&&(!t.line_id||t.line_id===l.id)),selected=takes.find(t=>t.id===l.audio_take_id);
 return `<details class="line-audio" data-disclosure="audio-${esc(l.id)}"><summary>配音与时间 <span>${selected?'已选音轨':'未配音'}</span></summary><label>这句使用的音轨<select data-line-audio="${esc(l.id)}" ${s.locked?'disabled':''}><option value="">尚未选用音轨</option>${takes.map(t=>`<option value="${esc(t.id)}" ${t.id===l.audio_take_id?'selected':''}>${esc(t.label)}</option>`).join('')}</select></label>${selected?`<audio controls preload="none" aria-label="试听这句音轨" src="/media/${esc(selected.file)}"></audio>`:''}${mediaImportField('导入这句音轨',`data-line-import="${esc(l.id)}" accept="audio/*" ${s.locked?'disabled':''}`)}<label>开始时间 / 秒<input data-line-start="${esc(l.id)}" type="number" min="0" step="0.01" value="${l.audio_start??''}" ${s.locked?'disabled':''}></label><p class="muted">${l.audio_duration?`实测 ${l.audio_duration.toFixed(2)} 秒`:'留空则接续上一句'}</p><button data-line-generate="${esc(l.id)}" ${s.locked?'disabled':''}>生成这句配音</button></details>`;
}
function bindLineAudio(s){
 async function select(lineId,takeId){
  const line=s.lines.find(l=>l.id===lineId),audioControl=document.querySelector(`[data-line-audio="${lineId}"]`),startControl=document.querySelector(`[data-line-start="${lineId}"]`);
  try{
   if(hasUnsavedShot()||hasUnsavedCut())throw Error('请先保存对白、镜头和剪辑，再安排音轨');
   await productionEdit({action:'bind_line_audio',shot_id:s.id,line_id:lineId,take_id:takeId,start:startControl.value===''?null:Number(startControl.value)});
   toast('逐句音轨已安排，请检查时长并重新审核');
  }catch(error){audioControl.value=line.audio_take_id||'';startControl.value=line.audio_start??'';throw error}
 }
 document.querySelectorAll('[data-line-audio]').forEach(el=>el.onchange=()=>select(el.dataset.lineAudio,el.value).catch(e=>toast(e.message)));
 document.querySelectorAll('[data-line-start]').forEach(el=>el.onchange=()=>{const l=s.lines.find(l=>l.id===el.dataset.lineStart);if(l.audio_take_id)select(l.id,l.audio_take_id).catch(e=>toast(e.message))});
 document.querySelectorAll('[data-line-generate]').forEach(b=>b.onclick=()=>run('audio',{shot_id:s.id,line_id:b.dataset.lineGenerate}).catch(e=>toast(e.message)));
 document.querySelectorAll('[data-line-import]').forEach(el=>el.onchange=async()=>{try{
  if(hasUnsavedShot())throw Error('请先保存对白，再导入音轨');
  const f=el.files[0];if(!f)return;const d=await uploadMedia(f);
  if(!d.streams.includes('audio'))throw Error('文件没有音频轨道');
  await productionEdit({action:'add_take',shot_id:s.id,kind:'audio',file:d.file,label:f.name,line_id:el.dataset.lineImport});
  toast('该句音轨已加入备选，请明确选用');
 }catch(e){toast(e.message)}});
}
