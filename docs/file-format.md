# OmniGraffle `.graffle` 文件格式调研

> 结论先行：**可以由 Agent 直接生成。** `.graffle` 本质是 *zip 包 + Apple property list*，
> 结构完全是明文的“对象树”（形状、连线、文本、样式、图片引用），没有加密，也没有私有二进制编码。
> 本仓库的 `ogkit` 已实现读、写、渲染与校验，并在你的 120 个历史文件上验证过：
>
> | 验证项 | 结果 |
> |---|---|
> | 读取 → 写回 → 再读取（plist 深比较 + 资源比较） | **120/120 无差异** |
> | 富文本 RTF 解析 → 生成 → 再解析（字体/字号/颜色/粗斜体/文本） | **10 541/10 541 段无差异** |
> | Linux 下渲染全部 120 个文件 | **120/120 成功**，与 OmniGraffle 自带预览目测一致 |
> | 生成文件结构校验（键名必须在真实文件中出现过、ID/引用一致） | 所有示例 **通过** |
>
> 唯一无法在本机完成的是“用 OmniGraffle 本体打开”（它只在 macOS 上运行），因此第一次在 Mac 上打开时请顺手检查一下，
> 见文末《在 Mac 上验收》。

---

## 1. 容器格式

OmniGraffle 7 支持三种存储方式，`ogkit.gio.load()` 全部支持：

| 形式 | 识别方式 | 内容 |
|---|---|---|
| **zip 单文件**（默认，你的 120 个文件全部是这种） | 文件头 `PK` | `data.plist`（**二进制** plist）、`preview.jpeg`（Finder/QuickLook 缩略图）、`image1.pdf`、`image2.png` … |
| package 目录 | `.graffle` 是文件夹 | 同上，只是不压缩 |
| 旧版 flat 文件（OG 5/6） | 文件头 `1F 8B`（gzip）或 `<?xml` | 单个（可 gzip 的）XML plist |

```
Claude Usage Demo.graffle  (zip, deflate)
├── data.plist      14 KB   ← 整个文档
├── preview.jpeg   124 KB   ← 可选，仅缩略图
└── image1.png       1 KB   ← 嵌入素材，名字固定为 image<ImageID>.<ext>
```

`ogkit.gio.save()` 永远写 zip 形式（与 OmniGraffle 7 自己保存的一模一样），并用我们的渲染器生成 `preview.jpeg`，所以在 Finder 里能直接看到缩略图。

## 2. 文档（`data.plist` 顶层）

```text
GraphDocumentVersion = 16            # OG7 文档版本（全部 120 个文件都是 16）
ApplicationVersion   = ["com.omnigroup.OmniGraffle7", "205.39.11"]
Creator / Modifier   = "Chuanbo Hua"
CreationDate / ModificationDate      # <date>
Sheets               = [ <sheet>, ... ]      # 画布（一个文件可有多页：Version 1, Version 2…）
ImageList            = ["image3.pdf", "image2.png", ...]   # 嵌入资源名（新的在前）
ImageCounter         = 4                    # 下一个可用的 ImageID
ImageLinkBack        = [{}, ...]            # 与 ImageList 等长
ColorProfiles        = [{space: <sha1>, data: <ICC>}]       # 取色器取到的 Display P3 / sRGB 配置
PrintInfo, WindowInfo, export*Key, ...      # 打印/窗口/导出设置，原样保留即可
```

## 3. 画布（Sheet）

```text
SheetTitle      "Canvas 1"
GraphicsList    [ ... ]        # ★ 所有图元；顺序 = 从最上层到最下层（front-to-back）
Layers          [{Name, View, Print, Lock, Artboards}]   # 图元用 "Layer": i 引用
CanvasSize      "{831, 366}"   CanvasDimensionsOrigin "{104, 230}"
BackgroundGraphic {...}        # 画布背景（ID 0）
ExportShapes    [ ... ]        # ★ 自定义形状（pdfImport-*）的矢量路径定义
GridInfo, LayoutInfo, AutoAdjust, CanvasSizingMode, ...
```

坐标单位是 pt，原点左上角，y 向下。几何量全部以 **字符串** 存储：`"{x, y}"`、`"{{x, y}, {w, h}}"`。

## 4. 图元（Graphic）

全部语料中只出现了 4 个类：

| Class | 数量 | 作用 |
|---|---|---|
| `ShapedGraphic` | 33 837 | 矩形/圆/三角/贝塞尔/自定义形状、文本框、图片 |
| `LineGraphic` | 9 421 | 连线、箭头 |
| `Group` | 581 | 编组（`Graphics` 子列表） |
| `TableGroup` | 33 | 表格（`GridH`、`Graphics`） |

### 4.1 ShapedGraphic

```text
ID          27                     # 页内唯一
Bounds      "{{477, 233}, {60, 29}}"
Shape       缺省=矩形 | Circle | HorizontalTriangle | RightTriangle | Parallelogram | Diamond |
            AdjustableArrow | AdjustableStar | Bezier(+ShapeData.UnitPoints) | pdfImport-378(自定义)
Style       { fill:{Draws, Color, FillType, GradientColor, GradientAngle, MiddleFraction},
              stroke:{Draws, Color, Width, CornerRadius, Pattern, Cap, Join},
              shadow:{Draws, Color, ShadowVector, Fuzziness} }
Text        { Text: <Cocoa RTF>, Pad, VerticalPad, Align }
FontInfo    { Font, Size, Color }   # 新输入文字的默认字体
FitText/Flow/Wrap   "YES"/"Resize"/"NO"   # 自动尺寸的纯文本标签
TextPlacement 0 顶 / 1 中(默认) / 2 底;  TextRelativeArea, TextRotation
ImageID, StretchImage, ManualSizeImage, Scale, Offset   # 图片
Rotation, HFlip, VFlip, Opacity, IsLocked, Name, Layer, Magnets
Line        {ID, Position, RotationType}   # 若存在：这是“贴在连线上的标签”
```

**默认值陷阱**（生成时必须显式写出）：缺省 `fill` 为白色、`stroke` 为 1pt 黑线、`shadow` **默认是开启的**。
你的文件里 97.7% 的图元都显式写了 `shadow: {Draws: NO}`，`ogkit` 生成时也总是写上。

### 4.2 颜色

```text
{"r": .4, "g": .4, "b": .4, "space": "srgb"}              # sRGB（最常见，44 089 次）
{"w": "0", "space": "gg22"}                                # 灰度（13 954 次）
{"r": .98, "g": .73, "b": .66, "space": "a029ace0…"}       # 指向 ColorProfiles 里的 ICC（Display P3）
{..., "a": 0.1}                                            # 透明度 —— 你的“浅色填充”就是靠它
```

`ogkit.colors` 会把 P3 精确转换为 sRGB；生成时统一写 `srgb`，跨机器一致。

### 4.3 文本：Cocoa RTF

每个标签都是一段 RTF，例如：

```rtf
{\rtf1\ansi\ansicpg1252\cocoartf2870
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fnil\fcharset0 LMSans10-Regular;\f1\fnil\fcharset0 Monaco;}
{\colortbl;\red255\green255\blue255;\red0\green84\blue147;}
{\*\expandedcolortbl;;\cssrgb\c0\c32941\c57647;}
\deftab720
\pard\pardeftab720\qc\partightenfactor0

\f0\fs16 \cf2 Encoder \f1 step()}
```

要点：字体用 **PostScript 名**（`LMSans10-Regular`、`MapleMono-NF-CN-Light`）；`\fs` 是半磅；
颜色在 `expandedcolortbl` 中以 `\cssrgb` 百分数存储；非 ASCII 用 `\uc0\uNNNN`；
`\fcharset134` 的字体里 `\'a1\'ad` 要按 GBK 解码（你的文件里就有这种“…”）。
`ogkit.rtf` 读写这一方言，并支持行内混排（粗体/斜体/等宽/上下标/颜色）。

### 4.4 LineGraphic（连线）

```text
Points      ["{381, 402.6}", "{381, 364.7}"]     # 折线顶点
Tail/Head   {ID: 21}  或 {ID, Info: 磁吸点序号, Position}   # 绑定到形状 → 拖动形状时线会跟着走
Style.stroke{ LineType: 缺省直线 | 1 曲线 | 2 正交,  CornerRadius(正交拐角圆角),
              HeadArrow/TailArrow: FilledArrow | StickArrow | Arrow | FilledBall | Diamond | NegativeControls ...,
              HeadScale, TailScale, Width, Pattern(虚线预设号), Bezier }
LogicalPath { elements: [MOVETO, LINETO, CURVETO{control1, control2}, ...] }   # 实际绘制路径（缓存）
ControlPoints  曲线控制点（相对端点的偏移）
OrthogonalBarAutomatic / OrthogonalBarPoint / OrthogonalBarPosition   # 正交线的中段位置
```

**两个关键发现：**

1. 绑定到形状的连线，`Points` 端点常常存的是 **形状中心**，OmniGraffle 绘制时才裁剪到形状轮廓；
   连线也可以把 `Tail` 绑在**另一条线**上（残差连接就是这么画的）。渲染器已实现这一裁剪。
2. `Head`/`Tail` 绑定意味着生成的文件在 OmniGraffle 里拖动方框时，箭头会自动跟随 —— 这正是“可编辑”的核心价值，
   `ogkit` 生成的所有连线都带绑定。

贴在线上的标签是一个带 `Line: {ID, Position}` 的 `ShapedGraphic`（OmniGraffle 会保持它相对线的偏移）。

### 4.5 图片与自定义形状

* 图片：`ShapedGraphic.ImageID = N` ↔ 包内 `imageN.<ext>` ↔ `ImageList` 中的名字。PDF 会以矢量形式保留
  （你的 925 个 PDF 资源里 473 个是 LaTeX 公式，126 个是 matplotlib 图）。`ogkit` 的 `d.math()` 用本机
  `pdflatex` 生成同样的矢量公式 PDF 并嵌入。
* 自定义形状：`Shape: "pdfImport-378"`，其单位坐标路径（[-0.5, 0.5]²）定义在页面的 `ExportShapes` 里。
  你的文件中这些其实是一套 **Material Design 图标**（Memory 芯片 ×160、Message ×65、Settings ×36…），
  已被抽取到 `library/icons/`，生成时随文件一起写入 `ExportShapes`，在 OmniGraffle 里仍是可改色的矢量形状。

### 4.6 层级、编组、表格

* `GraphicsList[0]` 在最上层。`ogkit` 按 “容器 < 连线 < 方框 < 文字” 排序，保证连线压在面板上、方框盖住线头。
* `Group.Graphics` 是子图元列表（同样 front-to-back）；`TableGroup` 额外有 `GridH`。

## 5. 生成路线对比

| 方案 | 可编辑性 | 自动化程度 | 是否需要 Mac | 评价 |
|---|---|---|---|---|
| **直接生成 `.graffle`（本仓库）** | ★★★ 原生对象、连线绑定、可改色图标 | 完全自动，Linux 可跑，可渲染自检 | 否（仅最终打开需要） | **推荐**，已实现 |
| Omni Automation（OmniGraffle 内置 JavaScript）/ AppleScript 驱动 App 画图 | ★★★ | 需要 App 在前台运行 | 是 | 适合“在已打开文档上做批量修改”，作为补充（见 `tools/`） |
| 生成 SVG 再导入 OmniGraffle | ★ 导入后多为路径/组，文字和连线关系丢失 | 高 | 导入需要 | 不推荐 |
| 生成 Visio `.vsdx` 再导入 | ★★ 字体样式易丢失 | 中 | 导入需要 | 不推荐 |

## 6. 生成时的约束（`ogkit` 已全部处理）

1. 写**二进制** plist + zip（deflate），名称 `data.plist`；资源命名 `image<ID>.<ext>`，同步 `ImageList/ImageCounter/ImageLinkBack`。
2. 文档级键直接取自你真实文件的模板（`ogkit/templates/document.plist`），只更新日期与作者。
3. 每个图元显式写 `fill/stroke/shadow`，ID 唯一且 > 0（0 留给背景）。
4. 文字度量：在 Linux 上用相同字体（LM Sans 10、Maple Mono、Fira Code）测量；对 4 000+ 个自动尺寸标签校准，
   宽度误差中位数 0%，行高按字体分别校准（LM Sans 1.438×、Monaco 1.369×、Maple Mono 1.29×…）。
5. `python -m ogkit validate` 会检查：所有键名在真实文件中出现过、引用（Head/Tail/Line/ImageID/自定义形状）完整、RTF 可解析。

## 7. 在 Mac 上验收（第一次使用时做一次）

1. 双击 `examples/out/*.graffle`，应直接打开、无“文件已损坏/需要转换”提示；
2. 拖动任意方框，连线端点应跟随；双击文字可直接编辑，字体为 LM Sans 10 / Monaco；
3. 选中一个图标（如 memory 芯片），在检查器里改填充色应生效；
4. 如有任何异常，把文件在 OmniGraffle 里“另存为”一份，运行
   `python -m ogkit inspect` 对比两者差异并反馈给 Agent —— 由于 OmniGraffle 会把文档规范化后再保存，差异即是需要修正的地方。

`tools/og_export.applescript` 提供了在 Mac 上用 OmniGraffle 本体批量导出 PDF/PNG 的脚本（得到与 App 完全一致的成品图）。
