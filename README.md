# skills

MerliniKing 的 agent skills 合集。`skills/<name>/` 每个子目录是一个完整技能，兼容各 agent 的 skill 发现路径与 `npx skills` 安装器。

## 安装

npx（装单个技能）：

```bash
npx skills add MerliniKing/skills@self-evolving-writing
npx skills add MerliniKing/skills@book-eat
```

手动（等价）：

```bash
git clone https://github.com/MerliniKing/skills.git
cp -r skills/skills/self-evolving-writing ~/.agents/skills/
```

## 技能列表

| 技能 | 说明 |
|------|------|
| [book-eat](skills/book-eat/) | 把书喂给 AI 的阅读流水线：逐页解析 → 知识图谱 → 间隔复习，吸收留给读书人 |
| [self-evolving-writing](skills/self-evolving-writing/) | 自进化个人风格写作：用你的声纹写公众号/知乎/技术社区文章，自动去 AI 味，从你的定稿修改里持续学风格 |

## 结构约定

- `skills/<name>/` 为一个完整技能：`SKILL.md` + 可选 `references/ scripts/ assets/`。
- 技能只带程序和种子模板；**用户数据永远长在用户自己的工作目录里**（book-eat 的 `my-library/`、self-evolving-writing 由 `config.md` 指向的目录），技能仓库不含任何个人数据。
- self-evolving-writing 的本机配置 `config.md` 在 `.gitignore` 中，仓库里只有 `config.example.md` 模板。

## License

MIT。`self-evolving-writing/references/ai-tells-zh.md` 提炼自 [blader/humanizer](https://github.com/blader/humanizer)（MIT）与 Wikipedia [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)。
