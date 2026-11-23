"""半开区间（左闭右开）上的集合运算。

区间统一表示为 ``(start, end)`` 且 ``end >= start``；等长（``start == end``）
为空区间，不贡献任何长度。所有函数都不修改入参，并返回排序后的新列表。
"""


def _pairs(intervals):
    return [(int(start), int(end)) for start, end in intervals if int(end) > int(start)]


def union(intervals):
    """求并集，相邻（首尾相接）区间合并为同一段。"""
    merged = []
    for start, end in sorted(_pairs(intervals)):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def intersect(intervals, bounds):
    """把区间集合逐个裁剪到 bounds（单个半开区间）内。"""
    lo, hi = bounds
    return union((max(start, lo), min(end, hi)) for start, end in _pairs(intervals))


def subtract(intervals, covered):
    """从 intervals 中扣除 covered 已覆盖的部分，返回剩余半开区间。"""
    covered = union(covered)
    remaining = []
    for start, end in union(intervals):
        cursor = start
        for lo, hi in covered:
            if hi <= cursor:
                continue
            if lo >= end:
                break
            if lo > cursor:
                remaining.append((cursor, lo))
            cursor = max(cursor, hi)
        if cursor < end:
            remaining.append((cursor, end))
    return union(remaining)


def length(intervals):
    return sum(end - start for start, end in _pairs(intervals))
