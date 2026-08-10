#!/usr/bin/env python3
"""自动生成：27将54技能运行时元数据类。具体机制由势力处理器执行。"""

from .skill_runtime_core import RuntimeSkill

class Skill_caocao_01(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='caocao_奸雄', name='奸雄',
            owner_hero_id='caocao', skill_type='trigger',
            trigger_event='DAMAGE_RECEIVED',
            forced=False, limited=False,
            description='当你受到伤害后，你可以获得对你造成伤害的牌并摸一张牌。', faction='wei',
            implementation_status='active',
        )

class Skill_caocao_02(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='caocao_护驾', name='护驾',
            owner_hero_id='caocao', skill_type='lord',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='主公技。①当你需要使用或打出一张【闪】时，你可以令其他魏势力角色选择是否打出一张【闪】。若有角色响应，则你视为使用或打出了一张【闪】。②每回合限一次。当有魏势力角色于回合外使用或打出【闪】时，其可以令你摸一张牌。', faction='wei',
            implementation_status='active',
        )

class Skill_simayi_03(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='simayi_反馈', name='反馈',
            owner_hero_id='simayi', skill_type='trigger',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='每当你受到1点伤害后，你可以获得伤害来源的一张牌。', faction='wei',
            implementation_status='active',
        )

class Skill_simayi_04(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='simayi_鬼才', name='鬼才',
            owner_hero_id='simayi', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='在任意角色的判定牌生效前，你可以打出一张牌代替之。', faction='wei',
            implementation_status='active',
        )

class Skill_xiahoudun_05(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='xiahoudun_刚烈', name='刚烈',
            owner_hero_id='xiahoudun', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='当你受到1点伤害后，你可进行判定，若结果为：红色，你对伤害来源造成1点伤害；黑色，你弃置伤害来源一张牌。', faction='wei',
            implementation_status='active',
        )

class Skill_xiahoudun_06(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='xiahoudun_清俭', name='清俭',
            owner_hero_id='xiahoudun', skill_type='trigger',
            trigger_event='DRAW_PHASE',
            forced=False, limited=False,
            description='每回合限一次。当你于摸牌阶段外得到牌后，你可以展示任意张牌并交给一名其他角色。然后，当前回合角色本回合的手牌上限+X（X为你给出的牌中包含的类别数）。', faction='wei',
            implementation_status='active',
        )

class Skill_zhangliao_07(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangliao_突袭', name='突袭',
            owner_hero_id='zhangliao', skill_type='trigger',
            trigger_event='DRAW_PHASE',
            forced=False, limited=False,
            description='摸牌阶段摸牌时，你可以少摸任意张牌，然后获得等量的角色的各一张手牌。', faction='wei',
            implementation_status='active',
        )

class Skill_xuchu_08(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='xuchu_裸衣', name='裸衣',
            owner_hero_id='xuchu', skill_type='trigger',
            trigger_event='DAMAGE_DEALT',
            forced=False, limited=False,
            description='摸牌阶段开始时，你亮出牌堆顶的三张牌。然后，你可以放弃摸牌。若如此做，你获得其中的基本牌、武器牌和【决斗】，且直到你的下回合开始，你使用的【杀】或【决斗】造成伤害时，此伤害+1。否则，你将这些牌置入弃牌堆。', faction='wei',
            implementation_status='active',
        )

class Skill_guojia_09(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='guojia_天妒', name='天妒',
            owner_hero_id='guojia', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='当你的判定牌生效后，你可以获得之。', faction='wei',
            implementation_status='active',
        )

class Skill_guojia_10(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='guojia_遗计', name='遗计',
            owner_hero_id='guojia', skill_type='trigger',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='当你受到1点伤害后，你可以摸两张牌，然后可以将至多两张手牌交给其他角色。', faction='wei',
            implementation_status='active',
        )

class Skill_zhenji_11(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhenji_洛神', name='洛神',
            owner_hero_id='zhenji', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='准备阶段，你可以进行判定，若结果为黑色则获得此判定牌，且可重复此流程直到出现红色的判定结果。你通过〖洛神〗得到的牌不计入当前回合的手牌上限。', faction='wei',
            implementation_status='active',
        )

class Skill_zhenji_12(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhenji_倾国', name='倾国',
            owner_hero_id='zhenji', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='你可以将一张黑色手牌当做【闪】使用或打出。', faction='wei',
            implementation_status='active',
        )

class Skill_liubei_13(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='liubei_仁德', name='仁德',
            owner_hero_id='liubei', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段，你可以将至少一张手牌交给其他角色，然后你于此阶段内不能再以此法交给该角色牌；若你于此阶段内给出的牌首次达到两张，你可以视为使用一张基本牌。', faction='shu',
            implementation_status='active',
        )

class Skill_liubei_14(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='liubei_激将', name='激将',
            owner_hero_id='liubei', skill_type='lord',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='主公技。①当你需要使用或打出【杀】时，你可以令其他蜀势力角色依次选择是否打出一张【杀】。若有角色响应，则你视为使用或打出了此【杀】。②每回合限一次。当有蜀势力角色于回合外使用或打出【杀】时，其可以令你摸一张牌。', faction='shu',
            implementation_status='active',
        )

class Skill_guanyu_15(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='guanyu_武圣', name='武圣',
            owner_hero_id='guanyu', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='你可以将一张红色牌当做【杀】使用或打出。你使用的方片【杀】没有距离限制。', faction='shu',
            implementation_status='active',
        )

class Skill_guanyu_16(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='guanyu_义绝', name='义绝',
            owner_hero_id='guanyu', skill_type='locked',
            trigger_event='PLAY_PHASE',
            forced=True, limited=False,
            description='出牌阶段限一次，你可以弃置一张牌并令一名有手牌的其他角色展示一张手牌。若此牌为黑色，则该角色不能使用或打出手牌，非锁定技失效且受到来自你的红桃【杀】的伤害+1直到回合结束。若此牌为红色，则你可以获得此牌，并可以令其回复1点体力。', faction='shu',
            implementation_status='active',
        )

class Skill_zhangfei_17(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangfei_咆哮', name='咆哮',
            owner_hero_id='zhangfei', skill_type='locked',
            trigger_event='DAMAGE_DEALT',
            forced=True, limited=False,
            description='①锁定技，你使用【杀】无次数限制。②锁定技，当你使用的【杀】被【闪】抵消时，你获得一枚“咆”（→）当你因【杀】造成伤害时，你弃置所有“咆”并令伤害值+X（X为“咆”数）。回合结束后，你弃置所有“咆”。', faction='shu',
            implementation_status='active',
        )

class Skill_zhangfei_18(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangfei_替身', name='替身',
            owner_hero_id='zhangfei', skill_type='limited',
            trigger_event='PREPARE_PHASE',
            forced=False, limited=True,
            description='限定技，准备阶段，你可以将体力回复至上限，然后摸X张牌（X为你回复的体力值）。', faction='shu',
            implementation_status='active',
        )

class Skill_zhugeliang_19(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhugeliang_观星', name='观星',
            owner_hero_id='zhugeliang', skill_type='trigger',
            trigger_event='PREPARE_PHASE',
            forced=False, limited=False,
            description='准备阶段，你可以观看牌堆顶的五张牌（存活角色小于4时改为三张），并将其以任意顺序置于牌堆顶或牌堆底，若你将〖观星〗的牌都放在了牌堆底，则你可以在结束阶段再次发动〖观星〗。', faction='shu',
            implementation_status='active',
        )

class Skill_zhugeliang_20(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhugeliang_空城', name='空城',
            owner_hero_id='zhugeliang', skill_type='locked',
            trigger_event='BECOME_TARGET',
            forced=True, limited=False,
            description='锁定技，当你没有手牌时，你不能成为【杀】或【决斗】的目标。', faction='shu',
            implementation_status='active',
        )

class Skill_zhaoyun_21(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhaoyun_龙胆', name='龙胆',
            owner_hero_id='zhaoyun', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='你可以将一张【杀】当做【闪】、【闪】当做【杀】、【酒】当做【桃】、【桃】当做【酒】使用或打出。', faction='shu',
            implementation_status='active',
        )

class Skill_zhaoyun_22(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhaoyun_涯角', name='涯角',
            owner_hero_id='zhaoyun', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='当你于回合外因使用或打出而失去手牌后，你可以亮出牌堆顶的一张牌。若这两张牌的类别相同，你可以将展示的牌交给一名角色；若类别不同，你可弃置攻击范围内包含你的角色区域里的一张牌。', faction='shu',
            implementation_status='active',
        )

class Skill_machao_23(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='machao_马术', name='马术',
            owner_hero_id='machao', skill_type='locked',
            trigger_event='PASSIVE',
            forced=True, limited=False,
            description='锁定技，你计算与其他角色的距离时-1。', faction='shu',
            implementation_status='active',
        )

class Skill_machao_24(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='machao_铁骑', name='铁骑',
            owner_hero_id='machao', skill_type='locked',
            trigger_event='JUDGE',
            forced=True, limited=False,
            description='当你使用【杀】指定一名角色为目标后，你可以进行一次判定并令该角色的非锁定技失效直到回合结束，除非该角色交给你一张与判定结果花色相同的牌，否则不能使用【闪】抵消此【杀】且此【杀】伤害+1。', faction='shu',
            implementation_status='active',
        )

class Skill_huangyueying_25(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huangyueying_集智', name='集智',
            owner_hero_id='huangyueying', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='当你使用锦囊牌时，你可以摸一张牌。若此牌为基本牌，则你可以弃置之，然后令本回合手牌上限+1。', faction='shu',
            implementation_status='active',
        )

class Skill_huangyueying_26(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huangyueying_奇才', name='奇才',
            owner_hero_id='huangyueying', skill_type='locked',
            trigger_event='CARD_USED',
            forced=True, limited=False,
            description='锁定技，你使用锦囊牌无距离限制，你装备区内的防具牌和宝物牌不能被其他角色弃置。', faction='shu',
            implementation_status='active',
        )

class Skill_sunquan_27(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='sunquan_制衡', name='制衡',
            owner_hero_id='sunquan', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限一次，你可以弃置任意张牌并摸等量的牌，若你在发动〖制衡〗时弃置了所有手牌，则你多摸一张牌。', faction='wu',
            implementation_status='active',
        )

class Skill_sunquan_28(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='sunquan_救援', name='救援',
            owner_hero_id='sunquan', skill_type='lord',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='主公技，其他吴势力角色于其回合内回复体力时，若其体力值大于等于你，则该角色可以改为令你回复1点体力，然后其摸一张牌。', faction='wu',
            implementation_status='active',
        )

class Skill_ganning_29(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='ganning_奇袭', name='奇袭',
            owner_hero_id='ganning', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='你可以将一张黑色牌当做【过河拆桥】使用。', faction='wu',
            implementation_status='active',
        )

class Skill_ganning_30(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='ganning_奋威', name='奋威',
            owner_hero_id='ganning', skill_type='limited',
            trigger_event='BECOME_TARGET',
            forced=False, limited=True,
            description='限定技，当一名角色使用的锦囊牌指定了至少两名角色为目标时，你可以令此牌对其中任意名角色无效。', faction='wu',
            implementation_status='active',
        )

class Skill_lvmeng_31(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='lvmeng_克己', name='克己',
            owner_hero_id='lvmeng', skill_type='active',
            trigger_event='DISCARD_PHASE',
            forced=False, limited=False,
            description='弃牌阶段开始时，若你于本回合的出牌阶段内没有使用或打出过【杀】，则你可以跳过此阶段。', faction='wu',
            implementation_status='active',
        )

class Skill_lvmeng_32(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='lvmeng_勤学', name='勤学',
            owner_hero_id='lvmeng', skill_type='awaken',
            trigger_event='PREPARE_PHASE',
            forced=True, limited=False,
            description='觉醒技。准备阶段或结束阶段开始时，若你的手牌数减体力值大于1，则你减1点体力上限，回复1点体力或摸两张牌，获得技能〖攻心〗。', faction='wu',
            implementation_status='active',
        )

class Skill_lvmeng_33(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='lvmeng_博图', name='博图',
            owner_hero_id='lvmeng', skill_type='trigger',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='每轮限X次。回合结束时，若本回合内置入弃牌堆的牌中包含至少四种花色，则你可获得一个额外的回合。（X为存活角色数且至多为3）', faction='wu',
            implementation_status='active',
        )

class Skill_huanggai_34(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huanggai_苦肉', name='苦肉',
            owner_hero_id='huanggai', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限一次，你可以弃置一张牌，然后失去1点体力。', faction='wu',
            implementation_status='active',
        )

class Skill_huanggai_35(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huanggai_诈降', name='诈降',
            owner_hero_id='huanggai', skill_type='locked',
            trigger_event='PLAY_PHASE',
            forced=True, limited=False,
            description='锁定技。当你失去1点体力后，你摸三张牌。然后若此时是你的出牌阶段，则你本回合获得此下效果：使用【杀】的次数上限+1，使用红色【杀】无距离限制且不能被【闪】响应。', faction='wu',
            implementation_status='active',
        )

class Skill_zhouyu_36(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhouyu_英姿', name='英姿',
            owner_hero_id='zhouyu', skill_type='locked',
            trigger_event='DRAW_PHASE',
            forced=True, limited=False,
            description='锁定技，摸牌阶段摸牌时，你额外摸一张牌；你的手牌上限为你的体力上限。', faction='wu',
            implementation_status='active',
        )

class Skill_zhouyu_37(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhouyu_反间', name='反间',
            owner_hero_id='zhouyu', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限一次，你可以展示一张手牌并将此牌交给一名其他角色。然后该角色选择一项：展示其手牌并弃置所有与此牌花色相同的牌，或失去1点体力。', faction='wu',
            implementation_status='active',
        )

class Skill_daqiao_38(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='daqiao_国色', name='国色',
            owner_hero_id='daqiao', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限一次，你可以选择一项：将一张方片花色牌当做【乐不思蜀】使用；或弃置一张方片花色牌并弃置场上的一张【乐不思蜀】。选择完成后，你摸一张牌。', faction='wu',
            implementation_status='active',
        )

class Skill_daqiao_39(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='daqiao_流离', name='流离',
            owner_hero_id='daqiao', skill_type='trigger',
            trigger_event='BECOME_TARGET',
            forced=False, limited=False,
            description='当你成为【杀】的目标时，你可以弃置一张牌并将此【杀】转移给攻击范围内的一名其他角色（不能是此【杀】的使用者）。', faction='wu',
            implementation_status='active',
        )

class Skill_luxun_40(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='luxun_谦逊', name='谦逊',
            owner_hero_id='luxun', skill_type='trigger',
            trigger_event='BECOME_TARGET',
            forced=False, limited=False,
            description='每当一张延时类锦囊牌或其他角色使用的普通锦囊牌生效时，若你是此牌的唯一目标，你可以将所有手牌置于你的武将牌上，若如此做，此回合结束时，你获得你武将牌上的所有牌。', faction='wu',
            implementation_status='active',
        )

class Skill_luxun_41(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='luxun_连营', name='连营',
            owner_hero_id='luxun', skill_type='trigger',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='当你失去最后的手牌时，你可以令至多X名角色各摸一张牌（X为你此次失去的手牌数）。', faction='wu',
            implementation_status='active',
        )

class Skill_huatuo_42(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huatuo_急救', name='急救',
            owner_hero_id='huatuo', skill_type='trigger',
            trigger_event='CARD_USED',
            forced=False, limited=False,
            description='你的回合外，你可以将一张红色牌当做【桃】使用。', faction='qun',
            implementation_status='active',
        )

class Skill_huatuo_43(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huatuo_青囊', name='青囊',
            owner_hero_id='huatuo', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段，你可以弃置一张手牌，令一名本回合内未成为过〖青囊〗的目标的角色回复1点体力。若你弃置的是黑色牌，则你本回合内不能再发动〖青囊〗。', faction='qun',
            implementation_status='active',
        )

class Skill_lvbu_44(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='lvbu_无双', name='无双',
            owner_hero_id='lvbu', skill_type='locked',
            trigger_event='BECOME_TARGET',
            forced=True, limited=False,
            description='锁定技，①当你使用【杀】指定一名角色为目标后，其需使用两张【闪】才能抵消；②当你使用【决斗】指定其他角色为目标后，或成为其他角色使用【决斗】的目标后，其每次响应需打出两张【杀】。', faction='qun',
            implementation_status='active',
        )

class Skill_lvbu_45(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='lvbu_利驭', name='利驭',
            owner_hero_id='lvbu', skill_type='trigger',
            trigger_event='DAMAGE_DEALT',
            forced=False, limited=False,
            description='当你使用【杀】对一名其他角色造成伤害后，你可以获得其区域内的一张牌。若此牌不为装备牌，则其摸一张牌。若此牌为装备牌，则视为你对其选择的另一名角色使用一张【决斗】。', faction='qun',
            implementation_status='active',
        )

class Skill_diaochan_46(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='diaochan_离间', name='离间',
            owner_hero_id='diaochan', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限一次，你可以弃置一张牌，视为一名男性角色对另一名男性角色使用一张【决斗】（不可被【无懈可击】响应）。', faction='qun',
            implementation_status='active',
        )

class Skill_diaochan_47(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='diaochan_闭月', name='闭月',
            owner_hero_id='diaochan', skill_type='trigger',
            trigger_event='END_PHASE',
            forced=False, limited=False,
            description='结束阶段，你可以摸一张牌，若你没有手牌，则改为摸两张牌。', faction='qun',
            implementation_status='active',
        )

class Skill_huaxiong_48(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huaxiong_耀武', name='耀武',
            owner_hero_id='huaxiong', skill_type='locked',
            trigger_event='PASSIVE',
            forced=True, limited=False,
            description='锁定技，当你受到牌造成的伤害时，若此牌为红色，则伤害来源摸一张牌；否则你摸一张牌。', faction='qun',
            implementation_status='active',
        )

class Skill_huaxiong_49(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='huaxiong_势斩', name='势斩',
            owner_hero_id='huaxiong', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段限两次，你可以选择一名其他角色。该角色视为对你使用一张【决斗】。', faction='qun',
            implementation_status='active',
        )

class Skill_yuanshao_50(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='yuanshao_乱击', name='乱击',
            owner_hero_id='yuanshao', skill_type='active',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='出牌阶段，你可以将任意两张相同花色的手牌当做【万箭齐发】使用。', faction='qun',
            implementation_status='active',
        )

class Skill_yuanshao_51(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='yuanshao_血裔', name='血裔',
            owner_hero_id='yuanshao', skill_type='lord',
            trigger_event='PASSIVE',
            forced=False, limited=False,
            description='主公技，锁定技，场上每有一名其他群雄角色存活，你的手牌上限便+2。', faction='qun',
            implementation_status='active',
        )

class Skill_zhangjiao_52(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangjiao_雷击', name='雷击',
            owner_hero_id='zhangjiao', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='①当你使用【闪】或【闪电】，或打出【闪】时，你可以进行判定。②当你的判定的判定牌生效后，若结果为：黑桃，你可对一名角色造成2点雷电伤害；梅花：你回复1点体力并可对一名角色造成1点雷电伤害。', faction='qun',
            implementation_status='active',
        )

class Skill_zhangjiao_53(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangjiao_鬼道', name='鬼道',
            owner_hero_id='zhangjiao', skill_type='trigger',
            trigger_event='JUDGE',
            forced=False, limited=False,
            description='一名角色的判定牌生效前，你可以打出一张黑色牌作为判定牌并获得原判定牌。若你以此法打出的牌为黑桃2-9，则你摸一张牌。', faction='qun',
            implementation_status='active',
        )

class Skill_zhangjiao_54(RuntimeSkill):
    def __init__(self):
        super().__init__(
            skill_id='zhangjiao_黄天', name='黄天',
            owner_hero_id='zhangjiao', skill_type='lord',
            trigger_event='PLAY_PHASE',
            forced=False, limited=False,
            description='主公技。其他群势力角色的出牌阶段限一次，该角色可以交给你一张【闪】或黑桃手牌。', faction='qun',
            implementation_status='active',
        )

SKILL_REGISTRY = {
    'caocao_奸雄': Skill_caocao_01,
    'caocao_护驾': Skill_caocao_02,
    'simayi_反馈': Skill_simayi_03,
    'simayi_鬼才': Skill_simayi_04,
    'xiahoudun_刚烈': Skill_xiahoudun_05,
    'xiahoudun_清俭': Skill_xiahoudun_06,
    'zhangliao_突袭': Skill_zhangliao_07,
    'xuchu_裸衣': Skill_xuchu_08,
    'guojia_天妒': Skill_guojia_09,
    'guojia_遗计': Skill_guojia_10,
    'zhenji_洛神': Skill_zhenji_11,
    'zhenji_倾国': Skill_zhenji_12,
    'liubei_仁德': Skill_liubei_13,
    'liubei_激将': Skill_liubei_14,
    'guanyu_武圣': Skill_guanyu_15,
    'guanyu_义绝': Skill_guanyu_16,
    'zhangfei_咆哮': Skill_zhangfei_17,
    'zhangfei_替身': Skill_zhangfei_18,
    'zhugeliang_观星': Skill_zhugeliang_19,
    'zhugeliang_空城': Skill_zhugeliang_20,
    'zhaoyun_龙胆': Skill_zhaoyun_21,
    'zhaoyun_涯角': Skill_zhaoyun_22,
    'machao_马术': Skill_machao_23,
    'machao_铁骑': Skill_machao_24,
    'huangyueying_集智': Skill_huangyueying_25,
    'huangyueying_奇才': Skill_huangyueying_26,
    'sunquan_制衡': Skill_sunquan_27,
    'sunquan_救援': Skill_sunquan_28,
    'ganning_奇袭': Skill_ganning_29,
    'ganning_奋威': Skill_ganning_30,
    'lvmeng_克己': Skill_lvmeng_31,
    'lvmeng_勤学': Skill_lvmeng_32,
    'lvmeng_博图': Skill_lvmeng_33,
    'huanggai_苦肉': Skill_huanggai_34,
    'huanggai_诈降': Skill_huanggai_35,
    'zhouyu_英姿': Skill_zhouyu_36,
    'zhouyu_反间': Skill_zhouyu_37,
    'daqiao_国色': Skill_daqiao_38,
    'daqiao_流离': Skill_daqiao_39,
    'luxun_谦逊': Skill_luxun_40,
    'luxun_连营': Skill_luxun_41,
    'huatuo_急救': Skill_huatuo_42,
    'huatuo_青囊': Skill_huatuo_43,
    'lvbu_无双': Skill_lvbu_44,
    'lvbu_利驭': Skill_lvbu_45,
    'diaochan_离间': Skill_diaochan_46,
    'diaochan_闭月': Skill_diaochan_47,
    'huaxiong_耀武': Skill_huaxiong_48,
    'huaxiong_势斩': Skill_huaxiong_49,
    'yuanshao_乱击': Skill_yuanshao_50,
    'yuanshao_血裔': Skill_yuanshao_51,
    'zhangjiao_雷击': Skill_zhangjiao_52,
    'zhangjiao_鬼道': Skill_zhangjiao_53,
    'zhangjiao_黄天': Skill_zhangjiao_54,
}

HERO_SKILLS = {
    'caocao': ['caocao_奸雄', 'caocao_护驾'],
    'simayi': ['simayi_反馈', 'simayi_鬼才'],
    'xiahoudun': ['xiahoudun_刚烈', 'xiahoudun_清俭'],
    'zhangliao': ['zhangliao_突袭'],
    'xuchu': ['xuchu_裸衣'],
    'guojia': ['guojia_天妒', 'guojia_遗计'],
    'zhenji': ['zhenji_洛神', 'zhenji_倾国'],
    'liubei': ['liubei_仁德', 'liubei_激将'],
    'guanyu': ['guanyu_武圣', 'guanyu_义绝'],
    'zhangfei': ['zhangfei_咆哮', 'zhangfei_替身'],
    'zhugeliang': ['zhugeliang_观星', 'zhugeliang_空城'],
    'zhaoyun': ['zhaoyun_龙胆', 'zhaoyun_涯角'],
    'machao': ['machao_马术', 'machao_铁骑'],
    'huangyueying': ['huangyueying_集智', 'huangyueying_奇才'],
    'sunquan': ['sunquan_制衡', 'sunquan_救援'],
    'ganning': ['ganning_奇袭', 'ganning_奋威'],
    'lvmeng': ['lvmeng_克己', 'lvmeng_勤学', 'lvmeng_博图'],
    'huanggai': ['huanggai_苦肉', 'huanggai_诈降'],
    'zhouyu': ['zhouyu_英姿', 'zhouyu_反间'],
    'daqiao': ['daqiao_国色', 'daqiao_流离'],
    'luxun': ['luxun_谦逊', 'luxun_连营'],
    'huatuo': ['huatuo_急救', 'huatuo_青囊'],
    'lvbu': ['lvbu_无双', 'lvbu_利驭'],
    'diaochan': ['diaochan_离间', 'diaochan_闭月'],
    'huaxiong': ['huaxiong_耀武', 'huaxiong_势斩'],
    'yuanshao': ['yuanshao_乱击', 'yuanshao_血裔'],
    'zhangjiao': ['zhangjiao_雷击', 'zhangjiao_鬼道', 'zhangjiao_黄天'],
}

def get_hero_skills(hero_id):
    return [SKILL_REGISTRY[sid]() for sid in HERO_SKILLS.get(hero_id, [])]

def get_all_skills():
    return [cls() for cls in SKILL_REGISTRY.values()]

__all__ = ['SKILL_REGISTRY', 'HERO_SKILLS', 'get_hero_skills', 'get_all_skills']
