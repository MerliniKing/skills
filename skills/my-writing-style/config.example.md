# 配置

首次运行时把本文件复制为 `config.md` 并填入实际路径（skill 会引导你完成）。skill 每次都从磁盘重读，改完即生效。

## 风格库目录

<你的写作工作仓>/style

- 声纹（voice.md）、硬规则（rules.md）、平台适配（platforms/）都住这里，建议放在你自己的文章工作仓里、进 git 版本化。
- 目录不存在也没关系：首次运行会创建它并放入种子模板（assets/style-template/）。

## 文章根目录

<你的写作工作仓>/articles

- 文章都按 `<文章根目录>/<日期-主题>/` 组织：`draft.md` 是工作稿，`final.md` 是定稿。
- 提炼语料 = 该目录下所有 `.md` / `.txt`（含 `imported/` 里导入的旧文章），自动排除 `draft*.md` 和 `README.md`。AI 写的初稿和说明文档永远不能当作你的风格素材。
