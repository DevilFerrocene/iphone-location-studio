# 行迹 · iPhone Location Studio

在本地地图上规划路线，通过 pymobiledevice3 向连接的 iPhone 发送模拟位置。

## 功能

- 地图选点、拖动调整、轨迹预览。
- 相邻选点组成一段，每段可独立设置速度、发送间隔、位置噪声和弯曲量。
- 随机速度按持续节奏缓慢变化，每次生成使用新种子，预览与发送使用同一组参数和种子。
- 暂停、继续、停止发送、恢复真实定位。

## 运行

需要 macOS、Python 3.11+、[uv](https://docs.astral.sh/uv/)、一台通过 USB 连接的 iPhone。手机需解锁、信任电脑并开启开发者模式。设备连接使用 pymobiledevice3 的 macOS 原生通道。

```sh
git clone https://github.com/DevilFerrocene/iphone-location-studio.git
cd iphone-location-studio
uv run python server.py
```

打开 <http://127.0.0.1:8769/>，点击“连接 iPhone”。也可以双击 `启动行迹.command`。

1. 在地图上依次选择路线点。
2. 设置全局参数，或展开某段并取消“沿用全局参数”。
3. 点击“生成轨迹预览”，再点击“开始发送到 iPhone”。

弯曲量单位为米，正数向行进方向左侧弯、负数向右侧弯，0 为直线。随机速度上下限均为 0 时使用固定速度，否则要求 `0 < 最低速度 ≤ 最高速度`。位置噪声为平滑坐标偏移，速度参数描述沿规划路径的运动，噪声和设备通信耗时会影响应用测得的速度。

暂停、停止和路线结束后保留最后模拟位置；“恢复真实定位”清除模拟。服务正常退出时尝试清除模拟位置，设备断开时可能无法完成清除。刷新页面会清空页面中的路线编辑内容，后台发送仍独立运行。

## 使用范围

在 macOS 上使用 iOS 26.6.1 真机完成过位置模拟验证。界面和生成器支持分段弧线与随机速度；设备使用情况以实际连接结果为准。当前设备连接实现仅针对 macOS。

服务仅监听 `127.0.0.1:8769`，修改操作需要页面携带本次启动的随机令牌。设备标识仅在连接时读取，路线和状态保存在内存中。地图瓦片由 OpenStreetMap 在线提供。轨迹没有人为数量上限，较密集的采样会增加内存和生成耗时。

本工具调用苹果开发者位置模拟服务，用于应用开发与位置功能测试。模拟位置可带有系统来源标记；工具不修改该标记。

## 许可证

本仓库自有代码采用 [MIT](LICENSE)。第三方组件分别遵循自身许可证：

- `static/vendor/leaflet.js`、`leaflet.css`：Leaflet 1.9.4，[BSD-2-Clause](static/vendor/Leaflet-LICENSE)。
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)：GPL-3.0-or-later，安装时作为外部依赖获取。
- FastAPI：MIT；Uvicorn：BSD-3-Clause。

MIT 授权不改变第三方许可证。分发包含 GPL 依赖的组合程序时，需遵守相应 GPL 条款。
