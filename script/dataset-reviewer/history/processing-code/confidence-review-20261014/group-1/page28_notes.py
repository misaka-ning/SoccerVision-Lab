from review_notes import *
opened(full=[28],roi=[56,57])
seq(1344,1345,'近处机器人挡住画面下沿，当前空框须原生检查脚下和底边球面。',scene='retain',label='retain')
seq(1346,1347,'机器人旁足球球面明显软化且黑前景贴近侧缘，现框四边是否包含球边不清。',scene='retain',label='retain')
seq(1348,1383,'电视支架前地毯静止小足球，白色拼块与黑色星形接缝可辨、圆形外缘连续，原生约24至29 px；现框四边覆盖全部可见球体，支架/机器人与球分离，无漏球或重复框，属于Small。',label='approve_positive')
seq(1384,1385,'机器人黑脚经过小球前方，球纹与边界明显软化，遮挡范围和框边不可靠。',scene='retain',label='retain')
seq(1386,1387,'机器人与黑衣人挡住球原位置，空框需原生查脚后和最下缘。',scene='retain',label='retain')
seq(1388,1391,'机器人或鞋旁小球约25至30 px，球面和全景有晃动/软化，现框边缘与前景脚覆盖不可靠。',scene='retain',label='retain')
save()
