# 高德 POI 爬取与矢量导出工具

基于 PyQt5 + PyQtWebEngine 的桌面工具，用于输入或捕捉高德地图 POI，在线获取官方 Web 端 `detail/get/detail` 接口返回的要素信息，并将外形多边形一键导出为 GeoJSON 与 ESRI Shapefile。

## 功能亮点
- **实时抓取**：借助网页自身的 `https://ditu.amap.com/detail/get/detail` 请求，只需输入 POI ID 或通过网页捕捉即可获取名称、地址、电话及 `mining_shape` 外形。 
- **网页嵌入**：右侧内置 `https://ditu.amap.com/`，点击地物即自动监听 detail 请求，无需手动粘贴 POI ID。界面采用多重 Splitter，自适应全屏尺寸。  
- **批量捕捉**：开启“开始捕捉”后可多次点击地物，停止后一次性选择导出 GeoJSON / Shapefile / 双格式。  
- **图形预览**：应用内使用 `QGraphicsView` 将多边形进行自适应缩放预览，方便核对地物轮廓。  
- **多格式导出**：支持 GeoJSON（含属性字段）和 Shapefile（自动生成 `.shp/.shx/.dbf/.prj`），批量导出时自动跳过无几何的 POI 并给出提示。  
- **坐标统一**：所有 `mining_shape` 坐标会自动从 GCJ-02（火星坐标）转换为 WGS84，导出的矢量文件可直接用于标准 GIS 软件。  
- **数据复用**：解析逻辑统一封装在 `gaode_client.py`，确保捕捉模式与单次查询都基于同一套 JSON 结构。

## 环境准备
确保已经安装 Python 3.10+，然后在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

> 若页面返回登录或验证码内容，需要先在嵌入式浏览器中完成对应操作，之后再进行捕捉或手动获取。

## 使用步骤
1. 启动应用，输入目标 POI 的编号（例如 `B0FFG4HF5W`），或点击右侧地图确认该地物是否会发起 `detail/get/detail` 请求。
2. 点击“获取数据”或直接在地图上开启捕捉：
	- 手动模式：输入 POI ID 后点击“获取数据”，应用会自动跳转至该 POI 的网页并复用其网络响应，左侧即展示属性、JSON 及矢量预览（可按 F11 进入全屏调度更多空间）。
	- 捕捉模式：点击“开始捕捉”，在 Web 地图中依次选取多个地物，最后点击“停止捕捉”进入批量导出对话框。
3. 单次查询可通过底部按钮导出 GeoJSON / Shapefile。批量捕捉可在弹窗中同时选择两种格式及输出目录。

## 代码结构
- `app.py`：PyQt5 图形界面、嵌入式 WebEngine 与捕捉导出逻辑。
- `gaode_client.py`：解析高德网页返回的 JSON 数据，生成统一的 `PlaceDetail` 模型。
- `geometry_utils.py`：处理多边形字符串解析、归一化和 GeoJSON 构造。
- `exporters.py`：输出 GeoJSON/Shapefile 的工具类。
- `models.py`：数据类定义。
- `requirements.txt`：依赖列表。

## 已知限制
- 某些 POI 需要登录或严格的防爬限制，需要在嵌入式浏览器中提前完成登录或验证。
- 本工具仅解析 `spec.mining_shape` 字段，若返回缺失外形，导出按钮与批量导出会跳过该 POI 并提示。

## Nuitka 打包（GaodeAtlas 1.0, Yserver）
项目提供 `build_with_nuitka.ps1`，使用 Nuitka 将 GUI 打包成单文件可执行程序。

1. 确保 `favicon.ico` 位于仓库根目录，PowerShell 中执行：

	```powershell
	Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
	.\build_with_nuitka.ps1
	```

2. 脚本会自动安装/升级 `nuitka`, `ordered-set`, `zstandard`，然后执行：
	- `--enable-plugin=pyqt5`：自动收集 PyQt5 运行时代码。
	- `--windows-company-name=Yserver`，`--windows-product-name=GaodeAtlas`，`--windows-file-version=1.0.0.0`，`--windows-product-version=1.0`：写入元数据。
	- `--windows-icon-from-ico=favicon.ico`：将 favicon 作为程序图标。
	- `--include-data-files=favicon.ico=favicon.ico`：运行期仍可访问图标资源。

3. 构建结果位于 `dist/` 目录，默认生成 `app.exe`（可自行重命名）。如需进一步签名或嵌入其他资源，可在脚本中附加 Nuitka 参数。

## 后续可拓展方向
1. 增加批量 POI 处理与文件列表导入。  
2. 集成地图控件（如 `folium`/`leaflet`）进行底图对比。  
3. 加入属性字段自定义映射与 CRS 选择。
