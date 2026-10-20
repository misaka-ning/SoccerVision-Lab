from review_notes import *
opened(full=[20],roi=[40,41])
seq(960,1007,'灰地毯前方与机器人旁背景各有蓝白足球，前球清楚，背景球完整尺寸约38至49 px处Small临界且面板较软，场景保留。',scene='retain',label='approve_positive')
add([961,973,977,981,982,988,991,1000],'前方足球清楚，背景足球最上白色球缘越过现框上边（或边缘覆盖不足），不能通过现label；Small亦临界。',scene='retain',label='retain')
save()
