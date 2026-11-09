# 流幕 Luma Studio

[English](README.md)

流幕是一个本机运行的漫剧与短片制作工作室。按集整理剧本、角色造型、镜头与对白，从选定的素材合成并导出成片。

**当前是开发预览版。** 本地素材可直接用于制作与交付。分镜、单镜修改和配音可选接入自己的 Dify 应用。图片、视频生成需要额外接入受支持的供应商。本机初次启动时，外部生成处于暂停状态。

## 启动与制作

安装 Python 3.11+ 和 FFmpeg（含 `ffprobe` 及 `libx264` 编码器），运行：

```sh
python3 studio.py check
python3 studio.py
```

打开 [本机工作室](http://127.0.0.1:7820/)。新建作品，填写剧本并添加镜头。为各镜导入和选用画面，按需添加对白音轨。确认镜头后到「成片」导出 MP4。服务仅供本机单用户访问。

## 接入 Dify

从 [工作流目录](workflows/production/) 导入对应应用，按自己的 Dify 环境配置节点与模型，发布后在流幕「设置」填写应用连接。使用「检查连接」核验接口，按需单独开启生成额度。

## 备份与恢复

停止对应的本机服务后执行。备份及恢复目标均须是新目录。

```sh
python3 studio.py backup ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py restore ./luma-backup
AUTEUR_DATA=./luma-restored python3 studio.py
```

备份包含数据库、素材和成片。恢复后外部生成保持暂停，未结束的远程任务标为中断。新安装的 Dify 凭据单独配置。

开发测试和贡献方式见 [贡献指南](CONTRIBUTING.md)。
