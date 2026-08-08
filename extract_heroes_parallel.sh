#!/bin/bash
echo "=== [P0-4] 开始提取皮肤资源 ==="
mkdir -p extracted_resources/heroes

HEROES="caocao simayi xiahoudun zhangliao xuzhu guojia zhenji liubei guanyu zhangfei zhugeliang zhaoyun machao huangyueying sunquan ganning lvmeng huanggai zhouyu daqiao luxun sunshangxiang huatuo lvbu diaochan huaxiong yuanshao"

total=0
for hero in $HEROES; do
  mkdir -p extracted_resources/heroes/$hero
  count=$(ls /storage/emulated/0/Download/sanguosha/sanguosha_data/noname-main/apps/core/image/character/*${hero}*.jpg 2>/dev/null | wc -l)
  if [ $count -gt 0 ]; then
    cp /storage/emulated/0/Download/sanguosha/sanguosha_data/noname-main/apps/core/image/character/*${hero}*.jpg extracted_resources/heroes/$hero/ 2>/dev/null
    echo "  ✓ ${hero}: ${count}个皮肤"
    total=$((total+count))
  fi
done

cd extracted_resources
zip -q -r noname_heroes_skins_complete.zip heroes/
cp noname_heroes_skins_complete.zip /storage/emulated/0/Download/sanguosha/

echo "[P0-4] 完成：${total}个皮肤文件"
echo "[P0-4] 输出：noname_heroes_skins_complete.zip"
