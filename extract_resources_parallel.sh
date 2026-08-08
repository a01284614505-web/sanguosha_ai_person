#!/bin/bash
echo "=== [P0-3] 开始提取卡牌资源 ==="
mkdir -p extracted_resources/cards

CARDS="sha shan tao jiu guohe shunshou wuxie juedou huogong tiesuo bingliang wanjian nanman taoyuan wugu jiedao"
count=0
for card in $CARDS; do
  if cp /storage/emulated/0/Download/sanguosha/sanguosha_data/noname-main/apps/core/image/card/${card}.png extracted_resources/cards/ 2>/dev/null; then
    count=$((count+1))
    echo "  ✓ ${card}.png"
  fi
done

cd extracted_resources
zip -q -r noname_cards_complete.zip cards/
cp noname_cards_complete.zip /storage/emulated/0/Download/sanguosha/

echo "[P0-3] 完成：${count}个卡牌文件"
echo "[P0-3] 输出：noname_cards_complete.zip"
