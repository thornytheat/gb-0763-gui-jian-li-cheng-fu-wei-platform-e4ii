from app.coverage.balance import balance
from app.coverage.intervals import subtract, union


def test_conservation(dirty):
    result = dirty['coverage']
    assert result['planned_mm'] == result['mapped_mm'] + result['missing_mm'] == 600000


def test_duplicate_coverage(dirty):
    assert (dirty['coverage']['mapped_mm'], dirty['coverage']['overlap_mm']) == (400000,100000)


def test_gap_explained(dirty):
    assert dirty['coverage']['missing_parts'] == [dict(chain='UP-B', start_mm=2100000, end_mm=2300000,
                                                      reasons=['SIGNAL_GAP'], sources=[5,6])]


def test_unplanned_chain_does_not_credit(dirty):
    result = balance([dict(chain='NONE',start_mm=1000000,end_mm=1100000)], dirty['chainage']['segments'], [])
    assert (result['mapped_mm'], result['missing_mm']) == (0, 100000)


def test_touching_and_contained():
    assert union([(0,7),(7,10),(1,2),(19,19)]) == [[0,10]]


def test_clean_api(client):
    result = client.get('/api/coverage?sample=clean').json
    assert (result['mapped_mm'], result['missing_parts']) == (600000,[])


def _span(run, chain, at, lo, hi):
    return {'left': {'run': run, 'chain': chain, 'at': at, 'station_mm': lo, 'ref': lo, 'line': 1},
            'right': {'run': run, 'chain': chain, 'at': at, 'station_mm': hi, 'ref': hi, 'line': 2},
            'reason': None}


PLAN = [dict(chain='C', start_mm=0, end_mm=1000)]


def test_claims_total_matches_coverage(dirty):
    claims = dirty['coverage']['claims']
    assert sum(item['claimed_mm'] for item in claims) == dirty['coverage']['mapped_mm'] == 400000
    assert sum(item['overlap_mm'] for item in claims) == dirty['coverage']['overlap_mm'] == 100000


def test_overlap_split_between_trains():
    # 两趟车部分重叠：R1 先到覆盖 0–600，R2 后到覆盖 400–1000。
    segments = [_span('R1', 'C', '2026-11-22T00:00:00+00:00', 0, 600),
                _span('R2', 'C', '2026-11-22T00:01:00+00:00', 400, 1000)]
    result = balance(PLAN, segments, [])
    by_run = {item['run']: item for item in result['claims']}
    assert result['mapped_mm'] == 1000 and result['overlap_mm'] == 200
    # 重叠的 400–600 全记先到的 R1；R2 只认领未被覆盖的 600–1000。
    assert by_run['R1']['claimed_mm'] == 600
    assert by_run['R2']['claimed_mm'] == 400 and by_run['R2']['overlap_mm'] == 200
    assert by_run['R2']['basis'][0]['parts'] == [[600, 1000]]
    assert sum(item['claimed_mm'] for item in result['claims']) == result['mapped_mm']


def test_later_train_keeps_uncontested_ground():
    # 后到的车覆盖了先到车没走的区段，这部分不能漏记。
    segments = [_span('R1', 'C', '2026-11-22T00:00:00+00:00', 0, 400),
                _span('R2', 'C', '2026-11-22T00:01:00+00:00', 300, 900)]
    result = balance(PLAN, segments, [])
    by_run = {item['run']: item for item in result['claims']}
    assert (by_run['R1']['claimed_mm'], by_run['R2']['claimed_mm']) == (400, 500)
    assert result['mapped_mm'] == 900 and result['missing_mm'] == 100


def test_claim_order_is_first_arrival_not_input_order():
    later = _span('LATE', 'C', '2026-11-22T00:05:00+00:00', 0, 800)
    early = _span('EARLY', 'C', '2026-11-22T00:00:00+00:00', 200, 1000)
    result = balance(PLAN, [later, early], [])  # 报文里晚到的车反而排在前面
    assert [item['run'] for item in result['claims']] == ['EARLY', 'LATE']
    by_run = {item['run']: item for item in result['claims']}
    assert by_run['EARLY']['claimed_mm'] == 800 and by_run['LATE']['claimed_mm'] == 200


def test_subtract_removes_claimed_ground():
    assert subtract([(0, 1000)], [(200, 400), (600, 800)]) == [[0, 200], [400, 600], [800, 1000]]
