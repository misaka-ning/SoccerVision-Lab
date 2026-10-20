from review_notes import *
opened(full=[23],roi=[46,47])
add(range(1104,1132,2),'机器人黑色前景盖住蓝白足球左球缘，剩余星纹和右/下外缘清楚；现框含全部可见足球，四边没有遗漏球面，完整球约83 px。',label='approve_positive',flags={'Small':'0','Occluded':'1','Blurred':'0','No Ball':'0'})
add(range(1105,1132,2),'机器人右侧蓝白球完整，球与黑前景有间隔；星纹和圆形外缘清楚，现框含完整球体，无误框、漏球或内纹重复。',label='approve_positive')
seq(1132,1147,'灰地毯蓝白足球完整，机器人已经移开球缘，白色拼块与蓝星纹清楚；现框包住全部四边可见外缘，没有其他漏球。',label='approve_positive')
seq(1148,1151,'机器人及黄裤腿前当前空label，需原生检查脚下、底边与身体后的足球，暂保留。',scene='retain',label='retain')
save()
