<div class="dl-home">
  <div class="dl-home__mark" aria-hidden="true">
    <img src="../assets/droplets-mark.svg" alt="">
  </div>
  <p class="dl-home__eyebrow">用于数字微流控的 Python 库</p>
  <h1 class="dl-home__title">DropLogic</h1>
  <p class="dl-home__copy">
    面向部署的数字微流控控制：系统、规划、执行、可视化和工具集中在一个库中。
  </p>
  <div class="dl-home__actions">
    <a class="md-button dl-button" href="getting_started/">入门</a>
    <a class="md-button dl-button" href="systems/">系统</a>
    <a class="md-button dl-button" href="planning/">规划</a>
    <a class="md-button dl-button" href="visualization/">可视化</a>
    <a class="md-button dl-button" href="mcp/">智能体控制</a>
  </div>
</div>

!!! info "平台兼容性"
    安装匹配的 DropLogic 原生 runtime 后，原生 `DMLite` 硬件控制支持 Windows x86_64、macOS Apple Silicon、Linux x86_64、Raspberry Pi OS 64-bit 和 Raspberry Pi OS 32-bit。`Simulator` 仍然是纯 Python，不需要原生硬件 assets。

欢迎阅读 **DropLogic** 文档。DropLogic 是一个用于数字微流控（DMF）控制的 Python 库。它用统一的 Python 接口封装系统、模块、规划、执行和可视化，让脚本保持可读，而不用在不同硬件接口之间来回切换。

## 这里有什么？
<ul class="dl-home__list">
  <li><strong><a href="installation/">安装</a></strong>：Python 安装、原生 runtime 布局，以及 Linux/Raspberry Pi 的 `libusb` 说明。</li>
  <li><strong><a href="getting_started/">入门</a></strong>：基础用法和第一步。</li>
  <li><strong><a href="configuration/">配置</a></strong>：仓库里的 `config.json`、必需字段和本机校准。</li>
  <li><strong><a href="repository_structure/">架构图</a></strong>：仓库结构和模块组织方式。</li>
  <li><strong><a href="systems/">系统</a></strong>：系统、模块、版本的结构，以及如何创建新机器。</li>
  <li><strong><a href="planning/">规划</a></strong>：AdvancedDrop、液滴计划、SIPP 移动和 executor runtime。</li>
  <li><strong><a href="visualization/">可视化</a></strong>：矩阵视图、streamer 视图、快照和同步录制。</li>
  <li><strong><a href="mcp/">智能体控制</a></strong>：供智能体规划、执行、检查 frame 和运行视觉检查的 MCP server 工具。</li>
  <li><strong><a href="utilities/">实用工具</a></strong>：硬件 helpers、液滴视觉、调试和诊断。</li>
</ul>
