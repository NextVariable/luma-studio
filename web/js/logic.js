/* 纯逻辑：不碰 DOM，可在 Node 中直接测试。 */
(function(root){
const L=root.L=root.L||{};

L.JOB_NAMES={script:'剧本拆解',assets:'角色与场景建议',shots:'AI 分镜',revision:'AI 改写',image:'生成画面',video:'生成视频',audio:'生成配音',plan:'制作规划',qc:'质量检查',export:'导出成片',assemble:'拼接片段'};
L.JOB_STATES={queued:'排队中',running:'进行中',submitting:'提交中',waiting_review:'等你审批',succeeded:'已完成',failed:'失败',interrupted:'已中断',cancelled:'已取消',blocked:'被阻断'};
L.jobName=k=>L.JOB_NAMES[k]||k;
L.jobState=s=>L.JOB_STATES[s]||s;
L.jobTone=s=>({succeeded:'ok',waiting_review:'wait',failed:'stop',interrupted:'stop',blocked:'stop',queued:'run',running:'run',submitting:'run'}[s]||'');
L.jobActive=s=>['queued','running','submitting'].includes(s);
L.ADOPTABLE=['script','assets','shots','revision'];

/* 秒数显示为 0:09 / 1:05.5 */
L.clock=sec=>{
  const v=Math.max(0,Number(sec)||0),m=Math.floor(v/60),s=v-m*60;
  const ss=Number.isInteger(s)?String(s).padStart(2,'0'):s.toFixed(1).padStart(4,'0');
  return m+':'+ss;
};
L.total=shots=>shots.reduce((a,s)=>a+(Number(s.duration)||0),0);

/* 镜头状态：唯一的来源是后端 readiness；本地字段只作兜底 */
L.shotState=(s,item)=>{
  if(s.locked)return {key:'locked',tone:'',label:'已锁定'};
  if(item?.ready)return {key:'ready',tone:'ok',label:'可交付'};
  if(item?.stale_media)return {key:'stale',tone:'stop',label:'画面待确认'};
  if(!(s.image||s.video))return {key:'missing',tone:'',label:'缺画面'};
  if(s.needs_review||!s.approved)return {key:'review',tone:'wait',label:'待确认'};
  return {key:'blocked',tone:'stop',label:item?.reason||'未就绪'};
};
L.PLACEHOLDER='写下这一镜要发生的事。';
L.realText=t=>(t||'').trim()===L.PLACEHOLDER?'':(t||'');
L.shotTitle=(s,i)=>{const t=L.realText(s.description).trim().split(/[。\n]/)[0];return t.length>34?t.slice(0,33)+'…':t||(i>=0?'镜头 '+(i+1)+'（未写描述）':'未写描述的镜头')};
L.filterShots=(shots,items,filter)=>shots.filter(s=>{
  const st=L.shotState(s,items?.find(x=>x.shot_id===s.id)).key;
  return filter==='all'||(filter==='missing'&&st==='missing')||(filter==='review'&&['review','stale','blocked'].includes(st))||(filter==='ready'&&st==='ready');
});

/* 成片是否对应当前版本 */
L.deliveryIsCurrent=(result,status)=>!!status?.can_export&&!!result?.review_basis&&result.review_basis===status.review_basis&&result.delivery_basis===status.delivery_basis;
/* 生成的候选是否基于旧的镜头设定（导入素材由后端的画面确认规则把关） */
L.candidateOutdated=(t,currentBasis)=>t.source!=='import'&&!!t.basis&&!!currentBasis&&t.basis!==currentBasis;
L.isPartialTake=(t,s)=>{const g=t.generation_segment;return !!g&&(g.start!==0||Math.abs(g.end-s.duration)>.001)};

/* 逐句对白 */
L.addLine=(lines,speaker=null)=>[...lines,{id:null,speaker_asset_id:speaker,text:''}];
L.removeLine=(lines,i)=>lines.filter((_,k)=>k!==i);
L.linesFromDialogue=(dialogue,speaker=null)=>dialogue?.trim()?[{id:null,speaker_asset_id:speaker,text:dialogue.trim()}]:[{id:null,speaker_asset_id:speaker,text:''}];

/* 生成记录 */
L.jobsFor=(jobs,pid,eid,scope='episode')=>jobs.filter(j=>j.project_id===pid&&(scope==='all'||!j.episode_id||j.episode_id===eid));
L.jobBucket=j=>L.jobActive(j.state)?'active':['waiting_review','failed','interrupted','blocked'].includes(j.state)?'attention':'done';
L.films=(jobs,pid,eid)=>jobs.filter(j=>j.project_id===pid&&j.kind==='export'&&j.state==='succeeded'&&j.episode_id===eid&&j.result).map(j=>({job:j,result:JSON.parse(j.result)}));
L.parseResult=j=>{try{return j.result?JSON.parse(j.result):{}}catch(e){return {}}};
L.canAdopt=(j,p)=>j.state==='succeeded'&&L.ADOPTABLE.includes(j.kind)&&!(p?.applied||[]).includes(j.id);
L.canReconcile=j=>{
  const r=L.parseResult(j);
  return ['interrupted','waiting_review','failed'].includes(j.state)&&Boolean(r.run_id||
    (['image','video','audio'].includes(j.kind)&&(r.candidate_file||r.result?.url)));
};
L.canCancel=j=>['queued','running','waiting_review'].includes(j.state);

/* 审批表单：工作室只支持不超过一个段落输入 */
L.reviewSupport=form=>{
  const inputs=form?.inputs||[];
  return inputs.length<=1&&inputs.every(f=>f.type==='paragraph'&&f.output_variable_name);
};

/* 没有画面时的光影：按作品或镜头编号固定选一组电影感配色 */
L.PALETTES=[
  ['#c49a6c','#6e4a33','#3a5560'],
  ['#a9675c','#4c2a2e','#34425e'],
  ['#9887b8','#4a3d66','#8f6a80'],
  ['#78a08f','#2e4a42','#a8936f'],
  ['#7f9fb8','#33475f','#5e5478'],
  ['#bf8f76','#5a3848','#3e3f63'],
  ['#bfae88','#5c4e38','#46605e'],
  ['#ad8290','#3e3050','#5a7f7c']
];
L.hash=str=>{let h=2166136261;for(const c of String(str||'luma')){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return h>>>0};
L.palette=seed=>L.PALETTES[L.hash(seed)%L.PALETTES.length];
L.glow=seed=>{
  const [a,b,c]=L.palette(seed),h=L.hash(seed),x=28+h%44,y=30+(h>>8)%34;
  return `radial-gradient(ellipse 85% 70% at ${x}% ${y}%,${a}99 0,${b}5c 40%,transparent 72%),radial-gradient(ellipse 90% 70% at ${100-x}% ${100-y}%,${c}73,transparent 70%),linear-gradient(170deg,#15171b,#070707 70%)`;
};
L.timeAgo=(t,now=Date.now()/1000)=>{
  const d=Math.max(0,now-t);
  if(d<60)return '刚刚';if(d<3600)return Math.floor(d/60)+' 分钟前';if(d<86400)return Math.floor(d/3600)+' 小时前';
  return new Date(t*1000).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});
};
})(typeof window!=='undefined'?window:globalThis);
