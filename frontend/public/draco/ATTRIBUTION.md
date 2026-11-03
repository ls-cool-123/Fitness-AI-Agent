# DRACO 解码器来源

本目录的 `draco_decoder.js`、`draco_decoder.wasm`、`draco_wasm_wrapper.js` 由
`scripts/fetch_anatomy_model.py` 从 `three` npm 包的
`examples/jsm/libs/draco/` 复制而来。

- three.js: https://github.com/mrdoob/three.js
- DRACO: https://github.com/google/draco
- 许可：Apache License 2.0

它们只用于在浏览器里解码 `../models/body.glb` 的 Draco 压缩几何数据。
