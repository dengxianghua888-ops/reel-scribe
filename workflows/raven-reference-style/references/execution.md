# 从机制到同一作品

read当前作品→观察目标素材→迁移矩阵→已决参数→scope候选→提交→导出→回读。不因更换参考而重新初始化同一作品。原风格和人工修改默认保持，只有请求中的维度开放。

LUT作用于素材时先对选中镜头做明确派生，保留source→normalization→LUT→derived时间和hash链；目标新素材ID引用派生文件、时间按派生原点映射。不能沿用指向原文件的证据单位而谎称直接覆盖派生hash，应显式保留推导关联并检查区间。

LUT不能重复烧录；重新选look从未调色的同一源派生，保留音轨。全片输出再调会一起改字幕色；若用户只要画面色调，应在字幕叠加前调素材。原子当前只接零起点CFR、8bit YUV、BT.709 SDR；原素材不满足时先用已有timeline-render明示重采样成指定工作片，不能把重采样说成原始帧一一对应。

选LUT前可用color-profile-scan以相同analysis_size、采样密度和区间语义分别测量参考与目标，把影调分位数、色度、中性偏移、调色板等差值写入迁移矩阵作为参考证据；参考与目标必须用同一种色彩解释（bt709-sdr或srgb-sdr）测量，照片类素材先用still-color-normalize转为sRGB再渲染。参数化look用color-grade-compile编译，interpretation与素材传递函数一致；提亮时在曝光后接highlight_rolloff，并复测高光裁切比例；调色后对派生素材复测，只能证明数值朝声明方向移动，不能证明更好看或已复刻参考。多个look比较用相同镜头/时间/文字/音量，差异只在LUT。

色彩维度的可执行链路：①选定色彩类风格卡，先查它的参数模板（`color_parameters`）里的禁用条件，命中就不做参考拟合，改用显式参数或放弃该维度；②用color-reference-fit，方法从模板的fit_methods中选，`bounds`取模板的fit_bounds，得到`adopted:false`的草案和迁移前后距离；距离变小只是证据，跨内容或跨光线时尤其不能据此判断像不像；③草案作为作品调色层（timeline-revise或style-recipe的color_grade参数组），强度不超过模板strength_max，按模板的建议保护项声明protections，经work-render的调色门禁和预览A/B比较；④看过预览的口头反馈按调色反馈合同的映射表换成累计步数，用color-grade-adjust并以模板adjust_caps收紧上限，再重新预览。每一步都只产生候选，采用仍走作品的版本与范围检查。叙事结构比较固定可比素材范围，必要改变清楚登记，不能凭镜长比例合格认定迁移成功。任何新素材、文字、音轨或派生来源都通过scope，不绕过版本检查。

冻结位置和冻结内容分开；继承主风格，把本轮参考profile及策略放notes。已许可的参考资产复用与抽象机制借鉴是两种行为，来源表分别记录。
