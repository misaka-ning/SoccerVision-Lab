from review_notes import *
add([1165],'原生全景地面主体无球，但左画面边缘白灰片段是否为球的残留弧面仍需放大，保留空label。',scene='retain',label='retain')
seq(1180,1181,'原生全景入口圆柱旁白衣人鞋侧明确有白黑足球片段，足球与整图明显拖影，label为空，应补球框而不能通过negative。',scene='retain',label='retain')
seq(1226,1229,'原生机器人脚间/身后白灰片段与人物鞋、金属脚混合，无法可靠确认是否仍有可见足球，保留visibility审核。',scene='retain',label='retain')
seq(1244,1248,'原生全景逐查展示架下方、电视支架、人物鞋、边缘机器人和最下沿，只有摆件/机器及地毯，没有可见足球，空label可确认为无球。',label='approve_negative',flags={'Small':'0','Occluded':'0','Blurred':'0','No Ball':'1'})
native([15,16]);save()
