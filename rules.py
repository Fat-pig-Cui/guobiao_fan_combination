"""Frozen, no-flower editor profile. Stable IDs follow the reference catalogue."""
from dataclasses import dataclass

NAMES = (
    '大四喜 大三元 绿一色 九莲宝灯 四杠 连七对 十三幺 '
    '清幺九 小四喜 小三元 字一色 四暗刻 一色双龙会 '
    '一色四同顺 一色四节高 一色四步高 三杠 混幺九 '
    '七对 七星不靠 全双刻 清一色 一色三同顺 一色三节高 全大 全中 全小 '
    '清龙 三色双龙会 一色三步高 全带五 三同刻 三暗刻 '
    '全不靠 组合龙 大于五 小于五 三风刻 '
    '花龙 推不倒 三色三同顺 三色三节高 无番和 妙手回春 海底捞月 杠上开花 抢杠和 '
    '碰碰和 混一色 三色三步高 五门齐 全求人 双暗杠 双箭刻 '
    '全带幺 不求人 双明杠 和绝张 '
    '箭刻白 箭刻发 箭刻中 圈风刻 门风刻 门前清 平和 四归一 双同刻 双暗刻 暗杠 断幺 '
    '一般高 喜相逢 连六 老少副 幺九刻 明杠 缺一门 无字 边张 坎张 单钓将 自摸 '
    '明暗杠 天和 地和 人和'
).split()
VALUES = ([88]*7 + [64]*6 + [48]*2 + [32]*3 + [24]*9 + [16]*6
          + [12]*5 + [8]*9 + [6]*7 + [4]*4 + [2]*12 + [1]*12 + [5,8,8,8])
FANS = {8000+i: {'name': n, 'value': v} for i,(n,v) in enumerate(zip(NAMES, VALUES))}
assert len(NAMES) == len(VALUES) == 86
NAME_ID = {v['name']: k for k,v in FANS.items()}
PROFILE = 'editor_no_flower_v1'

@dataclass(frozen=True)
class Profile:
    id: str = PROFILE
    version: int = 1
    min_fan: int = 8
    flowers: bool = False
    canonical: str = 'small:70,71,72,73;wait:78,79,80;then-id-count-lexicographic'

def get_profile(name=PROFILE):
    if name != PROFILE:
        raise ValueError('Only editor_no_flower_v1 is implemented; other profiles need separate rule audits')
    return Profile()

def project(raw):
    result = {}
    for fan, count in raw.items():
        fan = 8058 if fan in (8058,8059,8060) else fan
        result[fan] = result.get(fan,0) + count
    return tuple(sorted((fan,count) for fan,count in result.items() if count))

def fan_total(key):
    return sum(FANS[i]['value']*n for i,n in key)

def describe(key):
    return [{'id': i, 'name': '箭刻' if i == 8058 else FANS[i]['name'],
             'count': n, 'value': FANS[i]['value'], 'subtotal': n*FANS[i]['value']}
            for i,n in key]
