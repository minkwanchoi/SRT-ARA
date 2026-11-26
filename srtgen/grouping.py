"""같은 ID(규칙) 안에서 분석 내용에 따라 그룹을 나누거나 합치자는 제안.

그룹은 `SRT-S-C-ID1.2-1` 처럼 ID 뒤의 번호로 쓴다(notation). 도구는 분석 글을 보고 제안만 하고,
사용자가 화면에서 받아들여야 소스의 식별자가 바뀐다(writeback.regroup). 보고서를 만들 때는 쓰지 않는다.

- 나누기(split): 같은 그룹의 동일사항 위치에 대표와 다른 분석을 적었으면 새 그룹으로 나누자고 한다.
  그런 위치가 여럿이면 분석이 비슷한 것끼리 한 그룹으로 묶는다.
- 옮기기(join): 그 다른 분석이 같은 ID 의 다른 그룹 분석과 비슷하면 그 그룹으로 옮기자고 한다.
- 합치기(merge): 같은 ID 의 두 그룹 분석이 거의 같으면 하나로 합치자고 한다.

비슷한 정도는 표준 라이브러리 difflib 의 글자 단위 유사도(0~1)로, 사유 항목(@FA분석·@미달성사유)만 견준다.
@결론은 "SW신뢰성 및 기능에 문제가 없음" 같은 상투 문구가 많아, 함께 견주면 서로 다른 분석이 비슷해 보인다
(공개 소스로 잰 결과 다른 분석끼리 최대 0.62 → 0.89, 64단계). 기준값은 notation 의 KEEP·SIMILAR·SAME.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .notation import KEEP, SAME, SIMILAR, TEST_TYPES, similarity
from .scanner import ExceptionItem, Occurrence


@dataclass
class Suggestion:
    kind: str                   # "split" | "join" | "merge"
    item: ExceptionItem         # 옮길 위치가 지금 있는 그룹
    to: int                     # 옮겨 갈 그룹 번호
    new: bool                   # 아직 없는 그룹인가
    occurrences: List[Occurrence] = field(default_factory=list)   # 옮길 위치 (참조 코드도 함께 옮긴다)
    similarity: float = 0.0     # 견준 분석과의 유사도
    reason: str = ""


def analysis_keys(test: str) -> Tuple[str, ...]:
    """분석으로 견줄 항목: 그 유형의 사유 항목(@FA분석·@미달성사유)만. @결론은 상투 문구가 많아 견주지 않는다
    (합치기에서 지우는 글·혼동 경고가 보는 글은 @결론까지 든 notation.analysis_keys 이다)."""
    return (TEST_TYPES[test].default_field,)


def analysis(test: str, fields: Dict[str, str], keys: Tuple[str, ...] = ()) -> str:
    """견줄 분석 글. keys 를 주면 그 항목만 (동일사항 위치가 적은 항목끼리 견주려고)."""
    return " ".join(" ".join(fields.get(k, "").split()) for k in (keys or analysis_keys(test))).strip()


def _percent(x: float) -> str:
    return f"{round(x * 100)}%"


def suggest(items: List[ExceptionItem]) -> List[Suggestion]:
    by_rule: Dict[Tuple[str, int], List[ExceptionItem]] = {}
    for item in items:
        by_rule.setdefault((item.test, item.ex_id), []).append(item)
    out: List[Suggestion] = []
    for (test, _ex_id), members in by_rule.items():
        members = sorted(members, key=lambda i: i.group)
        texts = {m.group: analysis(test, m.fields) for m in members}
        next_free = max(m.group for m in members) + 1
        # 합치기: 두 그룹의 분석이 거의 같다
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                s = similarity(texts[a.group], texts[b.group])
                if s >= SAME:
                    out.append(Suggestion("merge", b, a.group, False, list(b.occurrences), s,
                                          f"{b.tag} 의 분석이 {a.tag} 와 거의 같습니다({_percent(s)}). "
                                          f"{a.tag} 로 합치면 한 건이 됩니다(옮긴 뒤 겹친 분석 글은 지워도 됩니다)."))
        # 나누기·옮기기: 동일사항 위치에 대표와 다른 분석을 적었다
        for item in members:
            new_groups: List[Tuple[int, str, Suggestion]] = []
            for occ in item.same:
                # 그 위치가 적은 항목끼리만 견준다 (@FA분석만 적었으면 대표의 @FA분석과)
                keys = tuple(k for k in analysis_keys(test) if occ.main.fields.get(k) or occ.fields.get(k))
                if not keys:
                    continue                # 분석을 적지 않은 동일사항은 대표의 분석을 따른다
                own = analysis(test, occ.fields, keys)
                s_rep = similarity(own, analysis(test, item.fields, keys))
                if s_rep >= KEEP:
                    continue                # 대표와 같은 분석으로 본다 (바꿔 쓴 글)
                others = [(similarity(own, analysis(test, m.fields, keys)), m) for m in members if m is not item]
                best = max(others, key=lambda x: x[0], default=(0.0, None))
                if best[1] is not None and best[0] >= SIMILAR:
                    m = best[1]
                    out.append(Suggestion("join", item, m.group, False, [occ], best[0],
                                          f"{occ.main.file}:{occ.main.lines} 의 분석이 대표와 다르고({_percent(s_rep)}) "
                                          f"{m.tag} 의 분석과 비슷합니다({_percent(best[0])})."))
                    continue
                near = max(((similarity(own, t), g) for g, t, _ in new_groups), key=lambda x: x[0],
                           default=(0.0, None))
                if near[1] is not None and near[0] >= SIMILAR:
                    sugg = next(sg for g, _t, sg in new_groups if g == near[1])
                    sugg.occurrences.append(occ)
                    sugg.reason += f" {occ.main.file}:{occ.main.lines} 도 분석이 비슷해({_percent(near[0])}) 함께 옮깁니다."
                    continue
                sugg = Suggestion("split", item, next_free, True, [occ], s_rep,
                                  f"{occ.main.file}:{occ.main.lines} 의 분석이 대표({item.representative.main.file}:"
                                  f"{item.representative.main.lines})와 다릅니다({_percent(s_rep)}). "
                                  f"새 그룹으로 나누면 따로 한 건이 됩니다.")
                new_groups.append((next_free, own, sugg))
                out.append(sugg)
                next_free += 1
    return out
