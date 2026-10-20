from review_notes import *
seq(898,899,'原生全景检查近处机器人边缘及底边，背景仅人物、地毯、支架，无可见足球。')
seq(1016,1017,'原生全景最下缘明确露出足球白色弧面，现label为空，必须补可见球框，不可通过negative。',scene='retain',label='retain')
add([1019],'原生全景上左地毯明确有足球及运动拖影，现label为空，需要补球框。',scene='retain',label='retain')
seq(1032,1033,'原生全景黄鞋前明确足球完整可见、星形拼块可辨而label为空，必须补框。',scene='retain',label='retain')
seq(1148,1155,'原生全景逐查机器人腿间、金属脚后、黄鞋旁和四条画面边缘，仅机器人与人物鞋/地毯，无可见足球；空label可确认为无球。',label='approve_negative',flags={'Small':'0','Occluded':'0','Blurred':'0','No Ball':'1'})
add([1157,1159,1163],'原生全景地面主体未见球，但左画面边缘白灰片段是否残留球与鞋/圆柱底座难区分，保留empty审核。',scene='retain',label='retain')
native([12,13,14]);save()
