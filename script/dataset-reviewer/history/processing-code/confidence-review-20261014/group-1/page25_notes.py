from review_notes import *
opened(full=[25],roi=[50,51])
seq(1200,1217,'地毯小足球完整约28至31 px，白黑拼块可辨且连续圆形外缘可定位；现框覆盖可见球四边，未误框或漏球；球面略软、当前Blurred=0需保留场景核查。',scene='retain',label='approve_positive')
seq(1218,1225,'黑衣人鞋尖或机器人脚旁小球，球面软化并贴近前景脚，顶部可见范围、是否Occluded与框完整覆盖不可靠。',scene='retain',label='retain')
seq(1226,1229,'机器人脚间足球原位置当前空框，须原生核查脚下是否仍有可见球面。',scene='retain',label='retain')
seq(1230,1243,'人或机器人脚旁约17至24 px小球候选，白黑拼块与上球缘软化并贴近鞋，框四边和遮挡证据无法高置信度核实。',scene='retain',label='retain')
seq(1244,1247,'人物与展示架场景空label，需原生检查最下缘、展示架下方与左右边缘球片。',scene='retain',label='retain')
save()
