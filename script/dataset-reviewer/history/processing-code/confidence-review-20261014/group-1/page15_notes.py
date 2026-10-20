from review_notes import *
opened(full=[15],roi=[30,31])
seq(720,727,'墙脚地毯蓝白足球仅下缘或右缘由图像截断，球纹可辨，球前方没有物件覆盖；对应完整球长边约50 px。',flags={'Small':'0','Occluded':'0','Blurred':'0','No Ball':'0'})
seq(728,743,'墙脚蓝白球出现裁边或尺寸约35至40 px，当前部分Occluded=1可能来自裁切；完整Small尺度及轻微球面模糊不可靠。',scene='retain')
seq(744,747,'墙脚球尺寸约39至44 px且部分右缘裁切，完整Small尺寸处阈值附近，保留场景审核。',scene='retain')
seq(748,763,'墙脚地毯蓝白球独立放置，右图整球长边约46至47 px，左图仅右边缘裁切；球面纹理可辨，无前景覆盖或明确方向拖影。',flags={'Small':'0','Occluded':'0','Blurred':'0','No Ball':'0'})
seq(764,765,'墙脚蓝白球与整体画面有明显晃动，当前Blurred=0且长边约41至44 px，分类保留。',scene='retain')
seq(766,767,'灰地毯近处和墙脚各一球，整图晃动、两球外缘软化，Small完整尺度与拖影边界不可靠。',scene='retain')
save()
