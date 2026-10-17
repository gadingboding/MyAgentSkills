---
name: bilibili-comment-fetch
description: 抓取哔哩哔哩（Bilibili）视频与动态（Opus）的评论并导出为 YAML 文件。当任务需要获取、分析、总结或保存哔哩哔哩视频或动态评论时使用此技能。
---

# 哔哩哔哩视频与动态评论抓取

通过内置脚本 `scripts/fetch-comment.py` 抓取指定哔哩哔哩视频或动态（Opus）的最热评论与最新评论，并结构化导出为纯文本 YAML 文件。

## 何时使用此技能

当任务符合以下场景时使用此技能：
1. 需要获取、查看、分析或总结哔哩哔哩视频或动态（Opus）的评论区内容。
2. 用户提供了哔哩哔哩视频链接/BV 号，或动态/Opus 链接/ID，并要求提取观众反馈、舆情或精彩热评。
3. 需要将视频或动态评论导出或持久化保存为 YAML 格式文件供后续处理。

## 使用方法

### 执行命令

在当前工作区直接执行脚本：

```bash
python3 scripts/fetch-comment.py "<目标标识或链接>" "<输出YAML路径>" [可选参数]
```

### 参数说明

1. 必选参数：
   - `target`：目标视频或动态标识，自动识别并二合一支持以下格式：
     - **视频**：标准 BV 号（例如 `BV1FmqGB8Ef9`）或视频链接（例如 `https://www.bilibili.com/video/BV1FmqGB8Ef9/`）。
     - **动态/Opus**：Opus 链接（例如 `https://www.bilibili.com/opus/1244951340878135321`）、动态链接（例如 `https://t.bilibili.com/1244951340878135321`）、纯数字动态 ID（例如 `1244951340878135321`）或前缀格式（如 `opus1244951340878135321`）。
     - 支持 `b23.tv` 短链接（自动跟随重定向）。
   - `output`：输出的 YAML 文件路径（若父目录不存在会自动创建）。用户未指定路径时，优先保存到当前 agent 会话的临时目录。

2. 可选参数：
   - `--hot <数量>`：抓取最热评论的数量上限，默认值为 50。若设为 0 则不抓取最热评论。
   - `--latest <数量>`：抓取最新评论的数量上限，默认值为 50。若设为 0 则不抓取最新评论。
   - `--sub <数量>`：每条主评论最多抓取的二级评论（楼中楼）数量上限，默认值为 10。若设为 0 则不抓取任何二级评论。

### 常用命令示例

```bash
# 1. 抓取动态评论（如 opus 链接）
python3 scripts/fetch-comment.py "https://www.bilibili.com/opus/1244951340878135321" "opus_comments.yaml"

# 2. 默认抓取视频评论（最热 50 条 + 最新 50 条，二级评论最多各 10 条）
python3 scripts/fetch-comment.py "BV1FmqGB8Ef9" "comments.yaml"

# 3. 使用视频完整链接
python3 scripts/fetch-comment.py "https://www.bilibili.com/video/BV1FmqGB8Ef9/" "comments.yaml"

# 4. 自定义抓取数量（例如最热 20 条、最新 10 条、二级评论最多 3 条）
python3 scripts/fetch-comment.py "https://www.bilibili.com/opus/1244951340878135321" "comments.yaml" --hot 20 --latest 10 --sub 3

# 5. 只抓取主评论，不抓取任何二级评论
python3 scripts/fetch-comment.py "https://www.bilibili.com/opus/1244951340878135321" "comments.yaml" --sub 0

# 6. 仅抓取最热评论（不抓取最新评论）
python3 scripts/fetch-comment.py "https://www.bilibili.com/opus/1244951340878135321" "comments.yaml" --latest 0
```

## 结果检查

1. 确认命令正常退出（退出码为 0），控制台会输出抓取统计摘要，例如：
   ```text
   Success: fetched 14 main comments for dynamic/opus (hot: 14, latest: 0) and 3 sub-comments.
   Output saved to: /path/to/comments.yaml
   ```
2. 检查生成的 YAML 文件是否存在且大小大于 0。
3. 若用于后续分析或总结，直接读取生成的 YAML 文件内容进行进一步处理。
