# bboverlay — Betaflight 黑匣子 + 眼镜视频叠加工具

把穿越机的黑匣子日志（`.bbl`）和眼镜/运动相机的视频自动对齐，生成带
**双摇杆 / 3D 姿态 / 卫星小地图 / GPS 坐标遮盖**的叠加视频。

- 自动解 BBL、自动测视频与日志的时间差（多段日志会逐段比对后自动挑段）
- 60 fps 绿幕 HUD 渲染，多进程并行；ffmpeg 抠绿合成成品 mp4
- 图形界面（tkinter）：选文件 → 填时间段 → 出片
- 「元素位置」窗口：摇杆 / 姿态 / 小地图 / 两块坐标遮盖都能拖拽+填数字，含一键对齐
- 支持日本手 MODE1 / 美国手 MODE2，四个通道都可单独反向
- 小地图支持在线卫星瓦片，也支持自己的正射影像/正俯视照片当底图

> 这是个人项目，界面和文档以中文为主；代码结构简单，欢迎 PR。

---

## 依赖

| 组件 | 说明 |
|---|---|
| Python 3.10+ | 需要 `pillow`、`numpy`、`pandas`，以及标准库 `tkinter` |
| ffmpeg | 编解码视频。自行下载后放到 `tools/ffmpeg.exe`，或设置环境变量 `FFMPEG` |
| blackbox_decode | Betaflight 黑匣子解码器。放到 `tools/blackbox_decode.exe`，或设置 `BLACKBOX_DECODE` |

```bash
pip install -r requirements.txt
```

两个 exe **没有随仓库分发**（第三方二进制），获取方式见 [tools/README.md](tools/README.md)，
也可以直接跑：

```powershell
powershell -ExecutionPolicy Bypass -File tools/download-tools.ps1
```

## 快速开始

### 命令行

```bash
python bboverlay.py 我的日志.BBL 眼镜视频.MOV --vstart 174 --dur 30
```

- `--vstart`：从**视频**第几秒开始（视频播放器里看到的秒数）
- `--dur`：做多长
- 输出：`成片_xxx.mp4`（已抠绿合成）和 `绿幕overlay_xxx.mp4`（拿去剪映自己叠）

常用参数：

| 参数 | 作用 |
|---|---|
| `--seg N` | 强制用第 N 段日志（0/不填=自动挑段） |
| `--lag X` | 手动指定时间差，跳过自动测量 |
| `--no-map` / `--no-att` | 不画小地图 / 不画 3D 姿态 |
| `--mask "x,y,w,h"` / `--mask2 ...` | GPS 坐标遮盖黑块（可两块） |
| `--stick-mode 1\|2` | 日本手 / 美国手 |
| `--inv-thr --inv-rol --inv-pit --inv-yaw` | 通道反向 |
| `--lstick-x/-y/-scale` `--rstick-*` | 左右摇杆各自的位置与缩放 |
| `--att-x/-y/-scale` `--map-x/-y/-scale` | 姿态 / 小地图的位置与缩放 |
| `--map-image 图.jpg` | 用自己航拍的正射图当底图（配 `--map-mpp` 等） |
| `--size 9:16 --portrait` | 竖屏成片（HUD 按 1080×1920 原生重排，`--portrait-mode band` 是整块缩小压底） |
| `--tele-color N` `--bar-color N` `--text-color N` | 数值面板 / 柱状图 / 水印 各自挑颜色（-1=跟框线色） |
| `--map-arrow-color N` `--map-trail-color N` `--trail-color N` | 地图箭头 / 地图轨迹 / 摇杆轨迹 颜色 |
| `--tele-alpha` `--bar-alpha` `--text-alpha` | 数值面板 / 柱状图 / 水印 透明度（0~1） |
| `--preview` | 只出一张叠好视频的 JPG |
| `--layers auto` | 切出各元素图层（给「元素位置」用，有缓存） |
| `--selftest` | 自检：Python 库、ffmpeg、解码器，以及版式算法 |

### 图形界面

Windows 下双击 `启动黑匣子叠加工具.exe` 或 `启动黑匣子叠加工具.vbs`（都不弹黑窗；
exe 需要自己编译：`powershell -ExecutionPolicy Bypass -File 启动器源码/编译.ps1`）。换电脑第一次先双击
`新电脑配置程序.vbs`，会自动装 Python 与依赖并记下解释器路径。

其他平台直接 `python bboverlay_gui.py`。

### 一键卸载

双击 `一键卸载程序.vbs`（界面「输出」卡片里也有按钮）。会先列出所有可删项目并让你勾选：

- 运行时文件（work / cache / 配置 / 日志）——默认删
- 「输出」文件夹里的成片——默认不删
- pip 依赖（pillow / numpy / pandas）——默认不删（可能影响其他 Python 程序）
- 本程序安装过的 Python——默认不删
- 整个程序文件夹——默认删（自删除由独立进程完成）

所有删除目标都会校验路径必须位于程序目录内，绝不动目录外的文件。

## 已知限制

- 目前主要针对 Betaflight 4.x 标准日志；`imuQuaternion`/`gyroADC` 字段不可靠，
  姿态是用 `gyroUnfilt` 自己积分（Mahony）出来的
- 小地图默认取高德卫星瓦片，见下方免责声明；离线或没 GPS 时会自动跳过小地图
- Windows 优先（启动器、配置脚本），其他平台走命令行/直接跑 py 均可

## 免责声明 / Disclaimer

- **地图瓦片**：默认的小地图底图来自高德地图的瓦片接口，**仅供个人学习与本地预览**。
  批量抓取、缓存再分发或商用不符合其服务条款；公开发布或商业使用时请改用
  [天地图](https://www.tianditu.gov.cn/)（可申请免费 key）或自备正射影像。
  可用环境变量 `BBOVERLAY_TILE_URL` 换成自有瓦片服务。
- **飞行安全与法规**：本工具只做视频后期叠加，不参与飞行控制。使用前请遵守当地的
  无人驾驶航空器管理规定，不要用于黑飞、禁飞区作业或非法测绘。
- **隐私**：日志和视频包含真实 GPS 坐标，分享成品/截图前请确认是否需要遮盖。

## License

[MIT](LICENSE)