# 真实局部机制、独立参考与视觉增量验收

本节云端证据文件名是验收记录中的定位，不表示仓库内含这些视频或回执；媒体未入仓，不凭缺失的在线链接声称读者可完整重现。

本次只执行已有能力，不修改runtime、不提交Work、不改变九卡或catalog的authored-unvalidated状态。四个最终操作回执所列源码均与当时冻结版本匹配，其中reference_transfer_ops SHA256为`8d6de467d0e102b7c0f52666a361d80c427f88781d56caf565c2e05e47241aaf`。这是原创卡机制试验，不是观察独立参考片后的迁移复刻；两卡均未达到whole-style-validated。

## 素材、改动与许可

Nikkimaria，WikEdtutorial1.webm，CC BY-SA 3.0：
https://commons.wikimedia.org/w/index.php?title=File:WikEdtutorial1.webm&oldid=1131672871
https://creativecommons.org/licenses/by-sa/3.0/

使用已有25–31秒派生源，原始归属和归一化记录保存在相邻`reel-real-evaluation/normalization-provenance.json`。评估修改包括局部裁切放大、显式橙色定位框、评估字幕及独立声轨混合；输出不是原作者未改动原片。现screen-focus把音轨stream-copy进MP4，已有源是PCM MOV；试验当时主动创建显式AAC副本：视频copy，音频有损AAC，不能宣称音频相对原源无损。后续独立实测当前FFmpeg将该PCM直接copy进MP4或MOV均成功，完整解码PCM与原源相同，故AAC副本并非已证明必需，不能据此宣称当前容器故障。兼容副本命令和前后SHA在compatibility-derivative.json。向外分发修改样片需保留作者、链接、许可证和改动声明及适用的相同方式共享条件；本次未公开发布。

## 阅读优先教学：固定字段聚焦，而非仅字号

真实源为1920×1080。显式选区`x260,y360,w1340,h670`，同尺寸输出；原源0–3秒在字段区画固定定位框。相对完整画面缩到960px的展示，这保留更多字段细节，但不是恢复原本没有的信息、不是OCR、不是自动定位。2秒抽帧可直接读到`library_name = Irving K. Barber Learning Centre`、`image = ikblclearningcentre.jpg`、`location = [[Vancouver]], [[Canada]]`。高亮框是编辑提示，不是软件原生状态。

**有限结论：**真实字段聚焦、时间不变及固定框机制可执行；未验证观看者能完成任务。裁切牺牲浏览器入口、完整上下文及右侧长段落，不能当完整教程交付。原素材后段光标移到右上Preferences，已不在此裁切范围，因此用户样片仅取0–3秒阅读窗口，不能全程套用这个裁切。

初次试验错误地把960px展示坐标直接用于1920px源，导致标题/字段截断。失败图`reading-2s.png`保留；修正后为`reading-corrected-2s.png`，不覆盖原错误证据。工具合同的源坐标约束有效，但不会判断选区是否选对。

## 局部采用：首段改画面提示，后段保留

独立Work分为源0–3秒与3–6秒两个连续段，仅首段改为完整画面的定位框派生源；后段保持原source身份与原窗。字幕位置/文本、全局字号、音轨定义及时间映射保持不变。候选diff只有`first`和新增`focused`源变化；没有字幕、音轨、后段位置或duration变化；Work未commit。

首次候选正确拒绝`CAPTION_REVIEW_SCOPE_REQUIRED`，仅明确允许首段字幕声画复核后又正确拒绝`AUDIO_REVIEW_SCOPE_REQUIRED`，因为跨段独立音轨也覆盖被替换视觉源。最终显式声明first-label及original-audio的复核scope，并核两者内容未改；这不是跳过复核，也不能把scope名单等同逐条内容不可改的额外锁。后段字幕恶意变更负例失败（见out-of-scope-result.json）。

1秒实际帧可见字段定位框，4秒帧已无新增框并返回原画面上下文；后段原素材的箭头仍保留。全音视频解码通过。基准/候选解码PCM完全相同；后段原source、源窗、字幕与声轨定义精确一致。**编码后后段RGB并不逐像素相同**：4秒抽帧RGB平均绝对差约0.361/0.323/0.428（0–255），最大21/17/22；整体后段RGB摘要不同。重新编码导致保持原编辑内容不等于无损拼接，不宣称像素严格冻结。未进行完整听审、审美或用户偏好验证。

## 云端验收样片（不随源码包分发，交付需附本归属声明）

- 阅读窗口3秒：`reading-window-3s.mp4`
- 局部采用6秒候选：`candidate-render/captions/captioned.mp4`
- 局部采用6秒基准：`base-render/captions/captioned.mp4`
- 对照抽帧：`reading-corrected-2s.png`、`candidate-1s.png`、`candidate-4s.png`、`base-4s.png`
- 精确记录：`result.json`、`decode-checks.json`、各操作receipt.json。

## 最小后续实现提案，不标为外部阻塞

1. **坐标准备器**：接收实际probe尺寸、展示尺寸和显式矩形，输出可回查源坐标+预览图；禁止悄悄用展示坐标。仍需人工确认目标，不假装自动UI理解。两套1920/960等比正例、非等比/旋转拒绝及越界负例可覆盖。
2. **显式容器选择增强（非已复现故障修复）**：当前FFmpeg下PCM复制至MP4/MOV均实测成功；若扩展目标编辑器容器选择，应保留原默认、明确音频copy及支持范围，验证PCM摘要保持；不因未知宿主兼容性推断必须转AAC，不新增隐式有损转码或付费服务。
3. **证据型产品演示剩余机制**：现有wikEd窗口没有足够保存并重开成品证据，不能靠换卡名继承通过。最小可实现扩展是既有tutorial proof中显式`artifact-check`事件（画面/文件hash、检查窗口、已执行检查声明、对应result依赖），先拒绝提前成功与缺产物检查，再用合法录屏实际保存后重开窗口验证。自动证明“保存成功”仍不成立；无需重写Work或加新权威。

## 独立叙事参考：从公开茶杯教程到原教程目标

Fun with Open Source，《Blender Tutorial. A cup of tea.》，2018-06-18，CC BY3.0；[固定许可页](https://commons.wikimedia.org/w/index.php?title=File:Blender_Tutorial._A_cup_of_tea..webm&oldid=1032137577)记录2020年许可核查，不代表每项第三方权利的独立法律核验。下载Commons官方426×240转码，22,273,840字节，SHA256 `815b9774dfb3a4083ebca6fa579ef1f5c3774352bb8c8423dd6a2d0e3c57bb4c`；全片解码通过。

实际查看2/20/30秒独立帧，20秒茶杯/茶包/糖块/碟子成图，30秒Blender简单柱状网格。请求仅将20和30秒单帧长度区间声明为观察；外层包络不表示连续看过。可支持明确选择“成图预览→制作过程”的顺序机制，但没有核完整制作过程、音频、因果或操作正确性，240p也不适合读参数。

冻结运行时下实际执行参考准备→权威目标编译→44秒渲染及全解码。目标仍是受保护wikEd原40秒流程，新增4秒同源后段预览；原clips/sources/protection精确保留，Work不提交改变。实际查看成片2/5/42秒帧的预览与返回标签及后段UI。输出SHA256 `5200dafa5849af3d11d70d1e66ae6c26fa2734e866bb20dde4dd35a3dc13f4c8`，与先前同机制目标一致；新增的是独立参考依据和完整技术链，不是新创意或美学提升。6份回执的43个运行时文件身份相同。完整看听、跨品类迁移和用户效果仍未验。

## 参考来源报告的纠正

独立复核发现旧`reference_media_in_output:false`不成立：同源参考本来就可能存在于目标作品。报告升级`reference-transfer/2`，删除该字段，改为“准备动作未新增参考媒体”、按SHA列当前plan/audio/visual来源匹配、实际成片存在性`NOT_EVALUATED`。同SHA异路径可匹配，未消费来源也可列出；不同SHA的派生不匹配，不代表它不含参考内容。不得用该报告证明版权隔离或实际消费。独立边界检查和新增测试覆盖同源/异源/异路径/三种来源集合；不改变已有目标编辑行为。

## 真实摄影视觉层的有限增量验证

此前教程缺可信色彩定义的失败不改为通过。新增检索的官方Spring360p、WING IT!480p/1080p文件也缺四项色彩字段；1080p H264头未提供video_signal_type，未仅改标签冒充bt709。

转而使用Hannes Röst的真实摄影[Fronalpstock_big.jpg](https://commons.wikimedia.org/wiki/File:Fronalpstock_big.jpg)，从多许可中选CC BY-SA3.0。原JPEG SHA256 `24eb29eccdf0af691b406d1a3d22c0ef5d761cc454d8a917848c33958f6fc857`，实际嵌入3144字节`sRGB IEC61966-2.1` ICC（SHA256 `2b3aa1645779a9e634744faf9b01e9102b0c9b88fd6deced7934df86b949af7e`），EXIFColorSpace=1。经ICC色管、明确左上10000×4500裁切/800×360缩放、zscale执行sRGB传递函数到bt709传递函数/矩阵/limited range转换，编码2秒H264静态载体并添加声明静音。不是给未知视频贴标签；有损编码、裁切、缩放均披露。原图保持不变。

原始ICC只是可信的输入编码声明，不是校准场景/显示器测量。此为真实照片静态载体，不是动态实拍视频或原片音频。

两个候选只改既有视觉层rect/opacity/z；实际timeline1次、visual-layer-render与QC各2次，分别与独立不共享渲染的全RGB/PCM摘要一致，两个候选RGB确实不同；Work不变。19份回执运行时身份一致且子回执链接核验通过。实际观察各1秒帧：同山景底图、缩放叠层，位置/透明度/叠放关系有变化。不是全片看听或色彩保真校准。首次候选与原文档相同正确触发NO_CHANGE_TO_PREVIEW，保留失败，再显式构造不同候选，未改运行时绕过。

向外提供照片改编样片应署名作者、原图、CC BY-SA3.0及上述修改，适用相同方式共享条件。源照片与视频均不入仓。
