# tools/ — 第三方可执行文件（不随仓库分发）

程序需要两个 exe，**本仓库不包含它们**（第三方二进制，各自有各自的许可证）：

| 文件 | 用途 | 许可证 / 来源 |
|---|---|---|
| `ffmpeg.exe` | 视频解码 / 编码 / 抠绿合成 | LGPL/GPL（取决于编译选项） https://ffmpeg.org/download.html |
| `blackbox_decode.exe` | Betaflight 黑匣子 BBL → CSV | GPLv3 https://github.com/betaflight/blackbox-tools/releases |

## 放哪里

放到本目录，文件名保持上面表格里的名字：

```
tools/ffmpeg.exe
tools/blackbox_decode.exe
```

程序查找顺序：**环境变量 → `tools/` → 系统 PATH**。

- ffmpeg：设置环境变量 `FFMPEG` 指向 ffmpeg.exe 的完整路径也可以
- blackbox_decode：设置环境变量 `BLACKBOX_DECODE`

## 自动下载（Windows）

```powershell
powershell -ExecutionPolicy Bypass -File tools/download-tools.ps1
```

脚本会从官方/常用镜像拉取并解出这两个 exe；失败时会打印手动下载地址。

## Windows 版 ffmpeg 常用来源

- gyan.dev（full/essentials 构建）：https://www.gyan.dev/ffmpeg/builds/
- BtbN（GitHub 构建，含 win64-gpl）：https://github.com/BtbN/FFmpeg-Builds/releases
- 只需要 `bin\ffmpeg.exe` 这一个文件即可

## 自己编译 / 系统包管理器

- macOS：`brew install ffmpeg`（然后在 PATH 里就能找到）
- Linux：`apt install ffmpeg`
- blackbox_decode 也可以自己编译 blackbox-tools，把生成的 exe 放进本目录