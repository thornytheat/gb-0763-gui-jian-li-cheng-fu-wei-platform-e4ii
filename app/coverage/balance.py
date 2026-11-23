"""轨段覆盖对账与车次里程认领。

同一段轨道只计一次：先按链把各车次的有效双基点区间（复位区段）求并集，
再与计划区间求交得到已映射长度；重叠部分通过 ``overlap_mm`` 单列复核量。

车次认领按“先到先得”复位：以每个车次第一段有效复位区段的 UTC 起点排序，
逐车把它覆盖到计划内、且尚未被前车认领的区段记为该车的认可里程。因此
``sum(claims[*].claimed_mm) == mapped_mm``，总量与实际覆盖相符，不会把
重叠轨段重复计入任何车次，也不会漏掉后车的复核贡献（重叠量另有统计）。
"""
from collections import defaultdict

from .intervals import intersect, length, subtract, union

NO_COVERAGE = 'NO_COVERAGE'


def _plan_by_chain(plan):
    grouped = defaultdict(list)
    for part in plan:
        grouped[part['chain']].append((part['start_mm'], part['end_mm']))
    return {chain: union(parts) for chain, parts in grouped.items()}


def _usable_segments(segments):
    """把复位区段还原成 (chain, run, 起点UTC, 标称区间)。

    跨断链（左右基点不在同一链）的区段本身没有有效覆盖，不能落进任何一条链。
    """
    usable = []
    for span in segments:
        left, right = span['left'], span['right']
        if left['chain'] != right['chain']:
            continue
        lo, hi = sorted((left['station_mm'], right['station_mm']))
        usable.append((left['chain'], left['run'], left['at'], (lo, hi)))
    return usable


def _missing_parts(chain, plan_parts, mapped_union, gap_book):
    missing = subtract(plan_parts, mapped_union)
    parts = []
    for start, end in missing:
        reasons, sources = [], []
        for gap in gap_book.get(chain, ()):
            if gap['end_mm'] <= start or gap['start_mm'] >= end:
                continue
            reasons.append(gap['reason'])
            for line in gap['sources']:
                if line not in sources:
                    sources.append(line)
        if not reasons:
            reasons.append(NO_COVERAGE)
        parts.append({'chain': chain, 'start_mm': start, 'end_mm': end,
                      'reasons': reasons, 'sources': sorted(sources)})
    return parts


def _claim_runs(plan_by_chain, segments):
    """先到先得认领，返回 (每车汇总, 每链每车认领地)。"""
    by_run = defaultdict(list)
    for chain, run, at, interval in _usable_segments(segments):
        if chain not in plan_by_chain:
            continue
        clipped = intersect([interval], (min(s for s, _ in plan_by_chain[chain]),
                                         max(e for _, e in plan_by_chain[chain])))
        if clipped:
            by_run[run].append((at, chain, clipped))

    # 先到先得：以该车第一段有效复位区段的 UTC 起点定序，同时刻用车次号兜底保证确定。
    order = sorted(by_run, key=lambda run: (min(item[0] for item in by_run[run]), run))

    taken = defaultdict(list)          # chain -> 已被前车认领的区间并集
    chain_claims = defaultdict(list)   # chain -> [{run, parts, claimed_mm}]
    run_totals = defaultdict(lambda: {'claimed_mm': 0, 'raw_mm': 0, 'overlap_mm': 0,
                                      'chains': defaultdict(list)})
    for run in order:
        per_chain = defaultdict(list)
        for _, chain, clipped in by_run[run]:
            per_chain[chain].extend(clipped)
        for chain in sorted(per_chain):
            raw = union(per_chain[chain])
            raw_len = length(raw)
            awarded = subtract(raw, taken[chain])
            claimed_len = length(awarded)
            taken[chain] = union(taken[chain] + awarded)
            if claimed_len:
                chain_claims[chain].append({'run': run, 'parts': awarded,
                                            'claimed_mm': claimed_len})
            totals = run_totals[run]
            totals['raw_mm'] += raw_len
            totals['claimed_mm'] += claimed_len
            totals['overlap_mm'] += raw_len - claimed_len
            totals['chains'][chain] = awarded

    claims = []
    for run in order:
        totals = run_totals[run]
        claims.append({'run': run, 'claimed_mm': totals['claimed_mm'],
                       'raw_mm': totals['raw_mm'], 'overlap_mm': totals['overlap_mm'],
                       'basis': sorted(({'chain': chain, 'parts': parts,
                                         'claimed_mm': length(parts)}
                                        for chain, parts in totals['chains'].items()
                                        if length(parts)),
                                       key=lambda item: item['chain'])})
    return claims, chain_claims


def balance(plan, segments, gaps):
    plan_by_chain = _plan_by_chain(plan)
    raw_by_chain = defaultdict(list)
    for chain, _run, _at, interval in _usable_segments(segments):
        if chain in plan_by_chain:
            raw_by_chain[chain].append(interval)

    gap_book = defaultdict(list)
    for gap in gaps:
        gap_book[gap['chain']].append(gap)

    tracks, missing_parts = [], []
    planned_mm = mapped_mm = missing_mm = overlap_mm = 0
    for chain in sorted(plan_by_chain):
        plan_parts = plan_by_chain[chain]
        planned = length(plan_parts)
        bound = (min(s for s, _ in plan_parts), max(e for _, e in plan_parts))
        # 先逐条裁剪再求和：保留同一段被多趟车重复覆盖的原始长度。
        raw_clipped = []
        for interval in raw_by_chain.get(chain, ()):
            raw_clipped.extend(intersect([interval], bound))
        raw_len = length(raw_clipped)
        mapped = length(union(raw_clipped))
        missing_parts.extend(_missing_parts(chain, plan_parts, union(raw_clipped), gap_book))
        tracks.append({'chain': chain,
                       'start_mm': bound[0], 'end_mm': bound[1],
                       'planned_mm': planned, 'mapped_mm': mapped,
                       'missing_mm': planned - mapped, 'mapped_parts': union(raw_clipped)})
        planned_mm += planned
        mapped_mm += mapped
        missing_mm += planned - mapped
        overlap_mm += raw_len - mapped

    claims, chain_claims = _claim_runs(plan_by_chain, segments)
    for track in tracks:
        track['claims'] = chain_claims.get(track['chain'], [])

    return {'planned_mm': planned_mm, 'mapped_mm': mapped_mm, 'missing_mm': missing_mm,
            'overlap_mm': overlap_mm, 'tracks': tracks, 'missing_parts': missing_parts,
            'claims': claims}
