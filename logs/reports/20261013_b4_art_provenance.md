# B4 新增牌图来源与生成提示

- 时间：2026-10-13 10:14–10:31 UTC。
- 生成方式：Codex 内置 `image_gen`，每张牌独立调用；工具未公开底层图像模型型号。原图保留于该次 Codex 生成目录，项目内 PNG 经等比例缩小到不超过 240×320，未裁切或覆盖原仓库文件。
- 筛选：逐张检查缩略图主体与牌名对应，不含牌名文字、官方标志和已有三国杀牌面的复制。
- 可复核数据：`20261013_b4_art_manifest.json` 逐张列出生成文件名、原图和项目图 SHA-256、字节数。`20261013_b4_art_matrix.md` 列出全部 42 种牌的最终映射。

## 提示词集

以下各行将牌名和主体代入对应类别的提示词。武器、防具和木牛使用“small portrait game card illustration; refined hand-painted digital ink wash, tactile parchment texture, rich restrained colors, clear silhouette at thumbnail scale; object centered; no people, writing, numbers, border, logo, watermark, or similarity to existing Sanguosha art”。坐骑使用相同画风，并要求“horse fully recognizable, no rider”；锦囊使用“atmospheric ancient Chinese scene”。

| 牌名 | 主要画面指令 |
|---|---|
| 诸葛连弩 | 木制连弩、匣中箭矢和铜制机件 |
| 雌雄双股剑 | 一银一铜的双剑交叉、不同剑柄 |
| 青釭剑 | 青绿色剑身，斜置于风化岩石 |
| 寒冰剑 | 覆霜长剑、冰河与冷雾 |
| 青龙偃月刀 | 新月形大刀、绿色龙纹刀座 |
| 丈八蛇矛 | 双叶形矛头、红缨与战场岩石 |
| 贯石斧 | 重战斧劈裂岩块、石屑与火花 |
| 方天画戟 | 对称月牙侧刃的长戟与风暴云 |
| 麒麟弓 | 弓柄麒麟纹、张弦与旁置箭矢 |
| 古锭刀 | 厚重古刀、青铜环首与岩石 |
| 朱雀羽扇 | 赤羽扇与火星，不画真实鸟 |
| 八卦阵 | 八卦几何纹样的圆形铜盾 |
| 仁王盾 | 守护者面纹的深铁盾 |
| 白银狮子 | 狮面银甲和分节甲片 |
| 藤甲 | 编织藤条护甲与皮革系带 |
| 木牛流马 | 牛形木制军用运输车、木齿轮与箱体 |
| 绝影 | 月下奔跑的黑色战马 |
| 的卢 | 跃过山涧的灰白花马 |
| 爪黄飞电 | 阳光和尘土中的金黄色战马 |
| 赤兔 | 烈焰色奔马，保持真实马体结构 |
| 大宛 | 沙漠绿洲中的栗色大宛马 |
| 紫骍 | 暮色中紫棕色战马 |
| 骅骝 | 秋草中浅栗色奔马 |
| 无中生有 | 空书案上由白纸生出的卷轴与光 |
| 乐不思蜀 | 宴席、未用的地图、窗外远路 |
| 闪电 | 暴风中的闪电击中青铜古塔 |

## 外部素材调查

Luna（`gpt-6-luna`）检查 GitHub 等来源，未找到许可明确且能覆盖 26 张的整套素材。候选 [QSanguosha 的 README](https://github.com/Mogara/QSanguosha) 明示美术素材为 CC BY-NC-ND 4.0，故没有复制其图。原仓库已有的 16 张牌图来源尚未在本批核验。
