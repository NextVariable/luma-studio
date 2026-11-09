"""Dependency fingerprints only; never rewrites narrative or pinned looks."""
import creative
import production


def narrative(s):
    spec=s.get('creative_spec',{})
    return {'id':s['id'],'description':s.get('description'),'dialogue':s.get('dialogue'),
            'lines':[{'speaker':l.get('speaker_asset_id'),'text':l.get('text')} for l in s.get('lines') or []],
            'asset_bindings':s.get('asset_bindings',{}),
            'facts':{k:spec.get(k) for k in ('visualSubject','locationId','propIds','subjectState','continuityIn','continuityOut')}}


def inputs(p,s):
    episode=next(e for e in p['episodes'] if e['id']==s['episode_id'])
    ordered=[x for x in p['shots'] if x['episode_id']==s['episode_id']]
    index=next(i for i,x in enumerate(ordered) if x['id']==s['id'])
    byid={x['id']:x for x in ordered};chain=[];seen={s['id']};parent=s.get('continuity_from')
    while parent:
        if parent in seen:raise ValueError('镜头承接不能形成循环')
        seen.add(parent);source=byid.get(parent)
        if not source:chain.append({'id':parent,'missing':True});break
        chain.append({'id':parent,'facts':production.semantic_shot(source),'clip':production.clip_of(source)})
        parent=source.get('continuity_from')
    spec=episode.get('creative_spec',{});state=creative.continuity_status(p,episode['id'])
    return {'prior_narrative':[narrative(x) for x in ordered[:index]],'visual_chain':chain,
            'episode_input':{'script':episode['script'],'entry_state':spec.get('entry_state'),'planned_end_state':spec.get('planned_end_state'),
                             'upstream_digest':state['upstream_digest'],'carry_digest':state.get('carry_digest'),
                             'requires_confirmation':state['requires_confirmation']}}


def basis(p,s):return creative.digest(inputs(p,s))


def visual_basis(p,s):
    return creative.digest({'shot':production.take_basis(s),'clip':production.clip_of(s),'inputs':basis(p,s) if s.get('preparation') or s.get('creative_spec') or s.get('continuity_from') else None})


def visual_issue(p,s):
    byid={x['id']:x for x in p['shots']};parent=s.get('continuity_from');seen={s['id']}
    while parent:
        if parent in seen:return '承接镜头形成循环，请先修正'
        seen.add(parent);source=byid.get(parent)
        if not source:return '承接镜头已不存在，请重新选择'
        plan=source.get('preparation')
        stale=plan and (plan.get('basis')!=creative.digest(production.semantic_shot(source)) or plan.get('dependency_basis')!=basis(p,source))
        approved=source.get('visual_review_basis')==visual_basis(p,source) if source.get('visual_review_basis') else source.get('approved') and not source.get('needs_review')
        if not approved or stale:return '承接镜头需先复核：'+parent
        parent=source.get('continuity_from')
    return None
