from review_notes import *
native([0,1,2])
seq(0,1,'原生全景复核仪器下方与右下边缘，白色支架/灰色弧面混合，库存旧备注提及灰球而当前人工negative，不能可靠排除真实足球，保留冲突。',scene='retain')
seq(591,594,'原生全景见红衣人左手下白灰圆形球体/弧面，手部遮挡且小，但现空label和No Ball=1存在可见物体冲突，保留核查补框。',scene='retain')
seq(605,608,'原生全景已检查地板、底边与桌脚，远处人物手侧极小白灰片段仍不能可靠区分球/手，现negative场景保留。',scene='retain')
seq(609,610,'原生全景仅手臂、近处机器结构、地砖/门边，未见可见足球；当前Blurred=1与部分清楚区域需核查，保留场景模糊项。',scene='retain')
seq(611,612,'原生全景展示架在右上边缘露出白黑足球片段而当前空label，人工negative与可见球冲突，保留补框复核。',scene='retain')
seq(619,620,'原生全景检查手臂周围、展示机器边缘与底边，只有机器金属结构，无可见足球，整体有运动晃动。',flags={'Small':'0','Occluded':'0','Blurred':'1','No Ball':'1'})
add([635],'原生全景检查机器脚后、侧边及最下沿，只有机器人、人物鞋和地毯白纸标记，无可见足球。')
add([636],'原生全景检查机器人身后与最下沿，无可见足球；整图有轻微运动晃动。')
# Restore native evidence after note replacements.
native([0,1,2]);save()
