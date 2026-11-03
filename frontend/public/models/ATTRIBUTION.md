# 3D 人体模型来源与许可

本目录的 `body.glb` 下载自并改编自：

- 模型仓库：https://github.com/hpfrei/body-anatomy-3d-viewer
- 原始模型作者：hpfrei（CC BY-SA 4.0）
- 上游数据：Z-Anatomy（https://www.z-anatomy.com/，CC BY-SA 4.0）

## 修改说明

原始文件 8,249,484 bytes，Git blob SHA `78c1f5bda9feba5577c85872f33257c99b789ef8`，SHA256 `0886b6a068e655b284903664e2178d7964f80b1c0ce798461909ac806bcef2e3`。

本项目通过 `scripts/fetch_anatomy_model.py`：

1. 删除每个节点 `extras` 中的 `description`、`wikiLink` 与 cross-section 字段；
2. 只保留 `type`、`name`、`nameDetail` 用于按肌肉群分组；
3. 重新打包 GLB，几何/BIN 数据未改动。

## 许可

本模型及其改编版本按 **CC BY-SA 4.0** 分发：
https://creativecommons.org/licenses/by-sa/4.0/

应用代码与模型资产是分开的；使用/分发模型时请保留本文件并注明修改。
