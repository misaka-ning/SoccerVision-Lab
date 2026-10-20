from review_notes import *
opened(full=[24],roi=[48,49])
seq(1152,1155,'机器人和黄裤腿前空标，需原生检查黑机器脚、黄鞋旁和下边缘是否有足球残片。',scene='retain',label='retain')
seq(1156,1179,'入口人物左鞋/墙边约14至26 px白黑候选球，部分裁边或球纹难辨，候选与鞋/背景物体的身份、完整外缘和框覆盖不足以高置信度通过。',scene='retain',label='retain')
seq(1180,1181,'入口全景强晃动且空标注，需原生查看下缘、鞋旁与两侧足球是否露出。',scene='retain',label='retain')
seq(1182,1199,'机器人前地毯小球约25至34 px，黑白拼块可隐约识别但球缘和内部纹理明显软化；当前Blurred=0与球体模糊需核查，框贴合亦无法高置信度核实。',scene='retain',label='retain')
save()
